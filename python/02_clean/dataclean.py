"""
Stage 1 cleaning for the Overture Dunkin' dataset.

Reads  data/raw/overture_dunkins_raw.csv  (never modified)
Writes data/clean/dunkins_stage1.csv     (every row, with dispositions)
       data/clean/auto_actions.csv       (merges and removals, with reasons)
       data/clean/manual_review.csv      (Nick's review queue)

Design rules Oct 18, 2026:
- Low confidence doesn't remove a store, just queues it for review.
- "permanently_closed" just flags for review (BrightQuery's
  flags have been incorrect when listed as closed).
- Auto-merge only when normalized address+town match and the pins
  are within 100 m.
- Auto-remove unambiguous non-stores under the retail
  definition (distribution, HQ, offices, a pet groomer, arena).
- Everything uncertain goes to a manual queue.
- Keep store display as "Dunkin'"; original name is
  preserved in column original_name.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

QUEUE_CAP = 100          # Tedium ceiling for manual review
MERGE_RADIUS_M = 100     # proximity half of the auto-merge rule
LOW_CONF_FILL = 0.70     # tier-3 queue fill threshold

RAW_PATH = (Path(__file__).resolve().parent.parent.parent
            / "data" / "raw" / "overture_dunkins_raw.csv")
CLEAN_DIR = (Path(__file__).resolve().parent.parent.parent / "data" / "clean")

# Referee verdicts already rendered by hand. Keyed by overture_id.
KNOWN_NOTES = {
    "572b63b3-f154-4c77-950e-15a8fe7c64bc":
        "REFEREE (Nick, official Dunkin' locator, 2026-10-18): no "
        "Dunkin' at 185 Weir St, Taunton. Real location is 491 Weir "
        "St, already in the dataset. This record is a wrong-address "
        "phantom.",
    "5c080e83-819d-49d5-be7b-9b7c415836c2":
        "REFEREE (Nick, official Dunkin' locator, 2026-10-18): this "
        "is a Honey Dew Donuts store, not a Dunkin'. No Dunkin' at "
        "185 Weir St.",
}

NONSTORE_PATTERNS = [
    r"distribution", r"brands university", r"charitable trust",
    r"global headquarters", r"doggies", r"donuts center providence",
]

SUFFIX_MAP = {
    "street": "st", "road": "rd", "avenue": "ave", "boulevard": "blvd",
    "drive": "dr", "turnpike": "tpke", "highway": "hwy",
    "parkway": "pkwy", "square": "sq", "lane": "ln", "court": "ct",
    "place": "pl", "st.": "st", "rd.": "rd", "ave.": "ave",
}
# Business names glued onto the end of addresses in this dataset.
# Stripped from the matching KEY only, never from the display text.
KEY_SUFFIX_JUNK = [
    "hamilton crossing plaza", "wrentham village outlets",
    "the corner store mart", "gulf", "shell",
]
ROAD_ALIASES = {"gar hwy": "grand army of the republic hwy"}
CITY_ALIASES = {"south hamilton": "hamilton"}  # village of Hamilton
SOURCE_PRIORITY = {"meta": 0, "Microsoft": 1, "BrightQuery": 2,
                   "Foursquare": 3, "AllThePlaces": 4}


def norm_address(addr: str) -> str:
    """Build the matching key for an address: house number + street."""
    if not isinstance(addr, str) or not addr.strip():
        return ""
    a = addr.lower().strip()
    a = re.sub(r"#.*$", "", a)                       # unit numbers
    a = re.sub(r"\b(suite|ste|unit|apt)\b.*$", "", a)
    a = re.sub(r"[.,]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    for junk in KEY_SUFFIX_JUNK:
        if a.endswith(junk):
            a = a[: -len(junk)].strip()
    toks = a.split(" ")
    if toks and toks[-1] in SUFFIX_MAP:
        toks[-1] = SUFFIX_MAP[toks[-1]]
    a = " ".join(toks)
    for alias, full in ROAD_ALIASES.items():
        a = a.replace(alias, full)
    return a


def norm_city(city: str) -> str:
    if not isinstance(city, str):
        return ""
    c = re.sub(r"\s+", " ", city.strip().lower())
    return CITY_ALIASES.get(c, c)


def clean_postcode(pc) -> str:
    if not isinstance(pc, str) or not pc.strip():
        return ""
    pc = pc.strip()
    m = re.fullmatch(r"(\d{5})-\d{4}", pc)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{4}", pc):
        return "0" + pc               # leading zero eaten upstream
    return pc


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main():
    df = pd.read_csv(RAW_PATH, dtype=str).fillna("")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    n_start = len(df)

    # ---- standardization (new columns; raw columns untouched) ----
    df["original_name"] = df["name"]
    df["name_display"] = "Dunkin'"
    df["city_clean"] = df["city"].str.strip().str.title()
    df["postcode_clean"] = df["postcode"].map(clean_postcode)
    df["address_key"] = [norm_address(a) for a in df["address"]]
    df["city_key"] = [norm_city(c) for c in df["city"]]
    df["disposition"] = "kept"
    df["merged_into"] = ""
    df["flags"] = ""

    actions = []   # (overture_id, action, reason)

    # ---- step 1: auto-remove unambiguous non-stores ----
    for i, row in df.iterrows():
        name_l = row["name"].lower()
        hit = next((p for p in NONSTORE_PATTERNS
                    if re.search(p, name_l)), None)
        if hit:
            df.at[i, "disposition"] = "auto_removed"
            actions.append((row["overture_id"], "removed",
                            f"non-store name pattern: {hit}"))

    alive = df[df["disposition"] == "kept"].index.tolist()

    # ---- step 2: auto-merge same address+town within radius ----
    uf = UnionFind(len(df))
    pos = {idx: k for k, idx in enumerate(df.index)}
    keyed = {}
    for i in alive:
        if df.at[i, "address_key"]:
            keyed.setdefault(
                (df.at[i, "address_key"], df.at[i, "city_key"]),
                []).append(i)
    far_groups = []
    for members in keyed.values():
        if len(members) < 2:
            continue
        merged_any = False
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                d = haversine_m(df.at[i, "lat"], df.at[i, "lon"],
                                df.at[j, "lat"], df.at[j, "lon"])
                if d <= MERGE_RADIUS_M:
                    uf.union(pos[i], pos[j])
                    merged_any = True
        if not merged_any:
            far_groups.append(members)

    clusters = {}
    for i in alive:
        clusters.setdefault(uf.find(pos[i]), []).append(i)
    closed_conflict = set()
    for members in clusters.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda i: (
            -df.at[i, "confidence"],
            0 if df.at[i, "operating_status"] == "open" else 1,
            SOURCE_PRIORITY.get(df.at[i, "source_dataset"], 9)))
        survivor = members[0]
        if any(df.at[m, "operating_status"] == "permanently_closed"
               for m in members):
            closed_conflict.add(survivor)
        for loser in members[1:]:
            df.at[loser, "disposition"] = "auto_merged"
            df.at[loser, "merged_into"] = df.at[survivor, "overture_id"]
            actions.append((df.at[loser, "overture_id"],
                            f"merged into {df.at[survivor, 'overture_id']}",
                            "same normalized address+town, pins "
                            f"within {MERGE_RADIUS_M} m"))

    alive = [i for i in alive if df.at[i, "disposition"] == "kept"]

    # ---- step 3: build the manual review queue ----
    reasons = {}   # index -> list of reason strings
    tiers = {}     # index -> tier (1 = structural, 2 = data casualty)

    def flag(i, tier, reason):
        reasons.setdefault(i, []).append(reason)
        tiers[i] = min(tiers.get(i, 9), tier)

    for members in far_groups:
        for i in members:
            if df.at[i, "disposition"] == "kept":
                flag(i, 1, "same address+town as another record but "
                           "pins far apart (bad pin or two stores)")

    # close neighbors with different keys: possible dupes or real pairs
    if alive:
        lat_r = np.radians(df.loc[alive, "lat"].to_numpy())
        lon_r = np.radians(df.loc[alive, "lon"].to_numpy())
        dp = lat_r[None, :] - lat_r[:, None]
        dl = lon_r[None, :] - lon_r[:, None]
        a = (np.sin(dp / 2) ** 2
             + np.cos(lat_r[:, None]) * np.cos(lat_r[None, :])
             * np.sin(dl / 2) ** 2)
        dist = 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        ii, jj = np.where(np.triu(dist <= MERGE_RADIUS_M, k=1))
        for x, y in zip(ii, jj):
            d = dist[x, y]
            flag(alive[x], 1, f"store {d:.0f} m away with a different "
                          "address (dupe or genuine neighbor)")
            flag(alive[y], 1, f"store {d:.0f} m away with a different "
                          "address (dupe or genuine neighbor)")


    for i in alive:
        row = df.loc[i]
        if row["operating_status"] == "permanently_closed":
            flag(i, 1, "flagged permanently_closed (single-source "
                       "flag; verify before removing)")
        if i in closed_conflict:
            flag(i, 1, "merged record whose sources disagreed on "
                       "open vs permanently_closed")
        if row["address"].strip() == "":
            flag(i, 2, "address missing")
        elif re.fullmatch(r"\d+", row["address"].strip()):
            flag(i, 2, "address is a bare number (street name lost)")
        if re.search(r"dba|\binc\b|\bllc\b|group|partners",
                     row["name"], re.I):
            flag(i, 2, "franchisee/entity name; sole listing check")
        if row["basic_category"] in ("sport_field", "financial_service",
                                     "animal_or_pet_service",
                                     "college_university",
                                     "corporate_or_business_office"):
            flag(i, 1, f"suspicious category: {row['basic_category']}")
        if row["overture_id"] in KNOWN_NOTES:
            flag(i, 1, "referee verdict on file (see known_note)")

    queue_idx = sorted(reasons, key=lambda i: (tiers[i],
                                              df.at[i, "confidence"]))

    # tier 3: fill remaining budget with lowest-confidence singletons
    if len(queue_idx) < QUEUE_CAP:
        rest = [i for i in alive
                if i not in reasons and df.at[i, "confidence"] < LOW_CONF_FILL]
        rest.sort(key=lambda i: df.at[i, "confidence"])
        for i in rest:
            if len(queue_idx) >= QUEUE_CAP:
                break
            reasons[i] = [f"low confidence ({df.at[i, 'confidence']:.2f}) "
                          "singleton spot-check"]
            tiers[i] = 3
            queue_idx.append(i)

    for i in queue_idx:
        df.at[i, "disposition"] = "manual_review"
        df.at[i, "flags"] = "; ".join(reasons[i])

    queue = df.loc[queue_idx].copy()
    queue["review_reasons"] = ["; ".join(reasons[i]) for i in queue_idx]
    queue["known_note"] = [KNOWN_NOTES.get(o, "") for o in queue["overture_id"]]
    queue["locator_query"] = [
        (f"{a}, {c}, MA" if str(a).strip() else f"Dunkin' {c} MA")
        for a, c in zip(queue["address"], queue["city_clean"])]
    queue["decision"] = ""
    queue["notes"] = ""
    queue_cols = ["overture_id", "original_name", "name_display",
                  "address", "city_clean", "postcode_clean", "lat",
                  "lon", "confidence", "operating_status",
                  "basic_category", "source_dataset", "review_reasons",
                  "known_note", "locator_query", "decision", "notes"]

    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN_DIR / "dunkins_stage1.csv", index=False)
    pd.DataFrame(actions, columns=["overture_id", "action", "reason"]).to_csv(
        CLEAN_DIR / "auto_actions.csv", index=False)
    queue[queue_cols].to_csv(CLEAN_DIR / "manual_review.csv", index=False)

    kept = (df["disposition"] == "kept").sum()
    merged = (df["disposition"] == "auto_merged").sum()
    removed = (df["disposition"] == "auto_removed").sum()
    print(f"Input rows:            {n_start}")
    print(f"Auto-removed (non-store): {removed}")
    print(f"Auto-merged (dupes):      {merged}")
    print(f"Manual review queue:      {len(queue)}")
    print(f"Clean kept outright:      {kept}")
    print(f"Stores after stage 1 (kept + queue): {kept + len(queue)}")


if __name__ == "__main__":
    main()
