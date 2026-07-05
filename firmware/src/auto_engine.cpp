/*
 * Движок автоматизацій — портовано з hub/automations.py.
 *
 * Правила (та сама схема, що в хабі, тому файли сумісні):
 * {
 *   "climate": {"enabled":false, "device":"ac_living", "trigger":27,
 *               "target":24, "mode":"cool", "auto_off":true, "off_below":23},
 *   "schedules": [
 *     {"enabled":true, "time":"22:30", "device":"ac_living", "action":"set",
 *      "set":{"mode":"cool","temp":25,"fan":0,"quiet":true,"sleep":true}}
 *   ]
 * }
 *
 * Клімат: кімната >= trigger і вимкнено -> увімкнути (target, mode);
 *         охолола <= off_below і вмикали МИ -> вимкнути (auto_off).
 *         Якщо людина вимкнула вручну — не сперечаємось (скидаємо прапорець).
 * Розклад: спрацьовує раз на хвилину на правило (за локальним часом NTP).
 */
#include "auto_engine.h"

#include <WiFi.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <time.h>
#include <string.h>

static const char* kRulesFile = "/auto.json";
static const int   kMaxSched  = 10;

struct ClimateRule {
  bool  enabled   = false;
  float trigger   = 27;    // вмикати, коли в кімнаті >= стільки
  int   target    = 24;    // яку температуру задати
  char  mode[8]   = "cool";
  bool  auto_off  = true;  // вимикати, коли охолоне...
  float off_below = 23;    // ...до стількох (гістерезис)
};

struct SchedRule {
  bool   enabled   = true;
  char   time[6]   = "00:00";  // "HH:MM"
  char   action[4] = "set";    // "on" | "off" | "set"
  // поля з "set" (відсутнє = не чіпаємо):
  char   mode[8]   = "";       // "" = не задано
  int    temp      = -1;       // -1 = не задано
  int    fan       = -1;       // -1 = не задано (0=авто, 1..5)
  int8_t quiet     = -1;       // -1 = не задано, 0/1
  int8_t sleepMode = -1;       // -1 = не задано, 0/1
};

static ClimateRule s_climate;
static SchedRule   s_scheds[kMaxSched];
static int         s_schedCount = 0;
static int32_t     s_schedFired[kMaxSched];  // epoch/60 останнього спрацювання
static bool        s_weTurnedItOn = false;   // чи це МИ увімкнули кондиціонер
static AcStatus    s_lastStatus;             // кеш стану для веб-сторінки
static uint32_t    s_lastTickMs = 0;
static bool        s_ticked = false;
static bool        s_stateDirty = false;      // стан AC змінився -> перепублікувати в MQTT
static bool        s_rulesDirty = false;      // правила змінилися -> перепублікувати в MQTT

