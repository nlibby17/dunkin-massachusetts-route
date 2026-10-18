"""
Geocode the remaining patch addresses with Nominatim
(OpenStreetMap's geocoder) and produce the completed dataset.

Reads  data/clean/geocode_queue.csv and
       data/clean/dunkins_final_v2.csv
Writes data/clean/dunkins_final_v3.csv with pins filled for
       every row the geocoder resolves, and prints the short
       list of addresses it could not place.

Nominatim's usage policy asks for at most one request per
second and an identifying user agent; both are honored here.
Results are sanity-checked against a Massachusetts bounding
box so a same-named street in another state cannot sneak in.
"""

import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v2.csv"
QUEUE_PATH = ROOT / "data" / "clean" / "geocode_queue.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v3.csv"

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "dunkin-ma-practice-project/1.0"
DELAY_SECONDS = 1.1
# rough Massachusetts bounds: reject anything outside
LAT_MIN, LAT_MAX = 41.2, 42.9
LON_MIN, LON_MAX = -73.6, -69.9


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def geocode(address: str, city: str, state: str):
    q = urllib.parse.urlencode({
        "q": f"{address}, {city}, {state}, USA",
        "format": "jsonv2", "limit": 1,
    })
    req = urllib.request.Request(
        f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        results = json.load(resp)
    if not results:
        return None
    lat = float(results[0]["lat"])
    lon = float(results[0]["lon"])
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return None
    return lat, lon


def main():
    final = read_csv(FINAL_PATH)
    queue = read_csv(QUEUE_PATH)

    pins = {}
    failed = []
    for i, row in enumerate(queue, 1):
        key = (row["address"], row["city"])
        try:
            hit = geocode(row["address"], row["city"], row["state"])
        except Exception as e:
            print(f"[{i}/{len(queue)}] {row['address']}, "
                  f"{row['city']}: request error {e}")
            hit = None
        if hit:
            pins[key] = hit
            print(f"[{i}/{len(queue)}] {row['address']}, "
                  f"{row['city']}: {hit[0]:.5f}, {hit[1]:.5f}")
        else:
            failed.append(key)
            print(f"[{i}/{len(queue)}] {row['address']}, "
                  f"{row['city']}: NOT FOUND")
        time.sleep(DELAY_SECONDS)

    filled = 0
    for r in final:
        if r.get("pin_source") == "geocode_pending":
            hit = pins.get((r["address"], r["city"]))
            if hit:
                r["lat"], r["lon"] = f"{hit[0]:.6f}", f"{hit[1]:.6f}"
                r["pin_source"] = "nominatim"
                filled += 1
            else:
                r["pin_source"] = "geocode_failed"

    cols = list(final[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)

    pinned = sum(1 for r in final if r.get("lat"))
    print("\n==== geocoding ====")
    print(f"  filled from Nominatim: {filled}")
    print(f"  stops with coordinates: {pinned} of {len(final)}")
    if failed:
        print("  addresses the geocoder could not place:")
        for address, city in failed:
            print(f"    {address}, {city}")
    else:
        print("  every queued address placed.")


if __name__ == "__main__":
    main()
