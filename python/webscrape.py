"""
Scrape the official Dunkin' directory's Massachusetts town pages.

The town pages load their location cards with JavaScript, so this
drives a real browser (Playwright) and reads the rendered cards.

Reads  data/raw/official_directory_towns.txt (town names + counts)
Writes data/raw/official_addresses.csv (one row per location)

Self-auditing: the expected count for every town comes from the
same directory list, and any town whose scraped count disagrees
is reported at the end instead of failing silently. Re-running
skips towns already present in the output (checkpoint/resume).

Set TEST_TOWN to a town name to scrape only that town (probe
mode). Set it to "" for the full pass.
"""

import csv
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

TEST_TOWN = ""          # probe first; "" for the full run
BASE = "https://www.dunkindonuts.com/locations/us/ma/{slug}/"
DELAY_SECONDS = 0.75           # politeness pause between pages

ROOT = Path(__file__).resolve().parent.parent
TOWNS_PATH = ROOT / "data" / "raw" / "official_directory_towns.txt"
OUT_PATH = ROOT / "data" / "raw" / "official_addresses.csv"

CITY_LINE = re.compile(r"^.+,\s*MA$")


def parse_towns(path):
    towns, pending = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.fullmatch(r"(.*?)\s*\((\d+)\)", line)
        if m and m.group(1):
            towns[m.group(1)] = int(m.group(2))
        elif re.fullmatch(r"\(\d+\)", line) and pending is not None:
            towns[pending] = int(line.strip("()"))
            pending = None
        else:
            pending = line
    return towns


def slugify(town: str) -> str:
    s = town.lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_card(text: str):
    """Card text lines: street, 'City, MA', hours, amenities..."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if CITY_LINE.match(ln) and i > 0:
            return lines[i - 1], ln
    return None, None


def main():
    towns = parse_towns(TOWNS_PATH)
    if TEST_TOWN:
        towns = {t: c for t, c in towns.items()
                 if t.lower() == TEST_TOWN.lower()}
        if not towns:
            raise SystemExit(f"TEST_TOWN {TEST_TOWN!r} not in list")

    done = set()
    if OUT_PATH.exists() and not TEST_TOWN:
        with open(OUT_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["town"])

    new_file = not OUT_PATH.exists() or bool(TEST_TOWN)
    mode = "w" if new_file else "a"
    mismatches, failures = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        with open(OUT_PATH, mode, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["town", "street_address", "city_line",
                            "page_url"])
            for town, expected in towns.items():
                if town in done:
                    print(f"skip {town} (already scraped)")
                    continue
                slug = slugify(town)
                url = BASE.format(slug=slug)
                try:
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=30000)
                    page.wait_for_selector("location-card",
                                           timeout=15000)
                    page.wait_for_timeout(750)
                    texts = page.locator(
                        "location-card").all_inner_texts()
                except Exception as e:
                    failures.append((town, f"load failed: {e}"))
                    continue
                found = 0
                for text in texts:
                    street, city_line = parse_card(text)
                    if street is None:
                        continue
                    w.writerow([town, street, city_line, url])
                    found += 1
                f.flush()
                status = "ok" if found == expected else "MISMATCH"
                print(f"{town}: scraped {found}, expected "
                      f"{expected} [{status}]")
                if found != expected:
                    mismatches.append((town, expected, found))
                time.sleep(DELAY_SECONDS)
        browser.close()

    print("\n==== summary ====")
    if failures:
        print("FAILED towns (check slugs by hand):")
        for town, why in failures:
            print(f"  {town}: {why}")
    if mismatches:
        print("COUNT MISMATCHES (scraped vs directory count):")
        for town, exp, got in mismatches:
            print(f"  {town}: expected {exp}, scraped {got}")
    if not failures and not mismatches:
        print("Every town scraped clean and counts agree.")


if __name__ == "__main__":
    main()
