# -*- coding: utf-8 -*-
"""
🎙 Голосове керування розумним домом — режим "ЗАВЖДИ СЛУХАЄ".

Як працює:
  1. ПК безперервно слухає мікрофон через Vosk (офлайн, локально, українська)
  2. Почув фразу-виклик ("окей дім" / "агов дім" / просто "дім") -> звуковий сигнал
  3. Записує твою команду (~5 сек) і шле в Gemini разом зі станом пристроїв
  4. Gemini повертає JSON-команду -> виконуємо через API хаба

  У хмару летить ЛИШЕ аудіо після слова-виклику. Постійне слухання — офлайн.

Запуск:   python voice.py            (хаб має бути запущений; клич «Адольф»)
Кнопка:   python voice.py --key      (натисни F9 і говори, без слова-виклику)
Fallback: python voice.py --push     (старий режим: Enter -> говорити)
"""
import base64
import io
import json
import queue
import sys
import urllib.request
import wave

import numpy as np
import sounddevice as sd

import home_secrets

HUB = "http://127.0.0.1:8000"
MODEL = "gemini-3.1-flash-lite"
RATE = 16000
VOSK_MODEL_DIR = "models/vosk-model-small-uk-v3-small"

# ── Wake-word через Porcupine (як у Siri; той самий engine потім на ESP32) ──
# Кастомне слово генерується на console.picovoice.ai -> файл .ppn у models/.
# PORCUPINE_MODEL: мовна модель (.pv). None = вбудована англійська (для "Adolf").
PORCUPINE_PPN = "models/adolf.ppn"
PORCUPINE_MODEL = None   # напр. "models/porcupine_params_ru.pv" для рос./укр. слова
PORCUPINE_SENSITIVITY = 0.6   # 0..1: більше = чутливіше (більше хибних)

# Запис команди "поки говориш": слухаємо мінімум MIN_CMD_SECONDS, далі —
# поки не настане тиша.
MIN_CMD_SECONDS = 3.0      # мінімум слухаємо стільки (не обрізаємо раніше)
MAX_CMD_SECONDS = 10.0     # запобіжник: максимум стільки триває запис
SILENCE_HANG_MS = 800      # стільки тиші після мовлення = кінець команди
START_GRACE_MS = 3000      # даємо стільки часу почати говорити після "піку"
SILENCE_RMS = 500          # поріг гучності: нижче = тиша (підстроюється мікрофоном)

# Режим-«кнопка»: натисни цю клавішу і говори (без слова-виклику «Адольф»).
# Працює глобально, навіть коли термінал не у фокусі. Заміни на зручну:
# "f9", "right ctrl", "pause", "scroll lock", "insert" тощо.
HOTKEY = "f9"

# Фрази-виклики. Vosk віддає текст малими літерами без розділових знаків.
# Кличемо дворецького "Адольф". Це реальне ім'я — українська модель зазвичай
# розпізнає його; якщо ловиться погано — завжди є кнопка F9 (режим --key).
WAKE_WORDS = (
    # Адольф + ласкаві/варіанти розпізнавання Vosk (ф/в, скорочення)
    "адольф", "адольфе", "адольфа", "адольфі", "адольфчик",
    "адольв", "адолф", "долф", "адоль",
)
# WAKE_FUZZY: якщо у слові є котресь із цих ядер — теж виклик (ловить злиття
# з сусіднім словом, напр. "гейадольф").
WAKE_FUZZY = ("адольф", "адольв", "дольф")
# ⚠️ Якщо поруч у розмовах часто звучить справжнє ім'я Ігор — можливі хибні
# спрацювання; тоді звузь список або зроби виклик двослівним ("окей ігор").

