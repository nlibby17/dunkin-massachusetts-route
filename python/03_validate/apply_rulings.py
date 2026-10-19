"""
Unified final pass: apply the duplicate rulings, then audit
every coordinate in the dataset.

Reads  data/clean/dunkins_final_v5.csv
Writes data/clean/dunkins_final_v6.csv (collapsed to 1,019,
       known bad pins repaired)
       data/clean/coord_audit.csv (one row per stop: pin vs
       fresh geocode distance and verdict bucket; written
       incrementally so the run can resume)

Audit method: each stop's address is geocoded fresh via
Nominatim from a cleaned bare string. Buckets:
  agree            <= 150 m (normal geocode slop)
  minor            150-500 m (logged, no action)
  SUSPECT          > 500 m (eyeball list, worst first)
  no_street_address  venue listings a geocoder cannot check
The five ruled bad pairs auto-repair on > 100 m disagreement
(vindicate/replace). All other suspects are reported only:
a geocoder disagreement is a flag, not a conviction.
A town-centroid check flags any pin sitting far from its own
town's other stops, independent of the geocoder.
"""

import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v5.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v6.csv"
AUDIT_PATH = ROOT / "data" / "clean" / "coord_audit.csv"

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "dunkin-ma-practice-project/1.0"
LAT_MIN, LAT_MAX = 41.2, 42.9
LON_MIN, LON_MAX = -73.6, -69.9

SUFFIX_MAP = {"street": "st", "road": "rd", "avenue": "ave",
              "boulevard": "blvd", "drive": "dr", "turnpike": "tpke",
              "highway": "hwy", "parkway": "pkwy", "square": "sq",
              "lane": "ln", "court": "ct", "place": "pl"}
SUFFIX_TOKENS = set(SUFFIX_MAP.values()) | {"cir", "way"}

KNOWN_BAD = {
    ("152 center st", "pembroke"), ("30 union st", "holbrook"),
    ("440 middlesex rd", "tyngsboro"), ("95 westford road",
     "tyngsboro"),
    ("1001 south st", "wrentham"), ("1048 south st", "wrentham"),
    ("171 broad st", "bridgewater"),
    ("1 south station", "boston"), ("757 centre st", "boston"),
}

# Hand-placed by Nick from Google Maps (right-click the spot,
# the menu shows the coordinates). None = still pending.
HAND_PINS = {
    ("route 24 northbound service pavilion", "bridgewater"): (41.956907685098294, -71.02574971746255),
    ("route 24 southbound service pavilion", "bridgewater"): (41.95580811566652, -71.02680916282976),
}

HAND_PIN_TARGETS = set(HAND_PINS)

QUERY_OVERRIDES = {
    ("hanscom air force base main exchange building", "bedford"):
        ["Hanscom Air Force Base, Bedford, MA, USA"],
    ("route 24 southbound service pavilion", "bridgewater"):
        ["Bridgewater Service Plaza, Bridgewater, MA, USA"],
    ("route 24 northbound service pavilion", "bridgewater"):
        ["Bridgewater Service Plaza, Bridgewater, MA, USA"],
    ("1 south station", "boston"):
        ["South Station, Boston, MA, USA"],
}


