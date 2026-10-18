"""
Reconcile the working set against the official directory scrape
and produce the final dataset.

Inputs:
  data/clean/dunkins_stage1.csv   (stage 1 output; still carries
                                   its auto-action rows, flagged in
                                   the disposition column)
  data/clean/manual_review.csv    (the DECIDED queue: keeps locked,
                                   tosses provisional)
  data/raw/official_addresses.csv (the directory scrape)

Outputs (data/clean/):
  dunkins_final.csv   matched working rows (pins intact), locked
                      keeps, rule matches, resurrected tosses, and
                      directory patch rows (pins blank, flagged)
  residue_queue.csv   working rows matching nothing official:
                      phantom suspects for a keep/toss ruling
  patch_rows.csv      the directory-only addresses added as
                      patches, listed for review and veto

Matching is 1:1 per (municipality, address key). Both sides run
through the SAME key function: directionals expanded, the Mass Ave
alias applied, and every key cut off after its street suffix so
venue names and plaza tails cannot break a match. Logan, Fenway,
and TD Garden are consumed by the one-stop-per-destination rule
before matching begins, each collapsing to a single stop.
"""

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE1_PATH = ROOT / "data" / "clean" / "dunkins_stage1.csv"
DECIDED_PATH = ROOT / "data" / "clean" / "manual_review.csv"
OFFICIAL_PATH = ROOT / "data" / "raw" / "official_addresses.csv"
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final.csv"
RESIDUE_PATH = ROOT / "data" / "clean" / "residue_queue.csv"
PATCH_PATH = ROOT / "data" / "clean" / "patch_rows.csv"

# ---------- shared normalization (BOTH sides, identical) ----------
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
    # numbered route: keep "111 route 6a" whole
    if len(toks) >= 3 and toks[1] in ("route", "rte"):
        return " ".join(toks[:3])
    # cut everything after the first street suffix token
    for i, t in enumerate(toks):
        t2 = SUFFIX_MAP.get(t, t)
        if t2 in SUFFIX_TOKENS and i >= 1:
            toks = toks[:i] + [t2]
            break
        toks[i] = t2
    return " ".join(toks)


def is_logan(street: str) -> bool:
    s = (street or "").lower()
    return "logan" in s or "harborside" in s


# ---------- load ----------
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pick(row, *names, default=""):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return default


