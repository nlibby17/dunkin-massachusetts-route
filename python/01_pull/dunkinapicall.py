"""
Pull every Dunkin' location in Massachusetts from OpenStreetMap
via the Overpass API and save the RAW result to dunkins_raw.csv.

The net is cast deliberately wide (name, brand, and operator tags)
so cleaning, not querying, decides what counts as a store.
Nothing in this script filters, dedupes, or drops rows.
"""

import time
from pathlib import Path

import pandas as pd
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:300];
area["ISO3166-2"="US-MA"]->.ma;
(
  nwr["name"~"Dunkin", i](area.ma);
  nwr["brand"~"Dunkin", i](area.ma);
  nwr["operator"~"Dunkin", i](area.ma);
  nwr["brand:wikidata"="Q847743"](area.ma);
);
out center tags;
"""

HEADERS = {"User-Agent": "dunkin-route-project/0.1 (personal practice project)"}


def fetch_elements():
    """POST the query to Overpass, retrying politely if the server is busy."""
    for attempt in range(1, 4):
        resp = requests.post(OVERPASS_URL, data={"data": QUERY},
                             headers=HEADERS, timeout=330)
        if resp.status_code == 200:
            return resp.json()["elements"]
        print(f"Attempt {attempt}: HTTP {resp.status_code}")
        print(resp.text[:300])
        if attempt < 3:
            wait = 15 * attempt
            print(f"Server busy. Waiting {wait}s and retrying...")
            time.sleep(wait)
    raise RuntimeError("Overpass did not answer after 3 attempts.")


def flatten(elements):
    rows = []
    for el in elements:
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        t = el.get("tags", {})
        rows.append({
            "osm_type": el["type"],
            "osm_id": el["id"],
            "name": t.get("name"),
            "brand": t.get("brand"),
            "operator": t.get("operator"),
            "lat": lat,
            "lon": lon,
            "housenumber": t.get("addr:housenumber"),
            "street": t.get("addr:street"),
            "city": t.get("addr:city"),
            "postcode": t.get("addr:postcode"),
        })
    return pd.DataFrame(rows)


def main():
    elements = fetch_elements()
    df = flatten(elements)

    out_path = (
        Path(__file__).resolve().parent.parent.parent
        / "data"
        / "raw"
        / "dunkins_raw.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(out_path, index=False)

    print(f"\nSaved {len(df)} raw rows to {out_path}\n")
    print("Name variants found (this is your cleaning census):")
    print(df["name"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
