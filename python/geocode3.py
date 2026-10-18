"""
Last automated pass over the five unpinned stops: alternate
query shapes (Broadway/Cutoff treated as endings, the
Tyngsborough spelling variant, and a POI name search).
Reads and rewrites data/clean/dunkins_final_v4.csv in place
as dunkins_final_v5.csv. Anything still unpinned after this
is hand-pinned at validation with a documented note.
"""

import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v4.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v5.csv"

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "dunkin-ma-practice-project/1.0"
LAT_MIN, LAT_MAX = 41.2, 42.9
LON_MIN, LON_MAX = -73.6, -69.9
TOWN_VARIANTS = {"Tyngsboro": "Tyngsborough"}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def try_query(query):
    q = urllib.parse.urlencode({"q": query, "format": "jsonv2",
                                "limit": 1})
    req = urllib.request.Request(
        f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.load(resp)
    except Exception:
        return None
    time.sleep(1.1)
    if not results:
        return None
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
        return lat, lon
    return None


def variants(address, city):
    out = []
    # Broadway / Cutoff act as street endings: cut the tail
    low = address.lower()
    for ender in ("broadway", "cutoff"):
        if ender in low:
            cut = low[: low.index(ender) + len(ender)]
            out.append(f"{cut}, {city}, MA, USA")
    if city in TOWN_VARIANTS:
        out.append(f"{address}, {TOWN_VARIANTS[city]}, MA, USA")
    out.append(f"Dunkin', {city}, MA, USA")          # POI search
    out.append(f"Dunkin' Donuts, {city}, MA, USA")   # POI variant
    return out


def main():
    final = read_csv(FINAL_PATH)
    targets = [r for r in final
               if r.get("pin_source") == "geocode_failed"]
    print(f"targets: {len(targets)}")
    for r in targets:
        hit = None
        for q in variants(r["address"], r["city"]):
            hit = try_query(q)
            if hit:
                print(f"  HIT  {r['address']}, {r['city']} "
                      f"via [{q}]: {hit[0]:.5f}, {hit[1]:.5f}")
                break
        if hit:
            r["lat"], r["lon"] = f"{hit[0]:.6f}", f"{hit[1]:.6f}"
            r["pin_source"] = "nominatim3"
        else:
            print(f"  FAIL {r['address']}, {r['city']}: "
                  f"hand-pin at validation")
    cols = list(final[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)
    pinned = sum(1 for r in final if r.get("lat"))
    print(f"\nstops with coordinates: {pinned} of {len(final)}")


if __name__ == "__main__":
    main()
