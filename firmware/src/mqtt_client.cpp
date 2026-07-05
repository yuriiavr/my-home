/*
 * Захищений хмарний MQTT (TLS 8883) через PubSubClient + WiFiClientSecure.
 *
 * Топіки (відносно MQTT_BASE):
 *   ${BASE}/ac/cmd    (підписка)  — вхідні команди, JSON: {"power":"on"|"off"}
 *                                   і/або будь-які ключі стану (temp, mode,
 *                                   fan, swing, swing_h, quiet, eco, sleep,
 *                                   xfan, health, light, turbo). Застосовуємо
 *                                   через apiSetDevice() з auto_engine.
 *   ${BASE}/ac/state  (публікація, retained) — той самий об'єкт стану, що й
 *                                   один пристрій у GET /api/devices.
 *   ${BASE}/rules     (публікація, retained) — правила автоматизацій, той
 *                                   самий JSON, що GET /api/automations.
 *   ${BASE}/rules/set (підписка)  — повний JSON правил; застосовуємо через
 *                                   autoSetRules() (та сама валідація, що
 *                                   POST /api/automations) і одразу
 *                                   перепубліковуємо ${BASE}/rules.
 *   ${BASE}/reboot    (підписка)  — payload "1" -> перезавантажити плату.
 *   ${BASE}/status    (публікація, retained) — "online" / "offline" (LWT).
 *
 * Публікація стану: після кожної команди (MQTT/веб/автоматизація — через
 * dirty-прапорець autoTakeDirty()) і періодично раз на 15 с. Правила —
 * після конекту і при кожній зміні (autoTakeRulesDirty()).
 */
#include "mqtt_client.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <string.h>

#include "auto_engine.h"
#include "secrets.h"  // креденшли брокера (НЕ в git; див. secrets.example.h)

// ── Конфіг брокера — значення живуть у src/secrets.h ──
// Поки SECRET_MQTT_HOST == "REPLACE_HOST" (як у secrets.example.h),
// MQTT вимкнено (no-op) — плата будується й працює без брокера.
static const char*    MQTT_HOST = SECRET_MQTT_HOST;
static const uint16_t MQTT_PORT = 8883;             // TLS
static const char*    MQTT_USER = SECRET_MQTT_USER;
static const char*    MQTT_PASS = SECRET_MQTT_PASS;
static const char*    MQTT_BASE = SECRET_MQTT_BASE; // простір топіків (унікальний)

static const uint32_t kReconnectEveryMs = 5000;   // не частіше 1 спроби / 5 с
static const uint32_t kPublishEveryMs   = 15000;  // періодична публікація стану

static WiFiClientSecure s_net;
static PubSubClient     s_mqtt(s_net);

static bool     s_enabled       = false;  // false, поки не налаштовано брокер
static bool     s_warned        = false;  // щоб лог "не налаштовано" був 1 раз
static uint32_t s_lastReconnect = 0;
static uint32_t s_lastPublish   = 0;
static String   s_topicCmd, s_topicState, s_topicStatus;
static String   s_topicRules, s_topicRulesSet, s_topicReboot;

static bool configured() { return strcmp(MQTT_HOST, "REPLACE_HOST") != 0; }

void mqttPublishState() {
  if (!s_enabled || !s_mqtt.connected()) return;
  String st = acStateJson();
  s_mqtt.publish(s_topicState.c_str(), st.c_str(), true);  // retained
  s_lastPublish = millis();
}

// Опублікувати правила автоматизацій (retained) — щоб хмарна PWA бачила
// той самий JSON, що й локальний GET /api/automations.
static void mqttPublishRules() {
  if (!s_enabled || !s_mqtt.connected()) return;
  String rules = autoGetRulesJson();
  if (!s_mqtt.publish(s_topicRules.c_str(), rules.c_str(), true))
    Serial.println("☁️ [MQTT] ⚠ rules не опубліковано (завеликий пакет?)");
}

// ── команда кондиціонеру (топік ac/cmd) ──────────────────────────────
static void handleAcCmd(const String& body) {
  // {"power":"on"|"off"} -> {"on":true|false}, далі — звичайний apiSetDevice()
  JsonDocument doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok || !doc.is<JsonObject>())
    return;
  if (doc["power"].is<const char*>()) {
    doc["on"] = (strcmp(doc["power"].as<const char*>(), "on") == 0);
    doc.remove("power");
  }
  String merged;
  serializeJson(doc, merged);

  Serial.printf("☁️ [MQTT] cmd -> %s\n", merged.c_str());
  apiSetDevice(merged);   // зливає в кеш і шле ОДНУ повну команду Gree
  mqttPublishState();     // одразу віддзеркалити новий стан
}

