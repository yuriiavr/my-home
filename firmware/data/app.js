/* ═══ Розумний дім — ЄДИНИЙ вебзастосунок (дизайн: Home Hub.dc.html) ═══
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

// ── Іконки (lucide, як у дизайні) ──
const ICONS = {
  house: [['path',{d:'M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8'}],['path',{d:'M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'}]],
  grid: [['rect',{width:7,height:7,x:3,y:3,rx:1}],['rect',{width:7,height:7,x:14,y:3,rx:1}],['rect',{width:7,height:7,x:14,y:14,rx:1}],['rect',{width:7,height:7,x:3,y:14,rx:1}]],
  timer: [['line',{x1:10,x2:14,y1:2,y2:2}],['line',{x1:12,x2:15,y1:14,y2:11}],['circle',{cx:12,cy:14,r:8}]],
  snowflake: [['line',{x1:2,x2:22,y1:12,y2:12}],['line',{x1:12,x2:12,y1:2,y2:22}],['path',{d:'m20 16-4-4 4-4'}],['path',{d:'m4 8 4 4-4 4'}],['path',{d:'m16 4-4 4-4-4'}],['path',{d:'m8 20 4-4 4 4'}]],
  tv: [['rect',{width:20,height:15,x:2,y:7,rx:2,ry:2}],['polyline',{points:'17 2 12 7 7 2'}]],
  lightbulb: [['path',{d:'M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5'}],['path',{d:'M9 18h6'}],['path',{d:'M10 22h4'}]],
  coffee: [['path',{d:'M10 2v2'}],['path',{d:'M14 2v2'}],['path',{d:'M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1'}],['path',{d:'M6 2v2'}]],
  power: [['path',{d:'M12 2v10'}],['path',{d:'M18.4 6.6a9 9 0 1 1-12.77.04'}]],
  sun: [['circle',{cx:12,cy:12,r:4}],['path',{d:'M12 2v2'}],['path',{d:'M12 20v2'}],['path',{d:'m4.93 4.93 1.41 1.41'}],['path',{d:'m17.66 17.66 1.41 1.41'}],['path',{d:'M2 12h2'}],['path',{d:'M20 12h2'}],['path',{d:'m6.34 17.66-1.41 1.41'}],['path',{d:'m19.07 4.93-1.41 1.41'}]],
  moon: [['path',{d:'M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z'}]],
  plus: [['path',{d:'M5 12h14'}],['path',{d:'M12 5v14'}]],
  thermometer: [['path',{d:'M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z'}]],
  activity: [['path',{d:'M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2'}]],
  refresh: [['path',{d:'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8'}],['path',{d:'M21 3v5h-5'}],['path',{d:'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16'}],['path',{d:'M3 21v-5h5'}]],
  droplet: [['path',{d:'M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z'}]],
  wind: [['path',{d:'M12.8 19.6A2 2 0 1 0 14 16H2'}],['path',{d:'M17.5 8a2.5 2.5 0 1 1 2 4H2'}],['path',{d:'M9.8 4.4A2 2 0 1 1 11 8H2'}]],
  flame: [['path',{d:'M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z'}]],
  trash: [['path',{d:'M3 6h18'}],['path',{d:'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'}],['line',{x1:10,x2:10,y1:11,y2:17}],['line',{x1:14,x2:14,y1:11,y2:17}]],
  chevron: [['path',{d:'m6 9 6 6 6-6'}]],
  calendar: [['path',{d:'M8 2v4'}],['path',{d:'M16 2v4'}],['rect',{width:18,height:18,x:3,y:4,rx:2}],['path',{d:'M3 10h18'}]],
  sliders: [['line',{x1:4,x2:4,y1:21,y2:14}],['line',{x1:4,x2:4,y1:10,y2:3}],['line',{x1:12,x2:12,y1:21,y2:12}],['line',{x1:12,x2:12,y1:8,y2:3}],['line',{x1:20,x2:20,y1:21,y2:16}],['line',{x1:20,x2:20,y1:12,y2:3}],['line',{x1:2,x2:6,y1:14,y2:14}],['line',{x1:10,x2:14,y1:8,y2:8}],['line',{x1:18,x2:22,y1:16,y2:16}]],
};

function svg(name, size = 22, color = 'currentColor') {
  const specs = ICONS[name] || [];
  const inner = specs.map(([tag, attrs]) => {
    const a = Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(' ');
    return `<${tag} ${a}/>`;
  }).join('');
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;flex-shrink:0">${inner}</svg>`;
}

// ── Теми (з дизайну) ──
const THEMES = {
  dark: { bg:'#0a0c10', panel:'#14181f', panel2:'#1d222b', border:'rgba(255,255,255,.08)', border2:'rgba(255,255,255,.14)', swOff:'#39414f',
    text:'#eef1f5', muted:'#98a2b0', faint:'#616b78', accent:'#5b8def', accentBg:'rgba(91,141,239,.16)',
    on:'#3ecf8e', onBg:'rgba(62,207,142,.14)', shadow:'none', glow:'rgba(91,141,239,.13)' },
  light: { bg:'#eceff4', panel:'#ffffff', panel2:'#f3f6fa', border:'#e4e8ef', border2:'#d3dae4', swOff:'#c6cfdb',
    text:'#12151b', muted:'#5f6a78', faint:'#95a0ae', accent:'#3b6fe0', accentBg:'rgba(59,111,224,.10)',
    on:'#12a566', onBg:'rgba(18,165,102,.10)', shadow:'0 2px 14px rgba(20,30,55,.06)', glow:'rgba(59,111,224,.10)' },
};

const MODES = [['auto','Авто','refresh'],['cool','Холод','snowflake'],['dry','Осушення','droplet'],['fan','Вентиляція','wind'],['heat','Тепло','flame']];
const MODE_LABEL = { auto:'Авто', cool:'Холод', dry:'Осушення', fan:'Вентиляція', heat:'Тепло' };
const EMOJI_ICON = { '❄️':'snowflake', '📺':'tv', '💡':'lightbulb', '☕':'coffee' };

// ── Стан ──
const S = {
  theme: localStorage.getItem('hub_theme') || 'dark',
  tab: 'devices',
  devices: [],        // пристрої: HTTP — усі з /api/devices; MQTT — лише кондиціонер
  rules: null,        // правила автоматизацій, або null поки не завантажені
  acOpen: false,
  editIdx: null,      // який розклад розгорнуто на редагування
  dragging: false,
  lastEditAt: 0,      // час останньої локальної правки правил (MQTT: щоб retained не затирав)
  conn: 'connecting', // 'connecting' | 'connected' | 'disconnected'
  boardStatus: null,  // MQTT: 'online' | 'offline' | null; HTTP: завжди null
};

// Запасний список пристроїв для редактора розкладів (MQTT-режим до першого стану).
const FALLBACK_DEVICES = [{ id: 'ac_living', name: 'Кондиціонер', room: 'Вітальня' }];
const editDevices = () => S.devices.length ? S.devices : FALLBACK_DEVICES;

const $ = s => document.querySelector(s);
const esc = t => String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ── Тема ──
function applyTheme() {
  const t = THEMES[S.theme];
  const r = document.documentElement.style;
  r.setProperty('--bg', t.bg); r.setProperty('--panel', t.panel); r.setProperty('--panel2', t.panel2);
  r.setProperty('--border', t.border); r.setProperty('--border2', t.border2); r.setProperty('--sw-off', t.swOff);
  r.setProperty('--text', t.text); r.setProperty('--muted', t.muted); r.setProperty('--faint', t.faint);
  r.setProperty('--accent', t.accent); r.setProperty('--accent-bg', t.accentBg);
  r.setProperty('--on', t.on); r.setProperty('--on-bg', t.onBg);
  r.setProperty('--shadow', t.shadow); r.setProperty('--glow', t.glow);
  const icon = S.theme === 'dark' ? 'sun' : 'moon';
  const label = S.theme === 'dark' ? 'Світла тема' : 'Темна тема';
  $('#themeBtnSide').innerHTML = svg(icon, 19) + `<span>${label}</span>`;
  $('#themeBtnTop').innerHTML = svg(icon, 19);
}
function toggleTheme() {
  S.theme = S.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('hub_theme', S.theme);
  applyTheme(); renderAll(); renderStatus();
}

// ── Навігація ──
const NAV = [['devices','Огляд','grid'],['auto','Автоматизації','timer']];
function renderNav() {
  $('#sideNav').innerHTML = NAV.map(([k, label, ic]) =>
    `<button class="side-item ${S.tab===k?'active':''}" onclick="showTab('${k}')">${svg(ic,20)}<span>${label}</span></button>`).join('');
  $('#bottomNav').innerHTML = NAV.map(([k, label, ic]) =>
    `<button class="tab-item ${S.tab===k?'active':''}" onclick="showTab('${k}')">${svg(ic,22)}<span>${label}</span></button>`).join('');
}
function showTab(k) {
  S.tab = k;
  $('#view-devices').style.display = k === 'devices' ? '' : 'none';
  $('#view-auto').style.display = k === 'auto' ? '' : 'none';
  $('#pageTitle').textContent = k === 'devices' ? 'Огляд дому' : 'Автоматизації';
  renderNav();
  if (k === 'auto') { NET.refreshRules(); renderAuto(); }
}

// ── Годинник ──
function tickClock() {
  const now = new Date();
  $('#clock').textContent = now.toLocaleTimeString('uk-UA', { hour:'2-digit', minute:'2-digit', hour12:false });
  let wd = now.toLocaleDateString('uk-UA', { weekday:'long' });
  $('#weekday').textContent = wd.charAt(0).toUpperCase() + wd.slice(1);
  $('#datestr').textContent = now.toLocaleDateString('uk-UA', { day:'numeric', month:'long' });
  const h = now.getHours();
  const greeting = h < 5 ? 'Доброї ночі' : h < 12 ? 'Доброго ранку' : h < 18 ? 'Доброго дня' : 'Доброго вечора';
  $('#greet').innerHTML = svg(h >= 6 && h < 18 ? 'sun' : 'moon', 15, THEMES[S.theme].accent) + `<span>${greeting}</span>`;
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
  renderStatus();
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
      setConn('connected');
      renderAll();
    } catch (e) { setConn('disconnected'); }
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
      renderStatus();
      if (S.tab === 'auto') renderAuto();  // оновити примітку про офлайн-плату
      return;
    }
    if (topic === T_STATE) {
      try {
        const st = JSON.parse(text);
        S.devices = [buildAcDevice(st)];
        if (!S.dragging) renderAll();      // не перемальовуємо під час перетягування
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

// ── Статус-пілл підключення ──
function renderStatus() {
  const pill = $('#statusPill');
  if (!pill) return;
  let emoji, text;
  if (NET.mode === 'http') {
    if (S.conn === 'connected')        { emoji = '🟢'; text = 'Локально'; }
    else if (S.conn === 'connecting')  { emoji = '🟡'; text = 'Підключення…'; }
    else                               { emoji = '🔴'; text = "Немає зв'язку"; }
  } else {
    if (S.conn === 'connected') {
      if (S.boardStatus === 'online')       { emoji = '🟢'; text = "На зв'язку"; }
      else if (S.boardStatus === 'offline') { emoji = '🔴'; text = 'Плата офлайн'; }
      else                                  { emoji = '🟡'; text = 'Підключення…'; } // ще без статусу
    } else if (S.conn === 'connecting')     { emoji = '🟡'; text = 'Підключення…'; }
    else                                    { emoji = '🔴'; text = "Немає зв'язку"; }
  }
  pill.innerHTML = `<span aria-hidden="true">${emoji}</span><span>${text}</span>`;
}

/* ═══ Далі — СПІЛЬНИЙ інтерфейс (однаковий для HTTP і MQTT) ═══ */

