// Мікрофон INMP441 (I2S) з голосовою активацією (VAD).
// Постійно слухає; коли рівень звуку піднімається над фоном — записує фразу
// (з невеликим «переролом», щоб не зрізати перший склад) і шле WAV на хаб.
// Хаб виконує команду ЛИШЕ якщо звучало «Адольф».
#include "voice_mic.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "secrets.h"

// ── Піни INMP441 ──
static const int PIN_WS  = 32;   // WS  (LRCLK)
static const int PIN_SCK = 14;   // SCK (BCLK)
static const int PIN_SD  = 33;   // SD  (дані)
static const i2s_port_t PORT = I2S_NUM_0;

// ── Звук ──
static const int  CHUNK = 256;         // семплів за одне читання
static int        GAIN_SHIFT = 12;     // 32→16 біт: МЕНШЕ = гучніше (регулюється по /micset?gain=)
static int        SR = 16000;          // частота (визначиться за наявною RAM)
static int        MAX_SAMP = 0;        // макс. семплів запису

// ── VAD (голосова активація) ──
static const int  START_MARGIN = 500;  // наскільки гучніше за шум = мовлення
static const int  SILENCE_MS   = 700;  // стільки тиші → кінець фрази
static const int  MIN_MS       = 700;  // коротше — вважаємо шумом, не шлемо
static const int  PREROLL_CH   = 8;    // ~130 мс до тригера (щоб зловити «А» в «Адольф»)
// Мовлення ТРИВАЛЕ; шумовий сплеск (клац, стук) — короткий. Тому пуск запису
// лише коли рівень тримається над порогом кілька кадрів поспіль. Це прибирає
// хибні спрацювання на шум (інакше плата шле сотні шумів і випалює квоту хаба).
static const int  NEED_CONSEC  = 6;    // кадрів поспіль > порога (~190 мс) щоб почати
static const unsigned long MIN_SEND_GAP_MS = 3000;  // не частіше, ніж раз на 3 с
// ЖОРСТКИЙ ліміт довжини запису: під час кіно/ТВ тиші не буває, тож запис міг би
// тягтись до кінця буфера — обрізаємо на 5 с (реально буфер ~3 с, це стеля).
static const unsigned long MAX_RECORD_MS = 5000;

static uint8_t*   buf = nullptr;       // 44 байти WAV-заголовку + PCM (суцільно для POST)
static bool       ready = false;
// Вимикач мікрофона. За замовчуванням УВІМКНЕНО: плата слухає завжди й шле кліпи
// на хаб; фільтр «Адольф» тепер на хабі (Vosk), він і вирішує, що пускати на Gemini.
// Аварійно вимкнути мікрофон можна по Wi-Fi: /micset?enable=0
static bool       micEnabled = true;
static float      noiseFloor = 300.0f;
// Поріг спрацювання = фон * THR_MULT + THR_BASE. Крутиться по Wi-Fi (/micset),
// щоб не перезаливати. Високий за замовчуванням, щоб не було хибних спрацювань.
static float      THR_MULT = 2.5f;
static float      THR_BASE = 1200.0f;  // за gain=12 з ФВЧ: фон ~300-500; поріг ~2000
static int32_t    winPeak = 0;         // пік гучності для /mic (скидається при читанні)
static int32_t    winPeakL = 0;        // діагностика: пік лівого каналу
static int32_t    winPeakR = 0;        // діагностика: пік правого каналу
#define DIAG_STEREO 0                  // 0 = робочий режим (запис+відправка); 1 = стерео-діагностика
static int16_t    preroll[PREROLL_CH][CHUNK];
static int        preIdx = 0;

// Фільтр високих частот (DC-blocker): y[n] = R*(y[n-1] + x[n] - x[n-1]).
// R=0.95 @16кГц ≈ зріз ~130 Гц: вирізає низькочастотний гул кімнати (кулер ПК,
// гудіння мережі 50 Гц), лишає голос (150–3000 Гц). Так голос виразно
// піднімається над фоном — інакше рівний гул забиває VAD.
static float hpX = 0.0f, hpY = 0.0f;
static const float HP_R = 0.95f;

// Прочитати CHUNK семплів; повертає к-сть, у *level — ПІК гучності (після ФВЧ).
static int readChunk(int16_t* out, int32_t* level) {
  int32_t raw[CHUNK];
  size_t br = 0;
  i2s_read(PORT, raw, sizeof(raw), &br, portMAX_DELAY);
  int n = br / sizeof(int32_t);
  int32_t peak = 0;
  for (int i = 0; i < n; i++) {
    float x = (float)(raw[i] >> GAIN_SHIFT);
    float y = HP_R * (hpY + x - hpX);   // ФВЧ: прибирає постійну складову + гул
    hpX = x; hpY = y;
    int32_t s = (int32_t)y;
    if (s > 32767) s = 32767; else if (s < -32768) s = -32768;
    out[i] = (int16_t)s;
    int32_t a = (s < 0 ? -s : s);
    if (a > peak) peak = a;     // ПІК (макс), а не середнє — краще відділяє голос від фону
  }
  *level = peak;
  return n;
}

