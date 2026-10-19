"""
Suspect repair pass: two-witness rule.

Reads  data/clean/dunkins_final_v6.csv
       data/clean/coord_audit.csv (the SUSPECT rows)
       data/clean/dunkins_final_v5.csv (Horizon Way twin)
Writes data/clean/dunkins_final_v7.csv
       data/clean/suspects_verdict.csv

For every suspect, the address is geocoded fresh by BOTH the
Census batch geocoder and Nominatim. If the two agree within
250 m and both disagree with the current pin by > 500 m, the
pin is replaced with the Census coordinate. A single witness
replaces only beyond 1,500 m. Anything else is reported as
an eyeball case with all coordinates printed. 1 Horizon Way
is report-only: its dropped twin's pin is a third witness
and Nick rules it himself.
"""

import csv
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V6_PATH = ROOT / "data" / "clean" / "dunkins_final_v6.csv"
V5_PATH = ROOT / "data" / "clean" / "dunkins_final_v5.csv"
AUDIT_PATH = ROOT / "data" / "clean" / "coord_audit.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v7.csv"
VERDICT_PATH = ROOT / "data" / "clean" / "suspects_verdict.csv"

NOM_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_URL = ("https://geocoding.geo.census.gov/geocoder/"
              "locations/addressbatch")
USER_AGENT = "dunkin-ma-practice-project/1.0"
LAT_MIN, LAT_MAX = 41.2, 42.9
LON_MIN, LON_MAX = -73.6, -69.9
REPORT_ONLY = {("1 horizon way", "everett")}

SUFFIX_MAP = {"street": "st", "road": "rd", "avenue": "ave",
              "boulevard": "blvd", "drive": "dr", "turnpike": "tpke",
              "highway": "hwy", "parkway": "pkwy", "square": "sq",
              "lane": "ln", "court": "ct", "place": "pl"}
SUFFIX_TOKENS = set(SUFFIX_MAP.values()) | {"cir", "way"}


