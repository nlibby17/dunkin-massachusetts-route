"""
Finalize the dataset from the directory side.

dataclean3 verified stores from the Overture side. This script
flips the frame: membership comes from the official directory
(dataclean3's dunkins_final.csv), and Overture rows serve only
as coordinate donors.

For each directory patch row (a confirmed store with no pin):
  1. Twin check: if a locked keep already represents the same
     address, the patch is dropped as a duplicate of the keep.
  2. Donor match: an unused stage-1 row in the same municipality
     with the same house number and a similar street donates
     its coordinates.
  3. Otherwise the address goes to geocode_queue.csv for the
     Nominatim step.

Outputs (data/clean/):
  dunkins_final_v2.csv   the definitive stop list
  geocode_queue.csv      patch addresses still needing pins
  finalization_log.csv   every patch's disposition
"""

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final.csv"
STAGE1_PATH = ROOT / "data" / "clean" / "dunkins_stage1.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v2.csv"
GEO_PATH = ROOT / "data" / "clean" / "geocode_queue.csv"
LOG_PATH = ROOT / "data" / "clean" / "finalization_log.csv"

SUFFIX_MAP = {"street": "st", "road": "rd", "avenue": "ave",
              "boulevard": "blvd", "drive": "dr", "turnpike": "tpke",
              "highway": "hwy", "parkway": "pkwy", "square": "sq",
              "lane": "ln", "court": "ct", "place": "pl"}
SUFFIX_TOKENS = set(SUFFIX_MAP.values()) | {"cir", "way"}
ROAD_ALIASES = {"gar hwy": "grand army of the republic hwy",
                "gar highway": "grand army of the republic hwy"}
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
    for alias, full in ROAD_ALIASES.items():
        a = a.replace(alias, full)
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


def token_sim(key_a: str, key_b: str) -> float:
    a, b = set(key_a.split(" ")), set(key_b.split(" "))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    final = read_csv(FINAL_PATH)
    stage1 = read_csv(STAGE1_PATH)

    members = [r for r in final
               if r["final_status"] != "patch_official"]
    patches = [r for r in final
               if r["final_status"] == "patch_official"]
    keeps = [r for r in members if r["final_status"] == "locked_keep"]
    member_ids = {r["overture_id"] for r in members if r["overture_id"]}

    # donor pool: any stage-1 row with a pin that is not already
    # a final member (merged duplicates included; for their own
    # address they are perfectly good pin donors)
    donors = []
    for r in stage1:
        if not r.get("lat") or not r.get("lon"):
            continue
        if r.get("overture_id", "") in member_ids:
            continue
        donors.append({
            "overture_id": r.get("overture_id", ""),
            "muni": fold(r.get("city", "")),
            "key": address_key(r.get("address", "")),
            "lat": r["lat"], "lon": r["lon"],
        })
    donors_by_muni = {}
    for d in donors:
        donors_by_muni.setdefault(d["muni"], []).append(d)

    for k in keeps:
        k["muni"] = fold(k["city"])
        k["key"] = address_key(k["address"])

    out, geo_queue, log = [], [], []
    out.extend(members)
    for r in out:
        r["pin_source"] = "overture" if r.get("lat") else ""

    for p in patches:
        muni = fold(p["city"])
        key = address_key(p["address"])
        num = house_number(key)
        entry = {"address": p["address"], "city": p["city"],
                 "disposition": "", "detail": ""}

        # 1. twin of a locked keep?
        twin = None
        for k in keeps:
            if k["muni"] != muni:
                continue
            if num and house_number(k["key"]) and \
                    num != house_number(k["key"]):
                continue
            if token_sim(key, k["key"]) >= 0.5:
                twin = k
                break
        if twin is not None:
            entry["disposition"] = "dropped_twin_of_locked_keep"
            entry["detail"] = twin["overture_id"]
            log.append(entry)
            continue

        # 2. donor match?
        best, best_score = None, 0.0
        for d in donors_by_muni.get(muni, []):
            dnum = house_number(d["key"])
            if num and dnum and num != dnum:
                continue
            score = token_sim(key, d["key"])
            if score > best_score:
                best, best_score = d, score
        if best is not None and best_score >= 0.5:
            p["lat"], p["lon"] = best["lat"], best["lon"]
            p["pin_source"] = "donor_fuzzy"
            out.append(p)
            entry["disposition"] = "pin_donated"
            entry["detail"] = f"{best['overture_id']} sim={best_score:.2f}"
            log.append(entry)
            continue

        # 3. geocode queue
        p["pin_source"] = "geocode_pending"
        out.append(p)
        geo_queue.append({"address": p["address"],
                          "city": p["city"], "state": "MA"})
        entry["disposition"] = "geocode_queued"
        log.append(entry)

    cols = ["overture_id", "name", "address", "city", "postcode",
            "lat", "lon", "confidence", "source_dataset",
            "operating_status", "final_status", "pin_source"]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    with open(GEO_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["address", "city", "state"])
        w.writeheader()
        w.writerows(geo_queue)
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["address", "city",
                                          "disposition", "detail"])
        w.writeheader()
        w.writerows(log)

    from collections import Counter
    by_disp = Counter(e["disposition"] for e in log)
    print("==== finalization ====")
    for disp, n in sorted(by_disp.items()):
        print(f"  patches {disp}: {n}")
    print(f"  final stops: {len(out)}")
    print(f"  stops still needing pins (geocode queue): "
          f"{len(geo_queue)}")


if __name__ == "__main__":
    main()
