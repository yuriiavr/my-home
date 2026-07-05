/*
 * Gree / Cooper&Hunter — WiFi-клієнт (UDP 7000, AES-128-GCM).
 * Портовано з hub/devices/gree.py.
 *
 * Пакет назовні: {"cid":"app","i":0,"pack":...,"tag":...,"t":"pack","tcid":MAC,"uid":0}
 * Всередині: {"opt":[...],"p":[...],"t":"cmd"} або {"cols":[...],"mac":MAC,"t":"status"}
 *
 * Якщо кондиціонер перестав відповідати (наприклад, роутер видав йому
 * нову IP-адресу) — робимо broadcast-скан {"t":"scan"} (відповідь
 * шифрована старим спільним ECB-ключем) і оновлюємо адресу.
 */
#include "gree_ac.h"

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <mbedtls/gcm.h>
#include <mbedtls/aes.h>
#include <mbedtls/base64.h>
#include <string.h>
#include <strings.h>
#include <memory>

#include "secrets.h"  // MAC/ключ/IP кондиціонера (НЕ в git; див. secrets.example.h)

// ── налаштування пристрою (значення живуть у src/secrets.h) ──────────
static const char*   kAcMac  = SECRET_AC_MAC;   // MAC кондиціонера
static const char*   kAcKey  = SECRET_AC_KEY;   // персональний AES-ключ (bind)
static IPAddress     s_ip(SECRET_AC_IP);        // остання відома адреса

// ── константи протоколу Gree ─────────────────────────────────────────
static const uint16_t kGreePort  = 7000;
static const uint16_t kLocalPort = 39500;                // наш UDP-порт
static const char*    kEcbKey    = "a3K8Bx%2r8Y7#xDh";   // спільний ключ scan (ECB)
static const char*    kGcmAad    = "qualcomm-test";
static const uint8_t  kGcmIv[12] = {0x54, 0x40, 0x78, 0x44, 0x49, 0x67,
                                    0x5a, 0x51, 0x6c, 0x5e, 0x63, 0x13};

// Таймінги: 2 спроби по ~950 мс = не більше ~2 с блокування на тік
static const uint32_t kUdpTimeoutMs = 950;
static const int      kUdpAttempts  = 2;

static const char* kIpFile = "/acip.txt";  // сюди зберігаємо знайдений IP

static bool     s_online     = false;
static int      s_failCount  = 0;
static uint32_t s_lastScanMs = 0;

// ── base64 (mbedtls) ─────────────────────────────────────────────────
static String b64enc(const uint8_t* data, size_t len) {
  size_t cap = 4 * ((len + 2) / 3) + 4;
  std::unique_ptr<uint8_t[]> buf(new uint8_t[cap]);
  size_t olen = 0;
  if (mbedtls_base64_encode(buf.get(), cap, &olen, data, len) != 0) return String();
  buf[olen] = 0;
  return String((const char*)buf.get());
}

static bool b64dec(const char* in, std::unique_ptr<uint8_t[]>& out, size_t& olen) {
  if (in == nullptr) return false;
  size_t inLen = strlen(in);
  size_t cap = (inLen / 4 + 1) * 3 + 1;
  out.reset(new uint8_t[cap]);
  return mbedtls_base64_decode(out.get(), cap, &olen, (const uint8_t*)in, inLen) == 0;
}

// ── AES-128-GCM (персональний ключ пристрою) ─────────────────────────
static bool gcmEncrypt(const String& plain, String& packB64, String& tagB64) {
  size_t len = plain.length();
  std::unique_ptr<uint8_t[]> enc(new uint8_t[len ? len : 1]);
  uint8_t tag[16];
  mbedtls_gcm_context g;
  mbedtls_gcm_init(&g);
  bool ok =
      mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, (const uint8_t*)kAcKey, 128) == 0 &&
      mbedtls_gcm_crypt_and_tag(&g, MBEDTLS_GCM_ENCRYPT, len, kGcmIv, sizeof(kGcmIv),
                                (const uint8_t*)kGcmAad, strlen(kGcmAad),
                                (const uint8_t*)plain.c_str(), enc.get(),
                                sizeof(tag), tag) == 0;
  mbedtls_gcm_free(&g);
  if (!ok) return false;
  packB64 = b64enc(enc.get(), len);
  tagB64  = b64enc(tag, sizeof(tag));
  return packB64.length() > 0 && tagB64.length() > 0;
}