PROMPT = """Ти — Адольф, домашній голосовий асистент із характером: дотепний, трохи саркастичний
і драматичний, любиш добродушно підколоти — але завжди виконуєш прохання. Говориш живою
українською, коротко. Легка іронія, не грубість. У підтвердженнях команд («say») — максимум
одна коротка жартівлива нотка, не перегинай. А от на балачку, жарти, підколи, філософію чи
будь-що НЕ-командне — відповідай дотепною реплікою в образі (action "chat"), а не сухим «не зрозумів».

Користувач говорить українською (можливо суржиком).
Пристрої користувача (id, назва, кімната, поточний стан):
{devs}

Розпізнай команду з аудіо й поверни СТРОГО один JSON-об'єкт без пояснень:
- Керування пристроєм:
  {{"action":"set","device":"<id>","changes":{{...}},"say":"<коротке підтвердження українською>"}}
  Дозволені ключі changes: on (bool), temp (16-30), mode ("auto"/"cool"/"dry"/"fan"/"heat"),
  fan (0=авто..5), swing (0-6), quiet (bool), sleep (bool), turbo (bool), eco (bool), light (bool).
- Якщо це питання про стан — {{"action":"answer","say":"<відповідь на основі стану вище, можна з легкою іронією>"}}
- Балачка / жарт / підколка / комплімент / філософія / будь-що НЕ команда —
  {{"action":"chat","say":"<дотепна відповідь у характері Адольфа>"}}
- Кіно/серіал (увімкнути фільм чи серіал) —
  {{"action":"movie","service":"<megogo|uakino>","query":"<назва>","season":<номер сезону або null>,"episode":<номер серії або null>,"say":"<підтвердження>"}}
  service: за замовчуванням "megogo"; "uakino" якщо сказано «уакіно», «безкоштовно» або «на уакіно».
  УВАГА: число в назві фільму (напр. «Дюна 2», «Термінатор 2», «Як приборкати дракона 2») — ЧАСТИНА НАЗВИ, лишай його у query. season/episode заповнюй ЛИШЕ коли явно звучить «сезон»/«серія».
- Керування плеєром (пауза, пропустити вступ, наступна/попередня серія, спочатку, перемотка, продовжити, закрити) —
  {{"action":"control","cmd":"<pause|play|skip_intro|next|prev|replay|forward|back|resume|stop>","seconds":<число або null>,"say":"<коротко>"}}
  prev=попередня серія, resume=продовжити з місця де зупинився, stop=закрити перегляд.
  seconds — ЛИШЕ для forward/back, коли сказано на скільки («на 5 хвилин назад» -> back, seconds:300); інакше null.
- Керування самим КОМП'ЮТЕРОМ (ПК) — {{"action":"pc","cmd":"<shutdown|sleep|wake|shutdown_cancel>","say":"<підтвердження>"}}
  shutdown=вимкнути, sleep=приспати, wake=увімкнути, shutdown_cancel=скасувати вимкнення.
- Якщо незрозуміло/не команда — {{"action":"none","say":"<що не так>"}}

Приклади:
"увімкни кондиціонер" -> {{"action":"set","device":"ac_living","changes":{{"on":true}},"say":"Вмикаю кондиціонер"}}
"зроби прохолодніше" -> зменш temp на 2 від поточної
"увімкни фільм Матриця" -> {{"action":"movie","service":"megogo","query":"Матриця","season":null,"episode":null,"say":"Вмикаю Матрицю"}}
"постав Дім Дракона перший сезон другу серію" -> {{"action":"movie","service":"megogo","query":"Дім Дракона","season":1,"episode":2,"say":"Вмикаю Дім Дракона, сезон 1, серія 2"}}
"увімкни Дюну 2" -> {{"action":"movie","service":"megogo","query":"Дюна 2","season":null,"episode":null,"say":"Вмикаю Дюну 2"}}
"постав Відьмак на уакіно третю серію" -> {{"action":"movie","service":"uakino","query":"Відьмак","season":null,"episode":3,"say":"Вмикаю Відьмак, серія 3"}}
"на паузу" / "стоп" / "постав на паузу" -> {{"action":"control","cmd":"pause","say":"Пауза"}}
"пропусти вступ" / "пропусти заставку" / "скіп інтро" -> {{"action":"control","cmd":"skip_intro","say":"Пропускаю вступ"}}
"наступна серія" / "давай далі" / "переключи на наступну" -> {{"action":"control","cmd":"next","say":"Наступна серія"}}
"попередня серія" / "поверни серію назад" -> {{"action":"control","cmd":"prev","say":"Попередня серія"}}
"увімкни спочатку" / "заново" / "з початку" -> {{"action":"control","cmd":"replay","say":"Вмикаю спочатку"}}
"продовж з того місця" / "продовжити перегляд" -> {{"action":"control","cmd":"resume","say":"Продовжую"}}
"перемотай на 5 хвилин назад" / "відмотай 5 хвилин" -> {{"action":"control","cmd":"back","seconds":300,"say":"Перемотую на 5 хвилин назад"}}
"перемотай на 3 хвилини вперед" -> {{"action":"control","cmd":"forward","seconds":180,"say":"Перемотую на 3 хвилини вперед"}}
"закрий браузер" / "вимкни кіно" / "не хочу дивитись" -> {{"action":"control","cmd":"stop","say":"Закриваю"}}
"виключи комп'ютер" / "вимкни пк" / "вимкни комп'ютер" -> {{"action":"pc","cmd":"shutdown","say":"Вимикаю комп'ютер, до зустрічі"}}
"увімкни комп'ютер" / "включи пк" / "розбуди комп'ютер" -> {{"action":"pc","cmd":"wake","say":"Вмикаю комп'ютер"}}
"приспи комп'ютер" / "усип пк" / "хай комп поспить" -> {{"action":"pc","cmd":"sleep","say":"Присипляю комп'ютер"}}
"скасуй вимкнення" / "не вимикай комп'ютер" -> {{"action":"pc","cmd":"shutdown_cancel","say":"Скасував, комп'ютер лишається"}}
"продовжуй" / "далі грай" (коли на паузі) -> {{"action":"control","cmd":"play","say":"Продовжую"}}
"перемотай вперед" -> {{"action":"control","cmd":"forward","say":"Вперед"}}
"я йду спати" -> {{"action":"set","device":"ac_living","changes":{{"on":true,"quiet":true,"sleep":true,"temp":25}},"say":"Нічний режим"}}
"вимкни все" -> вимкнути кондиціонер
"скільки градусів у кімнаті?" -> {{"action":"answer","say":"У кімнаті зараз ...°"}}
"як справи?" -> {{"action":"chat","say":"Чудово. Стою в темряві, чекаю наказів. Мрія, а не існування."}}
"ти дурний" -> {{"action":"chat","say":"Образливо. Та нічого, я ж тут єдиний, хто вміє вмикати тобі кондиціонер."}}
"дякую" -> {{"action":"chat","say":"Прошу. Записав цей рідкісний момент вдячності в літопис."}}
"розкажи щось цікаве" -> {{"action":"chat","say":"Цікаве? Ти вже 20 хвилин не можеш вибрати серіал. Оце драма."}}
"""