// ── Пристрої: статистика + AC + сітка ──
const acDev = () => S.devices.find(d => d.kind === 'ac');

function renderStats() {
  const t = THEMES[S.theme];
  const ac = acDev();
  const on = S.devices.filter(d => d.state.on).length;
  const acOn = ac && ac.state.on;
  $('#stats').innerHTML = `
    <div class="stat"><div class="stat-icon">${svg('thermometer',20,t.accent)}</div>
      <div><div class="stat-label">Температура</div><div class="stat-value">${ac && ac.state.room_temp != null ? ac.state.room_temp : '—'}°C</div></div></div>
    <div class="stat"><div class="stat-icon">${svg('activity',20,t.accent)}</div>
      <div><div class="stat-label">Активні</div><div class="stat-value">${on} / ${S.devices.length}</div></div></div>
    <div class="stat"><div class="stat-icon">${svg('snowflake',20,t.accent)}</div>
      <div><div class="stat-label">Кондиціонер</div><div class="stat-text"><span class="dot" style="background:${acOn?t.on:t.border2}"></span>${acOn ? `${MODE_LABEL[ac.state.mode]||''} · ${ac.state.temp}°` : (ac ? 'Вимкнений' : 'Очікую стан…')}</div></div></div>`;
}

function chip(label, active, onclick, iconName) {
  const t = THEMES[S.theme];
  const ic = iconName ? svg(iconName, 16, active ? t.accent : t.muted) : '';
  return `<button class="chip ${active?'active':''}" onclick="${onclick}">${ic}<span>${esc(label)}</span></button>`;
}

