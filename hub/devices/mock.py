"""
Тестовий драйвер: імітує пристрій БЕЗ заліза.

Дозволяє бачити роботу хаба вже зараз. Коли приїде ESP32/розетки —
підмінимо MockDevice на реальні драйвери, а система лишиться тією ж.
"""
from .base import Device


class MockDevice(Device):
    async def apply(self) -> None:
        state = "УВІМК" if self.state["on"] else "ВИМК"
        print(f"[MOCK] {self.name} ({self.room}) -> {state}")