// ── локальний час "HH:MM" (після синхронізації NTP) ──────────────────
static bool getHHMM(char* buf, size_t bufLen, int32_t* minuteEpoch) {
  time_t now = time(nullptr);
  if (now < 1600000000) return false;  // NTP ще не синхронізувався
  struct tm tmv;
  localtime_r(&now, &tmv);
  snprintf(buf, bufLen, "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  if (minuteEpoch != nullptr) *minuteEpoch = (int32_t)(now / 60);
  return true;
}

// ── правила <-> JSON ─────────────────────────────────────────────────
static void applyRules(JsonObject root) {
  ClimateRule cr;
  JsonObject c = root["climate"];
  if (!c.isNull()) {
    cr.enabled   = c["enabled"] | false;
    cr.trigger   = c["trigger"] | 27.0f;
    cr.target    = c["target"] | 24;
    strlcpy(cr.mode, c["mode"] | "cool", sizeof(cr.mode));
    cr.auto_off  = c["auto_off"] | true;
    cr.off_below = c["off_below"] | 23.0f;
  }
  s_climate = cr;

  s_schedCount = 0;
  JsonArray arr = root["schedules"];
  if (!arr.isNull()) {
    for (JsonObject r : arr) {
      if (s_schedCount >= kMaxSched) break;
      SchedRule s;
      s.enabled = r["enabled"] | true;
      strlcpy(s.time, r["time"] | "00:00", sizeof(s.time));
      strlcpy(s.action, r["action"] | "set", sizeof(s.action));
      JsonObject set = r["set"];
      if (!set.isNull()) {
        if (set["mode"].is<const char*>())
          strlcpy(s.mode, set["mode"].as<const char*>(), sizeof(s.mode));
        if (set["temp"].is<int>()) s.temp = set["temp"].as<int>();
        if (set["fan"].is<int>())  s.fan = set["fan"].as<int>();
        if (!set["quiet"].isNull()) s.quiet = set["quiet"].as<bool>() ? 1 : 0;
        if (!set["sleep"].isNull()) s.sleepMode = set["sleep"].as<bool>() ? 1 : 0;
      }
      s_scheds[s_schedCount]     = s;
      s_schedFired[s_schedCount] = -1;
      s_schedCount++;
    }
  }
}

static void buildRulesJson(JsonObject root) {
  JsonObject c   = root["climate"].to<JsonObject>();
  c["enabled"]   = s_climate.enabled;
  c["device"]    = "ac_living";  // для сумісності з хабом
  c["trigger"]   = s_climate.trigger;
  c["target"]    = s_climate.target;
  c["mode"]      = s_climate.mode;
  c["auto_off"]  = s_climate.auto_off;
  c["off_below"] = s_climate.off_below;

  JsonArray arr = root["schedules"].to<JsonArray>();
  for (int i = 0; i < s_schedCount; i++) {
    const SchedRule& s = s_scheds[i];
    JsonObject r = arr.add<JsonObject>();
    r["enabled"] = s.enabled;
    r["time"]    = s.time;
    r["device"]  = "ac_living";
    r["action"]  = s.action;
    if (strcmp(s.action, "off") != 0) {
      JsonObject set = r["set"].to<JsonObject>();
      if (s.mode[0] != 0)   set["mode"]  = s.mode;
      if (s.temp >= 0)      set["temp"]  = s.temp;
      if (s.fan >= 0)       set["fan"]   = s.fan;
      if (s.quiet >= 0)     set["quiet"] = (bool)s.quiet;
      if (s.sleepMode >= 0) set["sleep"] = (bool)s.sleepMode;
    }
  }
}

static bool saveRules() {
  JsonDocument doc;
  buildRulesJson(doc.to<JsonObject>());
  File f = LittleFS.open(kRulesFile, "w");
  if (!f) return false;
  serializeJson(doc, f);
  f.close();
  return true;
}

void autoInit() {
  for (int i = 0; i < kMaxSched; i++) s_schedFired[i] = -1;
  File f = LittleFS.open(kRulesFile, "r");
  if (!f) return;  // правил ще нема — стартуємо з типових (все вимкнено)
  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, f);
  f.close();
  if (e || !doc.is<JsonObject>()) {
    Serial.println("🤖 [AUTO] ⚠ /auto.json пошкоджено — типові правила");
    return;
  }
  applyRules(doc.as<JsonObject>());
  Serial.printf("🤖 [AUTO] правила завантажено: клімат=%s, розкладів=%d\n",
                s_climate.enabled ? "УВІМК" : "вимк", s_schedCount);
}

bool autoSetRules(const String& body) {
  JsonDocument doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) return false;
  if (!doc.is<JsonObject>()) return false;
  applyRules(doc.as<JsonObject>());
  bool ok = saveRules();
  if (ok) s_rulesDirty = true;  // сигнал для MQTT: перепублікувати правила
  return ok;
}

// ── клімат-контроль ──────────────────────────────────────────────────
static void climateTick(const AcStatus& st) {
  if (!s_climate.enabled) { s_weTurnedItOn = false; return; }
  if (!st.valid || st.roomTemp <= -100) return;  // нема кімнатної температури

  bool  on   = (st.Pow != 0);
  float room = st.roomTemp;

  if (!on && room >= s_climate.trigger) {
    if (acSetPower(true, s_climate.target, acModeFromName(s_climate.mode))) {
      s_weTurnedItOn = true;
      Serial.printf("🤖 [AUTO] 🌡 %.0f°C >= %.0f°C -> УВІМКНУВ %d°C (%s)\n",
                    room, s_climate.trigger, s_climate.target, s_climate.mode);
    }
    return;
  }
  if (on && s_climate.auto_off && s_weTurnedItOn && room <= s_climate.off_below) {
    if (acSetPower(false, s_climate.target, acModeFromName(s_climate.mode))) {
      s_weTurnedItOn = false;
      Serial.printf("🤖 [AUTO] 🌡 %.0f°C <= %.0f°C -> ВИМКНУВ\n",
                    room, s_climate.off_below);
    }
    return;
  }
  if (!on) s_weTurnedItOn = false;  // людина вимкнула вручну — не сперечаємось
}