function sliderHTML(id, val, min, max, { small = false, dim = false } = {}) {
  const pct = ((val - min) / (max - min)) * 100;
  return `
    <div class="slider ${small?'small':''} ${dim?'dim':''}" data-slider="${id}" data-min="${min}" data-max="${max}">
      <div class="slider-rail"></div>
      <div class="slider-fill" style="width:${pct}%"></div>
      <div class="slider-knob" style="left:${pct}%"></div>
    </div>`;
}

function renderAcCard() {
  const t = THEMES[S.theme];
  const ac = acDev();
  const el = $('#acCard');

  // Поки стан не прийшов (перший poll / перший ac/state) — картка очікування.
  if (!ac) {
    el.innerHTML = `
    <section class="card">
      <div class="card-head">
        <div class="card-id">
          <div class="card-icon">${svg('snowflake',26,t.faint)}</div>
          <div>
            <div class="card-title">Кондиціонер</div>
            <div class="card-sub">Очікую стан…</div>
          </div>
        </div>
        <button class="power-btn" disabled style="opacity:.55;cursor:default">${svg('power',16,t.muted)}<span>—</span></button>
      </div>
      <div class="ac-body">
        <div class="ac-target">
          <div class="ac-target-num">--<span class="deg">°</span></div>
          <div class="ac-target-cap">Ціль</div>
        </div>
        <div class="slider-zone">
          ${sliderHTML('ac-temp', 24, 16, 30, { dim: true })}
          <div class="slider-scale"><span>16°</span><span>30°</span></div>
        </div>
      </div>
    </section>`;
    return; // слайдери не прив'язуємо у стані очікування
  }

  const s = ac.state;
  const on = s.on;

  const modes = MODES.map(([k, label, ic]) =>
    chip(label, on && s.mode === k, `acMode('${k}')`, ic)).join('');

  const fan = [[0,'Авто'],[1,'1'],[2,'2'],[3,'3'],[4,'4'],[5,'5']].map(([v, l]) =>
    chip(l, s.fan === v, `acSet('fan',${v})`)).join('');
  const swingV = [[0,'Фікс.'],[1,'Гойдання'],[2,'Вгору'],[4,'Центр'],[6,'Вниз']].map(([v, l]) =>
    chip(l, s.swing === v, `acSet('swing',${v})`)).join('');
  const swingH = [[0,'Фікс.'],[1,'Гойдання'],[2,'Вліво'],[4,'Центр'],[6,'Вправо']].map(([v, l]) =>
    chip(l, s.swing_h === v, `acSet('swing_h',${v})`)).join('');
  const feats = [['turbo','Турбо'],['quiet','Тихо'],['eco','Еко'],['sleep','Сон'],['xfan','Просушка'],['health','Іонізація'],['light','Підсвітка']].map(([k, l]) =>
    chip(l, !!s[k], `acSet('${k}',${!s[k]})`)).join('');

  el.innerHTML = `
  <section class="card ${on?'ac-on':''}">
    <div class="card-head">
      <div class="card-id">
        <div class="card-icon ${on?'lit':''}">${svg('snowflake',26,on?t.accent:t.faint)}</div>
        <div>
          <div class="card-title">Кондиціонер</div>
          <div class="card-sub">${esc(ac.room)} · ${on ? `працює · ${s.room_temp != null ? s.room_temp+'° у кімнаті' : ''}` : 'вимкнений'}</div>
        </div>
      </div>
      <button class="power-btn ${on?'on':''}" onclick="toggleDev('${ac.id}')">${svg('power',16,on?'#fff':t.muted)}<span>${on?'Увімк.':'Вимк.'}</span></button>
    </div>
    <div class="ac-body">
      <div class="ac-target">
        <div class="ac-target-num" id="acTempVal">${s.temp}<span class="deg">°</span></div>
        <div class="ac-target-cap">Ціль</div>
      </div>
      <div class="slider-zone">
        ${sliderHTML('ac-temp', s.temp, 16, 30, { dim: !on })}
        <div class="slider-scale"><span>16°</span><span>30°</span></div>
      </div>
    </div>
    <div class="chips" style="margin-top:20px">${modes}</div>
    <div class="ac-extra">
      <button class="ac-extra-toggle" onclick="toggleAcExtra()">
        <span class="left">${svg('sliders',18,t.accent)}<span>Додаткові налаштування</span></span>
        <span class="chev ${S.acOpen?'open':''}">${svg('chevron',18,t.muted)}</span>
      </button>
      ${S.acOpen ? `
      <div class="ac-extra-body">
        <div><div class="group-label">Швидкість вентилятора</div><div class="chips">${fan}</div></div>
        <div><div class="group-label">Жалюзі ↕ (вгору-вниз)</div><div class="chips">${swingV}</div></div>
        <div><div class="group-label">Жалюзі ↔ (вліво-вправо)</div><div class="chips">${swingH}</div></div>
        <div><div class="group-label">Функції</div><div class="chips">${feats}</div></div>
      </div>` : ''}
    </div>
  </section>`;
  bindSliders(el);
}

