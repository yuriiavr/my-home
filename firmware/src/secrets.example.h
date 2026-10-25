/*
 * ═══════════════ ШАБЛОН СЕКРЕТІВ (комітиться в git) ═══════════════
 * Скопіюй цей файл як secrets.h (поруч, у src/) і заповни СВОЇ значення.
 * secrets.h у .gitignore — реальні паролі ніколи не потраплять у репозиторій.
 * ═══════════════════════════════════════════════════════════════════
 */
#pragma once

// ── WiFi ──
#define SECRET_WIFI_SSID "MY_WIFI"
#define SECRET_WIFI_PASS "MY_WIFI_PASSWORD"

// ── Хмарний MQTT-брокер (напр. безкоштовний HiveMQ Cloud, TLS 8883) ──
// Поки SECRET_MQTT_HOST == "REPLACE_HOST", MQTT вимкнено (no-op) —
// плата збирається і працює локально без брокера.
#define SECRET_MQTT_HOST "REPLACE_HOST"          // Cluster URL з панелі брокера
#define SECRET_MQTT_USER "REPLACE_USER"
#define SECRET_MQTT_PASS "REPLACE_PASS"
#define SECRET_MQTT_BASE "smarthome/REPLACE_TOKEN"  // вигадай унікальний суфікс

// ── Кондиціонер Gree/Cooper&Hunter (MAC і ключ дає процедура bind) ──
#define SECRET_AC_MAC "REPLACE_MAC"              // напр. "9424b8xxxxxx"
#define SECRET_AC_KEY "REPLACE_AC_KEY"           // 16 символів з bind
#define SECRET_AC_IP  192, 168, 0, 109           // IP кондиціонера (кома-формат IPAddress)

// ── Пароль бездротової прошивки (ArduinoOTA) — вигадай свій ──
#define SECRET_OTA_PASS "REPLACE_OTA_PASS"

// ── Адреса хаба (куди мікрофон INMP441 шле записаний голос) ──
#define SECRET_HUB_URL "http://192.168.0.109:8000/api/voice"
