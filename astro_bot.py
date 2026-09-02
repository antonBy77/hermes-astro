#!/usr/bin/env python3
"""
QS_astro_bot v2 — Telegram-бот натальной астрологии.
Расчёты: Swiss Ephemeris (pyswisseph). Интерпретации: LLM через Amvera-эндпоинт (QSmodels).

Спонсор: фонд quantumstocks (бета-версия).
Репозиторий: https://github.com/antonBy77/hermes-astro

Лимиты: 1 бесплатный прогноз/день + 3 общих на Telegram ID.
"""
import asyncio, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone

import swisseph as swe
import httpx
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          ConversationHandler, ContextTypes, filters)

# ---------- Конфиг ----------
TELEGRAM_TOKEN = os.environ.get("ASTRO_TG_TOKEN", "")
LLM_URL = os.environ.get("ASTRO_LLM_URL", "https://69rout-antonbustrov.waw0.amvera.tech/v1/chat/completions")
LLM_KEY = os.environ.get("ASTRO_LLM_KEY", "")
LLM_MODEL = os.environ.get("ASTRO_LLM_MODEL", "QSmodels")
MAX_TOKENS = 2000  # reasoning-модели: часть бюджета съедают reasoning_tokens

EPHE_PATH = os.path.expanduser("~/.hermes/ephe")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astro_bot.db")
MAX_TOTAL, MAX_DAILY = 3, 1
MAX_MSG = 4000

BETA_FOOTER_RU = "\n\n🎁 Бета-версия при поддержке фонда quantumstocks ★ github.com/antonBy77/hermes-astro"
BETA_FOOTER_EN = "\n\n🎁 Beta version sponsored by quantumstocks fund ★ github.com/antonBy77/hermes-astro"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
swe.set_ephe_path(EPHE_PATH)

