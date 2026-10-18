"""
Fix pass over the geocoder's failures.

Reads  data/clean/dunkins_final_v3.csv and
       data/clean/dunkins_stage1.csv (pin donor pool)
Writes data/clean/dunkins_final_v4.csv

Three repairs:
  1. The "Logal International Airport" patch is deleted: it is
     a Logan listing whose typo slipped the Logan rule, and
     Logan already has its stop.
  2. Donor retry with two alias repairs (spaced "g a r" and
     "mac arthur") that recover pins already sitting in the
     discarded rows, notably Swansea's 2368 GAR Hwy and
     Bourne's 568 MacArthur Blvd.
  3. Nominatim retry with cleaned query strings: venue tails,
     parentheticals, and unit markers cut before asking.
Whatever still fails prints as the true micro-residue.
"""

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v3.csv"
STAGE1_PATH = ROOT / "data" / "clean" / "dunkins_stage1.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v4.csv"

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "dunkin-ma-practice-project/1.0"
DELAY_SECONDS = 1.1
LAT_MIN, LAT_MAX = 41.2, 42.9
LON_MIN, LON_MAX = -73.6, -69.9
QUERY_OVERRIDES = {
    "Hanscom Air Force Base Main Exchange Building":
        "Hanscom Air Force Base, Bedford, MA, USA",
}

SUFFIX_MAP = {"street": "st", "road": "rd", "avenue": "ave",
              "boulevard": "blvd", "drive": "dr", "turnpike": "tpke",
              "highway": "hwy", "parkway": "pkwy", "square": "sq",
              "lane": "ln", "court": "ct", "place": "pl"}
SUFFIX_TOKENS = set(SUFFIX_MAP.values()) | {"cir", "way"}
DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}
CITY_ALIASES = {"south hamilton": "hamilton"}
FOLD = {
    "marlboro": "marlborough", "foxboro": "foxborough",
    "allston": "boston", "brighton": "boston",
    "charlestown": "boston", "dorchester": "boston",
    "east boston": "boston", "hyde park": "boston",
    "jamaica plain": "boston", "mattapan": "boston",
    "roslindale": "boston", "roxbury": "boston",
    "south boston": "boston", "west roxbury": "boston",
    "dorchester center": "boston",
    "north quincy": "quincy", "east taunton": "taunton",
    "centerville": "barnstable", "osterville": "barnstable",
    "hyannis": "barnstable", "marstons mills": "barnstable",
    "west barnstable": "barnstable",
    "south yarmouth": "yarmouth", "west yarmouth": "yarmouth",
    "south dennis": "dennis", "west dennis": "dennis",
    "dennis port": "dennis",
    "buzzards bay": "bourne", "sagamore beach": "bourne",
    "pocasset": "bourne",
    "east falmouth": "falmouth", "north falmouth": "falmouth",
    "teaticket": "falmouth",
    "south hamilton": "hamilton",
    "manchester": "manchester by the sea",
    "north attleborough": "north attleboro",
    "north dartmouth": "dartmouth", "south dartmouth": "dartmouth",
    "north easton": "easton", "south easton": "easton",
    "north chelmsford": "chelmsford",
    "north billerica": "billerica", "west concord": "concord",
    "bondsville": "palmer", "assonnet": "freetown",
    "east freetown": "freetown",
    "harwich port": "harwich",
    "north weymouth": "weymouth", "south weymouth": "weymouth",
    "east walpole": "walpole", "east wareham": "wareham",
    "auburndale": "newton", "newton highlands": "newton",
    "babson park": "wellesley", "whitinsville": "northbridge",
    "feeding hills": "agawam", "fiskdale": "sturbridge",
    "baldwinville": "templeton",
}


def fold(city: str) -> str:
    c = re.sub(r"\s+", " ", str(city or "").strip().lower()
               ).replace("-", " ")
    c = CITY_ALIASES.get(c, c)
    return FOLD.get(c, c)