def main():
    stage1 = read_csv(STAGE1_PATH)
    decided = read_csv(DECIDED_PATH)
    official = read_csv(OFFICIAL_PATH)

    toss_ids = {r["overture_id"] for r in decided
                if r.get("decision", "").strip().lower() == "toss"}
    keep_ids = {r["overture_id"] for r in decided
                if r.get("decision", "").strip().lower() == "keep"}

    working, toss_pool = [], []
    for r in stage1:
        # the stage-1 file still carries its auto-action rows,
        # flagged in disposition; they stay out of every pool
        if r.get("disposition", "") in ("auto_removed", "auto_merged"):
            continue
        row = {
            "overture_id": r.get("overture_id", ""),
            "name": pick(r, "name"),
            "address": pick(r, "address"),
            "city": pick(r, "city"),
            "postcode": pick(r, "postcode"),
            "lat": pick(r, "lat"), "lon": pick(r, "lon"),
            "confidence": pick(r, "confidence"),
            "source_dataset": pick(r, "source_dataset", "source"),
            "operating_status": pick(r, "operating_status"),
        }
        name_l = row["name"].lower()
        if "fenway" in name_l:
            row["muni"] = "boston"
        else:
            row["muni"] = fold(row["city"])
        row["key"] = address_key(row["address"])
        row["joinkey"] = row["muni"] + "|" + row["key"]
        row["is_logan"] = is_logan(row["address"]) or "logan" in name_l
        row["is_fenway"] = "fenway" in name_l
        if row["overture_id"] in toss_ids:
            toss_pool.append(row)
        else:
            working.append(row)

    off_rows = []
    logan_off, fenway_off, garden_off = [], [], []
    for r in official:
        city = r["city_line"].split(",")[0] if "," in r["city_line"] \
            else r["town"]
        o = {"town": r["town"], "street": r["street_address"],
             "muni": fold(city), "key": address_key(r["street_address"]),
             "page_url": r["page_url"]}
        o["joinkey"] = o["muni"] + "|" + o["key"]
        if is_logan(o["street"]):
            logan_off.append(o)
        elif "jersey" in o["street"].lower() and o["muni"] == "boston":
            fenway_off.append(o)
        elif "legends" in o["street"].lower() or \
                "fleet center" in o["street"].lower():
            garden_off.append(o)
        else:
            off_rows.append(o)

    final, residue, patches = [], [], []

    # ---- rule matches: one stop per destination ----
    logan_work = [r for r in working if r["is_logan"]]
    if logan_work:
        # the locked keep survives if present, else the highest
        # confidence airport row; the rest are reported in the
        # residue, not silently dropped
        logan_work.sort(key=lambda r: (
            0 if r["overture_id"] in keep_ids else 1,
            -float(r["confidence"] or 0)))
        survivor = logan_work[0]
        survivor["final_status"] = "rule_match_logan"
        final.append(survivor)
        for r in logan_work[1:]:
            residue.append({
                "overture_id": r["overture_id"], "name": r["name"],
                "address": r["address"], "city": r["city"],
                "confidence": r["confidence"],
                "source_dataset": r["source_dataset"],
                "status": "collapsed_logan",
                "possible_official_address": "",
                "decision": "", "notes": "Logan collapse: one stop",
            })
    working = [r for r in working if not r["is_logan"]]

    fenway_work = [r for r in working if r["is_fenway"]]
    for r in fenway_work:
        r["address"] = "4 Jersey Street"      # documented patch
        r["city"] = "Boston"
        r["final_status"] = "rule_match_fenway"
        final.append(r)
    working = [r for r in working if not r["is_fenway"]]

    garden_work = [r for r in working
                   if "legends" in r["address"].lower()]
    if garden_work:
        garden_work.sort(key=lambda r: -float(r["confidence"] or 0))
        gw = garden_work[0]
        gw["final_status"] = "rule_match_td_garden"
        final.append(gw)
        for r in garden_work[1:]:
            residue.append({
                "overture_id": r["overture_id"], "name": r["name"],
                "address": r["address"], "city": r["city"],
                "confidence": r["confidence"],
                "source_dataset": r["source_dataset"],
                "status": "collapsed_td_garden",
                "possible_official_address": "",
                "decision": "",
                "notes": "TD Garden collapse: one stop",
            })
    working = [r for r in working
               if "legends" not in r["address"].lower()]

    print(f"rule matches: Logan 1 stop from {len(logan_work)} row(s) "
          f"for {len(logan_off)} listings; Fenway "
          f"{len(fenway_work)} row(s) for {len(fenway_off)} listings; "
          f"TD Garden 1 stop from {len(garden_work)} row(s) for "
          f"{len(garden_off)} listings")

    # ---- exact 1:1 matching against official demand ----
    demand = Counter(o["joinkey"] for o in off_rows)
    matched, unmatched_work = 0, []
    for r in working:
        if demand.get(r["joinkey"], 0) > 0:
            demand[r["joinkey"]] -= 1
            r["final_status"] = "verified_match"
            final.append(r)
            matched += 1
        else:
            unmatched_work.append(r)
    print(f"verified exact matches: {matched}")

    # ---- resurrection: unmet demand checks the toss pool ----
    resurrected = 0
    for r in toss_pool:
        if r["is_logan"] or r["is_fenway"]:
            continue  # rule-covered; stays tossed
        if demand.get(r["joinkey"], 0) > 0:
            demand[r["joinkey"]] -= 1
            r["final_status"] = "resurrected_from_toss"
            final.append(r)
            resurrected += 1
    print(f"resurrected from provisional tosses: {resurrected}")

    # ---- patches: still-unmet official addresses ----
    seen = Counter()
    for o in off_rows:
        if demand[o["joinkey"]] > 0 and \
                seen[o["joinkey"]] < demand[o["joinkey"]]:
            seen[o["joinkey"]] += 1
            patches.append(o)
    print(f"directory-only addresses becoming patches: {len(patches)}")
    for o in patches:
        final.append({
            "overture_id": "", "name": "Dunkin'",
            "address": o["street"], "city": o["town"],
            "postcode": "", "lat": "", "lon": "",
            "confidence": "", "source_dataset": "official_directory",
            "operating_status": "",
            "final_status": "patch_official",
        })

    # ---- residue: unmatched working rows, with near-miss hints ----
    off_by_muni_street = defaultdict(list)
    for o in off_rows:
        toks = o["key"].split(" ")
        if len(toks) >= 2:
            off_by_muni_street[(o["muni"], " ".join(toks[1:]))].append(o)
    for r in unmatched_work:
        toks = r["key"].split(" ")
        hint = ""
        if len(toks) >= 2:
            near = off_by_muni_street.get(
                (r["muni"], " ".join(toks[1:])), [])
            hint = "; ".join(o["street"] for o in near[:3])
        residue.append({
            "overture_id": r["overture_id"], "name": r["name"],
            "address": r["address"], "city": r["city"],
            "confidence": r["confidence"],
            "source_dataset": r["source_dataset"],
            "status": "locked_keep" if r["overture_id"] in keep_ids
                      else "unmatched",
            "possible_official_address": hint,
            "decision": "", "notes": "",
        })
        if r["overture_id"] in keep_ids:
            r["final_status"] = "locked_keep"
            final.append(r)
    print(f"residue queue rows: {len(residue)} "
          f"(locked keeps among them stay in the final set)")

    # ---- write outputs ----
    final_cols = ["overture_id", "name", "address", "city",
                  "postcode", "lat", "lon", "confidence",
                  "source_dataset", "operating_status", "final_status"]
    with open(FINAL_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=final_cols,
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(final)
    with open(RESIDUE_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(residue[0].keys()))
        w.writeheader()
        w.writerows(residue)
    with open(PATCH_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["town", "street_address",
                                          "city_line", "page_url"])
        w.writeheader()
        for o in patches:
            w.writerow({"town": o["town"],
                        "street_address": o["street"],
                        "city_line": "", "page_url": o["page_url"]})

    by_status = Counter(r["final_status"] for r in final)
    print("\n==== final dataset ====")
    for status, n in sorted(by_status.items()):
        print(f"  {status}: {n}")
    print(f"  TOTAL: {len(final)}")
    need_pins = sum(1 for r in final
                    if r["final_status"] == "patch_official")
    print(f"  patch rows needing coordinates: {need_pins}")


if __name__ == "__main__":
    main()