// ── розклади ─────────────────────────────────────────────────────────
static void fireSchedule(const SchedRule& s) {
  if (strcmp(s.action, "off") == 0) {
    const char* opts[] = {"Pow"};
    int vals[]         = {0};
    if (acSendCmd(opts, vals, 1))
      Serial.printf("🤖 [AUTO] ⏰ %s -> вимкнено\n", s.time);
    return;
  }
  // "on" або "set": збираємо лише задані поля
  const char* opts[8];
  int vals[8];
  size_t n = 0;
  if (strcmp(s.action, "on") == 0) { opts[n] = "Pow"; vals[n++] = 1; }
  if (s.mode[0] != 0) { opts[n] = "Mod"; vals[n++] = acModeFromName(s.mode); }
  if (s.temp >= 0) {
    opts[n] = "SetTem"; vals[n++] = constrain(s.temp, 16, 30);
    opts[n] = "TemUn";  vals[n++] = 0;  // °C
  }
  if (s.fan >= 0)       { opts[n] = "WdSpd";  vals[n++] = s.fan; }
  if (s.quiet >= 0)     { opts[n] = "Quiet";  vals[n++] = s.quiet; }
  if (s.sleepMode >= 0) {  // сон: SwhSlp + SlpMod (дубль для нових прошивок)
    opts[n] = "SwhSlp"; vals[n++] = s.sleepMode;
    opts[n] = "SlpMod"; vals[n++] = s.sleepMode;
  }
  if (n == 0) return;
  if (acSendCmd(opts, vals, n))
    Serial.printf("🤖 [AUTO] ⏰ %s -> %s (%u парам.)\n", s.time, s.action, (unsigned)n);
}

static void schedulesTick() {
  char hhmm[6];
  int32_t minuteEpoch = 0;
  if (!getHHMM(hhmm, sizeof(hhmm), &minuteEpoch)) return;  // ще нема часу
  for (int i = 0; i < s_schedCount; i++) {
    SchedRule& s = s_scheds[i];
    if (!s.enabled || strcmp(s.time, hhmm) != 0) continue;
    if (s_schedFired[i] == minuteEpoch) continue;  // цієї хвилини вже було
    s_schedFired[i] = minuteEpoch;
    fireSchedule(s);
  }
}

// ── головний тік (виклик із loop) ────────────────────────────────────
void autoTick() {
  // якщо кондиціонер офлайн — опитуємо рідше, щоб не гальмувати веб
  uint32_t interval = acIsOnline() ? 10000UL : 30000UL;
  if (s_ticked && millis() - s_lastTickMs < interval) return;
  s_ticked = true;
  s_lastTickMs = millis();
  if (WiFi.status() != WL_CONNECTED) return;

  AcStatus st;
  if (acReadStatus(st)) {
    s_lastStatus = st;
    s_stateDirty = true;  // свіжий стан (в т.ч. зміни з пульта) -> у MQTT
    climateTick(st);
  }
  schedulesTick();
}

// ── Hub-сумісний API (як у hub/main.py, для гарного веб-UI) ──────────
String autoGetRulesJson() {
  JsonDocument doc;
  buildRulesJson(doc.to<JsonObject>());
  String out;
  serializeJson(doc, out);
  return out;
}

// Заповнити об'єкт стану кондиціонера (спільне для /api/devices і MQTT)
static void fillStateObj(JsonObject s) {
  const AcStatus& st = s_lastStatus;
  s["on"]      = (st.Pow != 0);
  s["temp"]    = st.SetTem;
  s["mode"]    = acModeName(st.Mod);
  s["fan"]     = st.WdSpd;
  s["swing"]   = st.SwUpDn;
  s["swing_h"] = st.SwingLfRig;
  s["quiet"]   = (st.Quiet != 0);
  s["eco"]     = (st.SvSt != 0);
  s["sleep"]   = (st.SwhSlp != 0);
  s["xfan"]    = (st.Blo != 0);
  s["health"]  = (st.Health != 0);
  s["light"]   = (st.Lig != 0);
  s["turbo"]   = (st.Tur != 0);
  if (st.valid && st.roomTemp > -100) s["room_temp"] = st.roomTemp;
  else                                s["room_temp"] = nullptr;
}

// GET /api/devices — один пристрій: кондиціонер (стан з кешу)
String apiDevicesJson() {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  JsonObject d = arr.add<JsonObject>();
  d["id"]   = "ac_living";
  d["kind"] = "ac";
  d["name"] = "Кондиціонер";
  d["icon"] = "❄️";
  d["room"] = "Вітальня";
  fillStateObj(d["state"].to<JsonObject>());
  String out;
  serializeJson(doc, out);
  return out;
}

// Лише об'єкт стану {on,temp,mode,...} — для публікації в MQTT
String acStateJson() {
  JsonDocument doc;
  fillStateObj(doc.to<JsonObject>());
  String out;
  serializeJson(doc, out);
  return out;
}

// Прапорець "стан змінився" — MQTT-цикл забирає його й публікує свіжий стан.
bool autoTakeDirty() {
  bool d = s_stateDirty;
  s_stateDirty = false;
  return d;
}