def address_key(addr: str) -> str:
    if not isinstance(addr, str) or not addr.strip():
        return ""
    a = addr.lower().strip()
    a = re.sub(r"#.*$", "", a)
    a = re.sub(r"\b(suite|ste|unit|apt)\b.*$", "", a)
    a = re.sub(r"[.,()]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    a = re.sub(r"\bg a r\b", "gar", a)          # repair: spaced GAR
    a = a.replace("mac arthur", "macarthur")   # repair: split name
    a = a.replace("gar hwy", "grand army of the republic hwy")
    a = a.replace("gar highway", "grand army of the republic hwy")
    a = a.replace("massachusetts ave", "mass ave")
    toks = [DIRECTIONS.get(t, t) for t in a.split(" ")]
    if len(toks) >= 3 and toks[1] in ("route", "rte"):
        return " ".join(toks[:3])
    for i, t in enumerate(toks):
        t2 = SUFFIX_MAP.get(t, t)
        if t2 in SUFFIX_TOKENS and i >= 1:
            toks = toks[:i] + [t2]
            break
        toks[i] = t2
    return " ".join(toks)


def house_number(key: str) -> str:
    toks = key.split(" ")
    if toks and re.fullmatch(r"\d+[a-z]?", toks[0]):
        return toks[0]
    return ""


def token_sim(a: str, b: str) -> float:
    sa, sb = set(a.split(" ")), set(b.split(" "))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def geocode_query(query: str):
    q = urllib.parse.urlencode({"q": query, "format": "jsonv2",
                                "limit": 1})
    req = urllib.request.Request(
        f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        results = json.load(resp)
    if not results:
        return None
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return None
    return lat, lon


def main():
    final = read_csv(FINAL_PATH)
    stage1 = read_csv(STAGE1_PATH)

    # 1. delete the typo'd Logan patch (rule-covered already)
    before = len(final)
    final = [r for r in final
             if not (r["final_status"] == "patch_official"
                     and "logal" in r["address"].lower())]
    print(f"Logal patch rows deleted: {before - len(final)}")

    member_ids = {r["overture_id"] for r in final
                  if r["final_status"] != "patch_official"
                  and r["overture_id"]}
    donors_by_muni = {}
    for r in stage1:
        if not r.get("lat") or not r.get("lon"):
            continue
        if r.get("overture_id", "") in member_ids:
            continue
        d = {"overture_id": r.get("overture_id", ""),
             "key": address_key(r.get("address", "")),
             "lat": r["lat"], "lon": r["lon"]}
        donors_by_muni.setdefault(fold(r.get("city", "")),
                                  []).append(d)

    failed_rows = [r for r in final
                   if r.get("pin_source") == "geocode_failed"]
    print(f"rows entering the fix pass: {len(failed_rows)}")
    still_failed = []

    for r in failed_rows:
        muni = fold(r["city"])
        key = address_key(r["address"])
        num = house_number(key)

        # 2. donor retry with repaired keys
        best, best_score = None, 0.0
        for d in donors_by_muni.get(muni, []):
            dnum = house_number(d["key"])
            if num and dnum and num != dnum:
                continue
            score = token_sim(key, d["key"])
            if score > best_score:
                best, best_score = d, score
        if best is not None and best_score >= 0.5:
            r["lat"], r["lon"] = best["lat"], best["lon"]
            r["pin_source"] = "donor_fuzzy2"
            print(f"  DONOR  {r['address']}, {r['city']} "
                  f"({best['overture_id']}, sim={best_score:.2f})")
            continue

        # 3. Nominatim retry with a cleaned query
        query = QUERY_OVERRIDES.get(
            r["address"], f"{key}, {r['city']}, MA, USA")
        try:
            hit = geocode_query(query)
        except Exception as e:
            print(f"  ERROR  {r['address']}, {r['city']}: {e}")
            hit = None
        time.sleep(DELAY_SECONDS)
        if hit:
            r["lat"], r["lon"] = f"{hit[0]:.6f}", f"{hit[1]:.6f}"
            r["pin_source"] = "nominatim2"
            print(f"  GEO    {r['address']}, {r['city']}: "
                  f"{hit[0]:.5f}, {hit[1]:.5f}")
        else:
            still_failed.append(r)
            print(f"  FAIL   {r['address']}, {r['city']}")

    cols = list(final[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)

    pinned = sum(1 for r in final if r.get("lat"))
    print("\n==== fix pass ====")
    print(f"  final stops: {len(final)}")
    print(f"  stops with coordinates: {pinned} of {len(final)}")
    if still_failed:
        print("  true micro-residue:")
        for r in still_failed:
            print(f"    {r['address']}, {r['city']}")
    else:
        print("  micro-residue: none. Every stop has a pin.")


if __name__ == "__main__":
    main()
