# -*- coding: utf-8 -*-
"""Розпізнавання через Groq whisper-large-v3 (хмара, точно, безкоштовний тариф).
Замінює локальний Vosk: приймає WAV -> текст -> чи звучало «Адольф».
Ключ у home_secrets.GROQ_API_KEY. Якщо ключа/помилка — кидає виняток (хаб має
фолбек на Vosk)."""
import json
import urllib.request
import difflib
import uuid

import home_secrets

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"

WAKE_SUB = ["адольф", "дольф", "адоль", "адольв", "одольф", "надольф",
            "гадольф", "адел", "одол", "вдольф"]
WAKE_TGT = ["адольф", "адольфе", "адольфа", "адольфчик"]


def is_wake(text: str) -> bool:
    text = (text or "").lower()
    for k in WAKE_SUB:
        if k in text:
            return True
    for tok in text.split():
        if len(tok) < 3:
            continue
        for tg in WAKE_TGT:
            if difflib.SequenceMatcher(None, tok, tg).ratio() >= 0.62:
                return True
    return False


def _transcribe(wav_bytes: bytes) -> str:
    key = getattr(home_secrets, "GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("no GROQ_API_KEY")
    b = "----groq" + uuid.uuid4().hex

    def fld(name, value):
        return ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (b, name, value)).encode()

    body = fld("model", MODEL) + fld("language", "uk") + fld("response_format", "json")
    body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n"
             "Content-Type: audio/wav\r\n\r\n" % b).encode()
    body += wav_bytes + ("\r\n--%s--\r\n" % b).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "multipart/form-data; boundary=" + b,
        # Cloudflare перед Groq блокує дефолтний UA Python (error 1010) — даємо браузерний
        "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("text", "").strip()


def check(wav_bytes: bytes) -> dict:
    """-> {"wake": bool, "text": <що почув whisper>}."""
    text = _transcribe(wav_bytes)   # виняток -> хаб фолбекне на Vosk
    return {"wake": is_wake(text), "text": text}
