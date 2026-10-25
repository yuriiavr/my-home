/* ═══ Розумний дім — ЄДИНИЙ вебзастосунок (мобільний дизайн) ═══
   Один і той самий код працює у трьох місцях:
     • Python-хаб (hub/main.py)        → HTTP-режим (/api)
     • Плата ESP32 (firmware/data)     → HTTP-режим (/api)
     • Хмара (Cloudflare Pages тощо)   → MQTT-режим (WSS-брокер)

   Вибір режиму — автоматично при старті:
     є window.HUB_CONFIG (файл config.js) і завантажена бібліотека mqtt
       → MQTT-режим (керування звідусіль через брокер);
     інакше → HTTP-режим (локальний /api на хабі чи платі).

   ⚠️ БЕЗПЕКА (тільки хмара): config.js з даними брокера НЕ лежить у git
   (шаблон — deploy-cloud/config.example.js) і при деплої видимий кожному,
   хто відкриє сайт. Створи окремий обмежений логін брокера для веб-клієнта
   і не публікуй адресу сайту. */

// ── Конфігурація транспорту ──
const CONFIG = window.HUB_CONFIG || {};
const USE_MQTT = !!(CONFIG.url && window.mqtt);

// ── Іконки (lucide) ──
const ICONS = {
  home: [['path',{d:'M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8'}],['path',{d:'M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'}]],
  timer: [['line',{x1:10,x2:14,y1:2,y2:2}],['line',{x1:12,x2:15,y1:14,y2:11}],['circle',{cx:12,cy:14,r:8}]],
  power: [['path',{d:'M12 2v10'}],['path',{d:'M18.4 6.6a9 9 0 1 1-12.77.04'}]],
  minus: [['path',{d:'M5 12h14'}]],
  plus: [['path',{d:'M5 12h14'}],['path',{d:'M12 5v14'}]],
  thermometer: [['path',{d:'M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z'}]],
  refresh: [['path',{d:'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8'}],['path',{d:'M21 3v5h-5'}],['path',{d:'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16'}],['path',{d:'M3 21v-5h5'}]],
  snowflake: [['line',{x1:2,x2:22,y1:12,y2:12}],['line',{x1:12,x2:12,y1:2,y2:22}],['path',{d:'m20 16-4-4 4-4'}],['path',{d:'m4 8 4 4-4 4'}],['path',{d:'m16 4-4 4-4-4'}],['path',{d:'m8 20 4-4 4 4'}]],
  droplet: [['path',{d:'M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z'}]],
  wind: [['path',{d:'M12.8 19.6A2 2 0 1 0 14 16H2'}],['path',{d:'M17.5 8a2.5 2.5 0 1 1 2 4H2'}],['path',{d:'M9.8 4.4A2 2 0 1 1 11 8H2'}]],
  flame: [['path',{d:'M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z'}]],
  tv: [['rect',{width:20,height:15,x:2,y:7,rx:2,ry:2}],['polyline',{points:'17 2 12 7 7 2'}]],
  lightbulb: [['path',{d:'M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5'}],['path',{d:'M9 18h6'}],['path',{d:'M10 22h4'}]],
  coffee: [['path',{d:'M10 2v2'}],['path',{d:'M14 2v2'}],['path',{d:'M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1'}],['path',{d:'M6 2v2'}]],
  chevron: [['path',{d:'m6 9 6 6 6-6'}]],
  sliders: [['line',{x1:4,x2:4,y1:21,y2:14}],['line',{x1:4,x2:4,y1:10,y2:3}],['line',{x1:12,x2:12,y1:21,y2:12}],['line',{x1:12,x2:12,y1:8,y2:3}],['line',{x1:20,x2:20,y1:21,y2:16}],['line',{x1:20,x2:20,y1:12,y2:3}],['line',{x1:2,x2:6,y1:14,y2:14}],['line',{x1:10,x2:14,y1:8,y2:8}],['line',{x1:18,x2:22,y1:16,y2:16}]],
  calendar: [['path',{d:'M8 2v4'}],['path',{d:'M16 2v4'}],['rect',{width:18,height:18,x:3,y:4,rx:2}],['path',{d:'M3 10h18'}]],
  trash: [['path',{d:'M3 6h18'}],['path',{d:'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'}],['line',{x1:10,x2:10,y1:11,y2:17}],['line',{x1:14,x2:14,y1:11,y2:17}]],
  lock: [['rect',{width:18,height:11,x:3,y:11,rx:2,ry:2}],['path',{d:'M7 11V7a5 5 0 0 1 10 0v4'}]],
  swingV: [['path',{d:'m7 15 5 5 5-5'}],['path',{d:'m7 9 5-5 5 5'}]],
  swingH: [['path',{d:'m15 7 5 5-5 5'}],['path',{d:'m9 7-5 5 5 5'}]],
  up: [['path',{d:'m18 15-6-6-6 6'}]],
  down: [['path',{d:'m6 9 6 6 6-6'}]],
  left: [['path',{d:'m15 18-6-6 6-6'}]],
  right: [['path',{d:'m9 18 6-6-6-6'}]],
  center: [['path',{d:'M5 12h14'}]],
};

function svg(name, size = 22, color = 'currentColor') {
  const specs = ICONS[name] || [];
  const inner = specs.map(([tag, attrs]) => {
    const a = Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(' ');
    return `<${tag} ${a}/>`;
  }).join('');
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;flex-shrink:0">${inner}</svg>`;
}

