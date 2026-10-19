"""
Stage 2 bookkeeping for the Dunkin' dataset: town reconciliation.

Reads  data/clean/dunkins_stage1.csv      (stage 1 output)
       data/clean/manual_review.csv       (Nick's decided worksheet)
       data/raw/official_directory_towns.txt  (official town counts)
Writes data/clean/town_reconciliation.csv (one row per municipality)
       data/clean/provisional_tosses.csv  (tosses grouped by town)

Rules encoded here (agreed Oct 18, 2026):
- Keeps from the worksheet are locked facts.
- Tosses are PROVISIONAL: they leave the working set for now and
  land on the verification list, to be checked town by town
  against the directory's address lists. A wrongful toss gets
  resurrected at final build time, not silently lost.
- Unreviewed queue rows return to the pool as if untouched.
- Official Boston count is adjusted by -10: Logan's 10 counters
  count once (-9) and Fenway's 2 locations count once (-1),
  per Nick's one-stop-per-destination rule.
- Town labels are folded to municipalities on both sides
  (neighborhoods and villages into parent towns, spelling and
  hyphenation variants merged).
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
STAGE1_PATH = ROOT / "data" / "clean" / "dunkins_stage1.csv"
DECIDED_PATH = ROOT / "data" / "clean" / "manual_review.csv"
OFFICIAL_PATH = ROOT / "data" / "raw" / "official_directory_towns.txt"
CLEAN_DIR = ROOT / "data" / "clean"

TARGET_ADJUSTMENTS = {"boston": -10}  # Logan -9, Fenway -1

ALIASES = {
    "marlboro": "marlborough", "foxboro": "foxborough",
    "allston": "boston", "brighton": "boston", "charlestown": "boston",
    "dorchester": "boston", "east boston": "boston",
    "hyde park": "boston", "jamaica plain": "boston",
    "mattapan": "boston", "roslindale": "boston", "roxbury": "boston",
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
    "south hamilton": "hamilton", "manchester": "manchester by the sea",
    "north attleborough": "north attleboro",
    "north dartmouth": "dartmouth", "south dartmouth": "dartmouth",
    "north easton": "easton", "south easton": "easton",
    "north chelmsford": "chelmsford", "north billerica": "billerica",
    "west concord": "concord", "bondsville": "palmer",
    "assonnet": "freetown", "east freetown": "freetown",
    "harwich port": "harwich", "north weymouth": "weymouth",
    "south weymouth": "weymouth", "east walpole": "walpole",
    "east wareham": "wareham", "auburndale": "newton",
    "newton highlands": "newton", "babson park": "wellesley",
    "whitinsville": "northbridge", "feeding hills": "agawam",
    "fiskdale": "sturbridge", "baldwinville": "templeton",
}


def fold(city) -> str:
    c = str(city or "").strip().lower().replace("-", " ")
    c = re.sub(r"\s+", " ", c)
    return ALIASES.get(c, c)


def municipality(row) -> str:
    if "fenway" in str(row["name"]).lower():
        return "boston"          # Fenway row carries no city
    return fold(row["city"])


def parse_official(path) -> dict:
    counts, pending = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.fullmatch(r"(.*?)\s*\((\d+)\)", line)
        if m and m.group(1):
            counts[fold(m.group(1))] = counts.get(fold(m.group(1)), 0) \
                + int(m.group(2))
        elif re.fullmatch(r"\(\d+\)", line) and pending is not None:
            counts[pending] = counts.get(pending, 0) \
                + int(line.strip("()"))
            pending = None
        else:
            pending = fold(line)
    return counts


def main():
    stage1 = pd.read_csv(STAGE1_PATH, dtype=str).fillna("")
    decided = pd.read_csv(DECIDED_PATH, dtype=str).fillna("")
    official = parse_official(OFFICIAL_PATH)

    rulings = {r["overture_id"]: r["decision"].strip().lower()
               for _, r in decided.iterrows()}
    notes_map = {r["overture_id"]: r["notes"]
             for _, r in decided.iterrows()}


    work = stage1[stage1["disposition"].isin(["kept", "manual_review"])]
    work = work.copy()
    work["ruling"] = [rulings.get(o, "") for o in work["overture_id"]]
    work["notes"] = [notes_map.get(o, "") for o in work["overture_id"]]
    work["town"] = [municipality(r) for _, r in work.iterrows()]

    tosses = work[work["ruling"] == "toss"]
    current = work[work["ruling"] != "toss"]

    cur_counts = current["town"].value_counts().to_dict()
    towns = sorted(set(official) | set(cur_counts))
    rows = []
    for t in towns:
        off = official.get(t, 0)
        target = off + TARGET_ADJUSTMENTS.get(t, 0)
        cur = cur_counts.get(t, 0)
        diff = cur - target
        status = "reconciled" if diff == 0 else ("over" if diff > 0
                                                 else "under")
        rows.append({"town": t, "official_count": off,
                     "target_count": target, "current_count": cur,
                     "diff": diff, "status": status})
    table = pd.DataFrame(rows)
    table["abs_diff"] = table["diff"].abs()
    table = table.sort_values(["abs_diff", "town"],
                              ascending=[False, True]).drop(
                              columns="abs_diff")

    toss_cols = ["overture_id", "original_name", "address", "city",
                 "confidence", "source_dataset", "notes", "town"]
    toss_out = tosses[toss_cols].sort_values(["town", "address"])

    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(CLEAN_DIR / "town_reconciliation.csv", index=False)
    toss_out.to_csv(CLEAN_DIR / "provisional_tosses.csv", index=False)

    sheet = work.copy()
    sheet["row_status"] = ["provisional toss" if r == "toss" else "in"
                       for r in sheet["ruling"]]
    sheet_cols = ["town", "address", "city", "original_name",
              "confidence", "source_dataset", "operating_status",
              "disposition", "ruling", "row_status"]
    sheet = sheet[sheet_cols].sort_values(["town", "address"])
    sheet["on_official_list"] = ""
    sheet["final_decision"] = ""
    sheet["check_notes"] = ""
    sheet.to_csv(CLEAN_DIR / "town_worksheets.csv", index=False)


    rec = (table["status"] == "reconciled").sum()
    over = (table["status"] == "over").sum()
    under = (table["status"] == "under").sum()
    print(f"Working set now: {len(current)} stores "
          f"({len(tosses)} provisional tosses set aside)")
    print(f"Target total:    {table['target_count'].sum()}")
    print(f"Towns: {rec} reconciled, {over} over, {under} under")
    print("\nWorst remaining overcounts:")
    worst = table[table["diff"] > 0].head(10)
    for _, r in worst.iterrows():
        print(f"  {r['town']:18s} target {r['target_count']:3d}  "
              f"current {r['current_count']:3d}  (+{r['diff']})")
    print("\nTowns still under target:")
    for _, r in table[table["diff"] < 0].iterrows():
        print(f"  {r['town']:18s} target {r['target_count']:3d}  "
              f"current {r['current_count']:3d}  ({r['diff']})")


if __name__ == "__main__":
    main()