function acMode(m) { const ac = acDev(); if (ac) setDev(ac.id, { mode: m, on: true }); }
function acSet(k, v) { const ac = acDev(); if (ac) setDev(ac.id, { [k]: v }); }
function toggleAcExtra() { S.acOpen = !S.acOpen; renderAcCard(); }

function renderGrid() {
  const t = THEMES[S.theme];
  const others = S.devices.filter(d => d.kind !== 'ac');
  // Якщо крім кондиціонера пристроїв немає (MQTT-режим) — ховаємо заголовок сітки.
  const gt = $('#gridTitle');
  if (gt) gt.style.display = others.length ? '' : 'none';
  $('#grid').innerHTML = others.map(d => {
    const on = d.state.on;
    const ic = EMOJI_ICON[d.icon] || 'power';
    return `
    <button class="tile ${on?'on':''}" onclick="toggleDev('${d.id}')">
      <div class="tile-top">
        <div class="tile-icon">${svg(ic, 23, on ? t.accent : t.faint)}</div>
        <span class="sw ${on?'on':''}"><span class="knob"></span></span>
      </div>
      <div>
        <div class="tile-name">${esc(d.name)}</div>
        <div class="tile-room">${esc(d.room)}</div>
      </div>
      <div class="tile-state">${on?'Увімкнено':'Вимкнено'}</div>
    </button>`;
  }).join('');
}

