"""
Basemap builder: town boundaries + tiered road network for
the video backdrop, with level-of-detail test frames.

Downloads (once, cached under data/raw/basemap/):
  Census TIGER town (county subdivision) boundaries for MA
  Census TIGER road files for the 12 mainland counties
  (island counties excluded, same as the dataset definition)

Writes data/clean/basemap_roads.npz (segment arrays by tier)
       data/clean/basemap_towns.npz (boundary segments + the
       town polygon fills that paint the land)
       data/clean/basemaps/test_state.png
       data/clean/basemaps/test_metro.png
       data/clean/basemaps/test_dense.png
       data/clean/basemaps/test_rural.png

The land is filled soft green (#6FC276) from the town
polygons; outside the state stays cream paper.

Road tiers by TIGER MTFCC class:
  T1  S1100  interstates and limited-access highways
  T2  S1200  primary and secondary highways
  T3  S1400  local roads
  T4  the rest (service drives, ramps, alleys)
Zoom rule (by window width in degrees of longitude):
  > 1.5 T1 | 0.3-1.5 T1+T2 | 0.2-0.3 T1+T2+T3 | < 0.2 all
"""

import zipfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
import shapefile
from matplotlib.collections import LineCollection

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw" / "basemap"
CLEAN = ROOT / "data" / "clean"
TEST_DIR = CLEAN / "basemap_tests"
FINAL_PATH = CLEAN / "dunkins_final_v8.csv"
ROADS_NPZ = CLEAN / "basemap_roads.npz"
TOWNS_NPZ = CLEAN / "basemap_towns.npz"

BASE = "https://www2.census.gov/geo/tiger/TIGER2024"
COUSUB_URL = ("https://www2.census.gov/geo/tiger/GENZ2024/shp/"
              "cb_2024_25_cousub_500k.zip")
COUNTIES = ["25001", "25003", "25005", "25009", "25011",
            "25013", "25015", "25017", "25021", "25023",
            "25025", "25027"]  # mainland only, islands excluded
TIER_OF = {"S1100": "t1", "S1200": "t2", "S1400": "t3"}
LAND_GREEN = "#6FC276"
PAPER = "#fff8f0"


def fetch(url, dest):
    if dest.exists():
        return dest
    print(f"downloading {dest.name}...")
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def shape_segments(reader, keep=None):
    """All line segments of all shapes as an (N, 2, 2) array."""
    segs = []
    for sr in reader.iterShapeRecords():
        if keep is not None and not keep(sr.record):
            continue
        pts = sr.shape.points
        parts = list(sr.shape.parts) + [len(pts)]
        for p in range(len(parts) - 1):
            ring = pts[parts[p]:parts[p + 1]]
            for i in range(len(ring) - 1):
                segs.append((ring[i], ring[i + 1]))
    return np.array(segs, dtype=np.float32)


def build_towns():
    """Returns (boundary segments, fill points, fill starts)."""
    if TOWNS_NPZ.exists():
        d = np.load(TOWNS_NPZ)
        if "fills_pts" in d:
            return d["towns"], d["fills_pts"], d["fills_starts"]
    RAW.mkdir(parents=True, exist_ok=True)
    z = fetch(COUSUB_URL, RAW / "cb_2024_25_cousub_500k.zip")
    shp = RAW / "cousub" / "cb_2024_25_cousub_500k.shp"

    if not shp.exists():
        with zipfile.ZipFile(z) as zf:
            zf.extractall(RAW / "cousub")
    reader = shapefile.Reader(str(shp))
    fields = [f[0] for f in reader.fields]
    ci = fields.index("COUNTYFP") - 1
    ni = fields.index("NAME") - 1
    island_towns = {"Aquinnah", "Chilmark", "Edgartown",
                    "Gosnold", "Oak Bluffs", "Tisbury",
                    "West Tisbury", "Nantucket"}

    def mainland(rec):
        return (rec[ci] not in ("25007", "25019")
                and rec[ni] not in island_towns)


    segs = shape_segments(reader, keep=mainland)
    reader = shapefile.Reader(str(shp))
    fill_pts, fill_starts = [], []
    for sr in reader.iterShapeRecords():
        if not mainland(sr.record):
            continue
        pts = sr.shape.points
        parts = list(sr.shape.parts) + [len(pts)]
        for p in range(len(parts) - 1):
            ring = pts[parts[p]:parts[p + 1]]
            if len(ring) >= 3:
                fill_starts.append(len(fill_pts))
                fill_pts.extend(ring)
    fills_pts = np.array(fill_pts, dtype=np.float32)
    fills_starts = np.array(fill_starts, dtype=np.int64)
    np.savez_compressed(TOWNS_NPZ, towns=segs, fills_pts=fills_pts,
                        fills_starts=fills_starts)
    print(f"town boundary segments: {len(segs):,}, "
          f"fill rings: {len(fills_starts):,}")
    return segs, fills_pts, fills_starts


