#!/usr/bin/env python3
"""
QS_astro_bot — Telegram-бот натальной астрологии на Swiss Ephemeris + GLM-4.7 (Z.AI).

Команды:
  /start — приветствие и лимиты
  /натал ДД.ММ.ГГГГ ЧЧ:ММ Город — натальная карта + интерпретация GLM
  /транзиты — транзиты к вашей сохранённой карте + интерпретация GLM
  /синастрия ДД.ММ.ГГГГ ЧЧ:ММ Город — совместимость с партнёром (требует сохранённую карту)

Лимиты: 3 общих прогноза на Telegram ID + 1 бесплатный в день (daily free).
Данные карт — в SQLite рядом со скриптом.
"""
import asyncio, json, os, re, sqlite3, sys
from datetime import datetime, timezone

import swisseph as swe
import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("ASTRO_TG_TOKEN", "")
ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
ZAI_MODEL = "glm-4.7"

EPHE_PATH = os.path.expanduser("~/.hermes/ephe")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astro_bot.db")
MAX_TOTAL = 3    # общих прогнозов на ID
MAX_DAILY = 1    # платных-на-лимите запросов в день (free daily)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
swe.set_ephe_path(EPHE_PATH)

SIGNS = ["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]
PLANETS = [(swe.SUN,"Солнце"),(swe.MOON,"Луна"),(swe.MERCURY,"Меркурий"),(swe.VENUS,"Венера"),
    (swe.MARS,"Марс"),(swe.JUPITER,"Юпитер"),(swe.SATURN,"Сатурн"),(swe.URANUS,"Уран"),
    (swe.NEPTUNE,"Нептун"),(swe.PLUTO,"Плутон"),(swe.TRUE_NODE,"Сев.Узел"),(swe.CHIRON,"Хирон")]
ASPECTS = [(0,"соединение",8),(60,"секстиль",5),(90,"квадрат",7),(120,"трин",7),(180,"оппозиция",8)]

# ---------- БД ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS users(
        tg_id INTEGER PRIMARY KEY, birth TEXT, lat REAL, lon REAL, total_used INTEGER DEFAULT 0,
        last_free_date TEXT)""")
    return con

def get_user(tg_id):
    con = db()
    r = con.execute("SELECT birth, lat, lon, total_used, last_free_date FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    con.close()
    return r

def save_chart(tg_id, birth, lat, lon):
    con = db()
    con.execute("""INSERT INTO users(tg_id,birth,lat,lon) VALUES(?,?,?,?)
        ON CONFLICT(tg_id) DO UPDATE SET birth=?, lat=?, lon=?""",
        (tg_id, birth, lat, lon, birth, lat, lon))
    con.commit(); con.close()

def consume_quota(tg_id):
    """True если запрос разрешён. Приоритет: daily free, потом общий лимит 3."""
    con = db()
    row = con.execute("SELECT total_used, last_free_date FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    if not row:
        con.close(); return False, "Сначала сохраните карту: /натал ДД.ММ.ГГГГ ЧЧ:ММ Город"
    total_used, last_free = row
    today = datetime.now().strftime("%Y-%m-%d")
    if last_free != today:
        con.execute("UPDATE users SET last_free_date=? WHERE tg_id=?", (today, tg_id))
        con.commit(); con.close()
        return True, "Использован дневной бесплатный прогноз (обновится завтра)"
    if total_used < MAX_TOTAL:
        con.execute("UPDATE users SET total_used=total_used+1 WHERE tg_id=?", (tg_id,))
        con.commit(); con.close()
        return True, f"Использован общий прогноз (осталось {MAX_TOTAL - total_used - 1} из {MAX_TOTAL})"
    con.close()
    return False, (f"Лимиты исчерпаны: {MAX_TOTAL} общих прогнозов использовано, "
                   f"дневной бесплатный уже получен. Ждите завтра ★")

# ---------- Астрономия ----------
def fmt(lon):
    s = int(lon // 30); d = lon % 30
    return f"{int(d):2d}°{int(d%1*60):02d}' {SIGNS[s]}"

def geocode_city(city):
    """Nominatim OSM."""
    import urllib.request, urllib.parse
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": city, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "qs-astro-bot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", city)

def calc_chart(birth_dt, lat, lon):
    jd = swe.julday(birth_dt.year, birth_dt.month, birth_dt.day,
                    birth_dt.hour + birth_dt.minute/60)
    cusps, ascmc = swe.houses(jd, lat, lon, b'P')
    planets = {}
    for pid, name in PLANETS:
        try:
            pos, _ = swe.calc_ut(jd, pid, swe.FLG_MOSEPH | swe.FLG_SPEED)
            planets[name] = (pos[0], pos[3] < 0)
        except Exception:
            pass
    return planets, ascmc[0], ascmc[1], cusps

def aspects_between(pos_a, pos_b, orbs=None):
    out = []
    for na,(la,_) in pos_a.items():
        for nb,(lb,_) in pos_b.items():
            d = abs(la-lb); d = 360-d if d > 180 else d
            for ang,nm,orb in (orbs or ASPECTS):
                if abs(d-ang) <= orb:
                    out.append((abs(d-ang), na, nm, nb)); break
    out.sort()
    return out

def chart_text(planets, asc, mc, cusps):
    lines = [f"АСЦ {fmt(asc)} | MC {fmt(mc)}"]
    for n,(l,r) in planets.items():
        lines.append(f"{n} {fmt(l)}{' R' if r else ''}")
    return "\n".join(lines)

# ---------- GLM ----------
async def glm(prompt: str) -> str:
    if not ZAI_API_KEY:
        return "(GLM недоступен — только расчётная часть)"
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(ZAI_URL, headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
            json={"model": ZAI_MODEL, "max_tokens": 1500, "temperature": 0.7, "messages": [
                {"role":"system","content":
                 "Ты астролог-консультант. Тебе дают точные астрономические данные натальной карты "
                 "(Swiss Ephemeris). Дай интерпретацию на русском: компактно, структурно, по классическим "
                 "трактовкам западной астрологии, без эзотерической воды и без предсказаний конкретных событий. "
                 "Объём до 400 слов."},
                {"role":"user","content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

# ---------- Хендлеры ----------
BIRTH_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})\s+(.+)$")

def parse_birth(arg):
    m = BIRTH_RE.match(arg.strip())
    if not m:
        return None
    d, mo, y, h, mi, city = m.groups()
    return datetime(int(y), int(mo), int(d), int(h), int(mi)), city

async def cmd_start(u: Update, ctx):
    await u.message.reply_text(
        "★ QS_astro — натальная астрология на Swiss Ephemeris\n\n"
        "Команды:\n"
        "/natal ДД.ММ.ГГГГ ЧЧ:ММ Город — построить карту (сохраняется)\n"
        "/transits — текущие транзиты к вашей карте\n"
        "/synastry ДД.ММ.ГГГГ ЧЧ:ММ Город — совместимость с партнёром\n\n"
        f"Лимиты: 1 бесплатный прогноз в день + {MAX_TOTAL} общих на аккаунт.\n"
        "⚠ Интерпретации — традиция астрологии, не научный прогноз.")

async def cmd_natal(u: Update, ctx):
    parsed = parse_birth(" ".join(ctx.args)) if ctx.args else None
    if not parsed:
        await u.message.reply_text("Формат: /natal ДД.ММ.ГГГГ ЧЧ:ММ Город\nПример: /natal 20.08.1987 14:15 Гуково")
        return
    birth, city = parsed
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    geo = await asyncio.to_thread(geocode_city, city)
    if not geo:
        await u.message.reply_text("Город не найден, уточните написание.")
        return
    lat, lon, display = geo
    save_chart(u.effective_user.id, birth.isoformat(), lat, lon)
    planets, asc, mc, cusps = await asyncio.to_thread(calc_chart, birth, lat, lon)
    txt = chart_text(planets, asc, mc, cusps)
    await u.message.reply_text(f"★ Карта сохранена: {display}\n\n{txt}")
    interp = await glm(f"Натальная карта (рождение {birth}, {display}):\n{txt}\nДай краткую интерпретацию личности.")
    await u.message.reply_text("🔮 " + interp[:4000])

async def cmd_transits(u: Update, ctx):
    row = get_user(u.effective_user.id)
    if not row:
        await u.message.reply_text("Сначала постройте карту: /natal ДД.ММ.ГГГГ ЧЧ:ММ Город")
        return
    ok, msg = consume_quota(u.effective_user.id)
    if not ok:
        await u.message.reply_text("⛔ " + msg); return
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    birth = datetime.fromisoformat(row[0]); lat, lon = row[1], row[2]
    natal, _, _, _ = await asyncio.to_thread(calc_chart, birth, lat, lon)
    natal_simple = {k: (v[0], v[1]) for k, v in natal.items()}
    now = datetime.now(timezone.utc)
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60)
    trans = {}
    for pid, name in PLANETS:
        try:
            pos, _ = swe.calc_ut(jd, pid, swe.FLG_MOSEPH | swe.FLG_SPEED)
            trans[name] = (pos[0], pos[3] < 0)
        except Exception:
            pass
    hits = await asyncio.to_thread(aspects_between, trans, natal_simple)
    t_lines = [f"{n} {fmt(l)}{' R' if r else ''}" for n,(l,r) in trans.items()]
    a_lines = [f"{na} {nm} {nb} (орб {o:.1f}°)" for o,na,nm,nb in hits[:12]]
    body = "Транзитные позиции:\n" + "\n".join(t_lines) + "\n\nТранзиты к наталу:\n" + "\n".join(a_lines)
    await u.message.reply_text("★ " + msg + "\n\n" + body)
    interp = await glm(f"Натал (рождение {birth}):\n{chart_text(natal,0,0,[])}\n\n{body}\n"
                       "Интерпретируйте текущие транзиты (фоны и быстрые), с оговоркой о рефлексивном характере.")
    await u.message.reply_text("🔮 " + interp[:4000])

async def cmd_synastry(u: Update, ctx):
    row = get_user(u.effective_user.id)
    if not row:
        await u.message.reply_text("Сначала постройте свою карту: /natal ДД.ММ.ГГГГ ЧЧ:ММ Город")
        return
    parsed = parse_birth(" ".join(ctx.args)) if ctx.args else None
    if not parsed:
        await u.message.reply_text("Формат: /синастрия ДД.ММ.ГГГГ ЧЧ:ММ Город (данные партнёра)")
        return
    ok, msg = consume_quota(u.effective_user.id)
    if not ok:
        await u.message.reply_text("⛔ " + msg); return
    birth, city = parsed
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    geo = await asyncio.to_thread(geocode_city, city)
    if not geo:
        await u.message.reply_text("Город партнёра не найден."); return
    lat, lon, display = geo
    mine, _, _, _ = await asyncio.to_thread(calc_chart, datetime.fromisoformat(row[0]), row[1], row[2])
    theirs, _, _, _ = await asyncio.to_thread(calc_chart, birth, lat, lon)
    hits = await asyncio.to_thread(aspects_between,
        {k: v for k, v in mine.items()}, {k: v for k, v in theirs.items()})
    a_lines = [f"{na} {nm} {nb} (орб {o:.1f}°)" for o,na,nm,nb in hits[:15]]
    body = f"Ваша карта:\n{chart_text(mine,0,0,[])}\n\nКарта партнёра ({display}):\n{chart_text(theirs,0,0,[])}\n\nМежкартные аспекты:\n" + "\n".join(a_lines)
    await u.message.reply_text("★ " + msg + "\n\n" + body[:4000])
    interp = await glm(f"Синастрия двух карт:\n{body}\nИнтерпретация совместимости: сильные стороны, зоны напряжения.")
    await u.message.reply_text("🔮 " + interp[:4000])

def main():
    if not TELEGRAM_TOKEN:
        print("ASTRO_TG_TOKEN не задан"); sys.exit(1)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler(["natal", "chart"], cmd_natal))
    app.add_handler(CommandHandler(["transits", "tr"], cmd_transits))
    app.add_handler(CommandHandler(["synastry", "syn"], cmd_synastry))
    print("QS_astro_bot запущен")
    while True:  # сеть может моргать — переподключаемся
        try:
            app.run_polling()
        except Exception as e:
            print(f"[restart] {e!r}; повтор через 5с")
            import time; time.sleep(5)

if __name__ == "__main__":
    main()