def clean_street(address: str):
    a = (address or "").lower().strip()
    a = re.sub(r"#.*$", "", a)
    a = re.sub(r"[.,()]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    toks = a.split(" ")
    for i, t in enumerate(toks):
        t2 = SUFFIX_MAP.get(t, t)
        if t2 in SUFFIX_TOKENS and i >= 1:
            return " ".join(toks[:i] + [t2])
    return a if re.match(r"^\d", a) else None


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def nominatim(query):
    q = urllib.parse.urlencode({"q": query, "format": "jsonv2",
                                "limit": 1})
    req = urllib.request.Request(
        f"{NOM_URL}?{q}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.load(resp)
    except Exception:
        results = []
    time.sleep(1.1)
    if not results:
        return None
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
        return lat, lon
    return None


def census_batch(items):
    buf = io.StringIO()
    w = csv.writer(buf)
    for idx, street, city, zipc in items:
        w.writerow([idx, street, city, "MA", zipc or ""])
    payload = buf.getvalue().encode("utf-8")
    boundary = "----dunkinbatchboundary"
    body = b""
    for name, value in (("benchmark", "Public_AR_Current"),
                        ("vintage", "Current_Current")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f"name=\"addressFile\"; filename=\"batch.csv\"\r\n"
             f"Content-Type: text/csv\r\n\r\n").encode()
    body += payload + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        CENSUS_URL, data=body,
        headers={"Content-Type":
                 f"multipart/form-data; boundary={boundary}",
                 "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=900) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        try:
            idx = int(row[0])
        except ValueError:
            continue
        match, mtype, coords = row[2].strip(), row[3].strip(), \
            row[5].strip()
        if match not in ("Match", "Tie") or not coords:
            continue
        lon_s, lat_s = coords.split(",")
        lat, lon = float(lat_s), float(lon_s)
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            if idx not in out or mtype == "Exact":
                out[idx] = (lat, lon)
    return out


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rows = read_csv(V6_PATH)
    suspects = [r for r in read_csv(AUDIT_PATH)
                if r["bucket"] == "SUSPECT"]
    print(f"suspects to process: {len(suspects)}")
    by_key = {(r["address"], r["city"]): r for r in rows}

    by_city = defaultdict(list)
    for r in rows:
        by_city[r["city"].lower()].append(
            (float(r["lat"]), float(r["lon"])))
    centroid = {c: (sorted(p[0] for p in pts)[len(pts) // 2],
                    sorted(p[1] for p in pts)[len(pts) // 2])
                for c, pts in by_city.items()}

    # Horizon Way twin witness from v5
    twins = [r for r in read_csv(V5_PATH)
             if "1 Horizon Way" in r["address"]
             and r["city"] == "Everett"]

    items = []
    street_of = {}
    for i, s in enumerate(suspects):
        street = clean_street(s["address"])
        street_of[i] = street
        if street:
            items.append((i, street, s["city"], ""))
    census = census_batch(items)

    verdicts = []
    replaced, eyeball = 0, []
    for i, s in enumerate(suspects):
        row = by_key.get((s["address"], s["city"]))
        if row is None:
            continue
        old = (float(row["lat"]), float(row["lon"]))
        cen = centroid[row["city"].lower()]
        c_pin = census.get(i)
        n_pin = None
        if street_of.get(i):
            n_pin = nominatim(
                f"{street_of[i]}, {s['city']}, MA, USA")
        d_c = haversine_m(*old, *c_pin) if c_pin else None
        d_n = haversine_m(*old, *n_pin) if n_pin else None
        d_cn = haversine_m(*c_pin, *n_pin) if c_pin and n_pin \
            else None
        low = (s["address"].lower().strip(),
               s["city"].lower().strip())
        decision, new_pin, stamp = "eyeball", None, ""

        if low in REPORT_ONLY:
            decision = "report_only"
            print(f"\n1 Horizon Way witnesses:")
            print(f"  surviving pin : {old}")
            for t in twins:
                print(f"  v5 row ({t['final_status']}): "
                      f"({t['lat']}, {t['lon']})")
            print(f"  census fresh  : {c_pin}")
            print(f"  nominatim     : {n_pin}")
        elif c_pin and n_pin and d_cn <= 250 and d_c > 500 \
                and d_n > 500:
            decision, new_pin, stamp = "replace", c_pin, \
                "repin_two_witness"
        elif (c_pin or n_pin):
            only = c_pin or n_pin
            d_only = d_c if c_pin else d_n
            if d_only > 1500:
                decision, new_pin, stamp = "replace", only, \
                    "repin_single_witness"

        if decision == "replace":
            gate = haversine_m(new_pin[0], new_pin[1],
                               cen[0], cen[1]) / 1000
            if gate > 15:
                decision = "eyeball"
                print(f"GATE REFUSAL {s['address']}, {s['city']}: "
                      f"fresh pin lands {gate:.0f} km from town")
            else:
                row["lat"] = f"{new_pin[0]:.6f}"
                row["lon"] = f"{new_pin[1]:.6f}"
                row["pin_source"] = stamp
                replaced += 1
        if decision == "eyeball":
            eyeball.append(s)
        verdicts.append([s["address"], s["city"], row["pin_source"],
                         f"{old[0]:.6f},{old[1]:.6f}",
                         f"{c_pin[0]:.6f},{c_pin[1]:.6f}"
                         if c_pin else "",
                         f"{n_pin[0]:.6f},{n_pin[1]:.6f}"
                         if n_pin else "",
                         decision])

    cols = list(rows[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(VERDICT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["address", "city", "pin_source", "old_pin",
                    "census_pin", "nominatim_pin", "decision"])
        w.writerows(verdicts)

    print(f"\nreplaced: {replaced}")
    print(f"eyeball list ({len(eyeball)}):")
    for s in eyeball:
        print(f"  {s['address']}, {s['city']}")
    print(f"final stops in {OUT_PATH.name}: {len(rows)}")


if __name__ == "__main__":
    main()
