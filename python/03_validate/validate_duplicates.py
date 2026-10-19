"""
Duplicate hunt over the final stop list.

Reads  data/clean/dunkins_final_v5.csv
Writes data/clean/duplicate_suspects.csv (pairs/groups with
       reasons and blank decision columns; nothing is removed)

Signals, strongest first:
  proximity   two stops within 150 m of each other
  same_key    identical normalized address + town (formatting
              variants of one address)
  directional listings differing only by a directional token
              (the Northbound/Southbound pavilion pattern)
  venue       two listings sharing a venue keyword in the same
              town (university, hospital, pavilion...)
"""

import csv
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v5.csv"
OUT_PATH = ROOT / "data" / "clean" / "duplicate_suspects.csv"

SUFFIX_MAP = {"street": "st", "road": "rd", "avenue": "ave",
              "boulevard": "blvd", "drive": "dr", "turnpike": "tpke",
              "highway": "hwy", "parkway": "pkwy", "square": "sq",
              "lane": "ln", "court": "ct", "place": "pl"}
SUFFIX_TOKENS = set(SUFFIX_MAP.values()) | {"cir", "way"}
VENUE_WORDS = ["university", "college", "hospital", "medical",
               "stadium", "arena", "pavilion", "campus", "airport",
               "station", "garden", "park"]
DIRECTIONALS = {"north", "south", "east", "west",
                "northbound", "southbound"}


def address_key(addr: str) -> str:
    if not isinstance(addr, str) or not addr.strip():
        return ""
    a = addr.lower().strip()
    a = re.sub(r"#.*$", "", a)
    a = re.sub(r"[.,()]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    toks = a.split(" ")
    for i, t in enumerate(toks):
        t2 = SUFFIX_MAP.get(t, t)
        if t2 in SUFFIX_TOKENS and i >= 1:
            return " ".join(toks[:i] + [t2])
    return a


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rows = read_csv(FINAL_PATH)
    for r in rows:
        r["key"] = address_key(r["address"])
        r["lat"] = float(r["lat"]) if r["lat"] else None
        r["lon"] = float(r["lon"]) if r["lon"] else None

    suspects = []

    def add(a, b, reason, dist=""):
        suspects.append({
            "reason": reason,
            "distance_m": dist,
            "address_a": a["address"], "city_a": a["city"],
            "status_a": a["final_status"],
            "address_b": b["address"], "city_b": b["city"],
            "status_b": b["final_status"],
            "decision": "", "notes": "",
        })

    # 1. same normalized address + town
    by_key = defaultdict(list)
    for r in rows:
        if r["key"]:
            by_key[(r["city"].lower(), r["key"])].append(r)
    n_key = 0
    for group in by_key.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add(group[i], group[j], "same_key")
                n_key += 1

    # 2. proximity: every pair within 150 m
    n_prox = 0
    pinned = [r for r in rows if r["lat"] is not None]
    for i in range(len(pinned)):
        for j in range(i + 1, len(pinned)):
            a, b = pinned[i], pinned[j]
            d = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if d <= 150:
                add(a, b, "proximity", f"{d:.0f}")
                n_prox += 1

    # 3. directional twins (pavilion pattern)
    def stripped(addr):
        toks = [t for t in address_key(addr).split(" ")
                if t not in DIRECTIONALS]
        return " ".join(toks)
    by_stem = defaultdict(list)
    for r in rows:
        by_stem[(r["city"].lower(), stripped(r["address"]))].append(r)
    n_dir = 0
    for group in by_stem.values():
        if len(group) > 1 and any(
                any(t in DIRECTIONALS
                    for t in r["address"].lower().split())
                for r in group):
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    if group[i]["key"] != group[j]["key"]:
                        add(group[i], group[j], "directional")
                        n_dir += 1

    # 4. venue groups: same town, shared venue word, 2+ listings
    by_venue = defaultdict(list)
    for r in rows:
        low = r["address"].lower()
        for w in VENUE_WORDS:
            if w in low:
                by_venue[(r["city"].lower(), w)].append(r)
                break
    n_venue = 0
    for group in by_venue.values():
        if len(group) > 1:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    add(group[i], group[j], "venue")
                    n_venue += 1

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(suspects[0].keys()))
        w.writeheader()
        w.writerows(suspects)

    print("==== duplicate suspects ====")
    print(f"  same_key pairs:   {n_key}")
    print(f"  proximity pairs:  {n_prox}")
    print(f"  directional pairs:{n_dir}")
    print(f"  venue pairs:      {n_venue}")
    print(f"  total rows in duplicate_suspects.csv: {len(suspects)}")


if __name__ == "__main__":
    main()
