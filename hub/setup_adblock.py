# -*- coding: utf-8 -*-
"""
🛡️ Встановлює uBlock Origin Lite (MV3) — сучасний адблок, який РЕАЛЬНО блокує
рекламу у свіжому Chromium (старий uBlock MV2 падав із «непідтримувана версія
маніфесту»). Це та сама команда uBlock Origin, лише нова MV3-версія.

Запусти ОДИН раз:   python setup_adblock.py
Далі cinema.py сам підхопить розширення з теки hub/adblock/.
"""
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "adblock")
API = "https://api.github.com/repos/uBlockOrigin/uBOL-home/releases/latest"
UA = {"User-Agent": "Mozilla/5.0 cinema-adblock-setup"}


# Крім базових списків доввімкнемо регіональні (RU/UA — саме з них реклама на
# піратських кінотеатрах) + оверлеї. Ключі = id рулсетів у manifest.json.
EXTRA_LISTS = ["ukr-0", "rus-0", "rus-1",
               "annoyances-overlays", "annoyances-others"]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def _boost_lists(manifest_path: str):
    """Увімкнути додаткові фільтр-списки (регіональні + оверлеї) прямо в
    manifest.json — вони стануть активні одразу при першому запуску."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        rr = m.get("declarative_net_request", {}).get("rule_resources", [])
        added = []
        for r in rr:
            if r.get("id") in EXTRA_LISTS and not r.get("enabled"):
                r["enabled"] = True
                added.append(r["id"])
        if added:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
            print("➕ Доввімкнув списки:", ", ".join(added))
    except Exception as e:
        print("⚠️ Не вдалося доввімкнути списки:", e)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("🔎 Шукаю останній реліз uBlock Origin Lite (MV3)…")
    data = json.loads(_get(API))
    ver = data.get("tag_name", "?")

    # шукаємо zip для Chromium (назва інколи змінюється: .chromium.zip або
    # .chromium.mv3.zip), але НЕ edge/firefox/safari
    asset = None
    for a in data.get("assets", []):
        n = a.get("name", "")
        if "chromium" in n and n.endswith(".zip"):
            asset = a
            break
    if not asset:
        print("❌ Не знайшов chromium.mv3.zip. Доступні файли релізу:")
        for a in data.get("assets", []):
            print("   ", a.get("name"))
        sys.exit(1)

    print(f"⬇️  Качаю {asset['name']} ({ver})…")
    blob = _get(asset["browser_download_url"])

    if os.path.isdir(DEST):
        shutil.rmtree(DEST, ignore_errors=True)
    os.makedirs(DEST, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(DEST)

    # знайти теку, де лежить manifest.json (буває вкладена)
    root = DEST
    if not os.path.exists(os.path.join(root, "manifest.json")):
        for d, _, files in os.walk(DEST):
            if "manifest.json" in files:
                root = d
                break

    _boost_lists(os.path.join(root, "manifest.json"))
    print(f"✅ Готово! Адблок розпаковано: {root}")
    print("▶️  Тепер запускай кінотеатр:  python cinema.py \"відьмак\" 1")


if __name__ == "__main__":
    main()