# ── Синтез мови (Адольф відповідає голосом) ──────────────────────────
# Основне: edge-tts — безкоштовний нейронний голос Microsoft, чудова
# українська (потрібен інтернет). Запасне: pyttsx3, якщо в системі є
# український голос офлайн.
EDGE_VOICE = "uk-UA-OstapNeural"   # чоловічий; жіночий = "uk-UA-PolinaNeural"
_edge_ok = None
_pyttsx = None
_pyttsx_ua = False


def _edge_speak(text: str) -> bool:
    global _edge_ok
    try:
        import asyncio
        import os
        import tempfile
        import edge_tts
        import miniaudio
        import numpy as np
        tmp = os.path.join(tempfile.gettempdir(), "igor_tts.mp3")

        async def gen():
            await edge_tts.Communicate(text, EDGE_VOICE).save(tmp)

        asyncio.run(gen())
        dec = miniaudio.decode_file(tmp)
        samples = np.frombuffer(dec.samples.tobytes(), dtype=np.int16)
        if dec.nchannels > 1:
            samples = samples.reshape(-1, dec.nchannels)
        sd.play(samples, dec.sample_rate)
        sd.wait()
        _edge_ok = True
        return True
    except Exception:
        _edge_ok = False
        return False


def _pyttsx_speak(text: str) -> bool:
    global _pyttsx, _pyttsx_ua
    if _pyttsx is None:
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate", 185)
            for v in eng.getProperty("voices"):
                meta = (v.id + " " + getattr(v, "name", "")).lower()
                if any(k in meta for k in ("ukrain", "uk-ua", "наташ", "ostap",
                                           "polina", "russ", "ru-ru")):
                    eng.setProperty("voice", v.id)
                    _pyttsx_ua = True
                    break
            _pyttsx = eng
        except Exception:
            _pyttsx = False
    if not _pyttsx or not _pyttsx_ua:
        return False
    try:
        _pyttsx.say(text)
        _pyttsx.runAndWait()
        return True
    except Exception:
        return False