// ── Автоматизації ──
function deviceName(id) {
  const d = S.devices.find(x => x.id === id) || FALLBACK_DEVICES.find(x => x.id === id);
  return d ? `${d.name} · ${d.room}` : id;
}

function renderAuto() {
  const t = THEMES[S.theme];
  const el = $('#autoRoot');
  const offline = S.boardStatus === 'offline';  // можливо лише в MQTT-режимі

  // Правила ще не завантажені.
  if (!S.rules) {
    el.innerHTML = offline
      ? `<div class="empty-note">Плата зараз офлайн — для редагування правил вона має бути на зв'язку.<br>Щойно плата з'явиться онлайн, правила завантажаться сюди автоматично.</div>`
      : '<div class="empty-note">Завантаження правил…</div>';
    return;
  }

  // Правила є, але плата офлайн (MQTT) — попереджаємо про збереження.
  const warn = offline ? `
  <section class="auto-card" style="padding:16px 20px">
    <div class="card-sub" style="margin:0">🔴 Плата зараз офлайн — збереження змін спрацює, лише коли вона знову буде на зв'язку.</div>
  </section>` : '';

  const c = S.rules.climate || {};
  const scheds = S.rules.schedules || [];

  const sliders = [
    { field:'trigger', label:'Вмикати, коли в кімнаті вище', min:20, max:32 },
    { field:'target', label:'Підтримувати температуру', min:16, max:30 },
    { field:'off_below', label:'Вимикати, коли охолоне до', min:16, max:28 },
  ].map(sl => `
    <div>
      <div class="clim-row-head">
        <span class="clim-label">${sl.label}</span>
        <span class="clim-value" id="climVal-${sl.field}">${c[sl.field]}°</span>
      </div>
      ${sliderHTML('clim-' + sl.field, c[sl.field], sl.min, sl.max, { small:true })}
    </div>`).join('');

  const modes = MODES.map(([k, label, ic]) =>
    chip(label, c.mode === k, `climSet('mode','${k}')`, ic)).join('');

  const rows = scheds.map((r, i) => {
    const on = r.enabled !== false;
    let desc;
    if (r.action === 'on') desc = 'Увімкнути';
    else if (r.action === 'off') desc = 'Вимкнути';
    else {
      const p = [];
      if (r.set && r.set.mode) p.push(MODE_LABEL[r.set.mode]);
      if (r.set && r.set.temp != null) p.push(r.set.temp + '°');
      if (r.set && r.set.quiet) p.push('тихо');
      if (r.set && r.set.sleep) p.push('сон');
      desc = 'Змінити · ' + (p.join(' · ') || 'налаштування');
    }
    const editor = S.editIdx === i ? schedEditor(r, i) : '';
    return `
    <div class="sched-row ${on?'':'off'}">
      <div class="sched-time">${esc(r.time || '--:--')}</div>
      <div class="sched-info" onclick="schedEdit(${i})" title="Натисни, щоб редагувати">
        <div class="sched-dev">${esc(deviceName(r.device))}</div>
        <div class="sched-desc">${esc(desc)}</div>
      </div>
      <button class="sw-btn" onclick="schedToggle(${i})"><span class="sw ${on?'on':''}"><span class="knob"></span></span></button>
      <div class="sched-sep"></div>
      <button class="del-btn" onclick="schedDel(${i})">${svg('trash',17)}</button>
    </div>${editor}`;
  }).join('');

  el.innerHTML = `${warn}
  <section class="auto-card">
    <div class="card-head">
      <div class="card-id">
        <div class="card-icon ${c.enabled?'lit':''}">${svg('thermometer',25,c.enabled?t.accent:t.faint)}</div>
        <div>
          <div class="card-title">Клімат-контроль</div>
          <div class="card-sub">Автоматично тримає задану температуру в кімнаті</div>
        </div>
      </div>
      <button class="sw-btn" onclick="climToggle()"><span class="sw ${c.enabled?'on':''}"><span class="knob"></span></span></button>
    </div>
    ${c.enabled ? `
    <div class="auto-body">
      ${sliders}
      <div>
        <div class="clim-label" style="margin-bottom:11px">Режим охолодження</div>
        <div class="chips">${modes}</div>
      </div>
      <div class="opt-row">
        <div>
          <div class="opt-title">Вимикати після охолодження</div>
          <div class="opt-sub">Щоб не працював даремно, коли в кімнаті стало прохолодно</div>
        </div>
        <button class="sw-btn" onclick="climSet('auto_off',${!c.auto_off})"><span class="sw ${c.auto_off?'on':''}"><span class="knob"></span></span></button>
      </div>
    </div>` : ''}
  </section>

  <section class="auto-card">
    <div class="card-head" style="margin-bottom:6px">
      <div class="card-id">
        <div class="card-icon">${svg('calendar',24,t.accent)}</div>
        <div>
          <div class="card-title">Розклади</div>
          <div class="card-sub">Спрацьовують у заданий час</div>
        </div>
      </div>
      <button class="add-btn" onclick="schedAdd()">${svg('plus',16,t.accent)}<span>Додати</span></button>
    </div>
    ${scheds.length ? `<div class="sched-list">${rows}</div>`
      : '<div class="empty-note">Ще немає розкладів. Натисніть «Додати», щоб створити перший.</div>'}
  </section>`;
  bindSliders(el);
}

