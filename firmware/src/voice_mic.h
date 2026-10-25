#pragma once
// Мікрофон INMP441 (I2S) з голосовою активацією (VAD).
// Слухає постійно; коли чує мовлення — записує кілька секунд і шле на хаб
// (/api/voice?src=mic). Хаб виконує команду ЛИШЕ якщо почалась зі слова «Адольф».
void voiceMicInit();   // виклик у setup()
void voiceMicLoop();   // виклик у loop() (неблокуючий, окрім часу самого запису)
// Діагностика для /mic: пік гучності з останнього запиту (і скидає його),
// фон і частоту. Дозволяє налаштувати чутливість по Wi-Fi, без serial.
void voiceMicStats(int* peak, float* floorv, int* sr);
void voiceMicSetThreshold(float mult, float base);   // /micset — крутити поріг по Wi-Fi
float voiceMicThreshold();                           // поточний поріг (для /mic)
void voiceMicSetGain(int g);                         // /micset?gain= — крутити підсилення
void voiceMicSetEnabled(bool e);                     // /micset?enable=0|1 — вимкнути/увімкнути мікрофон
bool voiceMicIsEnabled();