SIGNS = ["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]
SIGNS_EN = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
PLANETS = [(swe.SUN,"Солнце","Sun"),(swe.MOON,"Луна","Moon"),(swe.MERCURY,"Меркурий","Mercury"),
    (swe.VENUS,"Венера","Venus"),(swe.MARS,"Марс","Mars"),(swe.JUPITER,"Юпитер","Jupiter"),
    (swe.SATURN,"Сатурн","Saturn"),(swe.URANUS,"Уран","Uranus"),(swe.NEPTUNE,"Нептун","Neptune"),
    (swe.PLUTO,"Плутон","Pluto"),(swe.TRUE_NODE,"Сев.Узел","N.Node"),(swe.CHIRON,"Хирон","Chiron")]
ASPECTS = [(0,"соединение","conjunction",8),(60,"секстиль","sextile",5),(90,"квадрат","square",7),
           (120,"трин","trine",7),(180,"оппозиция","opposition",8)]

# ---------- Состояние диалога ----------
(LANG, NAT_DATE, NAT_TIME, NAT_CITY, SYN_DATE, SYN_TIME, SYN_CITY) = range(7)

# ---------- i18n ----------
T = {
"ru": {
"welcome": "★ QS_astro — натальная астрология на Swiss Ephemeris\nСпонсор: фонд quantumstocks (бета)\n\nВыберите язык / Choose language:",
"choose_lang": "Язык:",
"help": ("★ <b>QS_astro</b> — астрология на Swiss Ephemeris (точность ~0.1\")\n"
         "🎁 Бета-версия при поддержке фонда quantumstocks\n\n"
         "<b>Команды:</b>\n"
         "/natal — построить карту (пошагово)\n"
         "/transits — транзиты к вашей карте\n"
         "/synastry — совместимость с партнёром\n"
         "/lang — сменить язык\n\n"
         f"Лимиты: 1 бесплатный прогноз в день + {MAX_TOTAL} на аккаунт.\n"
         "⚠ Интерпретации — традиция астрологии, не научный прогноз."),
"help_en": ("<b>QS_astro</b> — Swiss Ephemeris astrology (accuracy ~0.1\")\n"
         "🎁 Beta sponsored by quantumstocks fund\n\n"
         "<b>Commands:</b>\n/natal — build chart (step by step)\n/transits — current transits\n"
         "/synastry — partner compatibility\n/lang — change language\n\n"
         f"Limits: 1 free forecast/day + {MAX_TOTAL} total per account.\n"
         "⚠ Interpretations are astrological tradition, not scientific prediction."),
"enter_date": "📅 Введите дату рождения: ДД.ММ.ГГГГ (напр. 20.08.1987)",
"enter_time": "⏰ Введите местное время рождения: ЧЧ:ММ (напр. 14:15).\nЕсли время неизвестно — отправьте 12:00",
"enter_city": "🏙 Введите место рождения (город):",
"enter_date_en": "📅 Enter birth date: DD.MM.YYYY (e.g. 20.08.1987)",
"enter_time_en": "⏰ Enter local birth time: HH:MM (e.g. 14:15).\nUnknown? Send 12:00",
"enter_city_en": "🏙 Enter birthplace (city):",
"bad_date": "Не понял дату. Формат ДД.ММ.ГГГГ, например 20.08.1987",
"bad_time": "Не понял время. Формат ЧЧ:ММ, например 14:15",
"bad_date_en": "Invalid date. Use DD.MM.YYYY, e.g. 20.08.1987",
"bad_time_en": "Invalid time. Use HH:MM, e.g. 14:15",
"city_not_found": "Город не найден, уточните написание.", "city_not_found_en": "City not found, check spelling.",
"saved": "✅ Карта сохранена:", "saved_en": "✅ Chart saved:",
"need_chart": "Сначала постройте карту: /natal", "need_chart_en": "Build a chart first: /natal",
"quota_day": "Использован дневной бесплатный прогноз (обновится завтра)",
"quota_day_en": "Daily free forecast used (resets tomorrow)",
"quota_total": "Использован общий прогноз (осталось {n} из {m})",
"quota_total_en": "Total forecast used ({n} of {m} left)",
"quota_done": "⛔ Лимиты исчерпаны на сегодня: дневной бесплатный уже получен, общий лимит 3 исчерпан. Возвращайтесь завтра ★",
"quota_done_en": "⛔ Limits reached: daily free used, total limit of 3 exhausted. Come back tomorrow ★",
"transit_header": "🌌 Транзиты на {now}:", "transit_header_en": "🌌 Transits as of {now}:",
},
"en": {}
}
# EN fallback: используем ключи en, если есть, иначе ru
def tr(lang, key, **kw):
    d = T.get(lang) or {}
    s = d.get(key) or T["ru"].get(key, key)
    return s.format(**kw) if kw else s

# ---------- БД ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS users(
        tg_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru', birth TEXT, lat REAL, lon REAL,
        total_used INTEGER DEFAULT 0, last_free_date TEXT)""")
    return con

def get_user(tg_id):
    con = db()
    r = con.execute("SELECT lang,birth,lat,lon,total_used,last_free_date FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    con.close(); return r

def set_lang(tg_id, lang):
    con = db()
    con.execute("""INSERT INTO users(tg_id,lang) VALUES(?,?) ON CONFLICT(tg_id) DO UPDATE SET lang=?""",
                (tg_id, lang, lang))
    con.commit(); con.close()

def save_chart(tg_id, birth, lat, lon):
    con = db()
    con.execute("""INSERT INTO users(tg_id,birth,lat,lon) VALUES(?,?,?,?)
        ON CONFLICT(tg_id) DO UPDATE SET birth=?, lat=?, lon=?""",
        (tg_id, birth, lat, lon, birth, lat, lon))
    con.commit(); con.close()

def consume_quota(tg_id, lang):
    con = db()
    row = con.execute("SELECT total_used,last_free_date FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    if not row:
        con.close(); return False, tr(lang,"need_chart")
    total_used, last_free = row
    today = time.strftime("%Y-%m-%d")
    if last_free != today:
        con.execute("UPDATE users SET last_free_date=? WHERE tg_id=?", (today, tg_id))
        con.commit(); con.close()
        return True, tr(lang, "quota_day")
    if total_used < MAX_TOTAL:
        con.execute("UPDATE users SET total_used=total_used+1 WHERE tg_id=?", (tg_id,))
        con.commit(); con.close()
        return True, tr(lang, "quota_total", n=MAX_TOTAL-total_used-1, m=MAX_TOTAL)
    con.close()
    return False, tr(lang, "quota_done")

# ---------- Астрономия ----------
def fmt(lon, lang="ru"):
    signs = SIGNS if lang == "ru" else SIGNS_EN
    s = int(lon // 30); d = lon % 30
    return f"{int(d):2d}°{int(d%1*60):02d}' {signs[s]}"

def geocode_city(city):
    import urllib.request, urllib.parse
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": city, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "qs-astro-bot/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except Exception:
        return None
    if not data: return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", city)

def calc_chart(birth_dt, lat, lon):
    jd = swe.julday(birth_dt.year, birth_dt.month, birth_dt.day, birth_dt.hour + birth_dt.minute/60)
    cusps, ascmc = swe.houses(jd, lat, lon, b'P')
    planets = {}
    for pid, ru, en in PLANETS:
        try:
            pos, _ = swe.calc_ut(jd, pid, swe.FLG_MOSEPH | swe.FLG_SPEED)
            planets[ru if LANG_DEFAULT_RU else en] = (pos[0], pos[3] < 0)
        except Exception:
            pass
    return planets, ascmc[0], ascmc[1], cusps

LANG_DEFAULT_RU = True

def chart_text(planets, asc, mc, lang="ru"):
    lines = [f"AC {fmt(asc,lang)} | MC {fmt(mc,lang)}"]
    for n,(l,r) in planets.items():
        lines.append(f"{n} {fmt(l,lang)}{' R' if r else ''}")
    return "\n".join(lines)

def aspects_between(a, b):
    out = []
    for na,(la,_) in a.items():
        for nb,(lb,_) in b.items():
            d = abs(la-lb); d = 360-d if d > 180 else d
            for ang,ru,en,orb in ASPECTS:
                if abs(d-ang) <= orb:
                    out.append((abs(d-ang), na, ru if LANG_DEFAULT_RU else en, nb)); break
    out.sort(); return out

# ---------- LLM ----------
async def glm(prompt: str) -> str:
    if not LLM_KEY:
        return "(LLM unavailable)"
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(LLM_URL, headers={"Authorization": f"Bearer {LLM_KEY}"},
            json={"model": LLM_MODEL, "max_tokens": MAX_TOKENS, "temperature": 0.7, "stream": False,
                  "messages": [{"role":"system","content":
                    "You are an astrologer consultant. You receive precise Swiss Ephemeris chart data. "
                    "Answer in the SAME LANGUAGE as the user's data/request. Structured, classic western "
                    "astrology interpretation, no esoteric fluff, no concrete event predictions. Max 400 words."},
                    {"role":"user","content": prompt}]})
        r.raise_for_status()
        d = r.json()
        return d["choices"][0]["message"].get("content") or "(пустой ответ модели, попробуйте ещё раз)"

# ---------- Хелперы ----------
def lang_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇬🇧 English")]],
                               resize_keyboard=True, one_time_keyboard=True)

def footer(lang):
    return BETA_FOOTER_RU if lang == "ru" else BETA_FOOTER_EN

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

def valid_date(s):
    m = DATE_RE.match(s.strip())
    if not m: return None
    try: return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError: return None

def valid_time(s):
    m = TIME_RE.match(s.strip())
    if not m: return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if h < 24 and mi < 60 else None

# ---------- Хендлеры ----------
async def cmd_start(u: Update, ctx):
    await u.message.reply_text(tr("ru","welcome"), reply_markup=lang_keyboard())
    return LANG

async def cmd_lang(u: Update, ctx):
    await u.message.reply_text(tr("ru","choose_lang"), reply_markup=lang_keyboard())
    return LANG

async def on_lang(u: Update, ctx):
    lang = "ru" if "Русский" in u.message.text else "en" if "English" in u.message.text else None
    if lang is None:
        await u.message.reply_text(tr("ru","choose_lang"), reply_markup=lang_keyboard())
        return LANG
    set_lang(u.effective_user.id, lang)
    await u.message.reply_text(tr(lang, "help_en" if lang == "en" else "help"), parse_mode="HTML")
    return ConversationHandler.END

async def cmd_help(u: Update, ctx):
    row = get_user(u.effective_user.id)
    lang = row[0] if row else "ru"
    await u.message.reply_text(tr(lang, "help_en" if lang == "en" else "help"), parse_mode="HTML")

async def cmd_natal(u: Update, ctx):
    row = get_user(u.effective_user.id)
    lang = row[0] if row else "ru"
    await u.message.reply_text(tr(lang, "enter_date_en" if lang == "en" else "enter_date"))
    return NAT_DATE

async def on_nat_date(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    d = valid_date(u.message.text)
    if not d:
        await u.message.reply_text(tr(lang, "bad_date_en" if lang == "en" else "bad_date")); return NAT_DATE
    ctx.user_data["nat_date"] = d.strftime("%Y-%m-%d")
    await u.message.reply_text(tr(lang, "enter_time_en" if lang == "en" else "enter_time"))
    return NAT_TIME

async def on_nat_time(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    t = valid_time(u.message.text)
    if t is None:
        await u.message.reply_text(tr(lang, "bad_time_en" if lang == "en" else "bad_time")); return NAT_TIME
    ctx.user_data["nat_time"] = "%02d:%02d" % t
    await u.message.reply_text(tr(lang, "enter_city_en" if lang == "en" else "enter_city"))
    return NAT_CITY

async def on_nat_city(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    geo = await asyncio.to_thread(geocode_city, u.message.text.strip()[:100])
    if not geo:
        await u.message.reply_text(tr(lang, "city_not_found_en" if lang == "en" else "city_not_found"))
        return NAT_CITY
    lat, lon, display = geo
    birth = datetime.fromisoformat(f"{ctx.user_data['nat_date']}T{ctx.user_data['nat_time']}:00")
    save_chart(u.effective_user.id, birth.isoformat(), lat, lon)
    planets, asc, mc, _ = await asyncio.to_thread(calc_chart, birth, lat, lon)
    txt = chart_text(planets, asc, mc, lang)
    await u.message.reply_text(f"★ {tr(lang, 'saved_en' if lang=='en' else 'saved')} {display}\n\n{txt}{footer(lang)}")
    interp = await glm(f"Натальная карта (рождение {birth}, {display}):\n{txt}\n\n"
                       f"Language: {'Russian' if lang=='ru' else 'English'}. Дай интерпретацию личности.")
    await u.message.reply_text(("🔮 " + interp[:MAX_MSG]) + footer(lang))
    ctx.user_data.clear()
    return ConversationHandler.END

async def cmd_transits(u: Update, ctx):
    row = get_user(u.effective_user.id)
    lang = (row[0] if row else "ru") or "ru"
    if not row or not row[1]:
        await u.message.reply_text(tr(lang, "need_chart_en" if lang == "en" else "need_chart")); return
    ok, msg = consume_quota(u.effective_user.id, lang)
    if not ok:
        await u.message.reply_text("⛔ " + msg); return
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    birth = datetime.fromisoformat(row[1]); lat, lon = row[2], row[3]
    global LANG_DEFAULT_RU; LANG_DEFAULT_RU = (lang == "ru")
    natal, asc, mc, _ = await asyncio.to_thread(calc_chart, birth, lat, lon)
    now = datetime.now(timezone.utc)
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60)
    trans = {}
    for pid, ru, en in PLANETS:
        try:
            pos, _ = swe.calc_ut(jd, pid, swe.FLG_MOSEPH | swe.FLG_SPEED)
            trans[ru if lang == "ru" else en] = (pos[0], pos[3] < 0)
        except Exception:
            pass
    hits = await asyncio.to_thread(aspects_between, trans, {k: v for k, v in natal.items()})
    t_lines = [f"{n} {fmt(l,lang)}{' R' if r else ''}" for n,(l,r) in trans.items()]
    a_lines = [f"{na} {nm} {nb} (орб {o:.1f}°)" if lang=="ru" else f"{na} {nm} {nb} (orb {o:.1f}°)"
               for o,na,nm,nb in hits[:12]]
    header = tr(lang, "transit_header_en" if lang == "en" else "transit_header", now=now.strftime("%d.%m.%Y %H:%M UTC"))
    body = "\n".join(t_lines) + "\n\n" + "\n".join(a_lines)
    await u.message.reply_text(f"★ {msg}\n\n{header}\n{body}{footer(lang)}")
    interp = await glm(f"Натал (рождение {birth}):\n{chart_text(natal, asc, mc, lang)}\n\nТранзиты {now}:\n{body}\n\n"
                       f"Answer in {'Russian' if lang=='ru' else 'English'}. Интерпретируйте транзиты.")
    await u.message.reply_text(("🔮 " + interp[:MAX_MSG]) + footer(lang))

async def cmd_synastry(u: Update, ctx):
    row = get_user(u.effective_user.id)
    lang = (row[0] if row else "ru") or "ru"
    if not row or not row[1]:
        await u.message.reply_text(tr(lang, "need_chart_en" if lang == "en" else "need_chart")); return
    await u.message.reply_text(tr(lang, "enter_date_en" if lang == "en" else "enter_date"))
    return SYN_DATE

async def on_syn_date(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    d = valid_date(u.message.text)
    if not d:
        await u.message.reply_text(tr(lang, "bad_date_en" if lang == "en" else "bad_date")); return SYN_DATE
    ctx.user_data["syn_date"] = d.strftime("%Y-%m-%d")
    await u.message.reply_text(tr(lang, "enter_time_en" if lang == "en" else "enter_time"))
    return SYN_TIME

async def on_syn_time(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    t = valid_time(u.message.text)
    if t is None:
        await u.message.reply_text(tr(lang, "bad_time_en" if lang == "en" else "bad_time")); return SYN_TIME
    ctx.user_data["syn_time"] = "%02d:%02d" % t
    await u.message.reply_text(tr(lang, "enter_city_en" if lang == "en" else "enter_city"))
    return SYN_CITY

async def on_syn_city(u: Update, ctx):
    lang = (get_user(u.effective_user.id) or ["ru"])[0] or "ru"
    row = get_user(u.effective_user.id)
    ok, msg = consume_quota(u.effective_user.id, lang)
    if not ok:
        await u.message.reply_text("⛔ " + msg)
        ctx.user_data.clear(); return ConversationHandler.END
    await ctx.bot.send_chat_action(u.effective_chat.id, ChatAction.TYPING)
    geo = await asyncio.to_thread(geocode_city, u.message.text.strip()[:100])
    if not geo:
        await u.message.reply_text(tr(lang, "city_not_found_en" if lang == "en" else "city_not_found"))
        return SYN_CITY
    lat, lon, display = geo
    global LANG_DEFAULT_RU; LANG_DEFAULT_RU = (lang == "ru")
    sbirth = datetime.fromisoformat(f"{ctx.user_data['syn_date']}T{ctx.user_data['syn_time']}:00")
    mine, _, _, _ = await asyncio.to_thread(calc_chart, datetime.fromisoformat(row[1]), row[2], row[3])
    theirs, _, _, _ = await asyncio.to_thread(calc_chart, sbirth, lat, lon)
    hits = await asyncio.to_thread(aspects_between, dict(mine), dict(theirs))
    a_lines = [f"{na} {nm} {nb} (орб {o:.1f}°)" if lang=="ru" else f"{na} {nm} {nb} (orb {o:.1f}°)"
               for o,na,nm,nb in hits[:15]]
    body = (f"1: {chart_text(mine,0,0,lang)}\n\n2 ({display}): {chart_text(theirs,0,0,lang)}\n\n"
            + "\n".join(a_lines))
    await u.message.reply_text(f"★ {msg}\n\n{body[:MAX_MSG-len(footer(lang))]}{footer(lang)}")
    interp = await glm(f"Синастрия:\n{body}\n\nAnswer in {'Russian' if lang=='ru' else 'English'}. "
                       "Совместимость: сильные стороны, зоны напряжения.")
    await u.message.reply_text(("🔮 " + interp[:MAX_MSG]) + footer(lang))
    ctx.user_data.clear()
    return ConversationHandler.END

async def on_fallback(u: Update, ctx):
    return ConversationHandler.END

def main():
    if not TELEGRAM_TOKEN:
        print("ASTRO_TG_TOKEN не задан"); sys.exit(1)
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    lang_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start), CommandHandler("lang", cmd_lang)],
        states={LANG: [MessageHandler(filters.Regex("Русский|English"), on_lang)]},
        fallbacks=[MessageHandler(filters.ALL, on_fallback)], allow_reentry=True)

    natal_conv = ConversationHandler(
        entry_points=[CommandHandler("natal", cmd_natal)],
        states={NAT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_nat_date)],
                NAT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_nat_time)],
                NAT_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_nat_city)]},
        fallbacks=[CommandHandler("cancel", on_fallback)], allow_reentry=True)

    syn_conv = ConversationHandler(
        entry_points=[CommandHandler("synastry", cmd_synastry)],
        states={SYN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_syn_date)],
                SYN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_syn_time)],
                SYN_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_syn_city)]},
        fallbacks=[CommandHandler("cancel", on_fallback)], allow_reentry=True)

    app.add_handler(lang_conv)
    app.add_handler(natal_conv)
    app.add_handler(syn_conv)
    app.add_handler(CommandHandler(["transits", "tr"], cmd_transits))
    app.add_handler(CommandHandler("help", cmd_help))

    print("QS_astro_bot v2 запущен")
    while True:
        try:
            app.run_polling()
        except Exception as e:
            print(f"[restart] {e!r}; retry in 5s")
            time.sleep(5)

if __name__ == "__main__":
    main()
