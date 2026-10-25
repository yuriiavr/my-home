"""
Розумний Дім — центральний ХАБ.

Поки що всі пристрої "фейкові" (MockDevice), щоб бачити роботу без заліза.
Коли з'явиться техніка — додамо реальні драйвери (ESP32 по MQTT, Shelly,
Tuya...) НЕ змінюючи цей файл суттєво: просто інший клас у реєстрі.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from automations import Engine
from devices.gree import GreeAC
from devices.mock import MockDevice

BASE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app):
    # Фонове опитування: кожні 10 сек читаємо реальний стан пристроїв
    # і даємо тікнути движку автоматизацій (клімат + розклади).
    async def poller():
        while True:
            for d in DEVICES.values():
                if hasattr(d, "refresh"):
                    await d.refresh()
            # DHT22 на платі — ІСТИНА: перезаписуємо room_temp кондиціонера його
            # температурою (і показ, і автоматика беруть точний датчик, а не
            # менш точний сенсор усередині кондея).
            cs = DEVICES.get("climate")
            ac = DEVICES.get("ac_living")
            if cs and ac and cs.state.get("temp") is not None:
                ac.state["room_temp"] = cs.state["temp"]
            await ENGINE.tick()
            await asyncio.sleep(10)
    task = asyncio.create_task(poller())
    yield
    task.cancel()


app = FastAPI(title="Мій Розумний Дім", lifespan=lifespan)

# ── Реєстр пристроїв ───────────────────────────────────────────────
# Поки MockDevice(id, назва, іконка, кімната).
# Щоб підключити реальний бренд — заміни клас тут на драйвер бренду.
DEVICES: dict[str, MockDevice] = {}

# Черга кіно-команд: хаб (телефон) приймає «постав фільм», кладе сюди, а агент
# на ПК (movie_agent.py) забирає й вмикає кіно в Chrome. Так телефон = пульт,
# а фільми грають на ПК (де є браузер).
MOVIE_QUEUE: list[dict] = []

# Історія переглядів (що і докуди дивилися). Живе на ПК у cinema.py, а агент на
# ПК періодично надсилає її сюди — щоб Адольф «бачив», що ти вже дивився, і міг
# продовжити з місця. Список словників: {title,service,season,episode,time,...}.
WATCH_HISTORY: list[dict] = []


def add(device) -> None:
    DEVICES[device.id] = device


def wake_pc() -> bool:
    """Розбудити ПК через Wake-on-LAN («магічний пакет» на MAC ПК). Робить це
    САМ ХАБ (телефон), бо коли ПК вимкнений, агент на ньому не працює.
    Пакет = 6 байтів 0xFF + MAC×16, шлемо broadcast'ом на порт 9."""
    import socket
    mac = getattr(home_secrets, "PC_MAC", "").replace(":", "").replace("-", "")
    if len(mac) != 12:
        print("[WOL] PC_MAC не заданий/некоректний")
        return False
    packet = bytes.fromhex("ff" * 6 + mac * 16)
    ok = False
    for addr in ("255.255.255.255", "192.168.0.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(packet, (addr, 9))
            s.sendto(packet, (addr, 7))    # дехто слухає порт 7
            s.close()
            ok = True
        except Exception as e:
            print("[WOL]", addr, type(e).__name__, e)
    print("[WOL] магічний пакет надіслано" if ok else "[WOL] не вдалося")
    return ok


# СПРАВЖНІЙ кондиціонер Cooper&Hunter — локально по WiFi (протокол Gree).
# Доступи лежать у home_secrets.py (не в git); шаблон — home_secrets.example.py.
import home_secrets

add(GreeAC("ac_living", "Кондиціонер", ip=home_secrets.AC_IP,
           mac=home_secrets.AC_MAC, key=home_secrets.AC_KEY,
           mode=home_secrets.AC_ENC, icon="❄️", room="Вітальня"))

# Розумна розетка Tapo P110 — тут керує БОЙЛЕРОМ (за розкладом 7:00–8:00).
if getattr(home_secrets, "TAPO_EMAIL", "") and getattr(home_secrets, "TAPO_PASSWORD", ""):
    from devices.tapo import TapoPlug
    add(TapoPlug("plug_1", "Бойлер", ip=home_secrets.TAPO_IP,
                 email=home_secrets.TAPO_EMAIL, password=home_secrets.TAPO_PASSWORD,
                 icon="🔌", room="Ванна"))

# Датчик клімату на платі ESP32 (DHT22) — температура/вологість. Його цифри —
# ІСТИНА для хаба (перезаписують room_temp кондиціонера, див. poller вище).
if getattr(home_secrets, "BOARD_IP", ""):
    from devices.climate import ClimateSensor
    add(ClimateSensor("climate", "Клімат", ip=home_secrets.BOARD_IP,
                      icon="🌡️", room="Вітальня"))

# Інших пристроїв (телевізор/світло/чайник) НЕМА — прибрано за запитом користувача.

# Движок автоматизацій (правила живуть у automations.json)
ENGINE = Engine(DEVICES)


# ── API ────────────────────────────────────────────────────────────
@app.get("/api/devices")
def list_devices():
    return [d.to_dict() for d in DEVICES.values()]


@app.post("/api/devices/{device_id}/toggle")
async def toggle_device(device_id: str):
    device = DEVICES.get(device_id)
    if not device:
        raise HTTPException(404, "Пристрій не знайдено")
    await device.toggle()
    return device.to_dict()


@app.post("/api/devices/{device_id}/set")
async def set_device(device_id: str, changes: dict):
    """Змінити будь-які налаштування пристрою: {"temp": 22, "mode": "cool", ...}"""
    device = DEVICES.get(device_id)
    if not device:
        raise HTTPException(404, "Пристрій не знайдено")
    for key, value in changes.items():
        device.state[key] = value
    await device.apply()
    return device.to_dict()


WAKELOG = []   # останні рішення фільтра (для /api/wakelog — видно, що чує Vosk)


def _wake_gate(wav_bytes: bytes) -> dict:
    """Розпізнати аудіо й сказати, чи звучало «Адольф»: {"wake":bool, "text":...}.
    Основне — Groq whisper-large-v3 (хмара, точно); фолбек — локальний Vosk."""
    if getattr(home_secrets, "GROQ_API_KEY", ""):
        try:
            import groq_gate
            return groq_gate.check(wav_bytes)
        except Exception as e:
            print("[GROQ]", type(e).__name__, e)   # -> фолбек на Vosk
    try:
        import vosk_gate
        return vosk_gate.check(wav_bytes)
    except Exception as e:
        print("[STT]", type(e).__name__, e)
        return {"wake": False, "text": "(немає розпізнавання: %s)" % type(e).__name__}


def _wakelog_add(text: str, wake: bool) -> dict:
    from datetime import datetime
    entry = {"t": datetime.now().strftime("%H:%M:%S"), "text": text,
             "wake": wake, "action": None}
    WAKELOG.append(entry)
    del WAKELOG[:-40]     # тримаємо останні 40
    return entry


@app.post("/api/voice")
async def voice_command(request: Request):
    """Голос: аудіо (WAV) з браузера -> Gemini -> виконати. Повертає {ok, say}.
    Мікрофон у браузері працює на http://127.0.0.1:8000 (з телефона-хаба)."""
    wav = await request.body()
    if not wav:
        return {"ok": False, "say": "Порожнє аудіо"}
    # src=mic -> завжди-слухаючий мікрофон плати: виконуємо ЛИШЕ якщо звучало «Адольф»
    wake_required = request.query_params.get("src") == "mic"
    # ФІЛЬТР «Адольф» ПЕРЕД Gemini. Плата слухає завжди й шле КОЖЕН кліп сюди
    # (локально, безкоштовно). Але на Gemini пускаємо лише те, де МІСЦЕВО (Vosk)
    # почули «Адольф» — інакше кіно/розмови палили б квоту. Поки Vosk не
    # встановлено -> _wake_word_present() поверне False -> усі mic-кліпи дропаємо.
    wl = None
    if wake_required:
        g = await asyncio.to_thread(_wake_gate, wav)
        wl = _wakelog_add(g.get("text", ""), bool(g.get("wake")))
        print("[GATE] wake=%s text=%r" % (g.get("wake"), g.get("text", "")[:60]))
        if not g.get("wake"):
            return {"ok": False, "say": ""}
    import voice_hub
    devices = [d.to_dict() for d in DEVICES.values()]
    try:
        cmd = await asyncio.to_thread(voice_hub.parse_command, wav, devices,
                                      WATCH_HISTORY, wake_required)
    except Exception as e:
        print("[VOICE] parse:", type(e).__name__, e)
        if wl is not None:
            wl["action"] = "Gemini error"
        return {"ok": False, "say": "Не вдалося розпізнати"}
    action = cmd.get("action")
    if wl is not None:
        wl["action"] = "%s: %s" % (action, cmd.get("say", ""))
    say = cmd.get("say", "")
    print(f"[VOICE] {cmd}")
    # Пам'ять стосунків: хто говорив і як ставився -> оновити прихильність.
    try:
        import adolf_persona
        adolf_persona.update(cmd.get("speaker"), cmd.get("tone"), cmd.get("note", ""))
    except Exception as e:
        print("[PERSONA]", type(e).__name__, e)
    if action == "set":
        dev = DEVICES.get(cmd.get("device"))
        if not dev:
            return {"ok": False, "say": "Не знайшов такий пристрій"}
        for k, v in (cmd.get("changes") or {}).items():
            dev.state[k] = v
        await dev.apply()
        return {"ok": True, "say": say or "Готово"}
    if action in ("answer", "chat"):
        return {"ok": True, "say": say}
    if action == "pc" and cmd.get("cmd") == "wake":
        wake_pc()                                # будимо ПК САМІ (агент ще спить)
        return {"ok": True, "say": say or "Вмикаю комп'ютер"}
    if action in ("movie", "control", "pc"):
        MOVIE_QUEUE.append(cmd)                  # забере агент на ПК
        return {"ok": True, "say": say or "Передаю на комп'ютер"}
    return {"ok": False, "say": say or "Не зрозумів команду"}


@app.get("/api/wakelog")
def get_wakelog():
    """Що почув Vosk з останніх кліпів мікрофона + чи пропустив на Gemini."""
    return list(reversed(WAKELOG))


@app.get("/wakelog")
def wakelog_page():
    """Жива сторінка «що чує Адольф» — відкрий http://192.168.0.109:8000/wakelog"""
    from fastapi.responses import HTMLResponse
    html = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Що чує Адольф</title><style>
body{font-family:sans-serif;background:#111;color:#eee;margin:0;padding:12px}
h2{font-size:18px}.e{padding:8px;margin:6px 0;border-radius:8px;background:#1d1d1d;border-left:4px solid #555}
.ok{border-left-color:#2ecc71}.no{border-left-color:#e74c3c}
.t{color:#888;font-size:12px}.txt{font-size:16px;margin:4px 0}.act{color:#7fd7ff;font-size:13px}
.b{font-size:11px;padding:2px 6px;border-radius:4px}.bok{background:#2ecc71;color:#000}.bno{background:#e74c3c;color:#fff}
</style></head><body><h2>🎤 Що чує Vosk (само оновлюється)</h2><div id=l>завантаження…</div><script>
async function u(){try{let d=await(await fetch('/api/wakelog')).json();
document.getElementById('l').innerHTML=d.map(e=>`<div class="e ${e.wake?'ok':'no'}">
<span class="t">${e.t}</span> <span class="b ${e.wake?'bok':'bno'}">${e.wake?'ПРОПУЩЕНО':'відкинуто'}</span>
<div class="txt">«${e.text||''}»</div>${e.action?`<div class="act">→ ${e.action}</div>`:''}</div>`).join('')||'поки порожньо (скажи щось)';
}catch(e){}}u();setInterval(u,1500);</script></body></html>"""
    return HTMLResponse(html)


@app.post("/api/movie")
async def enqueue_movie(cmd: dict):
    """Покласти кіно-команду в чергу (для агента на ПК)."""
    MOVIE_QUEUE.append(cmd)
    return {"ok": True, "queued": len(MOVIE_QUEUE)}


@app.get("/api/movie/next")
def next_movie():
    """Агент на ПК опитує це: віддаємо найстарішу команду й прибираємо з черги."""
    if MOVIE_QUEUE:
        return MOVIE_QUEUE.pop(0)
    return {}


@app.post("/api/watch")
async def set_watch(payload: dict):
    """Агент на ПК шле сюди історію переглядів (щоб Адольф її «бачив»)."""
    global WATCH_HISTORY
    WATCH_HISTORY = payload.get("items", [])
    return {"ok": True, "n": len(WATCH_HISTORY)}


@app.get("/api/watch")
def get_watch():
    """Історія переглядів (для вебсторінки «продовжити дивитися»)."""
    return WATCH_HISTORY


@app.post("/api/pc/wake")
def api_wake_pc():
    """Розбудити ПК через Wake-on-LAN (кнопка у вебінтерфейсі / тест)."""
    return {"ok": wake_pc()}


@app.get("/api/tts")
async def tts(text: str):
    """Озвучка голосом Остапа (edge-tts, uk-UA-OstapNeural) -> MP3 для браузера.
    Щоб голос на телефоні був такий самий, як у Адольфа на ПК."""
    from fastapi.responses import Response
    try:
        import edge_tts
        import io
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, "uk-UA-OstapNeural").stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return Response(content=buf.getvalue(), media_type="audio/mpeg")
    except Exception as e:
        print("[TTS]", type(e).__name__, e)
        return Response(status_code=204)   # браузер тоді озвучить сам (fallback)


@app.get("/api/automations")
def get_automations():
    return ENGINE.rules


@app.post("/api/automations")
def set_automations(rules: dict):
    ENGINE.update(rules)
    return {"ok": True}


# ── Веб-інтерфейс ───────────────────────────────────────────────────
# Єдиний вебзастосунок живе у <корінь проєкту>/webapp (спільний для хаба,
# плати та хмари). Монтуємо ПІСЛЯ /api-маршрутів, щоб вони мали пріоритет;
# html=True віддає index.html на "/" і робить відносні ./style.css робочими.
app.mount("/", StaticFiles(directory=BASE.parent / "webapp", html=True), name="webapp")