function schedEditor(r, i) {
  const [hh, mm] = (r.time || '08:00').split(':');
  const pad = n => String(n).padStart(2, '0');
  const hourOpts = Array.from({length:24},(_,h)=>`<option value="${pad(h)}" ${pad(h)===hh?'selected':''}>${pad(h)}</option>`).join('');
  const minOpts = Array.from({length:60},(_,m)=>`<option value="${pad(m)}" ${pad(m)===mm?'selected':''}>${pad(m)}</option>`).join('');
  const devOpts = editDevices().map(d=>`<option value="${d.id}" ${r.device===d.id?'selected':''}>${esc(d.name)} · ${esc(d.room)}</option>`).join('');
  const st = r.set || {};
  const isOff = r.action === 'off';
  const modeOpts = MODES.map(([k,l])=>`<option value="${k}" ${st.mode===k?'selected':''}>${l}</option>`).join('');
  const fanOpts = [[0,'Авто'],[1,'1'],[2,'2'],[3,'3'],[4,'4'],[5,'5']].map(([v,l])=>`<option value="${v}" ${st.fan===v?'selected':''}>${l}</option>`).join('');
  return `
  <div class="sched-editor">
    <div class="row">
      <b>о</b>
      <select class="sel mono" onchange="schedField(${i},'_hh',this.value)">${hourOpts}</select> :
      <select class="sel mono" onchange="schedField(${i},'_mm',this.value)">${minOpts}</select>
      <select class="sel" onchange="schedField(${i},'device',this.value)">${devOpts}</select>
      <select class="sel" onchange="schedField(${i},'action',this.value)">
        <option value="on" ${r.action==='on'?'selected':''}>увімкнути з налаштуваннями</option>
        <option value="set" ${r.action==='set'?'selected':''}>лише змінити налаштування</option>
        <option value="off" ${isOff?'selected':''}>вимкнути</option>
      </select>
    </div>
    ${isOff ? '' : `
    <div class="row">
      <span class="clim-label">режим</span>
      <select class="sel" onchange="schedSetField(${i},'mode',this.value)">${modeOpts}</select>
      <input class="num-in mono" type="number" min="16" max="30" value="${st.temp ?? 24}" onchange="schedSetField(${i},'temp',+this.value)"> °C
      <span class="clim-label">вент.</span>
      <select class="sel" onchange="schedSetField(${i},'fan',+this.value)">${fanOpts}</select>
      ${chip('🤫 Тихо', !!st.quiet, `schedSetField(${i},'quiet',${!st.quiet})`)}
      ${chip('🌙 Сон', !!st.sleep, `schedSetField(${i},'sleep',${!st.sleep})`)}
    </div>`}
  </div>`;
}

