#!/usr/bin/env python3
"""Натальная карта — Swiss Ephemeris (pyswisseph), Moshier-флаг (без файлов .se1, точность ~0.1")."""
import swisseph as swe
import json, sys, os

swe.set_ephe_path(os.path.expanduser("~/.hermes/ephe"))

# Пример: место рождения (широта/долгота в градусах) — поменяйте на своё
LAT, LON = 55.75, 37.62  # Москва
# Дата и время рождения
Y, M, D = 1990, 1, 1
UT = 9.0  # часы UTC (внимание: для исторических дат учтите декретное/летнее время!)

FLAGS = swe.FLG_MOSEPH | swe.FLG_SPEED

SIGNS = ["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]

PLANETS = [
    (swe.SUN,"Солнце"),(swe.MOON,"Луна"),(swe.MERCURY,"Меркурий"),(swe.VENUS,"Венера"),
    (swe.MARS,"Марс"),(swe.JUPITER,"Юпитер"),(swe.SATURN,"Сатурн"),(swe.URANUS,"Уран"),
    (swe.NEPTUNE,"Нептун"),(swe.PLUTO,"Плутон"),(swe.TRUE_NODE,"Сев.Узел"),(swe.CHIRON,"Хирон"),(swe.MEAN_APOG,"Лилит"),
]

def fmt(lon):
    sign = int(lon // 30)
    deg = lon % 30
    return f"{int(deg):2d}°{int(deg%1*60):02d}' {SIGNS[sign]}"

jd = swe.julday(Y, M, D, UT)
cusps, ascmc = swe.houses(jd, LAT, LON, b'P')  # Плацидус

out = {"дата": f"{D}.{M}.{Y}", "время_мск": "12:00 (UTC+3)", "место": f"{LAT}N {LON}E"}

print(f"=== НАТАЛЬНАЯ КАРТА {D}.{M}.{Y} {UT:05.2f} UT, {LAT}N {LON}E ===\n")
print(f"АСЦЕНДЕНТ: {fmt(ascmc[0])}")
print(f"MC:        {fmt(ascmc[1])}\n")
out["asc"] = fmt(ascmc[0]); out["mc"] = fmt(ascmc[1])

positions = {}
print("ПЛАНЕТЫ:")
for pid, name in PLANETS:
    try:
        pos, _ = swe.calc_ut(jd, pid, FLAGS)
        lon, speed = pos[0], pos[3]
        positions[name] = lon
        retro = " R" if speed < 0 else ""
        print(f"  {name:10s} {fmt(lon)}{retro}")
    except Exception as e:
        print(f"  {name:10s} ошибка: {e}")
out["planets"] = {k: fmt(v) for k, v in positions.items()}

print("\nДОМА (Плацидус):")
for i, c in enumerate(cusps, 1):
    print(f"  Дом {i:2d}: {fmt(c)}")
out["houses"] = [fmt(c) for c in cusps]

# Аспекты (мажорные, орбисы: соед/опп 8, трин/квадрат 7, секстиль 5)
ASPECTS = [(0,"соединение",8),(60,"секстиль",5),(90,"квадрат",7),(120,"трин",7),(180,"оппозиция",8)]
names = list(positions)
print("\nАСПЕКТЫ:")
for i in range(len(names)):
    for j in range(i+1, len(names)):
        d = abs(positions[names[i]] - positions[names[j]])
        if d > 180: d = 360 - d
        for ang, nm, orb in ASPECTS:
            if abs(d - ang) <= orb:
                print(f"  {names[i]} {nm} {names[j]} (орб {abs(d-ang):.1f}°)")
                break

with open(__file__.replace("natal_chart.py","natal_data.json"), "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