// ── Кольори (одна тема, як у дизайні) ──
const C = { panel: '#14181f', panel2: '#1d222b', border: 'rgba(255,255,255,0.08)', text: '#eef1f5', muted: '#98a2b0', faint: '#616b78', accent: '#5b8def', swOff: '#39414f', on: '#3ecf8e' };
const MODE_COLORS = { auto: '#5b8def', cool: '#5b8def', dry: '#49b6d6', fan: '#57d6b0', heat: '#f0883e' };
const MODE_LABELS = { auto: 'Авто', cool: 'Холод', dry: 'Осушення', fan: 'Вентиляція', heat: 'Тепло' };
// [ключ, коротка мітка для сегмента, іконка]
const MODES = [['auto','Авто','refresh'],['cool','Холод','snowflake'],['dry','Осуш.','droplet'],['fan','Вент.','wind'],['heat','Тепло','flame']];
const FAN_OPTS = [[0,'Авто'],[1,'1'],[2,'2'],[3,'3'],[4,'4'],[5,'5']];
const SWING_V_OPTS = [[0,'Фікс.','lock'],[1,'Авто','swingV'],[2,'Верх','up'],[4,'Центр','center'],[6,'Низ','down']];
const SWING_H_OPTS = [[0,'Фікс.','lock'],[1,'Авто','swingH'],[2,'Ліво','left'],[4,'Центр','center'],[6,'Право','right']];
const FEAT_OPTS = [['turbo','Турбо'],['quiet','Тихий режим'],['eco','Еко'],['sleep','Сон'],['xfan','Просушка'],['health','Іонізація'],['light','Підсвітка дисплея']];
const EMOJI_ICON = { '❄️':'snowflake', '📺':'tv', '💡':'lightbulb', '☕':'coffee' };

// ── Стан ──
const S = {
  tab: 'home',
  devices: [],        // пристрої: HTTP — усі з /api/devices; MQTT — лише кондиціонер
  rules: null,        // правила автоматизацій, або null поки не завантажені
  extraOpen: false,   // «Додаткові налаштування» AC розгорнуто
  editIdx: null,      // який розклад розгорнуто на редагування
  dragging: false,
  lastEditAt: 0,      // час останньої локальної правки правил (MQTT: щоб retained не затирав)
  conn: 'connecting', // 'connecting' | 'connected' | 'disconnected'
  boardStatus: null,  // MQTT: 'online' | 'offline' | null; HTTP: завжди null
  gotState: false,      // MQTT: чи прийшов хоч один ac/state
  everConnected: false, // чи були ми хоч раз «наживо» (для тексту «Відновлення…»)
  connStep: 0,          // індекс поточного повідомлення лоудера
};

// Запасний список пристроїв для редактора розкладів (MQTT-режим до першого стану).
const FALLBACK_DEVICES = [{ id: 'ac_living', name: 'Кондиціонер', room: 'Вітальня' }];
const editDevices = () => S.devices.length ? S.devices : FALLBACK_DEVICES;

const $ = s => document.querySelector(s);
const esc = t => String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ── Лоудер підключення (керується РЕАЛЬНИМ станом зв'язку) ──
const CONN_MSGS = ['Пошук хаба…', 'Автентифікація…', 'Синхронізація пристроїв…', 'Майже готово…'];
const RECONNECT_MSG = "Відновлення зв'язку…";
let connStepTimer = null, hideTimer = null;

// «Наживо» = справжнє з'єднання І дані. Лоудер видно, доки це НЕ так.
//   HTTP: останній poll /api/devices був успішним (S.conn === 'connected').
//   MQTT: сокет підключено ТА статус плати 'online' ТА прийшов хоч один ac/state.
function connLive() {
  if (NET.mode === 'http') return S.conn === 'connected';
  return S.conn === 'connected' && S.boardStatus === 'online' && S.gotState;
}

function renderLoaderMsg() {
  const el = $('#loaderMsg');
  if (!el) return;
  el.textContent = S.everConnected ? RECONNECT_MSG : CONN_MSGS[Math.min(CONN_MSGS.length - 1, S.connStep)];
}
function startMsgCycle() {
  if (connStepTimer) return;
  connStepTimer = setInterval(() => {
    S.connStep = Math.min(CONN_MSGS.length - 1, S.connStep + 1);
    renderLoaderMsg();
  }, 700);
}
function stopMsgCycle() { clearInterval(connStepTimer); connStepTimer = null; }

function showLoader() {
  const l = $('#loader');
  if (!l) return;
  clearTimeout(hideTimer);
  l.style.display = 'flex';
  l.style.opacity = '1';
  renderLoaderMsg();
  startMsgCycle();
}
function hideLoader() {
  const l = $('#loader');
  if (!l) return;
  stopMsgCycle();
  l.style.opacity = '0';
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => { if (connLive()) l.style.display = 'none'; }, 350);
}
// Єдина точка: показати/сховати лоудер за поточним станом зв'язку.
function updateLoader() {
  if (connLive()) { S.everConnected = true; hideLoader(); }
  else showLoader();
}

// ── Навігація / вкладки ──
const NAV = [['home','Дім','home'],['auto','Автоматизації','timer']];
function renderNav() {
  $('#bottomNav').innerHTML = NAV.map(([k, label, ic]) =>
    `<button class="nav-item ${S.tab===k?'active':''}" onclick="showTab('${k}')">${svg(ic, 23, S.tab===k?C.accent:C.faint)}<span>${label}</span></button>`).join('');
}
function showTab(k) {
  S.tab = k;
  $('#view-home').style.display = k === 'home' ? '' : 'none';
  $('#view-auto').style.display = k === 'auto' ? '' : 'none';
  renderNav();
  if (k === 'auto') { NET.refreshRules(); renderAuto(); }
}

// ── Годинник (щосекунди, укр. локаль) ──
function tickClock() {
  const now = new Date();
  const t = $('#clockTime'); if (t) t.textContent = now.toLocaleTimeString('uk-UA', { hour:'2-digit', minute:'2-digit', hour12:false });
  const wdEl = $('#clockWeekday'); if (wdEl) { let wd = now.toLocaleDateString('uk-UA', { weekday:'long' }); wdEl.textContent = wd.charAt(0).toUpperCase() + wd.slice(1); }
  const dEl = $('#clockDate'); if (dEl) dEl.textContent = now.toLocaleDateString('uk-UA', { day:'numeric', month:'long' });
}