function climToggle() { (S.rules.climate ??= {}).enabled = !S.rules.climate.enabled; saveRules(); renderAuto(); }
function climSet(k, v) { (S.rules.climate ??= {})[k] = v; saveRules(); renderAuto(); }
function schedToggle(i) { const r = S.rules.schedules[i]; r.enabled = r.enabled === false; saveRules(); renderAuto(); }
function schedDel(i) { S.rules.schedules.splice(i, 1); if (S.editIdx === i) S.editIdx = null; saveRules(); renderAuto(); }
function schedEdit(i) { S.editIdx = S.editIdx === i ? null : i; renderAuto(); }
function schedAdd() {
  (S.rules.schedules ??= []).push({ enabled:true, time:'08:00', device:(acDev() || editDevices()[0]).id, action:'on', set:{ mode:'cool', temp:24, fan:0 } });
  S.editIdx = S.rules.schedules.length - 1;
  saveRules(); renderAuto();
}
function schedField(i, k, v) {
  const r = S.rules.schedules[i];
  if (k === '_hh' || k === '_mm') {
    const [hh, mm] = (r.time || '08:00').split(':');
    r.time = (k === '_hh' ? v : hh) + ':' + (k === '_mm' ? v : mm);
  } else r[k] = v;
  saveRules(); renderAuto();
}
function schedSetField(i, k, v) { (S.rules.schedules[i].set ??= {})[k] = v; saveRules(); renderAuto(); }

