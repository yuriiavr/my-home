/*
 * Gree / Cooper&Hunter — WiFi-клієнт (локально, без хмари).
 * Протокол: UDP порт 7000, JSON, AES-128-GCM (нові прошивки 2022+).
 * Дзеркало hub/devices/gree.py, але на C++ (mbedtls з ядра ESP32).
 */
#pragma once
#include <Arduino.h>
#include <IPAddress.h>

// Поточний стан кондиціонера (відповідь на "status")
struct AcStatus {
  bool valid = false;   // чи вдалося прочитати
  int Pow = 0;          // 0/1 — живлення
  int Mod = 1;          // 0=auto 1=cool 2=dry 3=fan 4=heat
  int SetTem = 24;      // задана температура
  int WdSpd = 0;        // вентилятор: 0=авто, 1..5
  int SwUpDn = 0;       // жалюзі вгору-вниз
  int SwingLfRig = 0;   // жалюзі вліво-вправо
  int Lig = 1;          // підсвітка
  int Tur = 0;          // турбо
  int Quiet = 0;        // тихий режим
  int SvSt = 0;         // еко
  int SwhSlp = 0;       // сон
  int Blo = 0;          // X-Fan
  int Health = 0;       // іонізатор
  int TemSen = 0;       // датчик кімнатної температури (зсув +40)
  int roomTemp = -1000; // °C у кімнаті; -1000 = невідомо
};

void greeInit();  // виклич після LittleFS.begin(): підхоплює збережений IP

// Низькорівнева команда: opts = ["Pow","SetTem",...], vals = [1,24,...]
bool acSendCmd(const char* const opts[], const int vals[], size_t n);
// Прочитати реальний стан (двосторонній зв'язок)
bool acReadStatus(AcStatus& out);
// Зручне: увімкнути (з температурою і режимом 0..4) або вимкнути
bool acSetPower(bool on, int temp, int mode);

bool acIsOnline();    // чи відповідав кондиціонер останнім часом
IPAddress acGetIP();  // поточна адреса (може оновитись після rescan)

int acModeFromName(const char* name);  // "cool" -> 1 (auto/cool/dry/fan/heat)
const char* acModeName(int m);         // 1 -> "cool"
