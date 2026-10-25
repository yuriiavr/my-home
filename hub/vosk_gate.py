# -*- coding: utf-8 -*-
"""Обгортка над локальним Vosk-сервісом (Debian-proot, 127.0.0.1:8600).
Хаб питає його ПЕРЕД Gemini: чи звучало «Адольф»? Якщо сервіс недоступний —
{"wake": False, "text": "(vosk offline)"} (fail-closed, щоб не флудити Gemini)."""
import json
import urllib.request

URL = "http://127.0.0.1:8600/wake"


def check(wav_bytes: bytes) -> dict:
    """-> {"wake": bool, "text": <що почув Vosk>}."""
    try:
        req = urllib.request.Request(URL, data=wav_bytes,
                                     headers={"Content-Type": "audio/wav"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.load(r)
        return {"wake": bool(res.get("wake")), "text": res.get("text", "")}
    except Exception as e:
        return {"wake": False, "text": "(vosk offline: %s)" % type(e).__name__}


def has_wake(wav_bytes: bytes) -> bool:   # сумісність зі старим кодом
    return check(wav_bytes)["wake"]