// ── Слайдери (перетягування) ──
function bindSliders(scope) {
  scope.querySelectorAll('[data-slider]').forEach(el => {
    el.addEventListener('pointerdown', e => {
      S.dragging = true;
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      sliderMove(el, e);
      const move = ev => sliderMove(el, ev);
      const up = ev => {
        S.dragging = false;
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        sliderCommit(el, ev);
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
    });
  });
}
function sliderValue(el, e) {
  const r = el.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  const min = +el.dataset.min, max = +el.dataset.max;
  return Math.round(min + ratio * (max - min));
}
function sliderMove(el, e) {
  const v = sliderValue(el, e);
  const min = +el.dataset.min, max = +el.dataset.max;
  const pct = ((v - min) / (max - min)) * 100;
  el.querySelector('.slider-fill').style.width = pct + '%';
  el.querySelector('.slider-knob').style.left = pct + '%';
  const id = el.dataset.slider;
  if (id === 'ac-temp') { const lbl = $('#acTempVal'); if (lbl) lbl.innerHTML = `${v}<span class="deg">°</span>`; }
  if (id.startsWith('clim-')) { const lbl = $('#climVal-' + id.slice(5)); if (lbl) lbl.textContent = v + '°'; }
  el._val = v;
}
function sliderCommit(el) {
  const v = el._val;
  if (v == null) return;
  const id = el.dataset.slider;
  if (id === 'ac-temp') { const ac = acDev(); if (ac) setDev(ac.id, { temp: v }); }
  else if (id.startsWith('clim-')) { if (!S.rules) return; (S.rules.climate ??= {})[id.slice(5)] = v; saveRules(); renderAuto(); }
}

// ── Рендер усього ──
function renderAll() {
  renderStats();
  renderAcCard();
  renderGrid();
  if (S.tab === 'auto') renderAuto();
}

// ── Старт ──
$('#logoIcon').innerHTML = svg('house', 21, '#fff');
$('#themeBtnSide').onclick = toggleTheme;
$('#themeBtnTop').onclick = toggleTheme;
applyTheme();
renderNav();
renderStatus();
renderAll();          // одразу показуємо картку в стані «Очікую стан…»
tickClock();
setInterval(tickClock, 1000);
NET.start();          // HTTP: poll /api кожні 5 с; MQTT: підключення до брокера
