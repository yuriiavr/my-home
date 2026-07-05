/*
 * Розумний ІЧ-пульт на ESP32 — ЕТАП 1
 * --------------------------------------------------
 * Що вміє:
 *   1) Записати ІЧ-сигнал з будь-якого пульта ("навчання")
 *   2) Зберегти його в пам'ять під назвою (LittleFS, формат JSON)
 *   3) Відтворити збережений сигнал за командою
 *   4) Простий веб-інтерфейс для тестів з ПК/телефону (в одній WiFi)
 *
 * Етап 2 (MQTT для керування з вулиці) додамо поверх цього файлу.
 *
 * Сигнали зберігаємо у "сирому" вигляді (raw timing) — так працює
 * з БУДЬ-ЯКИМ пультом і кондиціонером, не залежимо від протоколу.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <IRremoteESP8266.h>
#include <IRrecv.h>
#include <IRsend.h>
#include <IRutils.h>
#include <ir_Gree.h>   // рідний протокол Gree (= Cooper&Hunter)
#include <IRac.h>      // універсальний відправник для "полювання" на протокол
#include <time.h>
#include <ArduinoOTA.h>   // бездротова прошивка (firmware + файлова система)
#include "gree_ac.h"      // WiFi-клієнт кондиціонера (UDP 7000, AES-GCM)
#include "auto_engine.h"  // автономні автоматизації (клімат + розклади)
#include "mqtt_client.h"  // захищений хмарний MQTT (керування з інтернету)
#include "secrets.h"      // паролі/ключі (НЕ в git; див. secrets.example.h)

// ======================= НАЛАШТУВАННЯ =======================
// 1) WiFi-мережа задається у src/secrets.h:
const char* WIFI_SSID = SECRET_WIFI_SSID;
const char* WIFI_PASS = SECRET_WIFI_PASS;

// 2) Ноги (GPIO), куди підключені компоненти:
const uint16_t kRecvPin  = 15;  // OUT ІЧ-приймача (VS1838B) -> GPIO15
const uint16_t kIrLedPin = 4;   // ІЧ-світлодіод (через транзистор) -> GPIO4
// ============================================================

// Великий буфер, щоб ловити довгі сигнали кондиціонерів:
const uint16_t kCaptureBufferSize = 2048;  // збільшено: запас проти шуму й довгих AC-протоколів
const uint8_t  kTimeout = 100;  // мс тиші = кінець сигналу (100 = захоплюємо AC-пакети з повторами цілком)
const uint32_t kLearnTimeoutMs = 30000;  // скільки чекаємо сигнал при навчанні

IRrecv irrecv(kRecvPin, kCaptureBufferSize, kTimeout, true);
IRsend irsend(kIrLedPin);
IRGreeAC ac(kIrLedPin);   // керування кондиціонером Cooper&Hunter (Gree)
IRac irac(kIrLedPin);     // універсальний AC-відправник (режим полювання)
decode_results results;

// Список протоколів для перебору (найпоширеніші кондиціонери)
const decode_type_t kHuntList[] = {
  decode_type_t::GREE,          // 0
  decode_type_t::KELVINATOR,    // 1  (теж родина Gree, стар. C&H)
  decode_type_t::MIDEA,         // 2
  decode_type_t::COOLIX,        // 3
  decode_type_t::TCL112AC,      // 4
  decode_type_t::DAIKIN,        // 5
  decode_type_t::MITSUBISHI_AC, // 6
  decode_type_t::SAMSUNG_AC,    // 7
  decode_type_t::LG,            // 8
  decode_type_t::HAIER_AC_YRW02,// 9
  decode_type_t::PANASONIC_AC,  // 10
  decode_type_t::FUJITSU_AC,    // 11
  decode_type_t::TOSHIBA_AC,    // 12
  decode_type_t::ELECTRA_AC,    // 13 (AUX та клони)
  decode_type_t::DAIKIN2,       // 14
  decode_type_t::HITACHI_AC,    // 15
};
const int kHuntTotal = sizeof(kHuntList) / sizeof(kHuntList[0]);

WebServer server(80);
const char* CMD_DIR = "/cmd";   // тут лежать файли команд: /cmd/<назва>.json

// Статистика приймача (видно через /irstat без Serial-монітора)
uint32_t irCount = 0;
String   irLastProto = "-";
uint16_t irLastLen = 0;

// ---- Допоміжне: безпечна назва файлу з вводу користувача ----
String sanitize(const String& in) {
  String out;
  for (size_t i = 0; i < in.length() && out.length() < 32; i++) {
    char c = in[i];
    if (isalnum((unsigned char)c) || c == '_' || c == '-') out += c;
    else if (c == ' ') out += '_';
  }
  if (out.length() == 0) out = "cmd";
  return out;
}
String cmdPath(const String& name) { return String(CMD_DIR) + "/" + name + ".json"; }

// ======================= ВЕБ-СТОРІНКА =======================
const char INDEX_HTML[] PROGMEM = R"HTML(
<!DOCTYPE html><html lang="uk"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Розумний ІЧ-пульт</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:520px;margin:24px auto;padding:0 16px;background:#0f1115;color:#e8eaed}
  h1{font-size:20px} input,button{font-size:16px;padding:10px;border-radius:8px;border:1px solid #333}
  input{width:60%;background:#1b1e24;color:#e8eaed} button{cursor:pointer;border:0;background:#2d6cdf;color:#fff;margin-left:6px}
  .row{display:flex;align-items:center;justify-content:space-between;background:#1b1e24;padding:10px 12px;border-radius:8px;margin:6px 0}
  .send{background:#2e9e5b}.del{background:#b13a3a}.muted{color:#9aa0a6;font-size:13px}
  #status{min-height:20px;margin:10px 0;color:#9aa0a6}
  input[type=checkbox],input[type=time]{width:auto} h4{margin:14px 0 6px}
  select.sel{font-size:14px;padding:6px;border-radius:8px;background:#1b1e24;color:#e8eaed;border:1px solid #333}
</style></head><body>
<h1>📡 Розумний ІЧ-пульт</h1>
<p class="muted">Наведи пульт на приймач, впиши назву й натисни «Записати».</p>
<div><input id="name" placeholder="напр. tv_on або ac_cool"><button onclick="learn()">Записати</button></div>
<div id="status"></div>
<h3>❄️ Кондиціонер (Cooper&amp;Hunter)</h3>
<div class="row"><span>Охолодження <input id="actemp" type="number" value="24" min="16" max="30" style="width:56px"> °C
  <select id="acmodel" style="font-size:16px;padding:8px;border-radius:8px;background:#1b1e24;color:#e8eaed;border:1px solid #333">
    <option value="1">v1</option><option value="2">v2</option></select></span><span>
  <button class="send" onclick="acCmd('on')">Увімкнути</button>
  <button class="del" onclick="acCmd('off')">Вимкнути</button></span></div>
<h3>🎯 Пошук протоколу</h3>
<p class="muted">Наведи діод на кондиціонер, тисни «Спробувати» знову й знову. Запам'ятай, на якій назві він пікнув!</p>
<div class="row"><span>№ <input id="huntn" type="number" value="0" min="0" max="15" style="width:56px"></span><span>
  <button class="send" onclick="hunt()">Спробувати</button></span></div>
<h3>🤖 Автоматизації (автономні, на платі)</h3>
<div id="acstate" class="muted">Стан кондиціонера: завантаження...</div>
<div class="row"><span>❄️ По WiFi: <input id="wtemp" type="number" value="24" min="16" max="30" style="width:56px"> °C</span><span>
  <button class="send" onclick="acw('on')">Увімкнути</button>
  <button class="del" onclick="acw('off')">Вимкнути</button></span></div>
<h4>🌡 Клімат-контроль</h4>
<div class="row"><label><input type="checkbox" id="c_en"> Увімкнено</label>
  <span>Режим <select id="c_md" class="sel"></select></span></div>
<div class="row"><span>Вмикати при ≥ <input id="c_tr" type="number" style="width:56px"> °C</span>
  <span>Ціль <input id="c_tg" type="number" min="16" max="30" style="width:56px"> °C</span></div>
<div class="row"><label><input type="checkbox" id="c_ao"> Вимикати, коли охолоне до ≤</label>
  <span><input id="c_ob" type="number" style="width:56px"> °C</span></div>
<h4>⏰ Розклади</h4>
<div id="scheds"></div>
<div style="margin:8px 0"><button onclick="addSched()">+ Додати розклад</button>
  <button class="send" onclick="saveAuto()">💾 Зберегти автоматизації</button></div>
<h3>Збережені команди</h3>
<div id="list"></div>
<script>
const $=s=>document.querySelector(s);
function st(t){$('#status').textContent=t;}
async function learn(){
  const n=$('#name').value.trim(); if(!n){st('Впиши назву');return;}
  st('⏳ Чекаю сигнал з пульта (10 сек)... натисни кнопку на пульті');
  try{const r=await fetch('/learn?name='+encodeURIComponent(n),{method:'POST'});const j=await r.json();
    st(j.ok?('✅ Записано "'+j.name+'" ('+j.len+' імпульсів)'):('❌ '+(j.error||'помилка')));
    $('#name').value=''; load();
  }catch(e){st('❌ Помилка зв\'язку');}
}
async function send(n){st('Відправляю '+n+'...');const r=await fetch('/send?name='+encodeURIComponent(n),{method:'POST'});const j=await r.json();st(j.ok?('📤 Відправлено '+n):'❌ помилка');}
async function hunt(){const el=document.querySelector('#huntn');const n=+el.value;
  st('📡 Шлю протокол #'+n+'...');
  try{const r=await fetch('/hunt?n='+n,{method:'POST'});const j=await r.json();
    if(j.ok){st('📡 #'+j.n+': '+j.name+' — дивись на кондиціонер! ('+(j.n+1)+'/'+j.total+')');el.value=n+1;}
    else{st('✅ Список закінчився ('+j.total+' протоколів). Почни з 0 або скажи Клоду.');}
  }catch(e){st('❌ зв\'язок');}}
async function acCmd(p){st('AC '+p+'...');const t=document.querySelector('#actemp').value;
  const m=document.querySelector('#acmodel').value;
  const r=await fetch('/ac?power='+p+'&temp='+t+'&model='+m,{method:'POST'});const j=await r.json();
  st(j.ok?('❄️ AC '+(p==='on'?('увімкнено, '+j.temp+'°C'):'вимкнено')+' (v'+m+')'):'❌ помилка');}
async function del(n){if(!confirm('Видалити '+n+'?'))return;await fetch('/delete?name='+encodeURIComponent(n),{method:'POST'});load();}
async function load(){const r=await fetch('/list');const a=await r.json();
  $('#list').innerHTML=a.length?a.map(n=>`<div class="row"><span>${n}</span><span>
    <button class="send" onclick="send('${n}')">▶ Надіслати</button>
    <button class="del" onclick="del('${n}')">✕</button></span></div>`).join(''):'<p class="muted">Поки порожньо</p>';}
// ─── Автономні автоматизації (виконуються на платі) ───
let AUTO={climate:{enabled:false,device:'ac_living',trigger:27,target:24,mode:'cool',auto_off:true,off_below:23},schedules:[]};
const MN={auto:'Авто',cool:'Холод',dry:'Осушення',fan:'Вентилятор',heat:'Тепло'};
function modeOpts(v){return Object.keys(MN).map(k=>`<option value="${k}"${k===v?' selected':''}>${MN[k]}</option>`).join('');}
function showAc(j){const a=j.ac||{};
  if(!a.online){$('#acstate').textContent='Кондиціонер: ❌ недоступний по WiFi ('+(a.ip||'?')+')';return;}
  const rt=(typeof a.room_temp==='number')?(a.room_temp+'°C'):'—';
  $('#acstate').textContent='Кондиціонер ('+(a.ip||'')+'): '+(a.on?'🟢 УВІМК':'⚪ вимк')+' • задано '+a.set_temp+'°C • '+(MN[a.mode]||a.mode)+' • в кімнаті: '+rt+(j.time?' • ⏱ '+j.time:'');}
function fillClimate(){const c=AUTO.climate||{};
  $('#c_en').checked=!!c.enabled;$('#c_md').innerHTML=modeOpts(c.mode||'cool');
  $('#c_tr').value=c.trigger!==undefined?c.trigger:27;$('#c_tg').value=c.target!==undefined?c.target:24;
  $('#c_ao').checked=c.auto_off!==false;$('#c_ob').value=c.off_below!==undefined?c.off_below:23;}
function renderScheds(){const b=$('#scheds');
  b.innerHTML=AUTO.schedules.length?AUTO.schedules.map((s,i)=>{const t=s.set||{};
    const setUi=s.action==='off'?'':`
      <select class="sel" onchange="updSet(${i},'mode',this.value)">${modeOpts(t.mode||'cool')}</select>
      <input type="number" value="${t.temp!==undefined?t.temp:24}" min="16" max="30" style="width:52px" onchange="updSet(${i},'temp',+this.value)">°C
      <select class="sel" onchange="updSet(${i},'fan',+this.value)">${[0,1,2,3,4,5].map(f=>`<option value="${f}"${(t.fan||0)===f?' selected':''}>${f===0?'💨Авто':'💨'+f}</option>`).join('')}</select>
      <label><input type="checkbox" ${t.quiet?'checked':''} onchange="updSet(${i},'quiet',this.checked)">🤫</label>
      <label><input type="checkbox" ${t.sleep?'checked':''} onchange="updSet(${i},'sleep',this.checked)">😴</label>`;
    return `<div class="row" style="flex-wrap:wrap;gap:6px">
      <label title="Увімкнено"><input type="checkbox" ${s.enabled!==false?'checked':''} onchange="updS(${i},'enabled',this.checked)"></label>
      <input type="time" value="${s.time||'00:00'}" onchange="updS(${i},'time',this.value)">
      <select class="sel" onchange="updS(${i},'action',this.value)">
        <option value="on"${s.action==='on'?' selected':''}>Увімкнути</option>
        <option value="off"${s.action==='off'?' selected':''}>Вимкнути</option>
        <option value="set"${s.action==='set'||!s.action?' selected':''}>Налаштувати</option></select>
      ${setUi}<button class="del" onclick="delSched(${i})">✕</button></div>`;}).join('')
    :'<p class="muted">Розкладів поки немає</p>';}
function updS(i,k,v){AUTO.schedules[i][k]=v;if(k==='action')renderScheds();}
function updSet(i,k,v){if(!AUTO.schedules[i].set)AUTO.schedules[i].set={};AUTO.schedules[i].set[k]=v;}
function addSched(){AUTO.schedules.push({enabled:true,time:'22:30',device:'ac_living',action:'on',set:{mode:'cool',temp:25,fan:0,quiet:false,sleep:false}});renderScheds();}
function delSched(i){AUTO.schedules.splice(i,1);renderScheds();}
async function saveAuto(){
  AUTO.climate={enabled:$('#c_en').checked,device:'ac_living',trigger:+$('#c_tr').value,target:+$('#c_tg').value,
    mode:$('#c_md').value,auto_off:$('#c_ao').checked,off_below:+$('#c_ob').value};
  st('💾 Зберігаю...');
  try{const r=await fetch('/auto',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(AUTO)});
    const j=await r.json();st(j.ok?'✅ Автоматизації збережено (працюють на платі автономно)':'❌ Помилка збереження');
  }catch(e){st('❌ Помилка зв\'язку');}}
async function loadAuto(){try{const r=await fetch('/auto');const j=await r.json();
  if(j.rules)AUTO=j.rules;if(!AUTO.schedules)AUTO.schedules=[];
  fillClimate();renderScheds();showAc(j);}catch(e){$('#acstate').textContent='Кондиціонер: помилка зв\'язку з платою';}}
async function refreshAc(){try{const r=await fetch('/auto');const j=await r.json();showAc(j);}catch(e){}}
async function acw(p){st('❄️ WiFi: '+(p==='on'?'вмикаю':'вимикаю')+'...');
  try{const r=await fetch('/acwifi?power='+p+'&temp='+$('#wtemp').value+'&mode=cool',{method:'POST'});
    const j=await r.json();
    st(j.ok?('❄️ По WiFi '+(p==='on'?('увімкнено, '+$('#wtemp').value+'°C'):'вимкнено')):'❌ Кондиціонер не відповів');
    setTimeout(refreshAc,1500);
  }catch(e){st('❌ Помилка зв\'язку');}}
load();loadAuto();setInterval(refreshAc,15000);
</script></body></html>
)HTML";

// ======================= ОБРОБНИКИ HTTP =======================
// Віддати файл з LittleFS (гарний UI, як у PC-хаба). true = віддали.
bool serveFsFile(const char* path, const char* ctype) {
  if (!LittleFS.exists(path)) return false;
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  server.streamFile(f, ctype);
  f.close();
  return true;
}

// "/" — якщо у LittleFS залито UI хаба (pio run -t uploadfs) — віддаємо його,
// інакше запасна вбудована сторінка (PROGMEM), щоб плата працювала одразу.
void handleRoot() {
  if (serveFsFile("/index.html", "text/html")) return;
  server.send_P(200, "text/html", INDEX_HTML);
}

// Навчання: чекаємо сигнал і зберігаємо у файл
void handleLearn() {
  if (!server.hasArg("name")) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"no name\"}"); return; }
  String name = sanitize(server.arg("name"));

  irrecv.resume();
  unsigned long start = millis();
  bool got = false;
  while (millis() - start < kLearnTimeoutMs) {
    if (irrecv.decode(&results)) { got = true; break; }
    delay(10);
  }
  if (!got) {
    server.send(504, "application/json", "{\"ok\":false,\"error\":\"timeout — сигнал не спіймано\"}");
    return;
  }

  uint16_t length = getCorrectedRawLength(&results);
  uint16_t* raw = resultToRawArray(&results);

  JsonDocument doc;
  doc["freq"] = 38;  // майже всі побутові пульти = 38 кГц
  JsonArray arr = doc["raw"].to<JsonArray>();
  for (uint16_t i = 0; i < length; i++) arr.add(raw[i]);
  delete[] raw;

  File f = LittleFS.open(cmdPath(name), "w");
  if (!f) { server.send(500, "application/json", "{\"ok\":false,\"error\":\"fs write\"}"); return; }
  serializeJson(doc, f);
  f.close();
  irrecv.resume();

  String out = String("{\"ok\":true,\"name\":\"") + name + "\",\"len\":" + length + "}";
  server.send(200, "application/json", out);
}

// Відправка збереженого сигналу
void handleSend() {
  if (!server.hasArg("name")) { server.send(400, "application/json", "{\"ok\":false}"); return; }
  String name = sanitize(server.arg("name"));
  File f = LittleFS.open(cmdPath(name), "r");
  if (!f) { server.send(404, "application/json", "{\"ok\":false,\"error\":\"not found\"}"); return; }

  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, f);
  f.close();
  if (e) { server.send(500, "application/json", "{\"ok\":false,\"error\":\"parse\"}"); return; }

  uint16_t freq = doc["freq"] | 38;
  JsonArray arr = doc["raw"].as<JsonArray>();
  uint16_t n = arr.size();
  if (n == 0) { server.send(500, "application/json", "{\"ok\":false,\"error\":\"empty\"}"); return; }

  uint16_t* raw = new uint16_t[n];
  uint16_t i = 0;
  for (JsonVariant v : arr) raw[i++] = v.as<uint16_t>();
  irsend.sendRaw(raw, n, freq);
  delete[] raw;

  server.send(200, "application/json", "{\"ok\":true}");
}

// Список збережених команд
void handleList() {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  File dir = LittleFS.open(CMD_DIR);
  if (dir && dir.isDirectory()) {
    File file = dir.openNextFile();
    while (file) {
      String n = String(file.name());
      int slash = n.lastIndexOf('/'); if (slash >= 0) n = n.substring(slash + 1);
      if (n.endsWith(".json")) n = n.substring(0, n.length() - 5);
      arr.add(n);
      file = dir.openNextFile();
    }
  }
  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
}

// Видалення команди
void handleDelete() {
  if (!server.hasArg("name")) { server.send(400, "application/json", "{\"ok\":false}"); return; }
  String name = sanitize(server.arg("name"));
  LittleFS.remove(cmdPath(name));
  server.send(200, "application/json", "{\"ok\":true}");
}

// ======================= SETUP / LOOP =======================
void setup() {
  Serial.begin(115200);
  delay(300);

  irsend.begin();
  ac.begin();                      // Gree/Cooper&Hunter
  irrecv.setUnknownThreshold(12);  // тимчасово нижче: щоб бачити луну від власного діода
  irrecv.enableIRIn(true);         // true = внутрішній підтягувач (діагностика обриву лінії)

  if (!LittleFS.begin(true)) Serial.println("⚠ LittleFS не змонтувався");
  if (!LittleFS.exists(CMD_DIR)) LittleFS.mkdir(CMD_DIR);

  Serial.printf("Підключаюсь до WiFi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);          // вимкнути енергозбереження WiFi (інакше плата "засинає" і не відповідає)
  WiFi.setAutoReconnect(true);   // якщо WiFi відпаде — плата сама перепідключиться
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\n✅ Підключено. Відкрий у браузері: http://%s\n", WiFi.localIP().toString().c_str());

  // Час по NTP (потрібен для розкладів). TZ = Україна (з літнім часом).
  configTzTime("EET-2EEST,M3.5.0/3,M10.5.0/4", "pool.ntp.org", "time.google.com");

  // Бездротова прошивка (OTA): і firmware, і файлова система (U_FS).
  // Далі оновлюємо через `pio run -e esp32dev_ota -t upload` (і -t uploadfs).
  ArduinoOTA.setHostname("rozumnyj-dim");
  ArduinoOTA.setPassword(SECRET_OTA_PASS);
  ArduinoOTA.onStart([]() {
    // під час запису FS треба відмонтувати LittleFS, щоб не пошкодити
    // (на ядрі ESP32 команда для файлової системи зветься U_SPIFFS)
    if (ArduinoOTA.getCommand() == U_SPIFFS) LittleFS.end();
    Serial.println("⬆️ OTA: старт оновлення...");
  });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("⬆️ OTA: помилка %u\n", e); });
  ArduinoOTA.begin();

  greeInit();   // WiFi-клієнт кондиціонера (підхопити збережений IP)
  autoInit();   // завантажити правила автоматизацій з LittleFS
  mqttInit();   // захищений хмарний MQTT (no-op, поки не задано брокер)

  server.on("/", handleRoot);
  // Статика гарного UI (лежить у LittleFS після `pio run -t uploadfs`)
  server.on("/style.css", HTTP_GET, []() {
    if (!serveFsFile("/style.css", "text/css"))
      server.send(404, "text/plain", "uploadfs?");
  });
  server.on("/app.js", HTTP_GET, []() {
    if (!serveFsFile("/app.js", "application/javascript"))
      server.send(404, "text/plain", "uploadfs?");
  });
  server.on("/learn",  HTTP_POST, handleLearn);
  server.on("/send",   HTTP_POST, handleSend);
  server.on("/list",   HTTP_GET,  handleList);
  server.on("/delete", HTTP_POST, handleDelete);
  // КОНДИЦІОНЕР (Gree/Cooper&Hunter): /ac?power=on&temp=24[&model=2]
  // model=1 (типово) = YAW1F, model=2 = YBOFB — два підваріанти Gree
  server.on("/ac", HTTP_POST, []() {
    bool on = server.arg("power") == "on";
    int temp = server.hasArg("temp") ? server.arg("temp").toInt() : 24;
    if (temp < 16) temp = 16;
    if (temp > 30) temp = 30;
    int model = server.hasArg("model") ? server.arg("model").toInt() : 1;
    ac.setModel(model == 2 ? gree_ac_remote_model_t::YBOFB
                           : gree_ac_remote_model_t::YAW1F);
    if (on) {
      ac.on();
      ac.setMode(kGreeCool);
      ac.setTemp(temp);
      ac.setFan(kGreeFanAuto);
    } else {
      ac.off();
    }
    ac.send();
    Serial.printf("❄️ AC: %s, %d°C\n", on ? "ON" : "OFF", temp);
    String out = String("{\"ok\":true,\"power\":\"") + (on ? "on" : "off") + "\",\"temp\":" + temp + "}";
    server.send(200, "application/json", out);
  });
  // ДІАГНОСТИКА: показує, що збережено в команді (довжина, частота)
  server.on("/info", HTTP_GET, []() {
    if (!server.hasArg("name")) { server.send(400, "application/json", "{\"ok\":false}"); return; }
    String name = sanitize(server.arg("name"));
    File f = LittleFS.open(cmdPath(name), "r");
    if (!f) { server.send(404, "application/json", "{\"ok\":false,\"error\":\"not found\"}"); return; }
    JsonDocument doc;
    DeserializationError e = deserializeJson(doc, f);
    f.close();
    if (e) { server.send(500, "application/json", "{\"ok\":false,\"error\":\"parse\"}"); return; }
    String out = String("{\"ok\":true,\"name\":\"") + name +
                 "\",\"freq\":" + (int)(doc["freq"] | 38) +
                 ",\"len\":" + doc["raw"].as<JsonArray>().size() + "}";
    server.send(200, "application/json", out);
  });
  // ДІАГНОСТИКА: вольтметр на IO34 (АЦП). ~4095 = 3.3В+, ~0 = нема напруги
  server.on("/adc", HTTP_GET, []() {
    String s = "{\"io34\":[";
    for (int i = 0; i < 5; i++) {
      s += String(analogRead(34));
      if (i < 4) s += ",";
      delay(20);
    }
    s += "]}";
    server.send(200, "application/json", s);
  });
  // ПОЛЮВАННЯ: шле "увімкнись, охолодження 24" протоколом №n зі списку
  server.on("/hunt", HTTP_POST, []() {
    int n = server.hasArg("n") ? server.arg("n").toInt() : -1;
    if (n < 0 || n >= kHuntTotal) {
      server.send(400, "application/json",
                  String("{\"ok\":false,\"total\":") + kHuntTotal + "}");
      return;
    }
    stdAc::state_t st;
    st.protocol = kHuntList[n];
    st.model    = 1;
    st.power    = true;
    st.mode     = stdAc::opmode_t::kCool;
    st.degrees  = 24;
    st.celsius  = true;
    st.fanspeed = stdAc::fanspeed_t::kAuto;
    st.swingv   = stdAc::swingv_t::kOff;
    st.swingh   = stdAc::swingh_t::kOff;
    st.quiet = st.turbo = st.econo = st.light = st.filter = st.clean = st.beep = false;
    st.sleep = -1;
    st.clock = -1;
    bool ok = irac.sendAc(st);
    String name = typeToString(kHuntList[n]);
    Serial.printf("🎯 HUNT #%d: %s -> %s\n", n, name.c_str(), ok ? "sent" : "FAIL");
    String out = String("{\"ok\":") + (ok ? "true" : "false") +
                 ",\"n\":" + n + ",\"name\":\"" + name +
                 "\",\"total\":" + kHuntTotal + "}";
    server.send(200, "application/json", out);
  });
  // ДІАГНОСТИКА: скільки ІЧ-сигналів почуто з моменту старту + останній протокол
  server.on("/irstat", HTTP_GET, []() {
    String out = String("{\"count\":") + irCount +
                 ",\"last_proto\":\"" + irLastProto +
                 "\",\"last_len\":" + irLastLen + "}";
    server.send(200, "application/json", out);
  });
  // ДІАГНОСТИКА: рівень лінії приймача (10 вимірів). Живий VS1838B у спокої = всі 1
  server.on("/pin", HTTP_GET, []() {
    String s = "{\"io15\":[";
    for (int i = 0; i < 10; i++) {
      s += String(digitalRead(kRecvPin));
      if (i < 9) s += ",";
      delay(5);
    }
    s += "]}";
    server.send(200, "application/json", s);
  });
  // ДІАГНОСТИКА: віддає повний "сирий" запис команди (JSON з таймінгами)
  server.on("/dump", HTTP_GET, []() {
    if (!server.hasArg("name")) { server.send(400, "application/json", "{\"ok\":false}"); return; }
    String name = sanitize(server.arg("name"));
    File f = LittleFS.open(cmdPath(name), "r");
    if (!f) { server.send(404, "application/json", "{\"ok\":false}"); return; }
    server.streamFile(f, "application/json");
    f.close();
  });
  // ДІАГНОСТИКА: вмикає ІЧ-діод і ОДНОЧАСНО міряє напругу на IO34
  // Повертає виміри під час УВІМК і після ВИМК — видно, чи реагує точка на сигнал
  server.on("/led_test", HTTP_POST, []() {
    digitalWrite(kIrLedPin, HIGH);
    delay(100);
    String s = "{\"during_on\":[";
    for (int i = 0; i < 5; i++) { s += String(analogRead(34)); if (i < 4) s += ","; delay(50); }
    delay(300);
    digitalWrite(kIrLedPin, LOW);
    delay(100);
    s += "],\"after_off\":[";
    for (int i = 0; i < 3; i++) { s += String(analogRead(34)); if (i < 2) s += ","; delay(20); }
    s += "]}";
    server.send(200, "application/json", s);
  });
  // ─── АВТОМАТИЗАЦІЇ (автономні, на платі) ───
  // GET /auto: правила + поточний стан кондиціонера + кімнатна температура
  server.on("/auto", HTTP_GET, []() {
    server.send(200, "application/json", autoGetJson());
  });
  // POST /auto: зберегти правила (JSON у тілі, схема як у хаба)
  server.on("/auto", HTTP_POST, []() {
    if (!server.hasArg("plain")) {
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"no body\"}");
      return;
    }
    if (autoSetRules(server.arg("plain")))
      server.send(200, "application/json", "{\"ok\":true}");
    else
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
  });
  // КОНДИЦІОНЕР ПО WIFI (напряму, без ІЧ): /acwifi?power=on|off&temp=24&mode=cool
  server.on("/acwifi", HTTP_POST, []() {
    String p = server.arg("power");
    int temp = server.hasArg("temp") ? server.arg("temp").toInt() : 24;
    int mode = acModeFromName(server.hasArg("mode") ? server.arg("mode").c_str() : "cool");
    bool ok = false;
    if (p == "on")       ok = acSetPower(true, temp, mode);
    else if (p == "off") ok = acSetPower(false, temp, mode);
    else {
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"power=on|off\"}");
      return;
    }
    Serial.printf("❄️ [WIFI-AC] %s %d°C -> %s\n", p.c_str(), temp, ok ? "ok" : "FAIL");
    String out = String("{\"ok\":") + (ok ? "true" : "false") +
                 ",\"power\":\"" + p + "\",\"temp\":" + temp + "}";
    server.send(ok ? 200 : 502, "application/json", out);
  });
  // ─── HUB-СУМІСНИЙ API (той самий, що в hub/main.py — для гарного UI) ───
  // GET /api/devices — список пристроїв (тут один: кондиціонер)
  server.on("/api/devices", HTTP_GET, []() {
    server.send(200, "application/json", apiDevicesJson());
  });
  // POST /api/devices/ac_living/toggle — перемкнути живлення
  server.on("/api/devices/ac_living/toggle", HTTP_POST, []() {
    bool ok = apiToggleDevice();
    server.send(ok ? 200 : 502, "application/json",
                ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"ac offline\"}");
  });
  // POST /api/devices/ac_living/set — часткові зміни стану (JSON-тіло)
  server.on("/api/devices/ac_living/set", HTTP_POST, []() {
    if (!server.hasArg("plain")) {
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"no body\"}");
      return;
    }
    bool ok = apiSetDevice(server.arg("plain"));
    server.send(ok ? 200 : 502, "application/json",
                ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"ac offline or bad json\"}");
  });
  // GET/POST /api/automations — правила (та сама схема, що /auto)
  server.on("/api/automations", HTTP_GET, []() {
    server.send(200, "application/json", autoGetRulesJson());
  });
  server.on("/api/automations", HTTP_POST, []() {
    if (!server.hasArg("plain")) {
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"no body\"}");
      return;
    }
    if (autoSetRules(server.arg("plain")))
      server.send(200, "application/json", "{\"ok\":true}");
    else
      server.send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
  });

  // Універсальна статика: будь-який інший шлях пробуємо віддати з LittleFS
  // (manifest.webmanifest, іконки PWA, майбутні файли). Тип — за розширенням.
  server.onNotFound([]() {
    String path = server.uri();
    const char* ct = "application/octet-stream";
    if      (path.endsWith(".png"))          ct = "image/png";
    else if (path.endsWith(".svg"))          ct = "image/svg+xml";
    else if (path.endsWith(".webmanifest") ||
             path.endsWith(".json"))         ct = "application/json";
    else if (path.endsWith(".css"))          ct = "text/css";
    else if (path.endsWith(".js"))           ct = "application/javascript";
    else if (path.endsWith(".html"))         ct = "text/html";
    if (!serveFsFile(path.c_str(), ct))
      server.send(404, "text/plain", "not found");
  });

  server.begin();
}

void loop() {
  ArduinoOTA.handle();   // бездротова прошивка — раніше за все, неблокуюче
  server.handleClient();

  // ☁️ Хмарний MQTT: керування з інтернету (неблокуюче; no-op без брокера)
  mqttLoop();

  // 🤖 Автономні автоматизації: клімат + розклади (тік раз на ~10 с,
  // всередині сам стежить за millis і не блокує довше ~2 с)
  autoTick();

  // Сторож WiFi: раз на 5 сек перевіряємо з'єднання, якщо нема — відновлюємо
  static unsigned long lastWifiCheck = 0;
  if (millis() - lastWifiCheck > 5000) {
    lastWifiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("⚠ WiFi відпав — перепідключаюсь...");
      WiFi.reconnect();
    }
  }

  // ДІАГНОСТИКА: друкуємо все, що чує приймач + перші 16 таймінгів (мкс)
  if (irrecv.decode(&results)) {
    irCount++;
    irLastProto = typeToString(results.decode_type);
    irLastLen = getCorrectedRawLength(&results);
    Serial.printf("👂 proto=%s len=%d :: ", irLastProto.c_str(), irLastLen);
    for (uint16_t i = 1; i <= 16 && i < results.rawlen; i++)
      Serial.printf("%u ", results.rawbuf[i] * kRawTick);
    Serial.println();
    irrecv.resume();
  }
}