static void wavHeader(uint8_t* h, int dataLen) {
  int riff = 36 + dataLen, br = SR * 2;
  memcpy(h, "RIFF", 4);
  h[4]=riff; h[5]=riff>>8; h[6]=riff>>16; h[7]=riff>>24;
  memcpy(h+8, "WAVEfmt ", 8);
  h[16]=16; h[17]=h[18]=h[19]=0;      // розмір fmt
  h[20]=1; h[21]=0;                    // PCM
  h[22]=1; h[23]=0;                    // моно
  h[24]=SR; h[25]=SR>>8; h[26]=SR>>16; h[27]=SR>>24;
  h[28]=br; h[29]=br>>8; h[30]=br>>16; h[31]=br>>24;
  h[32]=2; h[33]=0;                    // block align
  h[34]=16; h[35]=0;                   // біт на семпл
  memcpy(h+36, "data", 4);
  h[40]=dataLen; h[41]=dataLen>>8; h[42]=dataLen>>16; h[43]=dataLen>>24;
}

static void sendToHub(int nSamples) {
  if (WiFi.status() != WL_CONNECTED) return;
  int dataLen = nSamples * 2;
  wavHeader(buf, dataLen);
  HTTPClient http;
  http.begin(String(SECRET_HUB_URL) + "?src=mic");
  http.addHeader("Content-Type", "audio/wav");
  http.setTimeout(15000);
  int code = http.POST(buf, 44 + dataLen);
  Serial.printf("🎤 -> хаб: %d семплів, HTTP %d\n", nSamples, code);
  http.end();
}

void voiceMicInit() {
  // 16 кГц ОБОВʼЯЗКОВО (INMP441 на 8 кГц дає брудний сигнал/кашу). Буфер беремо
  // найбільший, що влазить у RAM (MQTT-TLS з'їдає купу): 3с→2.5с→2с на 16кГц,
  // і лише як зовсім тісно — 8 кГц. Драбина: перший вдалий malloc виграє.
  struct { int sr; int n; } cand[] = {
    {16000, 48000}, {16000, 40000}, {16000, 32000}, {8000, 32000}
  };
  for (auto& k : cand) {
    buf = (uint8_t*) malloc(44 + k.n * 2);
    if (buf) { SR = k.sr; MAX_SAMP = k.n; break; }
  }
  if (!buf) { Serial.println("🎤 мало RAM — мікрофон вимкнено"); return; }

  i2s_config_t c = {};
  c.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  c.sample_rate = SR;
  c.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;   // INMP441 віддає 24 біти в 32-бітних словах
#if DIAG_STEREO
  c.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;   // діагностика: слухаємо ОБИДВА канали
#else
  // ONLY_LEFT = повна тиша на цьому модулі, сигнал лише на ONLY_RIGHT (перевірено).
  c.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
#endif
  c.communication_format = I2S_COMM_FORMAT_STAND_I2S;  // стандарт для INMP441 (MSB-тест не допоміг)
  c.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  c.dma_buf_count = 6;
  c.dma_buf_len = CHUNK;
  c.use_apll = false;   // APLL не дав ефекту — лишаємо дефолт
  if (i2s_driver_install(PORT, &c, 0, NULL) != ESP_OK) {
    Serial.println("🎤 I2S install FAIL"); free(buf); buf = nullptr; return;
  }
  i2s_pin_config_t p = {};
  p.bck_io_num = PIN_SCK;
  p.ws_io_num = PIN_WS;
  p.data_out_num = I2S_PIN_NO_CHANGE;
  p.data_in_num = PIN_SD;
  i2s_set_pin(PORT, &p);
  i2s_zero_dma_buffer(PORT);
  ready = true;
  Serial.printf("🎤 мікрофон INMP441 готовий (%d Гц, до %d с)\n", SR, MAX_SAMP / SR);
}

