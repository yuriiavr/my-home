"""
Драйвер кондиціонера Gree / Cooper&Hunter (WiFi, локально, без хмари).

Протокол: UDP порт 7000, JSON, шифрування AES.
Старі прошивки — AES-ECB, нові (2022+) — AES-GCM. Підтримуємо обидві:
1) scan  — знайти кондиціонер у мережі (broadcast, завжди ECB)
2) bind  — отримати персональний ключ (пробуємо ECB, потім GCM)
3) cmd   — команди: Pow (увімк/вимк), SetTem (температура), Mod (режим)...

Реалізовано з нуля (лише pycryptodome).
"""
import base64
import json
import socket

from Crypto.Cipher import AES

from .base import Device

PORT = 7000
ECB_KEY = b"a3K8Bx%2r8Y7#xDh"       # спільний ключ старих прошивок
GCM_KEY = b"{yxAHAY_Lm6pbC/<"       # спільний ключ нових прошивок (GCM)
GCM_IV  = bytes.fromhex("5440784449675a516c5e6313")
GCM_AAD = b"qualcomm-test"


# ── шифрування ───────────────────────────────────────────────────────
def _enc_ecb(data: dict, key: bytes) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    return base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(raw)).decode()


def _dec_ecb(blob: str, key: bytes) -> dict:
    raw = AES.new(key, AES.MODE_ECB).decrypt(base64.b64decode(blob))
    raw = raw[: -raw[-1]]
    return json.loads(raw)


def _enc_gcm(data: dict, key: bytes) -> tuple[str, str]:
    raw = json.dumps(data, separators=(",", ":")).encode()
    c = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
    c.update(GCM_AAD)
    enc, tag = c.encrypt_and_digest(raw)
    return base64.b64encode(enc).decode(), base64.b64encode(tag).decode()


def _dec_gcm(blob: str, tag: str, key: bytes) -> dict:
    c = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
    c.update(GCM_AAD)
    raw = c.decrypt_and_verify(base64.b64decode(blob), base64.b64decode(tag))
    return json.loads(raw)


# ── UDP ──────────────────────────────────────────────────────────────
def _udp(ip: str, payload: dict, timeout: float = 4.0) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(json.dumps(payload, separators=(",", ":")).encode(), (ip, PORT))
        data, addr = sock.recvfrom(65536)
        resp = json.loads(data.decode())
        resp["_ip"] = addr[0]
        return resp
    finally:
        sock.close()


def scan(broadcast: str = "192.168.0.255") -> list[dict]:
    """Знайти всі Gree-пристрої в мережі."""
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(3.0)
    try:
        sock.sendto(b'{"t":"scan"}', (broadcast, PORT))
        while True:
            try:
                data, addr = sock.recvfrom(65536)
            except socket.timeout:
                break
            resp = json.loads(data.decode())
            if "pack" not in resp:
                continue
            pack = _dec_ecb(resp["pack"], ECB_KEY)
            found.append({
                "ip": addr[0],
                "mac": pack.get("cid") or pack.get("mac"),
                "name": pack.get("name", "?"),
            })
    finally:
        sock.close()
    return found


def bind(ip: str, mac: str) -> tuple[str, str]:
    """Отримати ключ пристрою. Повертає (key, mode), mode = 'ecb' | 'gcm'."""
    inner = {"mac": mac, "t": "bind", "uid": 0}
    # Спроба 1: стара прошивка (ECB)
    try:
        pack = _enc_ecb(inner, ECB_KEY)
        resp = _udp(ip, {"cid": "app", "i": 1, "pack": pack,
                         "t": "pack", "tcid": mac, "uid": 0}, timeout=3.0)
        return _dec_ecb(resp["pack"], ECB_KEY)["key"], "ecb"
    except (TimeoutError, socket.timeout, KeyError, ValueError):
        pass
    # Спроба 2: нова прошивка (GCM)
    pack, tag = _enc_gcm(inner, GCM_KEY)
    resp = _udp(ip, {"cid": "app", "i": 1, "pack": pack, "tag": tag,
                     "t": "pack", "tcid": mac, "uid": 0}, timeout=5.0)
    return _dec_gcm(resp["pack"], resp["tag"], GCM_KEY)["key"], "gcm"


# ── драйвер ──────────────────────────────────────────────────────────
# Режими кондиціонера в протоколі Gree:
MODES = {"auto": 0, "cool": 1, "dry": 2, "fan": 3, "heat": 4}
MODES_BACK = {v: k for k, v in MODES.items()}