static bool gcmDecrypt(const char* packB64, const char* tagB64, String& plainOut) {
  std::unique_ptr<uint8_t[]> ct, tg;
  size_t ctLen = 0, tgLen = 0;
  if (!b64dec(packB64, ct, ctLen) || !b64dec(tagB64, tg, tgLen) || tgLen != 16)
    return false;
  std::unique_ptr<uint8_t[]> pt(new uint8_t[ctLen + 1]);
  mbedtls_gcm_context g;
  mbedtls_gcm_init(&g);
  bool ok =
      mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, (const uint8_t*)kAcKey, 128) == 0 &&
      mbedtls_gcm_auth_decrypt(&g, ctLen, kGcmIv, sizeof(kGcmIv),
                               (const uint8_t*)kGcmAad, strlen(kGcmAad),
                               tg.get(), 16, ct.get(), pt.get()) == 0;
  mbedtls_gcm_free(&g);
  if (!ok) return false;
  pt[ctLen] = 0;
  plainOut = (const char*)pt.get();
  return true;
}

// ── AES-128-ECB (лише для розшифровки відповіді на scan) ─────────────
static bool ecbDecrypt(const char* packB64, String& plainOut) {
  std::unique_ptr<uint8_t[]> ct;
  size_t ctLen = 0;
  if (!b64dec(packB64, ct, ctLen) || ctLen == 0 || (ctLen % 16) != 0) return false;
  std::unique_ptr<uint8_t[]> pt(new uint8_t[ctLen + 1]);
  mbedtls_aes_context a;
  mbedtls_aes_init(&a);
  bool ok = mbedtls_aes_setkey_dec(&a, (const uint8_t*)kEcbKey, 128) == 0;
  for (size_t i = 0; ok && i < ctLen; i += 16)
    ok = mbedtls_aes_crypt_ecb(&a, MBEDTLS_AES_DECRYPT, ct.get() + i, pt.get() + i) == 0;
  mbedtls_aes_free(&a);
  if (!ok) return false;
  uint8_t pad = pt[ctLen - 1];  // зняти PKCS7-доповнення
  size_t len = (pad >= 1 && pad <= 16 && pad <= ctLen) ? ctLen - pad : ctLen;
  pt[len] = 0;
  plainOut = (const char*)pt.get();
  return true;
}

// ── IP: зберегти/відновити (щоб пережити перезавантаження) ──────────
static void saveIp() {
  File f = LittleFS.open(kIpFile, "w");
  if (f) { f.print(s_ip.toString()); f.close(); }
}

void greeInit() {
  File f = LittleFS.open(kIpFile, "r");
  if (f) {
    String s = f.readString();
    f.close();
    s.trim();
    IPAddress ip;
    if (ip.fromString(s)) {
      s_ip = ip;
      Serial.printf("❄️ [GREE] адреса з пам'яті: %s\n", s_ip.toString().c_str());
    }
  }
}