// ── вхідні повідомлення: розводимо за топіком ────────────────────────
static void onMessage(char* topic, uint8_t* payload, unsigned int len) {
  String body;
  body.reserve(len + 1);
  for (unsigned int i = 0; i < len; i++) body += (char)payload[i];

  if (s_topicRulesSet.equals(topic)) {
    // повний JSON правил — та сама валідація, що POST /api/automations
    if (autoSetRules(body)) {
      (void)autoTakeRulesDirty();  // спожити прапорець — публікуємо самі
      mqttPublishRules();          // всі клієнти одразу сходяться
      Serial.println("☁️ [MQTT] rules/set -> збережено й перепубліковано");
    } else {
      Serial.println("☁️ [MQTT] rules/set -> зіпсований JSON, ігнорую");
    }
    return;
  }

  if (s_topicReboot.equals(topic)) {
    if (body == "1") {
      Serial.println("☁️ [MQTT] reboot -> перезавантажуюсь...");
      s_mqtt.publish(s_topicStatus.c_str(), "offline", true);  // не чекати LWT
      s_mqtt.loop();   // проштовхнути пакет у мережу
      delay(500);
      ESP.restart();
    }
    return;
  }

  if (s_topicCmd.equals(topic)) handleAcCmd(body);
}

// ── неблокуюче (пере)підключення з бекофом ──────────────────────────
static void reconnect() {
  if (millis() - s_lastReconnect < kReconnectEveryMs) return;
  s_lastReconnect = millis();

  String cid = "esp32-hub-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  // LWT: якщо плата зникне, брокер сам опублікує "offline" (retained)
  if (s_mqtt.connect(cid.c_str(), MQTT_USER, MQTT_PASS,
                     s_topicStatus.c_str(), 0, true, "offline")) {
    s_mqtt.publish(s_topicStatus.c_str(), "online", true);  // retained
    s_mqtt.subscribe(s_topicCmd.c_str());
    s_mqtt.subscribe(s_topicRulesSet.c_str());
    s_mqtt.subscribe(s_topicReboot.c_str());
    mqttPublishState();
    mqttPublishRules();
    Serial.printf("☁️ [MQTT] підключено як %s\n", cid.c_str());
  } else {
    Serial.printf("☁️ [MQTT] не вдалось (rc=%d), повтор через 5с\n", s_mqtt.state());
  }
}

void mqttInit() {
  if (!configured()) {
    if (!s_warned) { Serial.println("☁️ MQTT: не налаштовано"); s_warned = true; }
    return;
  }
  s_enabled       = true;
  s_topicCmd      = String(MQTT_BASE) + "/ac/cmd";
  s_topicState    = String(MQTT_BASE) + "/ac/state";
  s_topicStatus   = String(MQTT_BASE) + "/status";
  s_topicRules    = String(MQTT_BASE) + "/rules";
  s_topicRulesSet = String(MQTT_BASE) + "/rules/set";
  s_topicReboot   = String(MQTT_BASE) + "/reboot";

  // setInsecure(): пропускаємо перевірку TLS-сертифіката брокера.
  // Прийнятно для хобі-проєкту (трафік усе одно шифрується); за бажанням
  // пізніше можна закласти кореневий CA через s_net.setCACert(...).
  s_net.setInsecure();
  s_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  s_mqtt.setBufferSize(2048);  // правила (до 10 розкладів) можуть перевищити 1024
  s_mqtt.setCallback(onMessage);
  Serial.printf("☁️ MQTT: %s:%u, база топіків \"%s\"\n", MQTT_HOST, MQTT_PORT, MQTT_BASE);
}

void mqttLoop() {
  if (!s_enabled) return;
  if (WiFi.status() != WL_CONNECTED) return;
  if (!s_mqtt.connected()) { reconnect(); return; }

  s_mqtt.loop();
  // публікуємо при зміні стану (команда/веб/автоматизація) або раз на 15с
  if (autoTakeDirty())                              mqttPublishState();
  else if (millis() - s_lastPublish > kPublishEveryMs) mqttPublishState();
  // правила змінилися (локальний веб POST /auto чи /api/automations) -> у хмару
  if (autoTakeRulesDirty()) mqttPublishRules();
}
