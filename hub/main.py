"""
Розумний Дім — центральний ХАБ.

Поки що всі пристрої "фейкові" (MockDevice), щоб бачити роботу без заліза.
Коли з'явиться техніка — додамо реальні драйвери (ESP32 по MQTT, Shelly,
Tuya...) НЕ змінюючи цей файл суттєво: просто інший клас у реєстрі.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
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


def add(device) -> None:
    DEVICES[device.id] = device


# СПРАВЖНІЙ кондиціонер Cooper&Hunter — локально по WiFi (протокол Gree).
# Доступи лежать у home_secrets.py (не в git); шаблон — home_secrets.example.py.
import home_secrets

add(GreeAC("ac_living", "Кондиціонер", ip=home_secrets.AC_IP,
           mac=home_secrets.AC_MAC, key=home_secrets.AC_KEY,
           mode=home_secrets.AC_ENC, icon="❄️", room="Вітальня"))
add(MockDevice("tv_living", "Телевізор", "📺", "Вітальня"))
add(MockDevice("light_living", "Світло", "💡", "Вітальня"))
add(MockDevice("kettle", "Чайник", "☕", "Кухня"))
add(MockDevice("light_bed", "Світло", "💡", "Спальня"))

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