class GreeAC(Device):
    """Кондиціонер Gree/C&H: повне керування локально по WiFi.

    state: on, temp(16-30), mode(auto/cool/dry/fan/heat),
           fan(0=авто,1..5), swing(bool), light(bool), turbo(bool)
    """

    kind = "ac"

    def __init__(self, id: str, name: str, ip: str, mac: str, key: str,
                 mode: str = "gcm", icon: str = "❄️", room: str = "Дім"):
        super().__init__(id, name, icon, room)
        self.ip = ip
        self.mac = mac
        self.key = key.encode()
        self.enc_mode = mode
        # swing / swing_h — позиція жалюзі: 0=як є, 1=гойдання, 2..6=фіксовані
        # (вертикальні: 2=вгорі ... 6=внизу; горизонтальні: 2=вліво ... 6=вправо)
        self.state.update({"temp": 24, "mode": "cool", "fan": 0,
                           "swing": 0, "swing_h": 0, "light": True,
                           "turbo": False, "quiet": False, "eco": False,
                           "sleep": False, "xfan": False, "health": False,
                           "room_temp": None})

    # -- низькорівневе: надіслати пакет пристрою --
    def _packet(self, inner: dict) -> dict:
        if self.enc_mode == "gcm":
            pack, tag = _enc_gcm(inner, self.key)
            msg = {"cid": "app", "i": 0, "pack": pack, "tag": tag,
                   "t": "pack", "tcid": self.mac, "uid": 0}
        else:
            pack = _enc_ecb(inner, self.key)
            msg = {"cid": "app", "i": 0, "pack": pack,
                   "t": "pack", "tcid": self.mac, "uid": 0}
        resp = _udp(self.ip, msg)
        if self.enc_mode == "gcm":
            return _dec_gcm(resp["pack"], resp["tag"], self.key)
        return _dec_ecb(resp["pack"], self.key)

    def _cmd_sync(self, opts: list[str], values: list[int]) -> None:
        self._packet({"opt": opts, "p": values, "t": "cmd"})

    def _status_sync(self) -> dict:
        cols = ["Pow", "Mod", "SetTem", "WdSpd", "SwUpDn", "SwingLfRig",
                "Lig", "Tur", "Quiet", "SvSt", "SwhSlp", "Blo", "Health",
                "TemSen"]
        resp = self._packet({"cols": cols, "mac": self.mac, "t": "status"})
        return dict(zip(resp["cols"], resp["dat"]))

    # -- інтерфейс Device --
    async def apply(self) -> None:
        s = self.state
        opts = ["Pow", "Mod", "SetTem", "TemUn", "WdSpd",
                "SwUpDn", "SwingLfRig", "Lig", "Tur",
                "Quiet", "SvSt", "SwhSlp", "SlpMod", "Blo", "Health"]
        vals = [
            1 if s["on"] else 0,
            MODES.get(s.get("mode", "cool"), 1),
            int(s.get("temp", 24)),
            0,                                    # °C
            int(s.get("fan", 0)),                 # 0=авто, 1..5
            int(s.get("swing", 0)),               # жалюзі вгору-вниз (0..6)
            int(s.get("swing_h", 0)),             # жалюзі вліво-вправо (0..6)
            1 if s.get("light", True) else 0,     # підсвітка дисплея
            1 if s.get("turbo") else 0,
            1 if s.get("quiet") else 0,           # тихий режим
            1 if s.get("eco") else 0,             # енергозбереження
            1 if s.get("sleep") else 0,           # нічний режим
            1 if s.get("sleep") else 0,           # (дублюємо для нових прошивок)
            1 if s.get("xfan") else 0,            # X-Fan: просушка після вимкнення
            1 if s.get("health") else 0,          # іонізатор
        ]
        import asyncio
        await asyncio.to_thread(self._cmd_sync, opts, vals)
        print(f"[GREE] {self.name} -> {s}")

    async def refresh(self) -> None:
        """Прочитати РЕАЛЬНИЙ стан кондиціонера (двосторонній зв'язок)."""
        import asyncio
        try:
            d = await asyncio.to_thread(self._status_sync)
        except Exception:
            return  # не дістукались — лишаємо попередній стан
        self.state["on"] = bool(d.get("Pow", 0))
        self.state["mode"] = MODES_BACK.get(d.get("Mod", 1), "cool")
        self.state["temp"] = d.get("SetTem", 24)
        self.state["fan"] = d.get("WdSpd", 0)
        self.state["swing"] = d.get("SwUpDn", 0)
        self.state["swing_h"] = d.get("SwingLfRig", 0)
        self.state["light"] = bool(d.get("Lig", 1))
        self.state["turbo"] = bool(d.get("Tur", 0))
        self.state["quiet"] = bool(d.get("Quiet", 0))
        self.state["eco"] = bool(d.get("SvSt", 0))
        self.state["sleep"] = bool(d.get("SwhSlp", 0))
        self.state["xfan"] = bool(d.get("Blo", 0))
        self.state["health"] = bool(d.get("Health", 0))
        # Температура В КІМНАТІ з датчика кондиціонера
        # (у протоколі зі зсувом +40: 65 означає 25°C)
        t = d.get("TemSen")
        if t is not None and t > 0:
            self.state["room_temp"] = t - 40 if t > 40 else t