// Прапорець "правила змінилися" (локальний веб POST або MQTT rules/set).
bool autoTakeRulesDirty() {
  bool d = s_rulesDirty;
  s_rulesDirty = false;
  return d;
}

// POST /api/devices/ac_living/toggle — перемкнути живлення
bool apiToggleDevice() {
  int newPow = (s_lastStatus.Pow != 0) ? 0 : 1;
  const char* opts[] = {"Pow"};
  int vals[]         = {newPow};
  bool ok = acSendCmd(opts, vals, 1);
  if (ok) { s_lastStatus.Pow = newPow; s_stateDirty = true; }
  return ok;
}

// POST /api/devices/ac_living/set — часткові зміни стану (JSON-тіло).
// Зливаємо в кеш і шлемо ОДНУ повну команду, як apply() у hub/devices/gree.py.
bool apiSetDevice(const String& body) {
  JsonDocument doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) return false;
  if (!doc.is<JsonObject>()) return false;
  JsonObject o = doc.as<JsonObject>();

  AcStatus st = s_lastStatus;  // старт з кешу, поверх — зміни з тіла
  if (!o["on"].isNull())      st.Pow    = o["on"].as<bool>() ? 1 : 0;
  if (o["temp"].is<int>())    st.SetTem = constrain(o["temp"].as<int>(), 16, 30);
  if (o["mode"].is<const char*>())
    st.Mod = acModeFromName(o["mode"].as<const char*>());
  if (o["fan"].is<int>())     st.WdSpd      = o["fan"].as<int>();
  if (o["swing"].is<int>())   st.SwUpDn     = o["swing"].as<int>();
  if (o["swing_h"].is<int>()) st.SwingLfRig = o["swing_h"].as<int>();
  if (!o["light"].isNull())   st.Lig    = o["light"].as<bool>() ? 1 : 0;
  if (!o["turbo"].isNull())   st.Tur    = o["turbo"].as<bool>() ? 1 : 0;
  if (!o["quiet"].isNull())   st.Quiet  = o["quiet"].as<bool>() ? 1 : 0;
  if (!o["eco"].isNull())     st.SvSt   = o["eco"].as<bool>() ? 1 : 0;
  if (!o["sleep"].isNull())   st.SwhSlp = o["sleep"].as<bool>() ? 1 : 0;
  if (!o["xfan"].isNull())    st.Blo    = o["xfan"].as<bool>() ? 1 : 0;
  if (!o["health"].isNull())  st.Health = o["health"].as<bool>() ? 1 : 0;

  // Повний список opt, як у gree.py apply() (SlpMod дублює SwhSlp)
  const char* opts[] = {"Pow", "Mod", "SetTem", "TemUn", "WdSpd",
                        "SwUpDn", "SwingLfRig", "Lig", "Tur",
                        "Quiet", "SvSt", "SwhSlp", "SlpMod", "Blo", "Health"};
  int vals[] = {st.Pow, st.Mod, st.SetTem, 0, st.WdSpd,
                st.SwUpDn, st.SwingLfRig, st.Lig, st.Tur,
                st.Quiet, st.SvSt, st.SwhSlp, st.SwhSlp, st.Blo, st.Health};
  bool ok = acSendCmd(opts, vals, 15);
  if (ok) { s_lastStatus = st; s_stateDirty = true; }  // кеш = задане (roomTemp зберігся)
  return ok;
}

// ── JSON для веб-сторінки ────────────────────────────────────────────
String autoGetJson() {
  JsonDocument doc;
  buildRulesJson(doc["rules"].to<JsonObject>());

  JsonObject ac = doc["ac"].to<JsonObject>();
  ac["online"] = acIsOnline();
  ac["ip"]     = acGetIP().toString();
  if (s_lastStatus.valid) {
    ac["on"]       = (s_lastStatus.Pow != 0);
    ac["mode"]     = acModeName(s_lastStatus.Mod);
    ac["set_temp"] = s_lastStatus.SetTem;
    ac["fan"]      = s_lastStatus.WdSpd;
    ac["quiet"]    = (s_lastStatus.Quiet != 0);
    ac["sleep"]    = (s_lastStatus.SwhSlp != 0);
    ac["turbo"]    = (s_lastStatus.Tur != 0);
    ac["light"]    = (s_lastStatus.Lig != 0);
    if (s_lastStatus.roomTemp > -100) ac["room_temp"] = s_lastStatus.roomTemp;
  }
  doc["we_turned_on"] = s_weTurnedItOn;

  char hhmm[6];
  if (getHHMM(hhmm, sizeof(hhmm), nullptr)) doc["time"] = hhmm;

  String out;
  serializeJson(doc, out);
  return out;
}