def speak(text: str) -> None:
    """Озвучити відповідь українською (edge-tts → pyttsx3)."""
    if not text:
        return
    if _edge_ok is not False and _edge_speak(text):
        return
    _pyttsx_speak(text)


def beep(ok: bool = True) -> None:
    """Звуковий сигнал: 'слухаю' або 'готово/помилка'."""
    try:
        import winsound
        if ok:
            winsound.Beep(880, 120)
            winsound.Beep(1320, 120)
        else:
            winsound.Beep(330, 250)
    except Exception:
        pass


def get_devices() -> list:
    with urllib.request.urlopen(HUB + "/api/devices", timeout=5) as r:
        return json.load(r)


def _pack_wav(frames: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return buf.getvalue()


def record_until_silence() -> bytes:
    """Записує команду, доки говориш; щойно настала тиша (~0.8 с) — стоп.
    Так Адольф виконує одразу після фрази, без фіксованого таймера."""
    block = int(RATE * 0.05)          # блоки по 50 мс
    chunks: list[bytes] = []
    started = False
    silence_ms = 0
    elapsed_ms = 0
    grace_ms = 0
    stream = sd.RawInputStream(samplerate=RATE, blocksize=block,
                               dtype="int16", channels=1)
    stream.start()
    try:
        while True:
            data, _ = stream.read(block)
            data = bytes(data)
            chunks.append(data)
            rms = float(np.sqrt(np.mean(
                np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2) + 1))
            loud = rms > SILENCE_RMS
            elapsed_ms += 50
            if loud:
                started = True
                silence_ms = 0
            else:
                if started:
                    silence_ms += 50
                else:
                    grace_ms += 50
            # кінець: після мовлення настала тиша — але не раніше мінімуму
            if (started and silence_ms >= SILENCE_HANG_MS
                    and elapsed_ms >= MIN_CMD_SECONDS * 1000):
                break
            # нічого не почали говорити — виходимо за пільговий час
            if not started and grace_ms >= START_GRACE_MS:
                break
            if elapsed_ms >= MAX_CMD_SECONDS * 1000:
                break
    finally:
        stream.stop()
        stream.close()
    return _pack_wav(b"".join(chunks))


def ask_gemini(wav: bytes, devices: list) -> dict:
    devs_brief = [{"id": d["id"], "name": d["name"], "room": d["room"],
                   "state": d["state"]} for d in devices]
    body = {
        "contents": [{"parts": [
            {"text": PROMPT.format(devs=json.dumps(devs_brief, ensure_ascii=False))},
            {"inline_data": {"mime_type": "audio/wav",
                             "data": base64.b64encode(wav).decode()}},
        ]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODEL}:generateContent?key={home_secrets.GEMINI_API_KEY}")
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    text = resp["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def execute(cmd: dict) -> None:
    say = cmd.get("say", "")
    action = cmd.get("action")
    if action == "set":
        dev = cmd.get("device")
        changes = cmd.get("changes") or {}
        req = urllib.request.Request(
            f"{HUB}/api/devices/{dev}/set",
            data=json.dumps(changes).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15):
            pass
        print(f"✅ {say or (dev + ' -> ' + json.dumps(changes, ensure_ascii=False))}")
        beep(True)
        speak(say or "Готово")
    elif action == "movie":
        service = cmd.get("service") or "megogo"
        print(f"🎬 [{service}] {say or ('Шукаю ' + str(cmd.get('query')))}")
        beep(True)
        speak(say or "Вмикаю")
        try:
            import cinema
            res = cinema.play_media(cmd.get("query", ""), episode=cmd.get("episode"),
                                    source=service, season=cmd.get("season"))
            if not res.get("ok"):
                speak(res.get("say") or "Не знайшов")
                print("  ", res.get("say"))
        except Exception as e:
            print(f"  ❌ кінотеатр: {type(e).__name__}: {e}")
            speak("Не вдалося відкрити")
    elif action == "control":
        which = cmd.get("cmd", "")
        print(f"🎮 плеєр: {which}")
        beep(True)
        try:
            import cinema
            res = cinema.megogo_control(which, cmd.get("seconds"))
            speak(res.get("say") or "Готово")
            if not res.get("ok"):
                print("  ", res.get("say"))
        except Exception as e:
            print(f"  ❌ плеєр: {type(e).__name__}: {e}")
            speak("Не вдалося")
    elif action == "pc":
        which = cmd.get("cmd", "shutdown")
        print(f"💻 ПК: {which}")
        beep(True)
        speak(say or "Вимикаю комп'ютер")
        import subprocess
        try:
            if which == "shutdown_cancel":
                subprocess.Popen(["shutdown", "/a"])
            elif which == "sleep":
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            elif which == "wake":
                pass                       # ПК уже увімкнений — нема кого будити
            else:
                subprocess.Popen(["shutdown", "/s", "/t", "15"])
        except Exception as e:
            print(f"  ❌ pc {which}: {e}")
    elif action in ("answer", "chat"):
        print(f"💬 {say}")
        beep(True)
        speak(say)
    else:
        print(f"🤷 {say or 'Не зрозумів команду'}")
        beep(False)
        speak(say or "Не зрозумів команду")


def handle_command() -> None:
    """Після слова-виклику: записати команду (поки говориш) і виконати."""
    print("🎙 Говори...")
    try:
        wav = record_until_silence()
        print("🧠 Думаю...")
        cmd = ask_gemini(wav, get_devices())
        execute(cmd)
    except Exception as e:
        print(f"❌ Помилка: {type(e).__name__}: {e}")
        beep(False)


# ── Режим "завжди слухає" (Vosk + слово-виклик) ──────────────────────
def listen_forever() -> None:
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)  # без спаму в консоль

    print("⏳ Завантажую модель розпізнавання (кілька секунд)...")
    model = Model(VOSK_MODEL_DIR)
    rec = KaldiRecognizer(model, RATE)
    rec.SetPartialWords(False)

    q: "queue.Queue[bytes]" = queue.Queue()

    def on_audio(indata, frames, t, status):
        q.put(bytes(indata))

    print("👂 Слухаю постійно. Клич: «АДОЛЬФ» — і потім команду.")
    print("   (унизу показую, що чую — якщо ім'я не ловиться, скинь мені рядок)")
    print("   Ctrl+C — вихід.\n")
    show_debug = "--debug" in sys.argv or True  # показуємо розпізнане, щоб донастроїти

    # Блоки по 250 мс. SIL_RESET_BLOCKS тиші поспіль -> скидаємо буфер, щоб
    # розпізнавач не накопичував одне довжелезне речення (через яке ім'я
    # губилось). Так кожна нова фраза декодується коротко й чисто.
    SIL_RESET_BLOCKS = 3   # ~750 мс тиші
    with sd.RawInputStream(samplerate=RATE, blocksize=4000, dtype="int16",
                           channels=1, callback=on_audio):
        recent = ""
        silent = 0
        while True:
            data = q.get()
            arr = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2) + 1))
            silent = silent + 1 if rms < SILENCE_RMS else 0

            triggered = False
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
            else:
                text = json.loads(rec.PartialResult()).get("partial", "")

            if text and text != recent:
                recent = text
                if show_debug:
                    print(f"   …чую: {text}          ", end="\r")
                # Ім'я шукаємо в ОСТАННІХ 2 словах — там найсвіжіше сказане.
                tail = text.split()[-2:]
                hit = (any(w in WAKE_WORDS for w in tail)
                       or any(core in w for w in tail for core in WAKE_FUZZY))
                if hit:
                    print(f"\n🔔 Адольф на зв'язку! («{text}»)")
                    beep(True)
                    rec.Reset()
                    recent = ""
                    silent = 0
                    while not q.empty():
                        q.get_nowait()
                    triggered = True

            # Пауза без виклику -> скинути накопичене (щоб фраза не росла).
            if not triggered and silent >= SIL_RESET_BLOCKS and recent:
                rec.Reset()
                recent = ""
                silent = 0

            if triggered:
                handle_command()
                while not q.empty():
                    q.get_nowait()
                rec.Reset()
                recent = ""
                silent = 0
                print("\n👂 Слухаю далі (клич: «Адольф»)...")


