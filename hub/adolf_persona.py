# -*- coding: utf-8 -*-
"""
Особистість Адольфа з ПАМ'ЯТТЮ ПРО СТОСУНКИ.

Пам'ятає, як кожна людина ставилась до нього останнім часом, і відповідає
відповідно: добре ставишся — теплий; грубиш — підколює й ображається;
вибачаєшся — може пробачити (на свій розсуд). Розрізняє людей за голосом
(Gemini визначає, хто говорить, зокрема чоловік/жінка).

Стан живе в adolf_memory.json (переживає перезапуск).
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(HERE, "adolf_memory.json")

# Люди, яких знає Адольф. gender ("чоловік"/"жінка") допомагає розрізняти за
# голосом. Заповни реальними іменами (див. PEOPLE у README/розмові).
PEOPLE = {
    "юра":  {"gender": "чоловік"},
    "маша": {"gender": "жінка"},
}

# Наскільки змінюється прихильність за тон репліки:
_DELTA = {"insult": -18, "rude": -10, "neutral": 0, "kind": 8,
          "thanks": 6, "compliment": 12, "apology": 14}


def _load() -> dict:
    try:
        with open(MEM, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        with open(MEM, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _person(mem: dict, name: str) -> dict:
    p = mem.setdefault(name, {"affinity": 0.0, "notes": [], "updated": time.time()})
    # Згасання: старі образи/симпатії потроху вивітрюються до нейтралу
    # (≈ повне згасання за ~3 доби без взаємодії).
    dt = time.time() - p.get("updated", time.time())
    if dt > 0:
        p["affinity"] *= max(0.0, 1.0 - min(1.0, dt / (3 * 24 * 3600)))
    return p


def _mood(aff: float) -> str:
    if aff > 60:  return "обожнює цю людину"
    if aff > 20:  return "тепло ставиться"
    if aff > -15: return "нейтрально"
    if aff > -45: return "ображений, холодний, підколює"
    return "злий, дуже уїдливий"


def context() -> str:
    """Опис людей + поточних стосунків для промпту Gemini."""
    mem = _load()
    lines = []
    for name, info in PEOPLE.items():
        p = _person(mem, name)
        aff = round(p["affinity"])
        notes = "; ".join(p["notes"][-4:]) or "поки без історії"
        lines.append(f"- {name} ({info['gender']}): прихильність {aff:+d} — "
                     f"{_mood(aff)}. Нещодавно: {notes}")
    return "\n".join(lines)


def names_hint() -> str:
    """Короткий список людей для інструкції розпізнавання голосу."""
    return "; ".join(f"«{n}» ({i['gender']})" for n, i in PEOPLE.items())


def update(speaker, tone, note: str = "") -> None:
    """Оновити стосунок після репліки. speaker — ім'я; tone — kind/thanks/
    compliment/neutral/rude/insult/apology; note — короткий спогад."""
    if not speaker:
        return
    speaker = str(speaker).strip().lower()
    if speaker not in PEOPLE:
        return
    mem = _load()
    p = _person(mem, speaker)
    p["affinity"] = max(-100.0, min(100.0, p["affinity"] + _DELTA.get(tone, 0)))
    if note:
        p["notes"] = (p["notes"] + [note.strip()])[-8:]
    p["updated"] = time.time()
    mem[speaker] = p
    _save(mem)
