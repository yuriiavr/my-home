/*
 * Захищений хмарний MQTT (TLS) — керування платою з інтернету,
 * навіть коли ПК вимкнено. Додаткова функція: не блокує ані веб-сервер,
 * ані 10-секундний автономний тік. Якщо брокер не налаштовано
 * (MQTT_HOST == "REPLACE_HOST") — усе стає no-op.
 */
#pragma once
#include <Arduino.h>

void mqttInit();          // виклич у setup() після WiFi + NTP
void mqttLoop();          // виклич у loop() (неблокуюче)
void mqttPublishState();  // опублікувати свіжий стан кондиціонера (retained)