def build_roads():
    if ROADS_NPZ.exists():
        d = np.load(ROADS_NPZ)
        return {k: d[k] for k in d.files}
    RAW.mkdir(parents=True, exist_ok=True)
    tiers = {"t1": [], "t2": [], "t3": [], "t4": []}
    for fips in COUNTIES:
        z = fetch(f"{BASE}/ROADS/tl_2024_{fips}_roads.zip",
                  RAW / f"tl_2024_{fips}_roads.zip")
        out = RAW / f"roads_{fips}"
        with zipfile.ZipFile(z) as zf:
            zf.extractall(out)
        reader = shapefile.Reader(
            str(out / f"tl_2024_{fips}_roads.shp"))
        fields = [f[0] for f in reader.fields]
        mi = fields.index("MTFCC") - 1
        by_tier = {"t1": [], "t2": [], "t3": [], "t4": []}
        for sr in reader.iterShapeRecords():
            tier = TIER_OF.get(sr.record[mi], "t4")
            pts = sr.shape.points
            parts = list(sr.shape.parts) + [len(pts)]
            for p in range(len(parts) - 1):
                ring = pts[parts[p]:parts[p + 1]]
                for i in range(len(ring) - 1):
                    by_tier[tier].append((ring[i], ring[i + 1]))
        for k in tiers:
            tiers[k].extend(by_tier[k])
        print(f"  county {fips} done")
    out = {k: np.array(v, dtype=np.float32) for k, v in tiers.items()}
    np.savez_compressed(ROADS_NPZ, **out)
    for k, v in out.items():
        print(f"tier {k}: {len(v):,} segments")
    return out


def visible(segs, xlim, ylim, pad=0.05):
    if len(segs) == 0:
        return segs
    mid = segs.mean(axis=1)
    m = ((mid[:, 0] >= xlim[0] - pad) & (mid[:, 0] <= xlim[1] + pad)
         & (mid[:, 1] >= ylim[0] - pad)
         & (mid[:, 1] <= ylim[1] + pad))
    return segs[m]


def draw_fills(ax, fills_pts, fills_starts, xlim, ylim):
    starts = list(fills_starts) + [len(fills_pts)]
    for s in range(len(starts) - 1):
        ring = fills_pts[starts[s]:starts[s + 1]]
        if len(ring) < 3:
            continue
        if (ring[:, 0].max() < xlim[0] or ring[:, 0].min() > xlim[1]
                or ring[:, 1].max() < ylim[0]
                or ring[:, 1].min() > ylim[1]):
            continue
        ax.fill(ring[:, 0], ring[:, 1], color=LAND_GREEN,
                zorder=0, linewidth=0)


def draw_basemap(ax, roads, towns, fills, xlim, ylim):
    draw_fills(ax, fills[0], fills[1], xlim, ylim)
    width = xlim[1] - xlim[0]
    tiers = ["t1"]
    if width <= 1.5:
        tiers.append("t2")
    if width <= 0.6:
        tiers.append("t3")
    if width <= 0.2:
        tiers.append("t4")
    styles = {"t1": (0.9, "#7d766d"), "t2": (0.65, "#8a8378"),
              "t3": (0.4, "#9c958a"), "t4": (0.28, "#aaa397")}
    for t in tiers:
        segs = visible(roads[t], xlim, ylim)
        if len(segs):
            lw, color = styles[t]
            ax.add_collection(LineCollection(
                segs, linewidths=lw, colors=color, zorder=1))
    tsegs = visible(towns, xlim, ylim)
    if len(tsegs):
        ax.add_collection(LineCollection(
            tsegs, linewidths=0.55, colors="#5f574c", zorder=2))


def test_frame(name, xlim, ylim, roads, towns, fills, stops, route):
    fig, ax = plt.subplots(figsize=(16, 9))
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    draw_basemap(ax, roads, towns, fills, xlim, ylim)
    xs = [c[0] for c in route]
    ys = [c[1] for c in route]
    ax.plot(xs, ys, color="#FF6712", linewidth=1.0, alpha=0.55,
            zorder=3)
    ax.scatter([s[0] for s in stops], [s[1] for s in stops],
               s=4, color="#DA1884", zorder=4)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_aspect(1.35)
    ax.axis("off")
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(TEST_DIR / name, dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"wrote {name}")


def main():
    import csv
    import json
    town_segs, fills_pts, fills_starts = build_towns()
    fills = (fills_pts, fills_starts)
    roads = build_roads()
    with open(FINAL_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    stops = [(float(r["lon"]), float(r["lat"])) for r in rows]
    with open(CLEAN / "route_geometry.geojson",
              encoding="utf-8") as f:
        route = json.load(f)["features"][0]["geometry"]["coordinates"]
    lons = [s[0] for s in stops]
    lats = [s[1] for s in stops]
    state = ((min(lons) - 0.15, max(lons) + 0.15),
             (min(lats) - 0.1, max(lats) + 0.1))
    test_frame("test_state.png", state[0], state[1],
               roads, town_segs, fills, stops, route)
    test_frame("test_metro.png", (-71.3, -70.8), (42.15, 42.5),
               roads, town_segs, fills, stops, route)
    test_frame("test_dense.png", (-71.12, -70.96), (42.27, 42.39),
               roads, town_segs, fills, stops, route)
    test_frame("test_rural.png", (-73.4, -72.9), (42.25, 42.7),
               roads, town_segs, fills, stops, route)
    print("basemap data and test frames ready")


if __name__ == "__main__":
    main()