def clean_query(address: str, city: str):
    a = (address or "").lower().strip()
    a = re.sub(r"#.*$", "", a)
    a = re.sub(r"[.,()]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    toks = a.split(" ")
    street = a
    for i, t in enumerate(toks):
        t2 = SUFFIX_MAP.get(t, t)
        if t2 in SUFFIX_TOKENS and i >= 1:
            street = " ".join(toks[:i] + [t2])
            break
    if not re.match(r"^\d", street):
        return None  # no house number: not address-geocodable
    return f"{street}, {city}, MA, USA"


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def geocode(query):
    q = urllib.parse.urlencode({"q": query, "format": "jsonv2",
                                "limit": 1})
    req = urllib.request.Request(
        f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
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


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rows = read_csv(FINAL_PATH)

    # ---- collapses (Nick's rulings) ----
    def collapse(city, frag, prefer_status=None):
        idx = [i for i, r in enumerate(rows)
               if r["city"].lower() == city.lower()
               and frag.lower() in r["address"].lower()]
        if len(idx) != 2:
            print(f"collapse {city} {frag}: {len(idx)} rows, skip")
            return
        keep = idx[0]
        if prefer_status:
            for i in idx:
                if rows[i]["final_status"] == prefer_status:
                    keep = i
        drop = [i for i in idx if i != keep][0]
        print(f"collapse: kept '{rows[keep]['address']}', "
              f"dropped '{rows[drop]['address']}'")
        rows.pop(drop)

    collapse("Carver", "80 Main")
    collapse("Everett", "1 Horizon Way", prefer_status="locked_keep")
    print(f"stops after collapses: {len(rows)} (expect 1019)")

    for r in rows:
        hp = HAND_PINS.get((r["address"].lower().strip(),
                            r["city"].lower().strip()))
        if hp:
            r["lat"], r["lon"] = f"{hp[0]:.6f}", f"{hp[1]:.6f}"
            r["pin_source"] = "hand_placed"
            print(f"hand pin applied: {r['address']}, {r['city']}")

    cols = list(rows[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT_PATH.name}; audit starting "
          f"(~{len(rows)} lookups, about 19 min, resumable)")

    # ---- town centroids from the pins themselves ----
    by_city = defaultdict(list)
    for r in rows:
        by_city[r["city"].lower()].append(
            (float(r["lat"]), float(r["lon"])))
    centroid = {}
    for city, pts in by_city.items():
        centroid[city] = (sorted(p[0] for p in pts)[len(pts) // 2],
                          sorted(p[1] for p in pts)[len(pts) // 2])

    # ---- resume support ----
    done = {}
    if AUDIT_PATH.exists():
        for r in read_csv(AUDIT_PATH):
            if r["bucket"] != "hand_pin_pending":
                done[(r["address"], r["city"])] = r

    audit_f = open(AUDIT_PATH, "a", newline="", encoding="utf-8")
    aw = csv.writer(audit_f)
    if not done:
        aw.writerow(["address", "city", "pin_source", "dist_m",
                     "bucket", "town_km"])

    suspects = []
    counts = defaultdict(int)
    for i, r in enumerate(rows, 1):
        key = (r["address"], r["city"])
        low_addr = r["address"].lower().strip()
        low_city = r["city"].lower().strip()
        pin = (float(r["lat"]), float(r["lon"]))
        cen = centroid[low_city]
        town_km = haversine_m(pin[0], pin[1], cen[0], cen[1]) / 1000

        if key in done:
            counts[done[key]["bucket"]] += 1
            continue

        if (low_addr, low_city) in HAND_PIN_TARGETS:
            bucket = "hand_placed" if HAND_PINS.get(
                (low_addr, low_city)) else "hand_pin_pending"
            counts[bucket] += 1
            aw.writerow([r["address"], r["city"], r["pin_source"],
                    "", bucket, f"{town_km:.1f}"])
            audit_f.flush()
            continue

        queries = QUERY_OVERRIDES.get((low_addr, low_city))
        if queries is None:
            q = clean_query(r["address"], r["city"])
            queries = [q] if q else []
        fresh = None
        for q in queries:
            fresh = geocode(q)
            if fresh:
                break
        if fresh is None:
            bucket, dist = "no_street_address", ""
        else:
            dist_m = haversine_m(pin[0], pin[1], fresh[0], fresh[1])
            dist = f"{dist_m:.0f}"
            if (low_addr, low_city) in KNOWN_BAD and dist_m > 100:
                r["lat"], r["lon"] = f"{fresh[0]:.6f}", f"{fresh[1]:.6f}"
                r["pin_source"] = "repin_nominatim"
                bucket = "known_bad_REPINNED"
                print(f"[{i}] REPINNED {r['address']}, {r['city']} "
                      f"(was {dist} m off)")
            elif dist_m <= 150:
                bucket = "agree"
            elif dist_m <= 500:
                bucket = "minor"
            else:
                bucket = "SUSPECT"
        if town_km > 20 and bucket in ("agree", "minor"):
            bucket = "SUSPECT"
            print(f"[{i}] FAR FROM TOWN {r['address']}, "
                  f"{r['city']} ({town_km:.0f} km)")
        if bucket == "SUSPECT":
            suspects.append((int(dist) if dist else 0, r))
        counts[bucket] += 1
        aw.writerow([r["address"], r["city"], r["pin_source"],
                     dist, bucket, f"{town_km:.1f}"])
        audit_f.flush()
        if i % 100 == 0:
            print(f"  ...{i}/{len(rows)} audited")
    audit_f.close()

    # rewrite the final file with any repins applied
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print("\n==== coordinate audit ====")
    for bucket, n in sorted(counts.items()):
        print(f"  {bucket}: {n}")
    if suspects:
        print("worst suspects (eyeball in this order):")
        for dist, r in sorted(suspects, reverse=True)[:20]:
            print(f"  {dist} m  {r['address']}, {r['city']} "
                  f"(pin: {r['pin_source']})")
    print(f"final stops in {OUT_PATH.name}: {len(rows)}")


if __name__ == "__main__":
    main()
