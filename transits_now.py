#!/usr/bin/env python3
"""Транзиты на текущий момент к натальной карте 20.08.1987."""
import swisseph as swe
import os
from datetime import datetime, timezone

swe.set_ephe_path(os.path.expanduser("~/.hermes/ephe"))
SIGNS = ["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]

def fmt(lon):
    s = int(lon // 30); d = lon % 30
    return f"{int(d):2d}°{int(d%1*60):02d}' {SIGNS[s]}"

# натал (из natal_chart.py)
NATAL = {
    "Солнце":26.867,"Луна":102.35,"Меркурий":147.07,"Венера":146.08,"Марс":148.47,
    "Юпитер":29.72,"Сатурн":254.53,"Уран":262.77,"Нептун":275.43,"Плутон":217.45,
    "Сев.Узел":2.95,"Хирон":87.38,"Лилит":120.22,
}
NATAL_LON = {k: (30*SIGNS.index(v.split()[-1]) + float(v.split('°')[0]) + float(v.split('°')[1].split("'")[0])/60)
             for k, v in {
    "Солнце":"26°52' Лев","Луна":"12°21' Рак","Меркурий":"27°04' Лев","Венера":"26°05' Лев",
    "Марс":"28°28' Лев","Юпитер":"29°43' Овен","Сатурн":"14°32' Стрелец","Уран":"22°46' Стрелец",
    "Нептун":"5°26' Козерог","Плутон":"7°27' Скорпион","Сев.Узел":"2°57' Овен",
    "Хирон":"27°23' Близнецы","Лилит":"0°13' Лев"}.items()}

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