/* ═══ ШАР ДАНИХ ═══════════════════════════════════════════════════════════
   Інтерфейс транспорту (єдина точка, де режими відрізняються):
     start()               — запустити зв'язок (poll або MQTT-підключення)
     toggleDevice(id)      — пристрій уже перемкнуто оптимістично в S
     setDevice(id, ch)     — зміни вже застосовано оптимістично в S
     pushRules()           — надіслати ПОВНИЙ S.rules (викликає saveRules)
     refreshRules()        — підтягнути правила при відкритті вкладки
   Все, що вище/нижче цього блоку — СПІЛЬНЕ для обох режимів.
   ═════════════════════════════════════════════════════════════════════════ */

function setConn(c) {
  if (S.conn === c) return;
  S.conn = c;
  updateLoader();
}

// Оптимістичні дії з UI (спільні), делегують у транспорт:
function toggleDev(id) {
  const d = S.devices.find(x => x.id === id);
  if (d) { d.state.on = !d.state.on; renderAll(); }
  NET.toggleDevice(id);
}
function setDev(id, changes) {
  const d = S.devices.find(x => x.id === id);
  if (d) { Object.assign(d.state, changes); renderAll(); }
  NET.setDevice(id, changes);
}
// Автозбереження правил з дебаунсом 400 мс (спільне для обох режимів).
let saveTimer = null;
function saveRules() {
  S.lastEditAt = Date.now();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { if (S.rules) NET.pushRules(); }, 400);
}

// ── HTTP-транспорт (локально: Python-хаб або сама плата) ──
function makeHttpTransport() {
  async function loadDevices() {
    if (S.dragging) return;
    try {
      const r = await fetch('/api/devices');
      if (!r.ok) throw new Error();
      S.devices = await r.json();
      setConn('connected');       // успішний poll → connLive() → ховаємо лоудер
      renderAll();
    } catch (e) { setConn('disconnected'); }  // збій poll → лоудер повертається
  }
  return {
    mode: 'http',
    start() { loadDevices(); setInterval(loadDevices, 5000); },
    toggleDevice(id) {
      fetch(`/api/devices/${id}/toggle`, { method:'POST' })
        .then(() => loadDevices())
        .catch(() => setConn('disconnected'));
    },
    setDevice(id, changes) {
      fetch(`/api/devices/${id}/set`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(changes),
      }).catch(() => setConn('disconnected'));
    },
    pushRules() {
      fetch('/api/automations', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(S.rules),
      }).catch(() => {});
    },
    async refreshRules() {
      try {
        const r = await fetch('/api/automations');
        S.rules = await r.json();
        if (S.tab === 'auto') renderAuto();
      } catch (e) {}
    },
  };
}

// ── MQTT-транспорт (звідусіль: через хмарний брокер по WSS) ──
function makeMqttTransport() {
  const T_STATE     = `${CONFIG.base}/ac/state`;    // ← стан кондиціонера (JSON) від плати
  const T_STATUS    = `${CONFIG.base}/status`;      // ← "online" / "offline" (LWT плати)
  const T_CMD       = `${CONFIG.base}/ac/cmd`;      // → команди до плати (JSON)
  const T_RULES     = `${CONFIG.base}/rules`;       // ← правила (retained JSON) від плати
  const T_RULES_SET = `${CONFIG.base}/rules/set`;   // → збереження правил (повний JSON, НЕ retained)
  let client = null;

  // Пристрій-кондиціонер із payload ac/state — та сама форма, що дає /api/devices.
  function buildAcDevice(st) {
    return {
      id: 'ac_living', kind: 'ac', name: 'Кондиціонер', icon: '❄️', room: 'Вітальня',
      state: {
        on: !!st.on, temp: st.temp, mode: st.mode, fan: st.fan,
        swing: st.swing, swing_h: st.swing_h,
        quiet: st.quiet, eco: st.eco, sleep: st.sleep, xfan: st.xfan,
        health: st.health, light: st.light, turbo: st.turbo,
        room_temp: st.room_temp,
      },
    };
  }

  function onMessage(topic, payload) {
    const text = payload.toString();
    if (topic === T_STATUS) {
      const v = text.trim();
      if (v === 'online' || v === 'offline') S.boardStatus = v;
      updateLoader();                        // статус плати впливає на «наживо»
      if (S.tab === 'auto') renderAuto();    // оновити примітку про офлайн-плату
      return;
    }
    if (topic === T_STATE) {
      try {
        const st = JSON.parse(text);
        S.devices = [buildAcDevice(st)];
        S.gotState = true;
        updateLoader();                      // отримали стан → можливо ховаємо лоудер
        if (!S.dragging) renderAll();        // не перемальовуємо під час перетягування
      } catch (e) { /* некоректний payload — ігноруємо, без логів */ }
      return;
    }
    if (topic === T_RULES) {
      // Канонічні правила з плати (retained). Не застосовуємо, якщо користувач
      // редагував правила протягом останніх 3 с — щоб не затерти зміни посеред
      // редагування (echo прийде після дебаунсу збереження).
      if (Date.now() - S.lastEditAt < 3000) return;
      try {
        const rules = JSON.parse(text);
        if (rules && typeof rules === 'object') {
          S.rules = rules;
          if (S.tab === 'auto' && !S.dragging) renderAuto();
        }
      } catch (e) { /* некоректний payload — ігноруємо */ }
      return;
    }
  }

  function publish(topic, obj, opts) {
    if (!client || S.conn !== 'connected') return;
    try { client.publish(topic, JSON.stringify(obj), opts || { qos: 0 }); } catch (e) {}
  }

  return {
    mode: 'mqtt',
    start() {
      setConn('connecting');
      client = mqtt.connect(CONFIG.url, {
        username: CONFIG.username,
        password: CONFIG.password,
        clientId: 'web_' + Math.random().toString(16).slice(2, 10),
        clean: true,
        reconnectPeriod: 3000,   // авто-перепідключення кожні 3 с
        connectTimeout: 15000,
        keepalive: 30,
      });
      client.on('connect', () => {
        setConn('connected');
        client.subscribe([T_STATE, T_STATUS, T_RULES], { qos: 0 });
      });
      client.on('reconnect', () => setConn('connecting'));
      client.on('close',     () => setConn('disconnected'));
      client.on('offline',   () => setConn('disconnected'));
      client.on('error',     () => setConn('disconnected')); // без логів секретів
      client.on('message', onMessage);
    },
    toggleDevice(id) {
      // Стан уже перемкнуто оптимістично — публікуємо НОВЕ значення.
      const d = S.devices.find(x => x.id === id);
      publish(T_CMD, { power: (d ? d.state.on : true) ? 'on' : 'off' });
    },
    setDevice(id, changes) {
      // Ключ 'on' (наприклад при виборі режиму) → 'power' для плати.
      const cmd = {};
      for (const [k, v] of Object.entries(changes)) {
        if (k === 'on') cmd.power = v ? 'on' : 'off';
        else cmd[k] = v;
      }
      publish(T_CMD, cmd);
    },
    pushRules() { publish(T_RULES_SET, S.rules, { qos: 1, retain: false }); },
    refreshRules() { /* правила приходять retained-повідомленням самі */ },
  };
}

