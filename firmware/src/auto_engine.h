/*
 * Автономні автоматизації на платі (клімат-контроль + розклади).
 * Дзеркало hub/automations.py: та сама JSON-схема правил,
 * зберігаються у LittleFS /auto.json.
 */
#pragma once
#include <Arduino.h>
#include "gree_ac.h"

void autoInit();   // виклич після LittleFS.begin(): завантажує правила
void autoTick();   // виклич із loop(): сам тікає раз на ~10 с (millis-guard)

String autoGetJson();                   // {"rules":...,"ac":...,"time":"HH:MM"}
bool autoSetRules(const String& body);  // прийняти й зберегти правила (JSON)

// ── Hub-сумісний API (той самий, що в PC-хаба, для гарного веб-UI) ──
String autoGetRulesJson();              // GET  /api/automations — лише правила
String apiDevicesJson();                // GET  /api/devices — [{id,kind,...,state}]
bool apiToggleDevice();                 // POST /api/devices/ac_living/toggle
bool apiSetDevice(const String& body);  // POST /api/devices/ac_living/set

// ── Для MQTT ──
String acStateJson();       // об'єкт стану {on,temp,mode,...} (як у /api/devices)
bool autoTakeDirty();       // true один раз, якщо стан AC змінився з минулого виклику
bool autoTakeRulesDirty();  // true один раз, якщо ПРАВИЛА змінилися (веб/MQTT)