// ── rescan: якщо кондиціонер "зник" — шукаємо його broadcast-ом ──────
static void tryRescan() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (s_lastScanMs != 0 && millis() - s_lastScanMs < 60000UL) return;  // не частіше 1 р/хв
  s_lastScanMs = millis();

  IPAddress ip = WiFi.localIP(), mask = WiFi.subnetMask(), bc;
  for (int i = 0; i < 4; i++) bc[i] = (ip[i] & mask[i]) | (uint8_t)~mask[i];

  WiFiUDP udp;
  if (!udp.begin(kLocalPort + 1)) return;
  const char* scanMsg = "{\"t\":\"scan\"}";
  udp.beginPacket(bc, kGreePort);
  udp.write((const uint8_t*)scanMsg, strlen(scanMsg));
  udp.endPacket();

  uint32_t start = millis();
  while (millis() - start < 1500) {  // збираємо відповіді ~1.5 с
    int sz = udp.parsePacket();
    if (sz > 0) {
      std::unique_ptr<char[]> buf(new char[sz + 1]);
      int n = udp.read(buf.get(), sz);
      buf[n > 0 ? n : 0] = 0;
      JsonDocument doc;
      if (deserializeJson(doc, (const char*)buf.get()) == DeserializationError::Ok &&
          doc["pack"].is<const char*>()) {
        String plain;
        if (ecbDecrypt(doc["pack"].as<const char*>(), plain)) {
          JsonDocument inner;
          if (deserializeJson(inner, plain) == DeserializationError::Ok) {
            const char* mac = inner["cid"].as<const char*>();
            if (mac == nullptr || mac[0] == 0) mac = inner["mac"].as<const char*>();
            if (mac != nullptr && strcasecmp(mac, kAcMac) == 0) {
              IPAddress from = udp.remoteIP();
              if (from != s_ip) { s_ip = from; saveIp(); }
              Serial.printf("❄️ [GREE] rescan: кондиціонер знайдено на %s\n",
                            s_ip.toString().c_str());
              break;
            }
          }
        }
      }
    }
    delay(5);
  }
  udp.stop();
}

static void onFail() {
  if (++s_failCount >= 3) {
    s_online = false;
    tryRescan();  // можливо, роутер змінив адресу кондиціонера
  }
}

// ── UDP-обмін: надіслати й дочекатись відповіді ──────────────────────
static bool udpExchange(const String& payload, String& respOut,
                        uint32_t timeoutMs, int attempts) {
  WiFiUDP udp;
  if (!udp.begin(kLocalPort)) return false;
  bool got = false;
  for (int a = 0; a < attempts && !got; a++) {
    udp.beginPacket(s_ip, kGreePort);
    udp.write((const uint8_t*)payload.c_str(), payload.length());
    if (udp.endPacket() != 1) continue;
    uint32_t start = millis();
    while (millis() - start < timeoutMs) {
      int sz = udp.parsePacket();
      if (sz > 0) {
        std::unique_ptr<char[]> buf(new char[sz + 1]);
        int n = udp.read(buf.get(), sz);
        buf[n > 0 ? n : 0] = 0;
        respOut = (const char*)buf.get();
        got = true;
        break;
      }
      delay(5);
    }
  }
  udp.stop();
  return got;
}

// ── зашифрувати inner-JSON, обгорнути в pack, надіслати, розкрити ────
static bool sendPack(const String& innerJson, JsonDocument& innerResp) {
  String pack, tag;
  if (!gcmEncrypt(innerJson, pack, tag)) return false;

  JsonDocument msg;
  msg["cid"]  = "app";
  msg["i"]    = 0;
  msg["pack"] = pack;
  msg["tag"]  = tag;
  msg["t"]    = "pack";
  msg["tcid"] = kAcMac;
  msg["uid"]  = 0;
  String payload;
  serializeJson(msg, payload);

  String resp;
  if (!udpExchange(payload, resp, kUdpTimeoutMs, kUdpAttempts)) { onFail(); return false; }

  JsonDocument rdoc;
  if (deserializeJson(rdoc, resp) != DeserializationError::Ok) { onFail(); return false; }
  const char* rpack = rdoc["pack"].as<const char*>();
  const char* rtag  = rdoc["tag"].as<const char*>();
  if (rpack == nullptr || rtag == nullptr) { onFail(); return false; }

  String plain;
  if (!gcmDecrypt(rpack, rtag, plain)) { onFail(); return false; }
  if (deserializeJson(innerResp, plain) != DeserializationError::Ok) { onFail(); return false; }

  s_failCount = 0;
  s_online = true;
  return true;
}

