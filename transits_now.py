#!/usr/bin/env python3
"""Транзиты на текущий момент к натальной карте (позиции задаются в NATAL_LON)."""
import swisseph as swe
import os
from datetime import datetime, timezone

swe.set_ephe_path(os.path.expanduser("~/.hermes/ephe"))
SIGNS = ["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]

def fmt(lon):
    s = int(lon // 30); d = lon % 30
    return f"{int(d):2d}°{int(d%1*60):02d}' {SIGNS[s]}"

# натальные позиции — замените на свои (формат: "ГГ°ММ' Знак")
NATAL_LON = {k: (30*SIGNS.index(v.split()[-1]) + float(v.split('°')[0]) + float(v.split('°')[1].split("'")[0])/60)
             for k, v in {
    "Солнце":"10°00' Козерог","Луна":"12°00' Овен","Меркурий":"05°00' Водолей","Венера":"20°00' Стрелец",
    "Марс":"08°00' Рыбы","Юпитер":"15°00' Рак","Сатурн":"22°00' Козерог","Уран":"10°00' Козерог",
    "Нептун":"05°00' Козерог","Плутон":"18°00' Скорпион","Сев.Узел":"10°00' Водолей",
    "Хирон":"18°00' Рак","Лилит":"25°00' Лев"}.items()}

now = datetime.now(timezone.utc)
jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60 + now.second/3600)
print(f"=== ТРАНЗИТЫ на {now.strftime('%d.%m.%Y %H:%M UTC')} ===\n")

PLANETS = [(swe.SUN,"Солнце"),(swe.MOON,"Луна"),(swe.MERCURY,"Меркурий"),(swe.VENUS,"Венера"),
    (swe.MARS,"Марс"),(swe.JUPITER,"Юпитер"),(swe.SATURN,"Сатурн"),(swe.URANUS,"Уран"),
    (swe.NEPTUNE,"Нептун"),(swe.PLUTO,"Плутон")]

ASPECTS = [(0,"соединение",8),(60,"секстиль",4),(90,"квадрат",5),(120,"трин",5),(180,"оппозиция",5)]

print("ТЕКУЩИЕ ПОЗИЦИИ:")
transit_lon = {}
for pid, name in PLANETS:
    pos, _ = swe.calc_ut(jd, pid, swe.FLG_MOSEPH | swe.FLG_SPEED)
    transit_lon[name] = pos[0]
    print(f"  {name:9s} {fmt(pos[0])}" + (" R" if pos[3] < 0 else ""))

print("\nТРАНЗИТЫ К НАТАЛЬНОЙ КАРТЕ:")
hits = []
for tname, tlon in transit_lon.items():
    for nname, nlon in NATAL_LON.items():
        d = abs(tlon - nlon)
        if d > 180: d = 360 - d
        for ang, nm, orb in ASPECTS:
            if abs(d - ang) <= orb:
                hits.append((abs(d-ang), tname, nm, nname, d-ang))
                break
hits.sort()
for orb, t, nm, n, diff in hits:
    print(f"  {t} {nm} натальному {n} (орб {orb:.1f}°)")
