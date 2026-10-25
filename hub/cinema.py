# -*- coding: utf-8 -*-
"""
🎬 Голосовий кінотеатр: керує браузером (Playwright), відкриває uakino.best,
шукає фільм/серіал, вмикає потрібну серію й робить повний екран.

- uBlock Origin Lite (MV3) як РОЗШИРЕННЯ -> реклама блокується (спершу: python setup_adblock.py)
- автозакриття рекламних попап-вкладок
- профіль постійний (browser-profile/) -> Cloudflare/налаштування зберігаються

Використання з voice.py:  from cinema import play_media
CLI-тест (uakino):        python cinema.py            (спитає назву й серію)
CLI-тест (MEGOGO):        python cinema.py megogo     (спитає назву, сезон, серію)
Вхід у MEGOGO (1 раз):    python cinema.py login
"""
import json
import os
import re
import sys
import time

SITE = "https://uakino.best/"
MEGOGO = "https://megogo.net/ua"
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "browser-profile")
ADBLOCK = os.path.join(HERE, "adblock")  # uBlock Origin Lite (див. setup_adblock.py)
HISTORY = os.path.join(HERE, "watch_history.json")  # щоденник: що і докуди дивилися


def _adblock_dir():
    """Тека розпакованого адблок-розширення (де є manifest.json) або None."""
    if os.path.exists(os.path.join(ADBLOCK, "manifest.json")):
        return ADBLOCK
    if os.path.isdir(ADBLOCK):
        for d, _, files in os.walk(ADBLOCK):
            if "manifest.json" in files:
                return d
    return None

# Блокуємо рекламу/трекери/попапи на рівні мережі (замість розширення —
# свіжий Chromium уже не тягне старі MV2-адблокери). Хости-порушники:
_AD_HOSTS = re.compile(
    r"(doubleclick|googlesyndication|google-analytics|googletagmanager|adservice|"
    r"popads|popcash|popundertotal|propellerads|propellerads|pushvamp|onclick|"
    r"exoclick|juicyads|adnxs|mgid|hilltopads|adsterra|clickadu|trafficjunky|"
    r"adskeeper|yandex\.ru/ads|mc\.yandex|criteo|taboola|outbrain|adriver|"
    r"pushnest|richads|admaven|bidvertiser|adcash|monetag|hthntb|schulist\.link/ads)",
    re.I)

_pw = None
_ctx = None
_AD_DOMAINS = None   # велика база рекламних доменів (adhosts_domains.txt)


def _load_ad_domains():
    global _AD_DOMAINS
    if _AD_DOMAINS is not None:
        return _AD_DOMAINS
    _AD_DOMAINS = set()
    path = os.path.join(HERE, "adhosts_domains.txt")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                d = line.strip().lower()
                if d:
                    _AD_DOMAINS.add(d)
    except OSError:
        pass
    return _AD_DOMAINS


def _host_blocked(url: str) -> bool:
    """Хост або будь-який його батьківський домен є в рекламній базі?"""
    try:
        host = re.sub(r"^\w+://", "", url).split("/")[0].split(":")[0].lower()
    except Exception:
        return False
    ads = _load_ad_domains()
    parts = host.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in ads:
            return True
    return False


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zа-яіїєґ ]", " ", (s or "").lower()).strip()


# ─────────────────── Пам'ять переглядів (що і докуди дивилися) ──────────────
# Простий JSON-«щоденник»: для кожного фільму/серіалу — остання серія і таймкод.
# Пишемо, коли ставиш на паузу або закриваєш перегляд; читаємо для «продовжити».
# Так Адольф «пам'ятає», де ти зупинився, і бачить, що ти вже дивився.
_current = None   # що грає ЗАРАЗ: {service,query,url,title,season,episode}


def _load_history() -> dict:
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": {}, "last": None}