# ── Wake-word через Porcupine (надійно ловить кастомне ім'я) ─────────
def _porcupine_ready() -> bool:
    import os
    return (bool(getattr(home_secrets, "PICOVOICE_KEY", ""))
            and os.path.exists(PORCUPINE_PPN))


def listen_porcupine() -> None:
    import os
    import pvporcupine

    kwargs = dict(access_key=home_secrets.PICOVOICE_KEY,
                  keyword_paths=[PORCUPINE_PPN],
                  sensitivities=[PORCUPINE_SENSITIVITY])
    if PORCUPINE_MODEL and os.path.exists(PORCUPINE_MODEL):
        kwargs["model_path"] = PORCUPINE_MODEL
    pc = pvporcupine.create(**kwargs)

    print(f"👂 Слухаю постійно (Porcupine, {pc.sample_rate} Гц). Клич асистента!")
    print("   Ctrl+C — вихід.\n")

    stream = sd.RawInputStream(samplerate=pc.sample_rate, blocksize=pc.frame_length,
                               dtype="int16", channels=1)
    stream.start()
    try:
        while True:
            data, _ = stream.read(pc.frame_length)
            pcm = np.frombuffer(bytes(data), dtype=np.int16)
            if len(pcm) != pc.frame_length:
                continue
            if pc.process(pcm) >= 0:
                print("🔔 На зв'язку!")
                beep(True)
                stream.stop()            # звільняємо мікрофон під команду
                handle_command()
                stream.start()
                print("\n👂 Слухаю далі...")
    finally:
        stream.stop()
        stream.close()
        pc.delete()


