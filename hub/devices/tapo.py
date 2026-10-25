"""
Драйвер розумної розетки TP-Link Tapo P110 (сумісно P100/P110/P115).

ВЛАСНА реалізація протоколу Tapo KLAP на ЧИСТОМУ Python + pycryptodome —
жодних сторонніх бібліотек (tapo/kasa/Rust). Тому працює всюди, де є
pycryptodome: і на ПК, і на телефоні (Termux).

Автентифікація — акаунт Tapo (email+пароль). У застосунку Tapo УВІМКНИ
для розетки «Сумісність зі сторонніми» (Third-Party Compatibility), інакше 403.
У home_secrets.py: TAPO_EMAIL, TAPO_PASSWORD, TAPO_IP.

Перевірка зв'язку:  (з теки hub)  python -m devices.tapo
"""
import hashlib
import json
import os
import urllib.error
import urllib.request

from Crypto.Cipher import AES

from .base import Device


def _s256(b): return hashlib.sha256(b).digest()
def _s1(b): return hashlib.sha1(b).digest()
def _pad(b): p = 16 - len(b) % 16; return b + bytes([p]) * p
def _unpad(b): return b[:-b[-1]]


class _Klap:
    """Одна KLAP-сесія з розеткою за IP (рукостискання + шифровані запити)."""

    def __init__(self, ip: str, email: str, password: str):
        self.ip = ip
        self.email = email
        self.password = password
        self.cookie = None
        self._ready = False

    def _post(self, path, data, seq=None):
        url = f"http://{self.ip}/app/{path}"
        if seq is not None:
            url += f"?seq={seq}"
        req = urllib.request.Request(url, data=data, method="POST")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.status, r.read(), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Set-Cookie")

    def connect(self):
        local = os.urandom(16)
        st, body, setc = self._post("handshake1", local)
        if st != 200 or len(body) < 48:
            raise RuntimeError(f"handshake1 -> {st} (увімкни Third-Party Compatibility?)")
        remote, server_hash = body[:16], body[16:48]
        self.cookie = setc.split(";")[0] if setc else None
        auth = None
        for ah in (_s256(_s1(self.email.encode()) + _s1(self.password.encode())),
                   _s256(_s256(self.email.encode()) + _s256(self.password.encode()))):
            if _s256(local + remote + ah) == server_hash:
                auth = ah
                break
        if auth is None:
            raise RuntimeError("невірний email/пароль Tapo")
        st2, _, _ = self._post("handshake2", _s256(remote + local + auth))
        if st2 != 200:
            raise RuntimeError(f"handshake2 -> {st2}")
        self.key = _s256(b"lsk" + local + remote + auth)[:16]
        ivseq = _s256(b"iv" + local + remote + auth)
        self.iv = ivseq[:12]
        self.seq = int.from_bytes(ivseq[12:16], "big", signed=True)
        self.sig = _s256(b"ldk" + local + remote + auth)[:28]
        self._ready = True

    def rpc(self, payload: dict) -> dict:
        if not self._ready:
            self.connect()
        self.seq += 1
        fiv = self.iv + self.seq.to_bytes(4, "big", signed=True)
        ct = AES.new(self.key, AES.MODE_CBC, fiv).encrypt(_pad(json.dumps(payload).encode()))
        signature = _s256(self.sig + self.seq.to_bytes(4, "big", signed=True) + ct)
        st, body, _ = self._post("request", signature + ct, seq=self.seq)
        if st != 200:
            self._ready = False
            raise RuntimeError(f"request -> {st}")
        return json.loads(_unpad(AES.new(self.key, AES.MODE_CBC, fiv).decrypt(body[32:])))


class TapoPlug(Device):
    """Розетка Tapo P110: вкл/викл + вимірювання потужності й енергії."""

    kind = "plug"

    def __init__(self, id: str, name: str, ip: str, email: str, password: str,
                 icon: str = "🔌", room: str = "Дім"):
        super().__init__(id, name, icon, room)
        self.ip = ip
        self.email = email
        self.password = password
        self._klap = None
        self.mac = None       # вчимо при 1-му опитуванні -> пошук за DHCP
        self.state.update({"power_w": 0, "today_kwh": 0.0, "month_kwh": 0.0})

    def _rpc(self, payload):
        if self._klap is None:
            self._klap = _Klap(self.ip, self.email, self.password)
        try:
            return self._klap.rpc(payload)
        except Exception:
            ip = self._find_ip()            # IP міг змінитись (DHCP) -> шукаємо
            if not ip:
                raise
            self.ip = ip
            self._klap = _Klap(ip, self.email, self.password)
            print(f"[TAPO] {self.name}: розетку знайдено на новому IP {ip}")
            return self._klap.rpc(payload)

    def _find_ip(self):
        """Хто в підмережі відповідає на KLAP handshake1 = розетка Tapo."""
        import concurrent.futures
        base = self.ip.rsplit(".", 1)[0]

        def probe(i):
            ip = f"{base}.{i}"
            try:
                req = urllib.request.Request(f"http://{ip}/app/handshake1",
                                             data=os.urandom(16), method="POST")
                with urllib.request.urlopen(req, timeout=1.5) as r:
                    return ip if len(r.read()) >= 48 else None
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as ex:
            futs = [ex.submit(probe, i) for i in range(2, 255)]
            for f in concurrent.futures.as_completed(futs):
                if f.result():
                    return f.result()
        return None

    async def apply(self) -> None:
        import asyncio
        try:
            await asyncio.to_thread(self._rpc, {
                "method": "set_device_info",
                "params": {"device_on": bool(self.state["on"])}})
            print(f"[TAPO] {self.name} -> {'УВІМК' if self.state['on'] else 'ВИМК'}")
        except Exception as e:
            print(f"[TAPO] apply {self.name}: {type(e).__name__}: {e}")

    async def refresh(self) -> None:
        import asyncio
        try:
            info = await asyncio.to_thread(self._rpc, {"method": "get_device_info"})
            r = info.get("result", {})
            self.state["on"] = bool(r.get("device_on"))
            if self.mac is None:
                self.mac = r.get("mac")
            en = await asyncio.to_thread(self._rpc, {"method": "get_energy_usage"})
            e = en.get("result", {})
            self.state["power_w"] = round((e.get("current_power") or 0) / 1000, 1)
            self.state["today_kwh"] = round((e.get("today_energy") or 0) / 1000, 3)
            self.state["month_kwh"] = round((e.get("month_energy") or 0) / 1000, 3)
        except Exception as e:
            print(f"[TAPO] refresh {self.name}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import home_secrets as hs
    plug = TapoPlug("plug_1", "Розетка", hs.TAPO_IP, hs.TAPO_EMAIL, hs.TAPO_PASSWORD)
    try:
        info = plug._rpc({"method": "get_device_info"}).get("result", {})
        en = plug._rpc({"method": "get_energy_usage"}).get("result", {})
        print(f"✅ {info.get('model')} на {plug.ip}: "
              f"{'увімк' if info.get('device_on') else 'вимк'}, "
              f"{(en.get('current_power') or 0)/1000:.1f} Вт, "
              f"сьогодні {(en.get('today_energy') or 0)/1000:.3f} кВт·год")
    except Exception as e:
        print("❌", type(e).__name__, e)