// ── публічний API ────────────────────────────────────────────────────
bool acSendCmd(const char* const opts[], const int vals[], size_t n) {
  JsonDocument inner;
  JsonArray o = inner["opt"].to<JsonArray>();
  JsonArray p = inner["p"].to<JsonArray>();
  for (size_t i = 0; i < n; i++) { o.add(opts[i]); p.add(vals[i]); }
  inner["t"] = "cmd";
  String innerJson;
  serializeJson(inner, innerJson);
  JsonDocument resp;
  return sendPack(innerJson, resp);
}

static const char* const kStatusCols[] = {
    "Pow", "Mod", "SetTem", "WdSpd", "SwUpDn", "SwingLfRig", "Lig", "Tur",
    "Quiet", "SvSt", "SwhSlp", "Blo", "Health", "TemSen"};

bool acReadStatus(AcStatus& out) {
  JsonDocument inner;
  JsonArray cols = inner["cols"].to<JsonArray>();
  for (auto c : kStatusCols) cols.add(c);
  inner["mac"] = kAcMac;
  inner["t"]   = "status";
  String innerJson;
  serializeJson(inner, innerJson);

  JsonDocument resp;
  if (!sendPack(innerJson, resp)) return false;
  JsonArray rcols = resp["cols"].as<JsonArray>();
  JsonArray dat   = resp["dat"].as<JsonArray>();
  if (rcols.isNull() || dat.isNull() || rcols.size() != dat.size()) return false;

  out = AcStatus();
  for (size_t i = 0; i < rcols.size(); i++) {
    const char* c = rcols[i].as<const char*>();
    if (c == nullptr) continue;
    int v = dat[i].as<int>();
    if      (strcmp(c, "Pow") == 0)    out.Pow = v;
    else if (strcmp(c, "Mod") == 0)    out.Mod = v;
    else if (strcmp(c, "SetTem") == 0) out.SetTem = v;
    else if (strcmp(c, "WdSpd") == 0)  out.WdSpd = v;
    else if (strcmp(c, "SwUpDn") == 0) out.SwUpDn = v;
    else if (strcmp(c, "SwingLfRig") == 0) out.SwingLfRig = v;
    else if (strcmp(c, "Lig") == 0)    out.Lig = v;
    else if (strcmp(c, "Tur") == 0)    out.Tur = v;
    else if (strcmp(c, "Quiet") == 0)  out.Quiet = v;
    else if (strcmp(c, "SvSt") == 0)   out.SvSt = v;
    else if (strcmp(c, "SwhSlp") == 0) out.SwhSlp = v;
    else if (strcmp(c, "Blo") == 0)    out.Blo = v;
    else if (strcmp(c, "Health") == 0) out.Health = v;
    else if (strcmp(c, "TemSen") == 0) out.TemSen = v;
  }
  // Температура в кімнаті: у протоколі зі зсувом +40 (65 = 25°C)
  if (out.TemSen > 40)     out.roomTemp = out.TemSen - 40;
  else if (out.TemSen > 0) out.roomTemp = out.TemSen;
  out.valid = true;
  return true;
}

bool acSetPower(bool on, int temp, int mode) {
  if (temp < 16) temp = 16;
  if (temp > 30) temp = 30;
  if (mode < 0 || mode > 4) mode = 1;  // cool
  if (on) {
    const char* opts[] = {"Pow", "Mod", "SetTem", "TemUn"};
    int vals[]         = {1, mode, temp, 0};  // TemUn=0 -> °C
    return acSendCmd(opts, vals, 4);
  }
  const char* opts[] = {"Pow"};
  int vals[]         = {0};
  return acSendCmd(opts, vals, 1);
}

bool acIsOnline() { return s_online; }
IPAddress acGetIP() { return s_ip; }

// Режими в протоколі Gree: auto=0 cool=1 dry=2 fan=3 heat=4
static const char* const kModeNames[] = {"auto", "cool", "dry", "fan", "heat"};

int acModeFromName(const char* name) {
  if (name != nullptr)
    for (int i = 0; i < 5; i++)
      if (strcasecmp(name, kModeNames[i]) == 0) return i;
  return 1;  // типово cool
}

const char* acModeName(int m) {
  return (m >= 0 && m <= 4) ? kModeNames[m] : "cool";
}