const NET = USE_MQTT ? makeMqttTransport() : makeHttpTransport();

/* ═══ Далі — СПІЛЬНИЙ інтерфейс (однаковий для HTTP і MQTT) ═══ */

const acDev = () => S.devices.find(d => d.kind === 'ac');
const sw = on => `<span class="sw ${on?'on':''}"><span class="knob"></span></span>`;

// ── Геометрія кругового термостата ──
function pol(a, r) { const rad = a * Math.PI / 180; return { x: 120 + r * Math.cos(rad), y: 120 + r * Math.sin(rad) }; }
function arc(a0, a1) {
  const R = 96; const s = pol(a0, R), e = pol(a1, R);
  const large = (a1 - a0) > 180 ? 1 : 0;
  return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${R} ${R} 0 ${large} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
}

// ── Інфо-картки (час + температура в кімнаті) ──
function renderInfoCards() {
  const ac = acDev();
  const rt = ac && ac.state.room_temp != null ? ac.state.room_temp : '—';
  // Вологість з датчика клімату на платі (DHT22), якщо є
  const cs = S.devices.find(d => d.kind === 'sensor');
  const hum = cs && cs.state.humid != null ? cs.state.humid : null;
  const now = new Date();
  const timeStr = now.toLocaleTimeString('uk-UA', { hour:'2-digit', minute:'2-digit', hour12:false });
  let wd = now.toLocaleDateString('uk-UA', { weekday:'long' }); wd = wd.charAt(0).toUpperCase() + wd.slice(1);
  const dateStr = now.toLocaleDateString('uk-UA', { day:'numeric', month:'long' });
  $('#infoCards').innerHTML = `
    <div class="info-card">
      <div class="info-time" id="clockTime">${timeStr}</div>
      <div class="info-date"><span id="clockWeekday">${wd}</span>, <span id="clockDate">${dateStr}</span></div>
    </div>
    <div class="info-card">
      <div class="info-room-cap">${svg('thermometer',14,C.accent)}<span>У кімнаті</span></div>
      <div class="info-room-val" id="roomTempVal">${rt}<span class="deg">°C</span></div>
      ${hum != null ? `<div class="info-room-hum" style="font-size:13px;color:${C.muted};margin-top:2px">💧 ${hum}% вологість</div>` : ''}
    </div>`;
}

// ── Сегментовані ряди ──
function modeSeg(cur, fn, dim) {
  return `<div class="seg-row">${MODES.map(([k, label, ic]) => {
    const isA = !dim && cur === k;
    const col = MODE_COLORS[k];
    const st = isA ? `background:${col}26` : '';
    return `<button class="seg-btn ${isA?'active':''}" style="${st}" onclick="${fn}('${k}')">${svg(ic, 18, isA?col:C.muted)}<span class="seg-label" style="${isA?`color:${col}`:''}">${label}</span></button>`;
  }).join('')}</div>`;
}
function fanSeg(cur) {
  return `<div class="seg-row">${FAN_OPTS.map(([v, l]) =>
    `<button class="seg-btn seg-plain ${cur===v?'active':''}" onclick="acSet('fan',${v})">${l}</button>`).join('')}</div>`;
}
function swingSeg(opts, cur, key) {
  return `<div class="seg-row">${opts.map(([v, l, ic]) => {
    const isA = cur === v;
    return `<button class="seg-btn ${isA?'active':''}" onclick="acSet('${key}',${v})">${svg(ic, 17, isA?C.accent:C.muted)}<span class="seg-label">${l}</span></button>`;
  }).join('')}</div>`;
}
function featList(s) {
  return `<div class="feat-card">${FEAT_OPTS.map(([k, l]) =>
    `<div class="feat-row"><span class="feat-label">${l}</span><button class="sw-btn" onclick="acSet('${k}',${!s[k]})">${sw(!!s[k])}</button></div>`).join('')}</div>`;
}

