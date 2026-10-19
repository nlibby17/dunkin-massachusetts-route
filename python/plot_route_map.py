"""
Draw the true road map of the solved tour.

Requires osrm-routed serving on localhost:5000.

Reads  data/clean/route_order.csv
       data/clean/duration_matrix.npy (for the title's hours)
Writes data/clean/route_geometry.geojson (the stitched path)
       data/clean/route_map.png

Each leg's fastest road geometry comes from the same engine
that produced the distance matrix, so the drawn path is the
path the numbers describe.
"""

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
ORDER_PATH = ROOT / "data" / "clean" / "route_order.csv"
DUR_PATH = ROOT / "data" / "clean" / "duration_matrix.npy"
GEO_PATH = ROOT / "data" / "clean" / "route_geometry.geojson"
MAP_PATH = ROOT / "data" / "clean" / "route_map.png"
BASE = "http://localhost:5000/route/v1/driving/"


def main():
    with open(ORDER_PATH, newline="", encoding="utf-8") as f:
        order = list(csv.DictReader(f))
    dur = np.load(DUR_PATH)
    n = len(order)
    total_mi = float(order[-1]["cumulative_miles"])
    idxs = [int(r["idx"]) for r in order]
    total_h = sum(dur[idxs[k], idxs[(k + 1) % n]]
                  for k in range(n)) / 3600

    path = []
    failures = []
    for k in range(n):
        a = order[k]
        b = order[(k + 1) % n]
        url = (f"{BASE}{a['lon']},{a['lat']};"
               f"{b['lon']},{b['lat']}"
               f"?overview=full&geometries=geojson")
        try:
            data = requests.get(url, timeout=60).json()
            coords = data["routes"][0]["geometry"]["coordinates"]
        except Exception:
            failures.append((a["address"], b["address"]))
            coords = [[float(a["lon"]), float(a["lat"])],
                      [float(b["lon"]), float(b["lat"])]]
        if path and coords and coords[0] == path[-1]:
            coords = coords[1:]
        path.extend(coords)
        if (k + 1) % 200 == 0:
            print(f"  {k + 1}/{n} legs fetched")
    print(f"legs: {n}, failures: {len(failures)}")
    for a, b in failures[:10]:
        print(f"  FAILED {a} -> {b}")

    geo = {"type": "FeatureCollection",
           "features": [{"type": "Feature",
                         "geometry": {"type": "LineString",
                                      "coordinates": path},
                         "properties": {"stops": n,
                                        "miles": total_mi}}]}
    with open(GEO_PATH, "w", encoding="utf-8") as f:
        json.dump(geo, f)

    lons = [float(r["lon"]) for r in order]
    lats = [float(r["lat"]) for r in order]
    xs = [c[0] for c in path]
    ys = [c[1] for c in path]
    plt.figure(figsize=(14, 10))
    plt.plot(xs, ys, linewidth=0.6, color="#1f4e79", alpha=0.9)
    plt.scatter(lons, lats, s=3, color="#d62728", zorder=5)
    plt.scatter([lons[0]], [lats[0]], s=180, marker="*",
                color="gold", edgecolors="black", zorder=6)
    plt.gca().set_aspect(1.35)
    plt.title(f"Every Dunkin' in Massachusetts: {n} stops, "
              f"{total_mi:,.0f} miles, {total_h:,.1f} driving hours")
    plt.savefig(MAP_PATH, dpi=200, bbox_inches="tight")
    print(f"wrote {GEO_PATH.name} ({len(path):,} path points) "
          f"and {MAP_PATH.name}")


if __name__ == "__main__":
    main()