void voiceMicLoop() {
  if (!ready) return;
  if (!micEnabled) return;   // мікрофон вимкнено (щоб не палити квоту Gemini)
#if DIAG_STEREO
  // ДІАГНОСТИКА: читаємо стерео, шукаємо, на якому каналі є сигнал.
  int32_t raw[CHUNK * 2];
  size_t br = 0;
  i2s_read(PORT, raw, sizeof(raw), &br, portMAX_DELAY);
  int frames = br / (int)(sizeof(int32_t) * 2);
  for (int i = 0; i < frames; i++) {
    int32_t l = raw[i * 2]     >> GAIN_SHIFT; if (l < 0) l = -l;
    int32_t r = raw[i * 2 + 1] >> GAIN_SHIFT; if (r < 0) r = -r;
    if (l > winPeakL) winPeakL = l;
    if (r > winPeakR) winPeakR = r;
  }
  return;
#endif
  int16_t chunk[CHUNK];
  int32_t level = 0;
  int n = readChunk(chunk, &level);

  // ДІАГНОСТИКА: раз на ~1 с друкуємо рівень — бачимо, що реально чує мікрофон.
  if (level > winPeak) winPeak = level;       // пік для /mic (Wi-Fi діагностика)
  static unsigned long dbgT = 0;
  static int32_t peak = 0;
  if (level > peak) peak = level;
  // Поріг «розумний» — ВІДНОСНО фону: голос має бути помітно гучніший за тишу.
  float thr = noiseFloor * THR_MULT + THR_BASE;
  if (millis() - dbgT > 1000) {
    dbgT = millis();
    Serial.printf("🎤 рівень зараз=%d пік=%d фон=%.0f поріг=%.0f\n",
                  (int)level, (int)peak, noiseFloor, thr);
    peak = 0;
  }

  memcpy(preroll[preIdx], chunk, n * 2);      // кільцевий прерол
  preIdx = (preIdx + 1) % PREROLL_CH;

  static int consec = 0;                       // кадрів поспіль над порогом
  static unsigned long lastSend = 0;           // коли востаннє слали (антифлуд)

  if (level <= thr) {                          // не мовлення
    consec = 0;
    // Фон вчимо ЛИШЕ з ТИХИХ кадрів (інакше голос, що трохи нижчий за поріг,
    // сам роздуває фон, і поріг тікає за голосом).
    if (level < noiseFloor * 2.0f + 400)
      noiseFloor = noiseFloor * 0.99f + level * 0.01f;
    if (noiseFloor < 80) noiseFloor = 80;
    return;
  }

  // Рівень над порогом. Але шумовий сплеск короткий — вимагаємо ТРИВАЛОСТІ:
  // лише коли тримається над порогом NEED_CONSEC кадрів поспіль -> це мовлення.
  consec++;
  if (consec < NEED_CONSEC) return;            // ще замало — можливо просто шум
  consec = 0;
  if (millis() - lastSend < MIN_SEND_GAP_MS)   // нещодавно вже слали — не флудимо
    return;
  lastSend = millis();

  // ── Мовлення: записуємо фразу ──
  Serial.printf("🎤 запис (рівень %d, фон %.0f)\n", (int)level, noiseFloor);
  int16_t* pcm = (int16_t*)(buf + 44);
  int written = 0;
  for (int k = 0; k < PREROLL_CH && written < MAX_SAMP - CHUNK; k++) {
    int idx = (preIdx + k) % PREROLL_CH;      // від найстарішого до найновішого
    memcpy(pcm + written, preroll[idx], CHUNK * 2);
    written += CHUNK;
  }
  int silence = 0;
  unsigned long recStart = millis();
  while (written < MAX_SAMP - CHUNK) {
    if (millis() - recStart >= MAX_RECORD_MS) break;   // стеля 5 с (кіно не замовкає)
    int32_t lv = 0;
    int m = readChunk(chunk, &lv);
    memcpy(pcm + written, chunk, m * 2);
    written += m;
    if (lv <= noiseFloor * THR_MULT + THR_BASE) {      // тиша (той самий поріг) -> кінець фрази
      silence += (m * 1000) / SR;
      if (silence >= SILENCE_MS) break;
    } else silence = 0;
  }
  float sec = written / (float)SR;
  Serial.printf("🎤 фраза %.1f с (%d семплів)\n", sec, written);
  if (written * 1000 / SR >= MIN_MS)          // надто короткий сплеск — ігноруємо
    sendToHub(written);
  i2s_zero_dma_buffer(PORT);
}

void voiceMicStats(int* peak, float* floorv, int* srOut) {
  *peak = winPeak;                 // рівень, який реально бачить VAD (для тюнінгу порогу)
  *floorv = noiseFloor;
  *srOut = SR;
  winPeak = 0; winPeakL = 0; winPeakR = 0;   // скидаємо для наступного запиту
}

void voiceMicSetThreshold(float mult, float base) {
  if (mult > 0) THR_MULT = mult;
  if (base >= 0) THR_BASE = base;
  Serial.printf("🎤 новий поріг: фон*%.1f + %.0f\n", THR_MULT, THR_BASE);
}

float voiceMicThreshold() { return noiseFloor * THR_MULT + THR_BASE; }

void voiceMicSetGain(int g) {
  if (g >= 8 && g <= 20) { GAIN_SHIFT = g; Serial.printf("🎤 нове підсилення: >>%d\n", g); }
}

void voiceMicSetEnabled(bool e) {
  micEnabled = e;
  if (e) i2s_zero_dma_buffer(PORT);   // почати з чистого буфера
  Serial.printf("🎤 мікрофон %s\n", e ? "УВІМКНЕНО" : "ВИМКНЕНО");
}
bool voiceMicIsEnabled() { return micEnabled; }