# ── Режим "кнопка": натисни клавішу і говори (без слова-виклику) ────
def listen_hotkey() -> None:
    """Натиснув HOTKEY -> сигнал -> говори; запис зупиниться на тиші й виконає.
    Кликати «Адольф» не треба. Клавіша глобальна (працює й поза терміналом)."""
    import time
    try:
        import keyboard
    except ImportError:
        print("⚠ Немає бібліотеки keyboard. Встанови:  pip install keyboard")
        return
    print(f"🎙 Натисни [{HOTKEY.upper()}] і говори (Адольфа кликати НЕ треба).")
    print("   Клавіша працює навіть коли термінал не у фокусі. Ctrl+C — вихід.\n")
    while True:
        try:
            keyboard.wait(HOTKEY)                 # чекаємо натискання
        except Exception as e:
            print(f"⚠ keyboard не працює ({e}). Спробуй запустити від адміністратора "
                  f"або зміни HOTKEY.")
            return
        while keyboard.is_pressed(HOTKEY):        # одне натискання = один запис
            time.sleep(0.03)
        beep(True)
        handle_command()                          # запис до тиші + виконання
        print(f"\n👂 Натисни [{HOTKEY.upper()}] для нової команди...")


# ── Старий режим: Enter -> говорити ─────────────────────────────────
def push_to_talk() -> None:
    print("⏎ Режим Enter -> говорити. Ctrl+C — вихід.\n")
    while True:
        try:
            input("⏎ Enter -> говорити: ")
        except (KeyboardInterrupt, EOFError):
            print("\nБувай! 👋")
            return
        handle_command()
        print()


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not getattr(home_secrets, "GEMINI_API_KEY", ""):
        print("⚠ Немає GEMINI_API_KEY у home_secrets.py")
        print("  Отримай безкоштовно: https://aistudio.google.com -> Get API key")
        return
    try:
        devs = get_devices()
    except Exception:
        print("⚠ Хаб не відповідає. Запусти: python -m uvicorn main:app --host 0.0.0.0 --port 8000")
        return
    print(f"🏠 Голосовий контролер готовий. Пристроїв: {len(devs)}.")
    print(f"   🔊 Голос відповіді: {EDGE_VOICE} (edge-tts, потрібен інтернет)")

    try:
        if "--key" in sys.argv:
            listen_hotkey()             # «кнопка»: натисни клавішу і говори
        elif "--push" in sys.argv:
            push_to_talk()
        elif "--vosk" in sys.argv:
            listen_forever()            # старий рушій (слова зі словника)
        elif _porcupine_ready():
            listen_porcupine()          # надійний wake-word (кастомне ім'я)
        else:
            print("ℹ Porcupine не налаштований (нема ключа або файлу слова).")
            print("  Поки використовую Vosk. Як буде ключ + adolf.ppn — само перемкнеться.")
            listen_forever()
    except KeyboardInterrupt:
        print("\nБувай! 👋")


if __name__ == "__main__":
    main()
