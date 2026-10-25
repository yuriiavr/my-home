"""
Движок автоматизацій: клімат-контроль + правила за розкладом.

Правила зберігаються у automations.json (переживають перезапуск).
Движок «тікає» разом із фоновим опитуванням пристроїв (кожні ~10 сек).

Структура правил:
{
  "climate": {
    "enabled": true,
    "device": "ac_living",
    "trigger": 27,     # вмикати, коли в кімнаті >= стільки
    "target": 24,      # яку температуру задати й підтримувати
    "mode": "cool",
    "auto_off": true,  # вимикати, коли охолоне
    "off_below": 23    # ...до стількох (гістерезис, щоб не клацав туди-сюди)
  },
  "schedules": [
    {"enabled": true, "time": "22:30", "device": "ac_living",
     "action": "set",  # "on" = увімкнути з налаштуваннями, "off", "set" = лише змінити
     "set": {"mode": "cool", "temp": 25, "fan": 0, "quiet": true, "sleep": true}}
  ]
}
"""
import json
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).parent / "automations.json"

DEFAULT = {
    "climate": {
        "enabled": False, "device": "ac_living",
        "trigger": 27, "target": 24, "mode": "cool",
        "auto_off": True, "off_below": 23,
    },
    "schedules": [],
}


def load() -> dict:
    if FILE.exists():
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT))


def save(rules: dict) -> None:
    FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=1),
                    encoding="utf-8")


class Engine:
    def __init__(self, devices: dict):
        self.devices = devices
        self.rules = load()
        self._fired: dict[int, str] = {}   # № правила -> коли востаннє спрацювало
        self._climate_on_by_us = False     # чи це МИ увімкнули (щоб не воювати з людиною)

    def update(self, rules: dict) -> None:
        self.rules = rules
        save(rules)

    async def tick(self) -> None:
        try:
            await self._climate()
        except Exception as e:
            print(f"[AUTO] climate error: {e}")
        try:
            await self._schedules()
        except Exception as e:
            print(f"[AUTO] schedule error: {e}")

    # ── Клімат-контроль ────────────────────────────────────────────
    async def _climate(self) -> None:
        c = self.rules.get("climate") or {}
        if not c.get("enabled"):
            self._climate_on_by_us = False
            return
        d = self.devices.get(c.get("device"))
        if d is None:
            return
        room = d.state.get("room_temp")
        if room is None:
            return

        if not d.state.get("on") and room >= c.get("trigger", 27):
            d.state.update({
                "on": True,
                "temp": int(c.get("target", 24)),
                "mode": c.get("mode", "cool"),
            })
            await d.apply()
            self._climate_on_by_us = True
            print(f"[AUTO] 🌡 {room}°C >= {c.get('trigger')}°C -> "
                  f"УВІМКНУВ {c.get('target')}°C")

        elif (d.state.get("on") and c.get("auto_off")
              and room <= c.get("off_below", 23)):
            # Термостат: охолов до off_below -> вимикаємо, НЕЗАЛЕЖНО хто ввімкнув
            # (раніше вимикали лише те, що самі ввімкнули — це збивало з пантелику).
            d.state["on"] = False
            await d.apply()
            self._climate_on_by_us = False
            print(f"[AUTO] 🌡 {room}°C <= {c.get('off_below')}°C -> ВИМКНУВ")

    # ── Розклади ───────────────────────────────────────────────────
    async def _schedules(self) -> None:
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        hhmm = now.strftime("%H:%M")
        for i, r in enumerate(self.rules.get("schedules", [])):
            if not r.get("enabled", True) or r.get("time") != hhmm:
                continue
            if self._fired.get(i) == stamp:
                continue  # цієї хвилини вже спрацювало
            d = self.devices.get(r.get("device"))
            if d is None:
                continue
            self._fired[i] = stamp

            action = r.get("action", "set")
            changes = dict(r.get("set") or {})
            if action == "on":
                changes["on"] = True
            elif action == "off":
                changes = {"on": False}
            for k, v in changes.items():
                d.state[k] = v
            await d.apply()
            print(f"[AUTO] ⏰ {r.get('time')} -> {d.name}: {changes}")
