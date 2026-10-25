# -*- coding: utf-8 -*-
"""
Датчик клімату на платі ESP32 (DHT22): читає температуру й вологість через
HTTP-ендпоінт плати /climate.

Ці цифри — ІСТИНА для хаба (точніші за сенсор усередині кондиціонера). Хаб
перезаписує ними room_temp кондея, тож і показ, і автоматика беруть цей датчик.

Якщо плата змінила IP (DHCP) — знаходимо її скануванням підмережі (як розетка).
"""
import json
import urllib.request

from .base import Device


class ClimateSensor(Device):
    kind = "sensor"

    def __init__(self, id: str, name: str, ip: str,
                 icon: str = "🌡️", room: str = "Дім"):
        super().__init__(id, name, icon, room)
        self.ip = ip
        self.state = {"temp": None, "humid": None, "online": False}

    async def apply(self) -> None:
        pass  # датчик лише читає — керувати нема чим

    def _get(self, ip: str) -> dict:
        with urllib.request.urlopen(f"http://{ip}/climate", timeout=4) as r:
            return json.load(r)

    def _find_board(self):
        """Плата змінила IP? Шукаємо, хто в підмережі віддає /climate."""
        import concurrent.futures
        base = self.ip.rsplit(".", 1)[0]

        def probe(i):
            ip = f"{base}.{i}"
            try:
                d = self._get(ip)
                return ip if isinstance(d, dict) and ("temp" in d or "status" in d) else None
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as ex:
            for f in concurrent.futures.as_completed(
                    [ex.submit(probe, i) for i in range(2, 255)]):
                if f.result():
                    return f.result()
        return None

    async def refresh(self) -> None:
        import asyncio
        try:
            d = await asyncio.to_thread(self._get, self.ip)
        except Exception:
            ip = await asyncio.to_thread(self._find_board)   # IP міг змінитись
            if not ip:
                self.state["online"] = False
                return
            self.ip = ip
            print(f"[CLIMATE] плату знайдено на новому IP {ip}")
            try:
                d = await asyncio.to_thread(self._get, self.ip)
            except Exception:
                self.state["online"] = False
                return
        if d.get("ok") and d.get("temp") is not None:
            self.state["temp"] = round(d["temp"], 1)
            self.state["humid"] = round(d["humid"])
            self.state["online"] = True
        else:
            # плата відповіла, але датчик мовчить (status: TIMEOUT тощо)
            self.state["online"] = False