// ── Кондиціонер: круговий термостат ──
function renderAcCard() {
  const ac = acDev();
  const el = $('#acCard');

  // Поки стан не прийшов (перший poll / перший ac/state) — картка очікування.
  if (!ac) {
    el.innerHTML = `<div class="hero">
      <div class="hero-head">
        <div class="hero-id">
          <div class="hero-icon">${svg('snowflake',24,C.faint)}</div>
          <div><div class="hero-title">Кондиціонер</div><div class="hero-sub">Очікую стан…</div></div>
        </div>
        <button class="power-btn" disabled>${svg('power',15,C.muted)}<span>—</span></button>
      </div>
      <div class="dial">
        <svg viewBox="0 0 240 240" class="dial-svg">
          <path d="${arc(135,405)}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="16" stroke-linecap="round"></path>
        </svg>
        <div class="dial-center">
          <div class="dial-cap">ЦІЛЬ</div>
          <div class="dial-num off"><span>--</span><span class="dial-unit">°C</span></div>
          <div class="dial-room">${svg('thermometer',13,C.muted)}<span>кімната —</span></div>
        </div>
      </div>
    </div>`;
    return;
  }

  const s = ac.state;
  const on = s.on;
  const effMode = s.mode || 'cool';
  const active = MODE_COLORS[effMode] || C.accent;
  const modeColor = on ? active : C.swOff;
  const temp = s.temp;
  const frac = (temp - 16) / 14;
  const endA = 135 + frac * 270;
  const knob = pol(Math.max(135.5, endA), 96);
  const roomLine = s.room_temp != null ? `${s.room_temp}° у кімнаті` : 'кімната —';

  el.innerHTML = `<div class="hero ${on?'on':''}">
    <div class="hero-head">
      <div class="hero-id">
        <div class="hero-icon ${on?'lit':''}">${svg('snowflake',24,on?active:C.faint)}</div>
        <div><div class="hero-title">Кондиціонер</div><div class="hero-sub">${esc(ac.room)}</div></div>
      </div>
      <button class="power-btn ${on?'on':''}" onclick="toggleDev('${ac.id}')">${svg('power',15,on?'#fff':C.muted)}<span>${on?'Увімк.':'Вимк.'}</span></button>
    </div>

    <div class="dial" id="dial">
      <svg viewBox="0 0 240 240" class="dial-svg">
        <path d="${arc(135,405)}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="16" stroke-linecap="round"></path>
        <path id="dialFill" d="${arc(135, Math.max(135.5, endA))}" fill="none" stroke="${modeColor}" stroke-width="16" stroke-linecap="round" style="${on?`filter:drop-shadow(0 0 9px ${active}77)`:''}"></path>
        <circle id="dialKnob" cx="${knob.x.toFixed(2)}" cy="${knob.y.toFixed(2)}" r="13" fill="#fff" stroke="${modeColor}" stroke-width="3" style="filter:drop-shadow(0 2px 6px rgba(0,0,0,0.45))"></circle>
      </svg>
      <div class="dial-center">
        <div class="dial-cap">ЦІЛЬ</div>
        <div class="dial-num ${on?'':'off'}"><span id="dialTemp">${temp}</span><span class="dial-unit">°C</span></div>
        <div class="dial-room">${svg('thermometer',13,C.muted)}<span>${roomLine}</span></div>
      </div>
    </div>

    <div class="dial-controls">
      <button class="round-btn" onclick="decTemp()" ${on?'':'disabled'}>${svg('minus',20,on?C.text:C.faint)}</button>
      <div class="dial-mode-label">
        <div class="dml-mode ${on?'':'off'}">${MODE_LABELS[effMode]}</div>
        <div class="dml-state">${on?'Працює зараз':'Вимкнено'}</div>
      </div>
      <button class="round-btn" onclick="incTemp()" ${on?'':'disabled'}>${svg('plus',20,on?C.text:C.faint)}</button>
    </div>

    <div class="hero-modes">${modeSeg(effMode, 'acMode', !on)}</div>

    <div class="extra">
      <button class="extra-toggle" onclick="toggleExtra()">
        <span class="left">${svg('sliders',18,C.accent)}<span>Додаткові налаштування</span></span>
        <span class="chev ${S.extraOpen?'open':''}">${svg('chevron',18,C.muted)}</span>
      </button>
      ${S.extraOpen ? `<div class="extra-body">
        <div><div class="group-label">Швидкість вентилятора</div>${fanSeg(s.fan)}</div>
        <div><div class="group-label">Жалюзі — вертикальні ↕</div>${swingSeg(SWING_V_OPTS, s.swing, 'swing')}</div>
        <div><div class="group-label">Жалюзі — горизонтальні ↔</div>${swingSeg(SWING_H_OPTS, s.swing_h, 'swing_h')}</div>
        <div><div class="group-label">Функції</div>${featList(s)}</div>
      </div>` : ''}
    </div>
  </div>`;

  const dial = $('#dial');
  if (dial && on) bindDial(dial);
}

// AC-дії
function acMode(m) { const ac = acDev(); if (ac) setDev(ac.id, { mode: m, on: true }); }
function acSet(k, v) { const ac = acDev(); if (ac) setDev(ac.id, { [k]: v }); }
function toggleExtra() { S.extraOpen = !S.extraOpen; renderAcCard(); }
function incTemp() { const ac = acDev(); if (!ac || !ac.state.on) return; setDev(ac.id, { temp: Math.min(30, ac.state.temp + 1) }); }
function decTemp() { const ac = acDev(); if (!ac || !ac.state.on) return; setDev(ac.id, { temp: Math.max(16, ac.state.temp - 1) }); }

