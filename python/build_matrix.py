"""
Build the full OSRM distance/duration matrices for all stops.

Requires osrm-routed serving on localhost:5000 (MLD,
--max-table-size 5000).

Reads  data/clean/dunkins_final_v8.csv
Writes data/clean/distance_matrix.npy (meters)
       data/clean/duration_matrix.npy (seconds)
       data/clean/matrix_index.csv (row index -> stop)

OSRM returns null for pairs it cannot route; the script counts
them and names any stop that has them.
"""

import csv
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
FINAL_PATH = ROOT / "data" / "clean" / "dunkins_final_v8.csv"
DIST_PATH = ROOT / "data" / "clean" / "distance_matrix.npy"
DUR_PATH = ROOT / "data" / "clean" / "duration_matrix.npy"
INDEX_PATH = ROOT / "data" / "clean" / "matrix_index.csv"
BASE = "http://localhost:5000/table/v1/driving/"


def to_array(raw):
    return np.array(
        [[np.nan if v is None else float(v) for v in row]
         for row in raw], dtype=float)


def main():
    with open(FINAL_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    coords = ";".join(f"{r['lon']},{r['lat']}" for r in rows)
    url = BASE + coords + "?annotations=distance,duration"
    print(f"requesting a {len(rows)} x {len(rows)} table "
          f"from OSRM (this is the one real wait)...")
    resp = requests.get(url, timeout=1800)
    data = resp.json()
    if data.get("code") != "Ok":
        print("OSRM said:", data.get("code"), data.get("message"))
        return

    raw_d = data["distances"]
    null_rows = {}
    total_nulls = 0
    for i, rowvals in enumerate(raw_d):
        n = sum(1 for v in rowvals if v is None)
        if n:
            null_rows[i] = n
            total_nulls += n

    dist = to_array(raw_d)
    dur = to_array(data["durations"])
    np.save(DIST_PATH, dist)
    np.save(DUR_PATH, dur)
    with open(INDEX_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "address", "city", "lat", "lon"])
        for i, r in enumerate(rows):
            w.writerow([i, r["address"], r["city"],
                        r["lat"], r["lon"]])

    print(f"distance matrix: {dist.shape}")
    print(f"duration matrix: {dur.shape}")
    print(f"unreachable pairs (null): {total_nulls}")
    if null_rows:
        print("stops with unreachable pairs (worst first):")
        for i, n in sorted(null_rows.items(),
                           key=lambda kv: -kv[1])[:15]:
            r = rows[i]
            print(f"  idx {i}: {n} nulls  "
                  f"{r['address']}, {r['city']}")
    finite = dist[np.isfinite(dist)]
    print(f"longest single leg in the state: "
          f"{finite.max() / 1000:.0f} km")
    print("matrices and index saved to data/clean/")


if __name__ == "__main__":
    main()
