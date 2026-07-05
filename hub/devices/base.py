"""
Базовий інтерфейс пристрою ("драйвер").

СЕРЦЕ РОЗШИРЮВАНОСТІ.
Уся система (API, інтерфейс) працює ЛИШЕ з цим інтерфейсом і не знає,
який бренд/протокол під ним. Щоб додати новий пристрій (ESP32, Shelly,
Tuya, Zigbee...) — створюєш новий клас, що успадковує Device, і реалізуєш
метод apply(). Решта хаба не змінюється — у цьому вся ідея.
"""
from abc import ABC, abstractmethod


class Device(ABC):
    kind = "switch"   # тип для інтерфейсу: "switch" = просто вкл/викл, "ac" = кондиціонер

    def __init__(self, id: str, name: str, icon: str = "🔌", room: str = "Дім"):
        self.id = id
        self.name = name
        self.icon = icon
        self.room = room
        self.state = {"on": False}

    @abstractmethod
    async def apply(self) -> None:
        """Надіслати поточний self.state у реальний пристрій.

        Тут живе код конкретного бренду (MQTT-повідомлення, HTTP-запит тощо).
        """
        ...

    async def set_on(self, on: bool) -> None:
        self.state["on"] = on
        await self.apply()

    async def toggle(self) -> None:
        await self.set_on(not self.state["on"])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "room": self.room,
            "kind": self.kind,
            "state": self.state,
        }
