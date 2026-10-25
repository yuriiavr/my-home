# -*- coding: utf-8 -*-
"""
🎬 Агент кінотеатру на ПК.

Опитує хаб (телефон) /api/movie/next. Коли з телефона надходить кіно-команда
(«постав фільм», «наступна серія» тощо) — вмикає її у Chrome на ЦЬОМУ ПК через
cinema.py. Так телефон-хаб = пульт, а фільми грають на великому екрані ПК.

Запуск на ПК (де є Chrome для кіно):  python movie_agent.py
"""
import json
import sys
import time
import urllib.request

# Спершу локальна адреса телефона (швидко), потім — постійний тунель (якщо
# телефон переїхав на інший IP). Тому резервувати IP не обов'язково.
HUBS = ["http://192.168.0.109:8000", "https://dim.tail5ca65d.ts.net"]
POLL = 3.0                          # опитувати кожні N секунд


def _next():
    for hub in HUBS:
        try:
            with urllib.request.urlopen(hub + "/api/movie/next", timeout=5) as r:
                return json.load(r)          # успіх (навіть {}) -> повертаємо
        except Exception:
            continue                          # цей хаб недоступний -> наступний
    return None


def _sync_history(cinema):
    """Надіслати історію переглядів на хаб, щоб Адольф «бачив», що ти дивився."""
    try:
        data = json.dumps({"items": cinema.get_history(12)}).encode()
    except Exception:
        return
    for hub in HUBS:
        try:
            req = urllib.request.Request(hub + "/api/watch", data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).close()
            return
        except Exception:
            continue


def _pc_command(cmd):
    """Керування самим ПК з телефона. shutdown — вимкнути комп'ютер (із запасом
    15 с, щоб можна було передумати), shutdown_cancel — скасувати вимкнення."""
    import subprocess
    try:
        if cmd == "shutdown_cancel":
            subprocess.Popen(["shutdown", "/a"])
            print("🚫 Скасовано вимкнення ПК")
        elif cmd == "sleep":
            print("😴 Присипляю комп'ютер (прокинеться від «увімкни комп'ютер»)")
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        else:
            print("💤 Вимикаю комп'ютер за 15 с (скажи «скасуй вимкнення» — відміню)")
            subprocess.Popen(["shutdown", "/s", "/t", "15"])
    except Exception as e:
        print(f"    ❌ pc {cmd}: {type(e).__name__}: {e}")


def main():
    import os
    # Під pythonw (фоновий запуск без консолі) stdout=None -> пишемо в лог-файл.
    if sys.stdout is None:
        logp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "movie_agent.log")
        sys.stdout = sys.stderr = open(logp, "a", encoding="utf-8", buffering=1)
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print(f"🎬 Агент кінотеатру. Опитую хаб {HUBS[0]} (з відкатом на тунель) кожні {POLL:.0f}с.")
    print("   Кажи голосом з телефона «постав фільм ...» — увімкнеться тут. Ctrl+C — вихід.\n")
    import cinema
    while True:
        cmd = _next()
        if cmd and cmd.get("action"):
            print(f"▶️  з телефона: {cmd}")
            try:
                if cmd["action"] == "movie":
                    res = cinema.play_media(
                        cmd.get("query", ""), episode=cmd.get("episode"),
                        source=cmd.get("service") or "megogo", season=cmd.get("season"))
                    print("   ", res.get("say"))
                elif cmd["action"] == "control":
                    res = cinema.megogo_control(cmd.get("cmd", ""), cmd.get("seconds"))
                    print("   ", res.get("say"))
                elif cmd["action"] == "pc":
                    _pc_command(cmd.get("cmd", "shutdown"))
                _sync_history(cinema)         # оновити «щоденник» на хабі
            except Exception as e:
                print(f"    ❌ {type(e).__name__}: {e}")
        else:
            # нема команди -> поки щось грає, тихо зберігаємо позицію (раз на ~20с),
            # щоб і через місяць пам'ятати, де зупинився
            try:
                if cinema.tick_progress():
                    _sync_history(cinema)
            except Exception:
                pass
        time.sleep(POLL)


if __name__ == "__main__":
    main()