// ── Перетягування диска термостата (математика з дизайну) ──
function dialTempFromPointer(el, e) {
  const rect = el.getBoundingClientRect();
  const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
  let a = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
  if (a < 0) a += 360;
  let p;
  if (a >= 135) p = a; else if (a <= 45) p = a + 360; else p = (a < 90) ? 405 : 135;
  const frac = Math.min(1, Math.max(0, (p - 135) / 270));
  return Math.round(16 + frac * 14);
}
function updateDialVisual(temp) {
  const ac = acDev();
  const effMode = (ac && ac.state.mode) || 'cool';
  const frac = (temp - 16) / 14; const endA = 135 + frac * 270;
  const knob = pol(Math.max(135.5, endA), 96);
  const f = $('#dialFill'); if (f) f.setAttribute('d', arc(135, Math.max(135.5, endA)));
  const k = $('#dialKnob'); if (k) { k.setAttribute('cx', knob.x.toFixed(2)); k.setAttribute('cy', knob.y.toFixed(2)); }
  const t = $('#dialTemp'); if (t) t.textContent = temp;
}
function bindDial(el) {
  el.addEventListener('pointerdown', e => {
    if (!acDev() || !acDev().state.on) return;
    S.dragging = true;
    try { el.setPointerCapture(e.pointerId); } catch (_) {}
    const apply = ev => { const v = dialTempFromPointer(el, ev); el._temp = v; updateDialVisual(v); };
    apply(e);
    const move = ev => { if (S.dragging) apply(ev); };
    const up = () => {
      S.dragging = false;
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      const v = el._temp; const ac = acDev();
      if (v != null && ac && v !== ac.state.temp) setDev(ac.id, { temp: v });
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  });
}

// ── Швидкий доступ (інші пристрої) ──
function renderQuickAccess() {
  // датчик (kind='sensor') не перемикається — його показуємо в картці «У кімнаті»
  const others = S.devices.filter(d => d.kind !== 'ac' && d.kind !== 'sensor');
  const el = $('#quickAccess');
  // MQTT-режим: інших пристроїв немає → ховаємо секцію повністю.
  if (!others.length) { el.innerHTML = ''; el.style.display = 'none'; return; }
  el.style.display = '';
  el.innerHTML = `<div class="section-label">Швидкий доступ</div>
    <div class="tile-grid">${others.map(d => {
      const on = d.state.on; const ic = EMOJI_ICON[d.icon] || 'power';
      return `<button class="tile ${on?'on':''}" onclick="toggleDev('${d.id}')">
        <div class="tile-top"><div class="tile-icon">${svg(ic,22,on?C.accent:C.faint)}</div>${sw(on)}</div>
        <div><div class="tile-name">${esc(d.name)}</div><div class="tile-room">${esc(d.room)}</div></div>
        <div class="tile-state ${on?'on':''}">${
          on ? (d.state.power_w != null ? d.state.power_w + ' Вт' : 'Увімкнено') : 'Вимкнено'
        }${d.state.today_kwh != null ? ` · ${d.state.today_kwh} кВт·год` : ''}</div>
      </button>`;
    }).join('')}</div>`;
}

// ── Автоматизації ──
function deviceName(id) {
  const d = S.devices.find(x => x.id === id) || FALLBACK_DEVICES.find(x => x.id === id);
  return d ? `${d.name} · ${d.room}` : id;
}
function schedDesc(r) {
  if (r.action === 'on') return 'Увімкнути';
  if (r.action === 'off') return 'Вимкнути';
  const p = [];
  if (r.set && r.set.mode) p.push(MODE_LABELS[r.set.mode]);
  if (r.set && r.set.temp != null) p.push(r.set.temp + '°');
  if (r.set && r.set.quiet) p.push('тихо');
  if (r.set && r.set.sleep) p.push('сон');
  return 'Змінити · ' + (p.join(' · ') || 'налаштування');
}

function renderAuto() {
  const el = $('#autoRoot');
  const offline = S.boardStatus === 'offline';  // можливо лише в MQTT-режимі
  const header = `<div class="auto-head">
    <div class="auto-eyebrow">${svg('timer',15,C.accent)}<span>Правила та розклади</span></div>
    <div class="auto-h1">Автоматизації</div>
  </div>`;

  // Правила ще не завантажені.
  if (!S.rules) {
    el.innerHTML = header + (offline
      ? `<div class="empty-note">Плата зараз офлайн — для редагування правил вона має бути на зв'язку.<br>Щойно плата з'явиться онлайн, правила завантажаться сюди автоматично.</div>`
      : '<div class="empty-note">Завантаження правил…</div>');
    return;
  }

  const warn = offline
    ? `<div class="warn-card">🔴 Плата зараз офлайн — збереження змін спрацює, лише коли вона знову буде на зв'язку.</div>`
    : '';

  const c = S.rules.climate || {};
  const scheds = S.rules.schedules || [];

  const steps = [
    { field:'trigger', label:'Вмикати, коли вище', min:20, max:32 },
    { field:'target', label:'Підтримувати', min:16, max:30 },
    { field:'off_below', label:'Вимикати, коли нижче', min:16, max:28 },
  ].map(st => `<div class="step-row">
    <span class="step-label">${st.label}</span>
    <div class="step-ctrl">
      <button class="step-btn" onclick="climStep('${st.field}',-1,${st.min},${st.max})">${svg('minus',17,C.text)}</button>
      <span class="step-val">${c[st.field] != null ? c[st.field] + '°' : '--'}</span>
      <button class="step-btn" onclick="climStep('${st.field}',1,${st.min},${st.max})">${svg('plus',17,C.text)}</button>
    </div>
  </div>`).join('');

  const rows = scheds.map((r, i) => {
    const on = r.enabled !== false;
    const editor = S.editIdx === i ? schedEditor(r, i) : '';
    return `<div class="sched-item ${on?'':'off'}">
      <div class="sched-row">
        <div class="sched-time">${esc(r.time || '--:--')}</div>
        <div class="sched-info" onclick="schedEdit(${i})" title="Натисни, щоб редагувати">
          <div class="sched-dev">${esc(deviceName(r.device))}</div>
          <div class="sched-desc">${esc(schedDesc(r))}</div>
        </div>
        <button class="sw-btn" onclick="schedToggle(${i})">${sw(on)}</button>
        <button class="del-btn" onclick="schedDel(${i})">${svg('trash',16,C.muted)}</button>
      </div>
      ${editor}
    </div>`;
  }).join('');

  el.innerHTML = `${header}${warn}
  <section class="auto-card">
    <div class="card-head-row">
      <div class="card-id">
        <div class="card-icon ${c.enabled?'lit':''}">${svg('thermometer',24,c.enabled?C.accent:C.faint)}</div>
        <div>
          <div class="card-title">Клімат-контроль</div>
          <div class="card-sub">Тримає задану температуру</div>
        </div>
      </div>
      <button class="sw-btn" onclick="climToggle()">${sw(!!c.enabled)}</button>
    </div>
    ${c.enabled ? `
    <div class="clim-body">
      ${steps}
      <div>
        <div class="group-label">Режим</div>
        ${modeSeg(c.mode, 'climMode', false)}
      </div>
      <div class="opt-row">
        <div>
          <div class="opt-title">Вимикати після охолодження</div>
          <div class="opt-sub">Щоб не працював даремно</div>
        </div>
        <button class="sw-btn" onclick="climSet('auto_off',${!c.auto_off})">${sw(!!c.auto_off)}</button>
      </div>
    </div>` : ''}
  </section>

  <section class="auto-card">
    <div class="card-head-row">
      <div class="card-id">
        <div class="card-icon">${svg('calendar',23,C.accent)}</div>
        <div>
          <div class="card-title">Розклади</div>
          <div class="card-sub">Спрацьовують у заданий час</div>
        </div>
      </div>
      <button class="add-btn" onclick="schedAdd()">${svg('plus',16,C.accent)}<span>Додати</span></button>
    </div>
    ${scheds.length ? `<div class="sched-list">${rows}</div>`
      : '<div class="empty-note">Ще немає розкладів. Натисніть «Додати», щоб створити перший.</div>'}
  </section>`;
}

function chip(label, active, onclick) {
  return `<button class="chip ${active?'active':''}" onclick="${onclick}">${esc(label)}</button>`;
}
// Пристрої, яким можна задавати розклад (сенсор увімк/вимк не має сенсу).
const schedDevices = () => editDevices().filter(d => d.kind !== 'sensor');
const devKind = id => (editDevices().find(d => d.id === id) || {}).kind;

function schedEditor(r, i) {
  const [hh, mm] = (r.time || '08:00').split(':');
  const pad = n => String(n).padStart(2, '0');
  const hourOpts = Array.from({length:24},(_,h)=>`<option value="${pad(h)}" ${pad(h)===hh?'selected':''}>${pad(h)}</option>`).join('');
  const minOpts = Array.from({length:60},(_,m)=>`<option value="${pad(m)}" ${pad(m)===mm?'selected':''}>${pad(m)}</option>`).join('');
  const devs = schedDevices();
  const devOpts = devs.map(d=>`<option value="${d.id}" ${r.device===d.id?'selected':''}>${esc(d.name)} · ${esc(d.room)}</option>`).join('');
  const isAc = devKind(r.device) === 'ac';
  const st = r.set || {};
  const isOff = r.action === 'off';
  const modeOpts = MODES.map(([k])=>`<option value="${k}" ${st.mode===k?'selected':''}>${MODE_LABELS[k]}</option>`).join('');
  const fanO = FAN_OPTS.map(([v,l])=>`<option value="${v}" ${st.fan===v?'selected':''}>${l}</option>`).join('');
  // Для кондиціонера — 3 варіанти дії; для розетки/світла — просто увімк/вимк.
  const actionOpts = isAc
    ? `<option value="on" ${r.action==='on'?'selected':''}>увімкнути (з налаштуваннями)</option>
       <option value="set" ${r.action==='set'?'selected':''}>лише змінити налаштування</option>
       <option value="off" ${isOff?'selected':''}>вимкнути</option>`
    : `<option value="on" ${r.action!=='off'?'selected':''}>увімкнути</option>
       <option value="off" ${isOff?'selected':''}>вимкнути</option>`;
  return `
  <div class="sched-editor">
    <div class="se-field">
      <label>Пристрій</label>
      <select class="sel" onchange="schedField(${i},'device',this.value)">${devOpts}</select>
    </div>
    <div class="se-2">
      <div class="se-field">
        <label>Час</label>
        <div class="se-time">
          <select class="sel mono" onchange="schedField(${i},'_hh',this.value)">${hourOpts}</select>
          <b>:</b>
          <select class="sel mono" onchange="schedField(${i},'_mm',this.value)">${minOpts}</select>
        </div>
      </div>
      <div class="se-field">
        <label>Дія</label>
        <select class="sel" onchange="schedField(${i},'action',this.value)">${actionOpts}</select>
      </div>
    </div>
    ${(isAc && !isOff) ? `
    <div class="se-field">
      <label>Налаштування кондиціонера</label>
      <div class="row">
        <select class="sel" onchange="schedSetField(${i},'mode',this.value)">${modeOpts}</select>
        <span><input class="num-in mono" type="number" min="16" max="30" value="${st.temp ?? 24}" onchange="schedSetField(${i},'temp',+this.value)"> °C</span>
        <span>вент.</span>
        <select class="sel" onchange="schedSetField(${i},'fan',+this.value)">${fanO}</select>
        ${chip('🤫 Тихо', !!st.quiet, `schedSetField(${i},'quiet',${!st.quiet})`)}
        ${chip('🌙 Сон', !!st.sleep, `schedSetField(${i},'sleep',${!st.sleep})`)}
      </div>
    </div>` : ''}
  </div>`;
}

// Клімат-контроль
function climToggle() { const c = (S.rules.climate ??= {}); c.enabled = !c.enabled; saveRules(); renderAuto(); }
function climSet(k, v) { (S.rules.climate ??= {})[k] = v; saveRules(); renderAuto(); }
function climMode(k) { climSet('mode', k); }
function climStep(field, delta, min, max) {
  const c = (S.rules.climate ??= {});
  const cur = c[field] != null ? c[field] : min;
  c[field] = Math.min(max, Math.max(min, cur + delta));
  saveRules(); renderAuto();
}
// Розклади
function schedToggle(i) { const r = S.rules.schedules[i]; r.enabled = r.enabled === false; saveRules(); renderAuto(); }
function schedDel(i) { S.rules.schedules.splice(i, 1); if (S.editIdx === i) S.editIdx = null; saveRules(); renderAuto(); }
function schedEdit(i) { S.editIdx = S.editIdx === i ? null : i; renderAuto(); }
function schedAdd() {
  const dev = acDev() || schedDevices()[0];
  const rule = { enabled:true, time:'08:00', device: dev ? dev.id : '', action:'on' };
  if (dev && dev.kind === 'ac') rule.set = { mode:'cool', temp:24, fan:0 };
  (S.rules.schedules ??= []).push(rule);
  S.editIdx = S.rules.schedules.length - 1;
  saveRules(); renderAuto();
}
function schedField(i, k, v) {
  const r = S.rules.schedules[i];
  if (k === '_hh' || k === '_mm') {
    const [hh, mm] = (r.time || '08:00').split(':');
    r.time = (k === '_hh' ? v : hh) + ':' + (k === '_mm' ? v : mm);
  } else {
    r[k] = v;
    // Розетка/світло не мають налаштувань кондея — чистимо, щоб не плутало.
    if (k === 'device') {
      if (devKind(v) === 'ac') { if (!r.set) r.set = { mode:'cool', temp:24, fan:0 }; }
      else { if (r.action === 'set') r.action = 'on'; delete r.set; }
    }
    if (k === 'action' && v !== 'off' && devKind(r.device) === 'ac' && !r.set) {
      r.set = { mode:'cool', temp:24, fan:0 };
    }
  }
  saveRules(); renderAuto();
}
function schedSetField(i, k, v) { (S.rules.schedules[i].set ??= {})[k] = v; saveRules(); renderAuto(); }

// ── Рендер усього ──
function renderAll() {
  renderInfoCards();
  renderAcCard();
  renderQuickAccess();
  if (S.tab === 'auto') renderAuto();
}

// ── Старт ──
renderNav();
renderAll();          // одразу показуємо картку в стані «Очікую стан…»
tickClock();
setInterval(tickClock, 1000);
showLoader();         // лоудер видно, доки не буде реального «наживо»-з'єднання
NET.start();          // HTTP: poll /api кожні 5 с; MQTT: підключення до брокера

// Далі лоудер вмикає/вимикає лише updateLoader() за реальним станом зв'язку
// (setConn у HTTP-poll; connect/close/status/state у MQTT). Жодного таймауту-«здатися».

// ── Голосова команда: кнопка мікрофона (лише HTTP-режим = хаб/плата) ──
// Мікрофон у браузері дозволений на http://127.0.0.1:8000 (з телефона-хаба)
// або https. На http://<LAN-IP> браузер мікрофон блокує (небезпечний контекст).
(function initVoice() {
  if (NET.mode !== 'http') return;
  const btn = document.createElement('button');
  Object.assign(btn.style, {
    position: 'fixed', right: '18px', bottom: '90px', width: '62px', height: '62px',
    borderRadius: '50%', border: 'none', background: C.accent, color: '#fff', zIndex: 900,
    boxShadow: '0 6px 22px rgba(0,0,0,.45)', cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  });
  const MIC = '<svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>';
  btn.innerHTML = MIC;
  document.body.appendChild(btn);

  const toast = document.createElement('div');
  Object.assign(toast.style, {
    position: 'fixed', left: '50%', bottom: '170px', transform: 'translateX(-50%)',
    maxWidth: '82%', background: C.panel2, color: C.text, padding: '11px 16px',
    borderRadius: '13px', fontSize: '15px', zIndex: 900, opacity: 0, textAlign: 'center',
    transition: 'opacity .2s', pointerEvents: 'none', border: '1px solid ' + C.border,
  });
  document.body.appendChild(toast);
  const showToast = (t, ms = 3500) => {
    toast.textContent = t; toast.style.opacity = 1;
    clearTimeout(toast._t); if (ms) toast._t = setTimeout(() => toast.style.opacity = 0, ms);
  };
  // Голос Остапа з хабу (edge-tts); якщо не вийшло — власний голос браузера
  const speakBrowser = t => { try { const u = new SpeechSynthesisUtterance(t); u.lang = 'uk-UA'; speechSynthesis.speak(u); } catch (e) {} };
  // Мобільний браузер блокує автопрогравання поза жестом користувача. Тому один
  // <audio>, який «розблоковуємо» тихим кліпом ПІД ЧАС тапу — далі можна грати
  // голос Остапа програмно (інакше відкат на жіночий голос браузера).
  const ttsAudio = new Audio();
  const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
  const unlockAudio = () => { try { ttsAudio.src = SILENT; ttsAudio.play().then(() => ttsAudio.pause()).catch(() => {}); } catch (e) {} };
  const speak = t => {
    if (!t) return;
    try {
      ttsAudio.onerror = () => speakBrowser(t);
      ttsAudio.src = '/api/tts?text=' + encodeURIComponent(t);
      ttsAudio.play().catch(() => speakBrowser(t));
    } catch (e) { speakBrowser(t); }
  };

  let rec = false, ctx, stream, proc, chunks;
  btn.onclick = async () => {
    unlockAudio();                     // розблокувати аудіо в межах жесту
    if (rec) return stopRec();
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) { showToast('Нема доступу до мікрофона. Відкрий хаб через http://127.0.0.1:8000', 6000); return; }
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    chunks = [];
    proc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(proc); proc.connect(ctx.destination);
    rec = true; btn.style.background = '#e0555f';
    showToast('🎙 Слухаю… (тапни ще раз, коли скажеш)', 0);
    btn._auto = setTimeout(stopRec, 8000);
  };

  async function stopRec() {
    if (!rec) return;
    rec = false; clearTimeout(btn._auto); btn.style.background = C.accent;
    try { proc.disconnect(); } catch (e) {}
    stream.getTracks().forEach(t => t.stop());
    const rate = ctx.sampleRate; const wav = encodeWav(chunks, rate);
    try { ctx.close(); } catch (e) {}
    showToast('🧠 Думаю…', 0);
    try {
      const r = await fetch('/api/voice', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav });
      const res = await r.json();
      showToast((res.ok ? '✅ ' : '🤷 ') + (res.say || 'Готово'));
      if (res.say) speak(res.say);
    } catch (e) { showToast('Помилка зв\'язку з хабом'); }
  }

  function encodeWav(chunks, rate) {
    let len = 0; chunks.forEach(c => len += c.length);
    const pcm = new Int16Array(len); let o = 0;
    chunks.forEach(c => { for (let i = 0; i < c.length; i++) { const s = Math.max(-1, Math.min(1, c[i])); pcm[o++] = s < 0 ? s * 0x8000 : s * 0x7fff; } });
    const buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf);
    const ws = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
    ws(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
    dv.setUint32(24, rate, true); dv.setUint32(28, rate * 2, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); ws(36, 'data'); dv.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) dv.setInt16(44 + i * 2, pcm[i], true);
    return buf;
  }
})();