def _save_history(h: dict) -> None:
    try:
        with open(HISTORY, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _hist_key(meta: dict) -> str:
    """Стабільний ключ запису: сервіс + id зі сторінки (або назва)."""
    url = meta.get("url") or ""
    m = re.search(r"/view/(\d+)", url) or re.search(r"/(\d+)-[^/]+\.html", url)
    ident = m.group(1) if m else _norm(meta.get("query") or meta.get("title") or "?")
    return f"{meta.get('service', '?')}:{ident}"


# JS для пошуку ГОЛОВНОГО відео: беремо НАЙДОВШЕ (справжня серія ~53хв), а не
# фоновий трейлер на сторінці серіалу (~60с) чи рекламу. Так пауза/таймкод/
# перемотка завжди про справжнє відео, а не про заставку.
_FINDV = ("const vs=[...document.querySelectorAll('video')];"
          "let v=null,_bd=-1;"
          "for(const x of vs){const d=x.duration||0; if(x.currentSrc&&d>_bd){_bd=d;v=x;}}"
          "if(!v)v=vs.find(x=>x.currentSrc)||vs[0];")


def _video_state(page):
    """(таймкод, тривалість) головного відео — шукаємо і в iframe-плеєрах."""
    if page is None:
        return (None, None)
    js = "()=>{" + _FINDV + "if(!v)return null;return [v.currentTime||0, v.duration||0];}"
    for fr in page.frames:
        try:
            r = fr.evaluate(js)
            if r and r[0] is not None:
                return (r[0], r[1])
        except Exception:
            pass
    return (None, None)


def _seek_video(page, t) -> bool:
    """Перемотати головне відео на t секунд (чекаємо, поки завантажиться буфер)."""
    js = ("(t)=>{" + _FINDV +
          "if(v&&v.readyState>0&&(v.duration||0)>t+2){v.currentTime=t;"
          "if(v.play)v.play();return true;} return false;}")
    for _ in range(12):
        for fr in page.frames:
            try:
                if fr.evaluate(js, t):
                    return True
            except Exception:
                pass
        time.sleep(1)
    return False


def _uakino_page():
    """Пасивно (БЕЗ запуску браузера) знайти відкриту вкладку uakino."""
    if _ctx is None:
        return None
    for pg in _ctx.pages:
        if "uakino" in (pg.url or ""):
            return pg
    return None


def _set_current(service, query, url=None, title=None, season=None, episode=None):
    """Запам'ятати, що грає, і зафіксувати в щоденнику (навіть без таймкоду)."""
    global _current
    _current = {"service": service, "query": query, "url": url,
                "title": title or query, "season": season, "episode": episode}
    h = _load_history()
    key = _hist_key(_current)
    e = h["items"].get(key, {})
    e.update(_current)
    e.setdefault("time", 0)
    e["updated"] = time.time()
    h["items"][key] = e
    h["last"] = key
    _save_history(h)


def _megogo_current_episode(page):
    """РЕАЛЬНІ (сезон, серія) з URL відкритої сторінки — ground truth, а не
    припущення з команд. MEGOGO кодує їх у посиланні: ...sezon-1-seriya-2.html"""
    if page is None:
        return (None, None)
    try:
        u = page.url or ""
    except Exception:
        return (None, None)
    s = re.search(r"sezon-(\d+)", u, re.I)
    e = re.search(r"seriya-(\d+)", u, re.I)
    return (int(s.group(1)) if s else None, int(e.group(1)) if e else None)


def _sync_current_from_page(page) -> None:
    """Підтягнути в пам'ять РЕАЛЬНУ серію з URL, щоб памʼять не залежала від того,
    спрацювала команда чи ні (ти сказав «наступна», а вона могла не перемкнутись)."""
    if not _current or page is None:
        return
    s, e = _megogo_current_episode(page)
    if e is not None:
        _current["episode"] = e
        if s is not None:
            _current["season"] = s


def _record_progress(page=None, verbose=True) -> None:
    """Зберегти серію + таймкод, де зупинилися (на паузі/закритті/періодично)."""
    if not _current:
        return
    if page is None:
        page = _megogo_page() or _uakino_page()
    _sync_current_from_page(page)     # памʼять = реальна серія зі сторінки
    t, dur = _video_state(page)
    h = _load_history()
    key = _hist_key(_current)
    e = h["items"].get(key, {})
    e.update(_current)
    if t is not None and t > 5:      # не перетираємо валідний час нулем
        e["time"] = round(t, 1)
    if dur:
        e["duration"] = round(dur)
    e["updated"] = time.time()
    h["items"][key] = e
    h["last"] = key
    _save_history(h)
    if verbose:
        where = f" на {int((e.get('time') or 0)//60)} хв" if e.get("time") else ""
        print(f"💾 запам'ятав: {e.get('title', '?')}{where}")


_last_save = 0.0


def tick_progress() -> bool:
    """Тихо зберегти позицію раз на ~20с ПОКИ щось грає — щоб і через місяць
    пам'ятати, де зупинився, навіть якщо ти не ставив на паузу, а просто вимкнув
    комп'ютер. Викликає агент на ПК щоцикл (безпечно: той самий потік браузера).
    Повертає True, якщо цього разу зберіг (тоді агент синхронізує на хаб)."""
    global _last_save
    if not _current:
        return False
    now = time.time()
    if now - _last_save < 20:
        return False
    try:
        page = _megogo_page() or _uakino_page()
        if not page:
            return False
        t, _ = _video_state(page)
        if t and t > 5:
            _last_save = now
            _record_progress(page, verbose=False)
            return True
    except Exception:
        pass
    return False


def get_history(limit: int = 12) -> list:
    """Останні перегляди (найновіші перші) — для показу/синхронізації з хабом."""
    items = list(_load_history().get("items", {}).values())
    items.sort(key=lambda x: x.get("updated", 0), reverse=True)
    return items[:limit]


def _mark_clean_exit():
    """Позначити профіль як «закритий штатно», щоб Chrome не показував попап
    «Відновити сторінки? Chrome було неправильно закрито»."""
    import json
    prefs = os.path.join(PROFILE, "Default", "Preferences")
    try:
        with open(prefs, encoding="utf-8") as f:
            data = json.load(f)
        prof = data.setdefault("profile", {})
        prof["exit_type"] = "Normal"
        prof["exited_cleanly"] = True
        with open(prefs, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass  # немає файлу / перший запуск — не критично


def _ensure_browser():
    """Запустити (один раз) Chromium з uBlock і автозакриттям попапів."""
    global _pw, _ctx
    if _ctx is not None:
        return _ctx
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _mark_clean_exit()   # прибрати попап «Відновити сторінки?»
    args = ["--disable-blink-features=AutomationControlled", "--start-maximized",
            "--test-type",                 # ховає банер про «--no-sandbox»/автоматизацію
            "--hide-crash-restore-bubble"]  # ховає «Відновити сторінки?»

    # 1) СПРАВЖНІЙ адблок: uBlock Origin Lite (MV3) як розширення -> реально
    #    ВИРІЗАЄ рекламу (включно з пре-рол у плеєрі), а не пропускає її.
    ext = _adblock_dir()
    if ext:
        args += [f"--disable-extensions-except={ext}", f"--load-extension={ext}"]
        print("🛡️  Адблок увімкнено:", ext)
    else:
        print("⚠️  Адблок не встановлено. Запусти: python setup_adblock.py")

    # Справжній Google Chrome — ПОТРІБЕН для MEGOGO (шифрує відео через DRM/
    # Widevine, якого нема в Chromium від Playwright). uakino теж чудово працює.
    # Запасний Chromium іде на ОКРЕМИЙ профіль (-cr), щоб конфлікт версій не
    # псував основний профіль Chrome.
    # ignore_default_args прибирає --disable-component-update: інакше Chrome НЕ
    # активує Widevine (DRM), і платні відео MEGOGO не грають (бачиш «обмеження»).
    launch = dict(headless=False, no_viewport=True, args=args,
                  ignore_default_args=["--disable-component-update"])
    try:
        _ctx = _pw.chromium.launch_persistent_context(
            PROFILE, channel="chrome", **launch)
        print("🌐 Браузер: Google Chrome (DRM для MEGOGO працює)")
    except Exception as e:
        print("⚠️ Chrome не стартував:", str(e).splitlines()[0][:70])
        print("   Пробую Chromium (окремий профіль; відео MEGOGO там може не грати)")
        _ctx = _pw.chromium.launch_persistent_context(PROFILE + "-cr", **launch)

    # 2) Запасний мережевий блок — ЛИШЕ якщо розширення нема (щоб йому не
    #    заважати). Перехоплює тільки рекламні URL за коротким regex.
    if not ext:
        def route(r):
            try:
                r.abort()
            except Exception:
                pass  # контекст міг закритись — ігноруємо
        _ctx.route(_AD_HOSTS, route)

    main = _ctx.pages[0] if _ctx.pages else _ctx.new_page()

    # 3) Автозакриття рекламних попап-вкладок (лишаємо потрібні сайти й сторінки
    #    входу — щоб не прибити випадково вкладку логіну MEGOGO/Google).
    keep = ("uakino", "megogo", "accounts.google", "facebook.com", "appleid")

    def on_page(pg):
        try:
            time.sleep(0.6)
            if pg is main:
                return
            u = pg.url or ""
            if not any(k in u for k in keep) and len(_ctx.pages) > 1:
                pg.close()
        except Exception:
            pass
    _ctx.on("page", on_page)
    time.sleep(1)
    return _ctx


def _page():
    ctx = _ensure_browser()
    for pg in ctx.pages:
        if "uakino" in (pg.url or ""):
            return pg
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _main_page():
    """Будь-яка робоча вкладка (для MEGOGO/логіну)."""
    ctx = _ensure_browser()
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _find_chrome():
    """Шлях до встановленого Google Chrome (не Chromium від Playwright)."""
    cands = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def login_megogo():
    """Вхід у MEGOGO у ЗВИЧАЙНОМУ Chrome (БЕЗ автоматизації) — інакше reCAPTCHA
    блокує вхід, бо бачить робота. Сесія лягає в той самий профіль, яким далі
    керує Адольф (Playwright) -> надалі вхід уже не потрібен."""
    import subprocess
    chrome = _find_chrome()
    if not chrome:
        print("❌ Не знайшов Google Chrome. Встанови його або онови _find_chrome().")
        return
    print("🚀 Відкриваю ЗВИЧАЙНИЙ Chrome на профілі Адольфа (тут reCAPTCHA пройде)…")
    try:
        subprocess.Popen([chrome, f"--user-data-dir={PROFILE}",
                          "--no-first-run", "--no-default-browser-check", MEGOGO])
    except Exception as e:
        print("Не вдалося запустити Chrome:", e)
        return
    print("\n" + "=" * 64)
    print("👉 У вікні Chrome, що відкрилось:")
    print("   1) «Вхід» → номер телефону → «Отримати код»")
    print("   2) введи код із SMS")
    print("   3) переконайся, що вгорі з'явився твій акаунт/аватар")
    print("   4) ЗАКРИЙ це вікно Chrome (щоб звільнити профіль для Адольфа)")
    print("=" * 64)
    input("\n⏎  Залогінився і ЗАКРИВ вікно Chrome? Натисни Enter ТУТ… ")
    print("✅ Сесію збережено у профілі. Наступного разу MEGOGO не проситиме вхід.")


def _search(page, query: str):
    """DLE-пошук (поле сховане, тож сабмітимо форму) -> список {href,title}."""
    if "uakino" not in (page.url or ""):
        page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
    page.evaluate("""(q)=>{
      let inp=document.querySelector("input[name='story']");
      let form=inp?inp.closest('form'):document.querySelector("form[method='post']");
      if(!form) return;
      const put=(n,v)=>{let e=form.querySelector(`[name='${n}']`);
        if(!e){e=document.createElement('input');e.type='hidden';e.name=n;form.appendChild(e);} e.value=v;};
      put('do','search'); put('subaction','search'); put('story',q); form.submit();
    }""", query)
    # чекаємо, поки сторінка результатів устаканиться (можлива повторна навігація)
    try:
        page.wait_for_load_state("load", timeout=25000)
    except Exception:
        pass
    try:
        page.wait_for_selector("#dle-content", timeout=15000)
    except Exception:
        pass
    time.sleep(2)
    # збір із ретраєм — сторінка могла ще раз навігуватись під час зчитування
    items = []
    for _ in range(3):
        try:
            items = page.eval_on_selector_all(
                "a[href$='.html']",
                """els => els.map(a => ({href:a.href, title:(a.textContent||'').replace(/\\s+/g,' ').trim()}))
                     .filter(x => /\\/\\d+-[^/]+\\.html$/.test(x.href) && x.title.length>1)""")
            break
        except Exception:
            time.sleep(2)
    seen, uniq = set(), []
    for it in items:
        if it["href"] not in seen:
            seen.add(it["href"]); uniq.append(it)
    return uniq


def _best_match(items, query: str):
    """Обрати результат, чий заголовок найкраще збігається із запитом."""
    qw = set(_norm(query).split())
    best, score = None, -1
    for it in items:
        tw = set(_norm(it["title"]).split())
        s = len(qw & tw)
        # бонус, якщо весь запит є підрядком назви
        if _norm(query) in _norm(it["title"]):
            s += 5
        if s > score:
            best, score = it, s
    return best if score > 0 else (items[0] if items else None)


def _pick_episode(page, episode):
    """Якщо це серіал і задано номер серії — клікнути її у .playlists-ajax."""
    if not episode:
        return
    try:
        page.wait_for_selector(".playlists-ajax, .playlists-items", timeout=8000)
    except Exception:
        return
    # елементи серій зазвичай мають номер у тексті або data-file
    clicked = page.evaluate("""(ep)=>{
      const wrap=document.querySelector('.playlists-ajax, .playlists-items');
      if(!wrap) return false;
      const items=[...wrap.querySelectorAll('li,div,a')].filter(e=>/\\d/.test(e.textContent));
      // шукаємо елемент, чий текст = номеру серії
      let t=items.find(e=>e.textContent.trim()===String(ep))
           || items.find(e=>new RegExp('(^|\\\\D)'+ep+'(\\\\D|$)').test(e.textContent.trim()));
      if(t){ t.click(); return true; }
      return false;
    }""", int(episode))
    time.sleep(3)
    return clicked


def _skip_ads(page, total_s=60):
    """Пре-рол реклама вшита в плеєр (не блокується доменами) — тиснемо
    «Пропустити», щойно вона стає доступною. Полимо всі фрейми плеєра."""
    js = r"""()=>{
      const els=[...document.querySelectorAll('button,div,span,a')];
      const b=els.find(e=>{
        const t=(e.textContent||'').trim().toLowerCase();
        const ok=(/^пропуст/.test(t)||/skip\s*ad/.test(t)||t==='skip'||t==='пропустити');
        return ok && e.offsetParent!==null;
      });
      if(b){ b.click(); return (b.textContent||'').trim(); }
      return '';
    }"""
    end = time.time() + total_s
    last = 0
    while time.time() < end:
        hit = ""
        for fr in list(page.frames):
            try:
                r = fr.evaluate(js)
                if r:
                    hit = r
            except Exception:
                pass
        # якщо кнопка ще рахує ("Пропустити через 13") — чекаємо; коли зникне
        # лічильник, наступний клік реально пропустить. Виходимо, коли 2 рекламу
        # пропущено або довго нема кнопки.
        if hit and "через" not in hit.lower():
            last += 1
            time.sleep(2)
            if last >= 2:
                break
        else:
            time.sleep(2)


def _play_and_fullscreen(page):
    """Запустити відео у зовнішньому iframe-плеєрі та зробити повний екран."""
    time.sleep(3)
    # 0) прокрутити до зони плеєра через JS (надійніше за scroll_into_view)
    try:
        page.evaluate("""()=>{const p=document.querySelector('#pesok,.video-box,#dle-content iframe,iframe');
                             if(p) p.scrollIntoView({block:'center'});}""")
    except Exception:
        pass
    time.sleep(1)
    # 1) інколи над плеєром є постер-заглушка з кнопкою play — клікнемо її
    try:
        page.evaluate("""()=>{const b=document.querySelector('.play,.playbtn,.player-poster,.poster');
                             if(b) b.click();}""")
    except Exception:
        pass
    time.sleep(1)
    # 2) клік по центру видимого iframe -> старт відео
    clicked_box = None
    try:
        el = page.query_selector("#pesok iframe, .video-box iframe, #dle-content iframe, iframe")
        if el:
            bb = el.bounding_box()
            if bb and bb["width"] > 80 and bb["height"] > 60:
                clicked_box = bb
                page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                time.sleep(2)
    except Exception as e:
        print("play click:", e)
    # 2.5) пре-рол реклама в плеєрі ("BETON" тощо) — тиснемо «Пропустити»
    _skip_ads(page)
    # 3) повний екран: спершу кнопка всередині плеєра (крос-домен iframe)
    fs_done = False
    for fr in page.frames:
        u = fr.url or ""
        if u.startswith("http") and "uakino" not in u:
            for sel in [".vjs-fullscreen-control", ".jw-icon-fullscreen",
                        "[aria-label*='ull']", "[title*='ull']",
                        ".fullscreen", ".fullscreen-btn", ".pjsdiv[title*='кран']"]:
                try:
                    b = fr.query_selector(sel)
                    if b:
                        b.click(timeout=2000)
                        fs_done = True
                        break
                except Exception:
                    pass
        if fs_done:
            break
    # 4) якщо кнопки не знайшли — подвійний клік + 'f' (типово для HTML5-плеєрів)
    if not fs_done and clicked_box:
        try:
            page.mouse.dblclick(clicked_box["x"] + clicked_box["width"] / 2,
                                clicked_box["y"] + clicked_box["height"] / 2)
            time.sleep(0.5)
            page.keyboard.press("f")
        except Exception:
            pass


# ─────────────────────────── MEGOGO (легально, DRM) ────────────────────────
def _megogo_search(page, query: str):
    """Пошук на megogo.net -> список {href,title}. Форма веде на search-extended."""
    from urllib.parse import quote
    page.goto("https://megogo.net/ua/search-extended?q=" + quote(query),
              wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    time.sleep(3)
    items = []
    for _ in range(3):
        try:
            items = page.eval_on_selector_all("a[href*='/view/']", """els=>{
              const byId={};
              for(const a of els){
                const m=a.href.match(/\\/view\\/(\\d+)/); if(!m) continue;
                const id=m[1];
                let t=(a.textContent||a.getAttribute('title')||'').replace(/\\s+/g,' ').trim();
                if(/^(дивитися|дивитись|watch|play|грати)$/i.test(t)) t='';
                if(!byId[id]) byId[id]={href:a.href.split('?')[0], title:''};
                if(t.length>byId[id].title.length) byId[id].title=t;   // найдовша назва
              }
              return Object.values(byId).filter(x=>x.title.length>=2);
            }""")
            if items:
                break
        except Exception:
            time.sleep(2)
    return items


def _megogo_age_gate(page):
    """Попап «обмеження за віком. Вам є 18?» -> РЕАЛЬНИЙ клік миші по «Так»
    (JS .click() на React-кнопці не спрацьовує, треба справжній pointer-клік)."""
    try:
        btn = page.evaluate("""()=>{
          for(const e of document.querySelectorAll('button,a,div,span')){
            // лише власний текст елемента (не текст батьків-контейнерів)
            const own=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
            if((own==='Так'||/^так,?\\s*мені/i.test(own)) && e.offsetParent){
              const r=e.getBoundingClientRect();
              if(r.width>10) return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
            }
          }
          return null;
        }""")
        if btn:
            page.mouse.click(btn["x"], btn["y"])
            time.sleep(2)
            return True
        return False
    except Exception:
        return False


def _megogo_playing(page):
    """Чи грає СПРАВЖНЯ серія (не фоновий трейлер). Трейлер на сторінці серіалу
    короткий (~60с) — вимагаємо тривалість > 5 хв, щоб його не зарахувати."""
    try:
        return page.evaluate("()=>{" + _VID +
            "return !!(v && !v.paused && v.currentTime>0 && (v.duration||0)>300);}")
    except Exception:
        return False


def _megogo_click_watch(page) -> bool:
    """Натиснути головну кнопку запуску плеєра: «Дивитися», «Продовжити»,
    «Продовжити перегляд», «Play». Потрібно і для фільмів без серій, і для нової
    серії (там плеєр не стартує сам — треба натиснути «Продовжити»)."""
    try:
        coords = page.evaluate("""()=>{
          const cand=[];
          for(const e of document.querySelectorAll('a,button,div,span')){
            if(!e.offsetParent) continue;
            const own=[...e.childNodes].filter(n=>n.nodeType===3)
                        .map(n=>n.textContent).join('').trim().toLowerCase();
            if(/^(дивит|продовж|відновити|watch|play|грати|перегляд|розпочати)/.test(own)
               && own.length<30){
              const r=e.getBoundingClientRect();
              if(r.width>20&&r.height>10)
                cand.push({top:r.top, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
            }
          }
          if(!cand.length) return null;
          cand.sort((a,b)=>a.top-b.top);      // найвища на сторінці = головна
          return {x:cand[0].x, y:cand[0].y};
        }""")
        if coords:
            page.mouse.click(coords["x"], coords["y"])
            time.sleep(4)
            return True
    except Exception as e:
        print("megogo watch:", e)
    return False


def _megogo_play_fullscreen(page, seek=None):
    """Підтвердити вік, запустити вбудований плеєр megogo й зробити повний екран.
    seek — перемотати на цю секунду (для «продовжити з місця»)."""
    time.sleep(5)                       # дати плеєру й вік-попапу відрендеритись
    _megogo_age_gate(page)              # клік «Так»
    time.sleep(2)
    # Плеєр сам не стартує -> тиснемо «Дивитися»/«Продовжити», ПОКИ кнопка є
    # (не дивимось на «чи грає», бо на сторінці серіалу грає фоновий трейлер).
    for _ in range(3):
        if not _megogo_click_watch(page):
            break                       # кнопки більше нема -> плеєр завантажується
        time.sleep(3)
        _megogo_age_gate(page)
    # Дати СПРАВЖНІЙ серії розігратись (чекаємо довге відео, що реально грає)
    for _ in range(8):
        if _megogo_playing(page):
            break
        time.sleep(1.5)
    # Крайній засіб: якщо й досі не грає — клік по центру найбільшого відео
    if not _megogo_playing(page):
        try:
            c = page.evaluate("""()=>{const v=[...document.querySelectorAll('video')]
                .sort((a,b)=>(b.duration||0)-(a.duration||0))[0];
                if(!v) return null; const r=v.getBoundingClientRect();
                return (r.width>200)?{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}:null;}""")
            if c:
                page.mouse.click(c["x"], c["y"])
                time.sleep(3)
                _megogo_age_gate(page)
        except Exception as e:
            print("megogo center click:", e)
    if seek and seek > 5:               # продовжити з місця, де зупинилися
        _seek_video(page, seek)
    box = None
    try:
        el = page.query_selector("video")
        if el:
            box = el.bounding_box()
    except Exception:
        pass
    _megogo_fullscreen(page, box)


def _megogo_fullscreen(page, box=None):
    """Повний екран ЯК РУКАМИ: клавіша «f» (хоткей плеєра megogo розгортає
    відео) + F11-еквівалент (робимо ВІКНО браузера повноекранним через CDP —
    надійніше за клавішу F11, яку автоматизований браузер часто ігнорує)."""
    # 1) навести мишу на плеєр (фокус) і натиснути 'f' — плеєр на весь кадр
    try:
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(0.3)
        page.keyboard.press("f")
        time.sleep(1)
    except Exception:
        pass
    # 2) F11-еквівалент: справжній повний екран вікна (ховає панель браузера)
    try:
        ctx = _ensure_browser()
        cdp = ctx.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {
            "windowId": win["windowId"],
            "bounds": {"windowState": "fullscreen"}})
    except Exception as e:
        print("CDP fullscreen:", e)


def _megogo_pick_season_episode(page, season=None, episode=None):
    """Серіал: обрати сезон (вкладка a.season-link) і серію (a.video-episode).
    Клікаємо РЕАЛЬНОЮ мишею (React-елементи), з прокруткою до елемента."""
    if season:
        try:
            coords = page.evaluate("""(n)=>{
              const links=[...document.querySelectorAll('a.season-link')].filter(a=>a.offsetParent);
              const t=links.find(a=>{ const m=(a.textContent||'').match(/(\\d+)/); return m && +m[1]===n; });
              if(!t) return null;
              t.scrollIntoView({block:'center'});
              const r=t.getBoundingClientRect();
              return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
            }""", int(season))
            if coords:
                page.mouse.click(coords["x"], coords["y"])
                time.sleep(3)   # AJAX-довантаження серій сезону
        except Exception as e:
            print("megogo season:", e)
    if episode:
        try:
            coords = page.evaluate("""(n)=>{
              const eps=[...document.querySelectorAll('a.video-episode')].filter(e=>e.offsetParent);
              if(!eps.length) return null;
              // за номером у тексті/підказці, інакше за порядком
              let t=eps.find(e=>{ const s=(e.textContent||e.getAttribute('title')||e.getAttribute('aria-label')||'');
                                  const m=s.match(/(\\d+)/); return m && +m[1]===n; });
              if(!t) t=eps[n-1];
              if(!t) return null;
              t.scrollIntoView({block:'center', inline:'center'});
              const r=t.getBoundingClientRect();
              return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
            }""", int(episode))
            if coords:
                page.mouse.click(coords["x"], coords["y"])
                time.sleep(4)   # завантаження серії у плеєр (можлива навігація)
        except Exception as e:
            print("megogo episode:", e)


def megogo_play(query: str, episode=None, season=None, seek=None) -> dict:
    """MEGOGO: знайти й увімкнути. Для серіалів можна задати сезон і серію.
    seek — перемотати на цю секунду (для «продовжити з місця»)."""
    page = _main_page()
    items = _megogo_search(page, query)
    if not items:
        return {"ok": False, "say": f"Не знайшов «{query}» на MEGOGO"}
    pick = _best_match(items, query)
    page.goto(pick["href"], wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)
    _megogo_age_gate(page)                 # підтвердити вік ДО вибору серії
    if season or episode:
        _megogo_pick_season_episode(page, season, episode)
    _set_current("megogo", query, url=pick["href"], title=pick["title"],
                 season=season, episode=episode)
    _megogo_play_fullscreen(page, seek=seek)
    _sync_current_from_page(page)          # памʼять = реально відкрита серія
    tail = ""
    if season:
        tail += f", сезон {season}"
    if episode:
        tail += f", серія {episode}"
    return {"ok": True, "title": pick["title"], "url": pick["href"],
            "say": f"Вмикаю {pick['title'][:40]}{tail} на MEGOGO"}


# ── Керування вже запущеним плеєром MEGOGO (голосом) ────────────────
# Обираємо ГОЛОВНИЙ <video> (той, що реально грає, а не прихований/рекламний)
# і керуємо ним напряму — так надійно, без пошуку хитрих кнопок плеєра.
_VID = ("const vs=[...document.querySelectorAll('video')];"
        "let v=null,_bd=-1;"
        "for(const x of vs){const d=x.duration||0; if(x.currentSrc&&d>_bd){_bd=d;v=x;}}"
        "if(!v)v=vs.find(x=>x.currentSrc)||vs[0];")


def _megogo_page():
    """Поточна вкладка megogo (де грає відео) або None."""
    if _ctx is None:
        return None
    for pg in _ctx.pages:
        if "megogo" in (pg.url or ""):
            return pg
    return None


def _megogo_click_skip(page) -> bool:
    """Клікнути кнопку «Пропустити вступ/заставку». Пробуємо кілька секунд, бо
    кнопка може з'явитись не одразу. Шукаємо і на сторінці, і в iframe плеєра."""
    js = """()=>{
      for(const e of document.querySelectorAll('button,a,div,span')){
        const t=(e.textContent||'').trim().toLowerCase();
        if(/пропуст|скіп|^skip|далі до|intro/.test(t) && t.length<32 && e.offsetParent){
          const r=e.getBoundingClientRect();
          if(r.width>10 && r.height>6)
            return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
        }
      }
      return null;
    }"""
    for _ in range(4):                     # кнопка могла ще не з'явитись
        try:
            coords = page.evaluate(js)
            if coords:
                page.mouse.click(coords["x"], coords["y"])
                return True
        except Exception:
            pass
        time.sleep(0.7)
    return False


def _megogo_episode_links(page) -> dict:
    """Зібрати зі сторінки посилання на серії -> {(сезон, серія): url}.
    На MEGOGO кожна серія має ОКРЕМЕ посилання виду
    /ua/view/ID-...-sezon-1-seriya-2.html (сезон інколи відсутній)."""
    try:
        links = page.evaluate(r"""()=>{
          const out=[];
          for(const a of document.querySelectorAll('a[href*="/view/"]')){
            const h=a.href||'';
            const m=h.match(/seriya-(\d+)/i);
            if(!m) continue;
            const s=h.match(/sezon-(\d+)/i);
            out.push({season: s?+s[1]:null, episode:+m[1], url:h.split('?')[0]});
          }
          return out;
        }""")
    except Exception as e:
        print("ep links:", e)
        return {}
    uniq = {}
    for l in links:
        uniq[(l["season"], l["episode"])] = l["url"]
    return uniq


def _megogo_goto_episode(page, season, episode) -> bool:
    """Відкрити КОНКРЕТНУ серію ПРЯМИМ переходом за її URL — надійно, без кліків
    по крихких елементах. Якщо прямого посилання нема — запасний варіант: клік
    по списку серій (старий спосіб)."""
    try:
        season = int(season) if season not in (None, "") else None
        episode = int(episode)
    except (TypeError, ValueError):
        pass
    # 1) зібрати посилання на серії з поточної сторінки; якщо їх нема — з серіалу
    links = _megogo_episode_links(page)
    if not links and _current and _current.get("url"):
        page.goto(_current["series_url"], wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        _megogo_age_gate(page)
        links = _megogo_episode_links(page)
    # 2) знайти URL потрібної серії (з тим самим сезоном, або будь-яку з цим №)
    url = (links.get((season, episode)) or links.get((None, episode))
           or next((u for (s, e), u in links.items() if e == episode), None))
    if url:
        print(f"▶ серія {episode} -> {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        _megogo_age_gate(page)
        _megogo_play_fullscreen(page)
        return True
    # 3) запасний спосіб — клік по списку серій
    print(f"прямого посилання на серію {episode} нема ({sorted(links)}), пробую кліком")
    if not page.query_selector("a.video-episode") and _current and _current.get("url"):
        page.goto(_current["series_url"], wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        _megogo_age_gate(page)
    _megogo_pick_season_episode(page, season, episode)
    _megogo_play_fullscreen(page)
    return True


def resume_last() -> dict:
    """Продовжити ОСТАННІЙ перегляд із збереженого місця (серія + таймкод)."""
    h = _load_history()
    it = h.get("items", {}).get(h.get("last") or "")
    if not it:
        return {"ok": False, "say": "Ще нема що продовжувати"}
    t = it.get("time") or 0
    res = play_media(it.get("query", ""), episode=it.get("episode"),
                     source=it.get("service", "megogo"), season=it.get("season"),
                     seek=t)
    if res.get("ok"):
        mins = int(t // 60)
        where = f" з {mins}-ї хвилини" if mins else ""
        title = (it.get("title") or it.get("query") or "")[:40]
        res["say"] = f"Продовжую {title}{where}"
    return res


def close_player() -> dict:
    """«Закрий браузер / не хочу дивитись»: запам'ятати місце й ПОВНІСТЮ закрити
    браузер (вікно зникає). Наступного разу «продовж» відкриє з того ж місця."""
    global _ctx, _pw, _current
    page = _megogo_page() or _uakino_page()
    _record_progress(page)                    # зберегти позицію ДО закриття
    try:
        _mark_clean_exit()                    # без попапа «відновити сторінки?»
        if _ctx is not None:
            _ctx.close()                      # закрити вікно браузера
    except Exception as e:
        print("close ctx:", e)
    try:
        if _pw is not None:
            _pw.stop()                        # зупинити Playwright
    except Exception:
        pass
    _ctx = None
    _pw = None
    _current = None                           # нічого не грає -> автозбереження стоп
    return {"ok": True, "say": "Закрив браузер. Запам'ятав, де ти зупинився"}


def _fmt_min(sec: int) -> str:
    """'на 5 хвилин' / 'на 30 секунд' — для озвучки перемотки."""
    if sec % 60 == 0 and sec >= 60:
        return f"на {sec // 60} хв"
    if sec >= 60:
        return f"на {sec // 60} хв {sec % 60} с"
    return f"на {sec} с"


def megogo_control(action: str, seconds=None) -> dict:
    """Керування плеєром MEGOGO:
    pause/play/replay/skip_intro/next/prev/forward/back/resume/stop.
    seconds — на скільки перемотати (для forward/back), напр. 300 = 5 хв."""
    if action in ("resume", "continue"):
        return resume_last()               # продовжити з місця (сам відкриє)
    if action in ("stop", "close"):
        return close_player()              # запам'ятати й закрити
    page = _megogo_page()
    if page is None:
        return {"ok": False, "say": "Спершу увімкни щось на MEGOGO"}
    try:
        if action == "pause":
            paused = page.evaluate("()=>{" + _VID +
                "if(!v)return null;if(v.paused){v.play();return false;}v.pause();return true;}")
            if paused:
                _record_progress(page)     # на паузі — запам'ятати таймкод
            return {"ok": True, "say": "Пауза" if paused else "Продовжую"}
        if action == "play":
            page.evaluate("()=>{" + _VID + "if(v)v.play();}")
            return {"ok": True, "say": "Продовжую"}
        if action == "replay":
            page.evaluate("()=>{" + _VID + "if(v){v.currentTime=0;v.play();}}")
            return {"ok": True, "say": "Вмикаю спочатку"}
        if action == "skip_intro":
            if not _megogo_click_skip(page):
                page.evaluate("()=>{" + _VID + "if(v)v.currentTime+=85;}")  # немає кнопки -> +85с
            return {"ok": True, "say": "Пропускаю вступ"}
        if action == "forward":
            sec = int(seconds) if seconds else 30       # типово 30 с
            page.evaluate("(s)=>{" + _VID + "if(v)v.currentTime+=s;}", sec)
            return {"ok": True, "say": f"Перемотую вперед {_fmt_min(sec)}"}
        if action == "back":
            sec = int(seconds) if seconds else 15       # типово 15 с
            page.evaluate("(s)=>{" + _VID +
                          "if(v)v.currentTime=Math.max(0,v.currentTime-s);}", sec)
            return {"ok": True, "say": f"Перемотую назад {_fmt_min(sec)}"}
        if action in ("next", "prev"):
            if not _current:
                return {"ok": False, "say": "Спершу увімкни серіал"}
            # РЕАЛЬНА поточна серія з URL сторінки (а не з припущень команд!)
            _sync_current_from_page(page)
            rs, real_cur = _megogo_current_episode(page)
            cur = real_cur or (_current.get("episode") if isinstance(
                _current.get("episode"), int) else 1)
            season = rs if rs is not None else _current.get("season")
            if action == "prev" and cur <= 1:
                return {"ok": True, "say": "Це вже перша серія"}
            target = cur + 1 if action == "next" else cur - 1
            _megogo_goto_episode(page, season, target)
            # ПЕРЕВІРКА за реальним URL: серія справді перемкнулась?
            time.sleep(1)
            _s2, now_ep = _megogo_current_episode(page)
            word = "Наступна" if action == "next" else "Попередня"
            if now_ep == target:
                _set_current(**{**_current, "season": season, "episode": target})
                return {"ok": True, "say": f"{word} серія, {target}"}
            # НЕ перемкнулось -> памʼять НЕ псуємо (лишаємо реальну поточну)
            if now_ep is not None:
                _set_current(**{**_current, "episode": now_ep})
            return {"ok": False,
                    "say": f"Не вдалося перемкнути на {target}, лишаєшся на {cur}"}
    except Exception as e:
        print("megogo_control:", e)
        return {"ok": False, "say": "Не вдалося"}
    return {"ok": False, "say": "Невідома команда плеєра"}


def play_media(query: str, episode=None, source: str = "uakino", season=None,
               seek=None) -> dict:
    """Головна дія: знайти й увімкнути. source: 'uakino' або 'megogo'.
    seek — перемотати на цю секунду (для «продовжити з місця»)."""
    if source == "megogo":
        return megogo_play(query, episode, season, seek=seek)
    page = _page()
    items = _search(page, query)
    if not items:
        return {"ok": False, "say": f"Не знайшов «{query}» на сайті"}
    pick = _best_match(items, query)
    page.goto(pick["href"], wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    if episode:
        _pick_episode(page, episode)
    _set_current("uakino", query, url=pick["href"], title=pick["title"],
                 season=season, episode=episode)
    _play_and_fullscreen(page)
    if seek and seek > 5:
        _seek_video(page, seek)
    ep_txt = f", серія {episode}" if episode else ""
    return {"ok": True, "title": pick["title"], "url": pick["href"],
            "say": f"Вмикаю {pick['title'][:40]}{ep_txt}"}


def _ask(prompt, default=None):
    """Запит рядка в терміналі; порожньо -> default."""
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v or default


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("login", "login-megogo", "megogo-login"):
        login_megogo()
    elif cmd in ("continue", "resume", "далі"):
        print(resume_last())
        input("Enter — закрити браузер...")
    elif cmd in ("history", "історія"):
        for it in get_history():
            tm = int((it.get("time") or 0) // 60)
            print(f"  • {it.get('title')} "
                  f"{('с'+str(it['season'])) if it.get('season') else ''}"
                  f"{('е'+str(it['episode'])) if it.get('episode') else ''} "
                  f"— {tm} хв [{it.get('service')}]")
    elif cmd == "megogo":
        # Питаємо ОКРЕМО — жодного вгадування, де назва, а де сезон/серія
        q = _ask("Назва фільму/серіалу: ", "відьмак")
        se = _ask("Сезон (Enter — якщо фільм/без сезону): ")
        ep = _ask("Серія (Enter — якщо без серії): ")
        print(play_media(q, episode=ep, source="megogo", season=se))
        input("Enter — закрити браузер...")
    else:
        # uakino
        q = _ask("Назва (uakino): ", "відьмак")
        ep = _ask("Серія (Enter — пропустити): ")
        print(play_media(q, ep))
        input("Enter — закрити браузер...")
