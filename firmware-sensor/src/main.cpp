/*
 * Датчик клімату на ESP32 — тільки температура й вологість (DHT22)
 * --------------------------------------------------
 * Плата підключається до WiFi і віддає останні показники по HTTP:
 *   GET /climate  ->  {"ok":true,"temp":23.4,"humid":47.0}
 *   GET /         ->  те саме
 * Якщо датчик мовчить довше хвилини: {"ok":false,"status":"TIMEOUT"}
 *
 * Формат /climate той самий, що був у старій прошивці, тож хаб
 * (hub/devices/climate.py) працює без змін.
 * Адреса в мережі: IP з монітора порту (закріпи його в роутері).
 * mDNS (room-sensor.local) НЕ вмикати: з ним DHT22 постійно дає TIMEOUT.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DHTesp.h>     // датчик температури й вологості DHT22
#include "secrets.h"    // WiFi (НЕ в git; див. secrets.example.h)

const uint8_t kDhtPin   = 27;              // DATA (OUT) датчика DHT22 -> GPIO27
const char*   kHostname = "room-sensor";   // ім'я плати у списку пристроїв роутера
const unsigned long kStaleMs = 60000;      // скільки вважати показник свіжим

DHTesp dht;
WebServer server(80);
float g_temp = NAN;                 // °C, остання вдала температура
float g_humid = NAN;                // %, остання вдала вологість
unsigned long g_lastOk = 0;         // millis() останнього вдалого читання
const char* g_dhtStatus = "?";      // остання діагностика датчика

void handleClimate() {
  bool fresh = g_lastOk != 0 && millis() - g_lastOk < kStaleMs;
  if (!fresh) {
    String s = String("{\"ok\":false,\"status\":\"") + g_dhtStatus + "\"}";
    server.send(200, "application/json", s);
    return;
  }
  char buf[64];
  snprintf(buf, sizeof(buf), "{\"ok\":true,\"temp\":%.1f,\"humid\":%.1f}",
           g_temp, g_humid);
  server.send(200, "application/json", buf);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  dht.setup(kDhtPin, DHTesp::DHT22);
  pinMode(kDhtPin, INPUT_PULLUP);   // підтягувач (рятує, якщо на платі нема резистора)

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(kHostname);
  WiFi.setSleep(false);             // без енергозбереження — плата завжди відповідає
  WiFi.setAutoReconnect(true);
  WiFi.begin(SECRET_WIFI_SSID, SECRET_WIFI_PASS);
  Serial.printf("Підключаюсь до WiFi \"%s\"", SECRET_WIFI_SSID);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
    if (millis() - start > 30000) {   // 30 с без WiFi — пробуємо з нуля
      Serial.println("\n⚠ Не вдалось підключитись (пароль?) — перезапуск");
      ESP.restart();
    }
  }
  Serial.printf("\n✅ Підключено: http://%s/climate\n", WiFi.localIP().toString().c_str());

  server.on("/", HTTP_GET, handleClimate);
  server.on("/climate", HTTP_GET, handleClimate);
  server.begin();
}

void loop() {
  server.handleClient();

  // DHT22: читаємо раз на ~3 с (мінімум для DHT22 — 2 с). Інколи датчик
  // віддає NAN — тоді лишаємо попереднє значення, поки воно не застаріло.
  static unsigned long lastDht = 0;
  if (millis() - lastDht > 3000) {
    lastDht = millis();
    TempAndHumidity th = dht.getTempAndHumidity();
    g_dhtStatus = dht.getStatusString();   // "OK" / "TIMEOUT" / "CHECKSUM"
    if (!isnan(th.temperature) && !isnan(th.humidity)) {
      g_temp = th.temperature;
      g_humid = th.humidity;
      g_lastOk = millis();
    }
  }

  // Сторож WiFi: раз на 5 сек перевіряємо з'єднання, якщо нема — відновлюємо
  static unsigned long lastWifiCheck = 0;
  if (millis() - lastWifiCheck > 5000) {
    lastWifiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("⚠ WiFi відпав — перепідключаюсь...");
      WiFi.reconnect();
    }
  }
}
