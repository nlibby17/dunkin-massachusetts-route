"""
Dashboard + camera + renderer for the Dunkin' tour video.

The map fills the frame; the dashboard is a band across the
top. Left: miles gauge (fills light green to deep green) with
the number and a MILES DRIVEN label under it. Then the Dunkin'
header, the stops fraction, HEADED TO (town + address), and
the metric rows: time with a day counter, iced coffee dollars,
gas dollars and gallons for the 2011 Jetta TDI.

Timeline: about 60 s of motion at 30 fps, each frame advancing
simulated time in proportion to real OSRM leg durations. The
camera is rule driven: its window scales with the distance to
the next stop (gain 10, floor 0.65 degrees, so the view stays
at region scale and always shows which part of Massachusetts
you are in), smoothed so it glides. The video opens and
closes on the full-state view (the 2 s stillness bookends),
diving in at the start and pulling back at the end.

Modes (no argument renders the three review stills):
  (none)     still_opening / still_boston / still_final PNGs
  --test     the opening 10 s at half resolution -> mp4
  --render   the full ~64 s at 1920x1080 -> mp4
"""

import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
from matplotlib import font_manager
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_map

ROOT = Path(__file__).resolve().parent.parent.parent
CLEAN = ROOT / "data" / "clean"
OUT_DIR = CLEAN / "dashboard_tests"
FONT_DIR = CLEAN / "fonts"

# Nick's constants
COFFEE_PRICE = 3.84      # medium iced vanilla, 2 whole milk, 1 sugar
DIESEL_PRICE = 6.29      # per gallon
MPG = 35.0               # 2011 Jetta TDI, estimated
FPS = 30
MOTION_S = 60
STILL_S = 2
TEST_S = 10
TEST_DPI = 50
FULL_DPI = 100
ORANGE = "#FF6712"
PINK = "#DA1884"
PAPER = "#fff8f0"
BAND = "#fff3e4"
INK = "#3a2e28"
GAUGE_LIGHT = (0.62, 0.90, 0.60)
GAUGE_DEEP = (0.10, 0.45, 0.16)
ASPECT = 1.35
FIG_W, FIG_H = 19.2, 10.8
MAP_FRAC = 0.845                       # map share of the height
H_PER_W = (FIG_H * MAP_FRAC) / FIG_W / ASPECT
HUD_H = 175                            # HUD canvas height (px-ish)

FONTS = [
    ("Titan One",
     "https://github.com/google/fonts/raw/main/ofl/titanone/"
     "TitanOne-Regular.ttf"),
    ("Archivo Black",
     "https://github.com/google/fonts/raw/main/ofl/archivoblack/"
     "ArchivoBlack-Regular.ttf"),
]


def setup_fonts():
    got = {}
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS:
        dest = FONT_DIR / (name.replace(" ", "") + ".ttf")
        try:
            if not dest.exists():
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                dest.write_bytes(r.content)
            font_manager.fontManager.addfont(str(dest))
            got[name] = name
        except Exception as e:
            print(f"font {name} unavailable ({e}); falling back")
    title = got.get("Titan One", "DejaVu Sans")
    nums = got.get("Archivo Black", "DejaVu Sans")
    return title, nums


def load_tour():
    with open(CLEAN / "route_order.csv", newline="",
              encoding="utf-8-sig") as f:
        order = list(csv.DictReader(f))
    idx = [int(r["idx"]) for r in order]
    dist_m = np.load(CLEAN / "distance_matrix.npy")
    dur_s = np.load(CLEAN / "duration_matrix.npy")
    n = len(order)
    leg_dist_mi = np.array(
        [dist_m[idx[i], idx[(i + 1) % n]] for i in range(n)],
        dtype=float) / 1609.344
    leg_dur_h = np.array(
        [dur_s[idx[i], idx[(i + 1) % n]] for i in range(n)],
        dtype=float) / 3600.0
    with open(CLEAN / "route_geometry.geojson",
              encoding="utf-8") as f:
        coords = np.array(json.load(f)["features"][0]
                          ["geometry"]["coordinates"], dtype=float)
    stops_xy = np.array([(float(r["lon"]), float(r["lat"]))
                         for r in order])
    legs = split_legs(coords, stops_xy)
    return order, legs, leg_dist_mi, leg_dur_h, stops_xy


def split_legs(coords, stops_xy):
    """Cut the full tour polyline into per-leg arrays."""
    legs = []
    start = 0
    n = len(coords)
    for s in range(1, len(stops_xy) + 1):
        target = stops_xy[s % len(stops_xy)]
        window = coords[start:min(n, start + 20000)]
        j = int(np.argmin(((window - target) ** 2).sum(axis=1)))
        end = start + j
        if s == len(stops_xy):
            end = n - 1
        legs.append(coords[start:end + 1])
        start = end
    return legs


def leg_point(leg, frac):
    """Position at arc-length fraction along one leg + the
    coordinates up to that point."""
    if len(leg) == 1:
        return leg[0], leg
    seg = np.hypot(*np.diff(leg, axis=0).T)
    total = seg.sum()
    if total == 0:
        return leg[0], leg[:1]
    target = frac * total
    cum = np.concatenate([[0], np.cumsum(seg)])
    k = int(np.searchsorted(cum, target) - 1)
    k = max(0, min(k, len(seg) - 1))
    f = (target - cum[k]) / seg[k] if seg[k] > 0 else 0.0
    pos = leg[k] + f * (leg[k + 1] - leg[k])
    return pos, np.vstack([leg[:k + 1], pos])


class Timeline:
    def __init__(self, legs, leg_dist_mi, leg_dur_h):
        self.legs = legs
        self.leg_dist = leg_dist_mi
        self.leg_dur = leg_dur_h
        self.cum_dist = np.concatenate([[0], np.cumsum(leg_dist_mi)])
        self.cum_dur = np.concatenate([[0], np.cumsum(leg_dur_h)])
        self.total_mi = float(self.cum_dist[-1])
        self.total_h = float(self.cum_dur[-1])

    def state(self, t_h):
        """Everything the dashboard needs at simulated hour t."""
        t_h = min(max(t_h, 0.0), self.total_h)
        leg = int(np.searchsorted(self.cum_dur, t_h) - 1)
        leg = max(0, min(leg, len(self.legs) - 1))
        dur = self.leg_dur[leg]
        frac = (t_h - self.cum_dur[leg]) / dur if dur > 0 else 1.0
        pos, partial = leg_point(self.legs[leg], frac)
        miles = self.cum_dist[leg] + frac * self.leg_dist[leg]
        visited = leg + 1
        return {"leg": leg, "frac": frac, "pos": pos,
                "partial": partial, "miles": float(miles),
                "hours": float(t_h), "visited": visited}


def state_camera(stops_xy):
    """Contain-fit view of the whole state in the map area."""
    lon_span = stops_xy[:, 0].max() - stops_xy[:, 0].min()
    lat_span = stops_xy[:, 1].max() - stops_xy[:, 1].min()
    w = max(lon_span + 0.35, (lat_span + 0.25) / H_PER_W)
    c = ((stops_xy[:, 0].min() + stops_xy[:, 0].max()) / 2,
         (stops_xy[:, 1].min() + stops_xy[:, 1].max()) / 2)
    return np.array([c[0], c[1], w])


def camera_path(tl, stops_xy, frames, state_cam):
    """Smoothed camera (cx, cy, width) for every motion frame."""
    cam = state_cam.copy()
    log_w = float(np.log(cam[2]))
    path = []
    for f in range(frames):
        t_h = tl.total_h * f / (frames - 1)
        st = tl.state(t_h)
        nxt = stops_xy[(st["leg"] + 1) % len(stops_xy)]
        d = float(np.hypot(*(nxt - st["pos"])))
        w_t = min(max(10.0 * d, 0.65), state_cam[2])
        c_t = st["pos"] + 0.35 * (nxt - st["pos"])
        target = np.array([c_t[0], c_t[1], w_t])
        if f > frames - 121:  # final pull-back to the state view
            target = state_cam
        cam[:2] = cam[:2] + 0.08 * (target[:2] - cam[:2])
        log_w += 0.03 * (float(np.log(target[2])) - log_w)
        cam[2] = float(np.exp(log_w))

        path.append(cam.copy())
    return path


def lerp_color(a, b, f):
    return tuple(a[i] + (b[i] - a[i]) * f for i in range(3))


class Dashboard:
    def __init__(self, tl, order, stops_xy, title_font, num_font):
        self.tl = tl
        self.order = order
        self.stops = stops_xy
        self.title_font = title_font
        self.num_font = num_font
        self.fig = plt.figure(figsize=(FIG_W, FIG_H))
        self.fig.patch.set_facecolor(PAPER)
        self.map_ax = self.fig.add_axes([0, 0, 1, MAP_FRAC])
        self.map_ax.set_axis_off()
        self.hud = self.fig.add_axes([0, MAP_FRAC - 0.007, 1,
                                      1 - MAP_FRAC + 0.007])
        self.hud.set_axis_off()
        self.roads = base_map.build_roads()
        tsegs, fpts, fstarts = base_map.build_towns()
        self.town_segs = tsegs
        self.fills = (fpts, fstarts)

    def draw(self, t_h, cam):
        ax = self.map_ax
        ax.clear()
        ax.set_axis_off()
        ax.set_facecolor(PAPER)
        cx, cy, w = cam
        h = w * H_PER_W
        xlim = (cx - w / 2, cx + w / 2)
        ylim = (cy - h / 2, cy + h / 2)
        base_map.draw_basemap(ax, self.roads, self.town_segs,
                              self.fills, xlim, ylim)
        st = self.tl.state(t_h)
        allx = np.concatenate([leg[:, 0] for leg in self.tl.legs])
        ally = np.concatenate([leg[:, 1] for leg in self.tl.legs])
        ax.plot(allx, ally, color=ORANGE, linewidth=1.0,
                alpha=0.28, zorder=3)
        driven = [self.tl.legs[i] for i in range(st["leg"])]
        driven.append(st["partial"])
        dx = np.concatenate([p[:, 0] for p in driven])
        dy = np.concatenate([p[:, 1] for p in driven])
        ax.plot(dx, dy, color=ORANGE, linewidth=2.3, zorder=4)
        dot = float(np.clip(8.0 / w, 9.0, 16.0))
        ax.scatter(self.stops[:, 0], self.stops[:, 1], s=dot * 2.6,
                   color="white", zorder=4.6, linewidths=0,
                   alpha=0.55)
        ax.scatter(self.stops[:, 0], self.stops[:, 1], s=dot,
                   color=PINK, zorder=5, linewidths=0)

        vis = self.stops[:st["visited"]]
        ax.scatter(vis[:, 0], vis[:, 1], s=dot * 1.5,
                   color=ORANGE, zorder=6, linewidths=0)
        ax.scatter([st["pos"][0]], [st["pos"][1]], s=110,
                   color=PINK, edgecolors="white", linewidths=2,
                   zorder=7)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_aspect(ASPECT)
        self.draw_hud(st)

    def draw_hud(self, st):
        hud = self.hud
        hud.clear()
        hud.set_axis_off()
        hud.set_xlim(0, 1920)
        hud.set_ylim(0, HUD_H)
        hud.add_patch(Rectangle((0, 0), 1920, HUD_H,
                                color=BAND, alpha=0.97, zorder=0))
        hud.add_patch(Rectangle((0, 0), 1920, 6,
                                color=ORANGE, zorder=1))
        frac = st["miles"] / self.tl.total_mi if self.tl.total_mi \
            else 0.0
        # miles gauge, left
        hud.add_patch(Rectangle((30, 132), 400, 26,
                                facecolor="#ddd5c9",
                                edgecolor="none", zorder=2))
        hud.add_patch(Rectangle(
            (30, 132), 400 * frac, 26, zorder=3, edgecolor="none",
            facecolor=lerp_color(GAUGE_LIGHT, GAUGE_DEEP, frac)))
        hud.text(30, 70, f"{st['miles']:,.1f}",
                 family=self.num_font, fontsize=40, color=INK)
        hud.text(32, 24, "MILES DRIVEN", family=self.num_font,
                 fontsize=15.5, color="#7a6a5e")
        # header, two lines so it can never reach the counters
        hud.text(478, 114, "EVERY DUNKIN'", family=self.title_font,
                 fontsize=33, color=ORANGE)
        hud.text(478, 58, "IN MASSACHUSETTS",
                 family=self.title_font, fontsize=33, color=ORANGE)
        hud.text(480, 16, "1,019 STOPS · ONE LOOP",
                 family=self.num_font, fontsize=14, color=PINK)
        # stops fraction, label centered under the counter
        hud.text(1120, 84, f"{st['visited']} / 1,019",
                 family=self.num_font, fontsize=27, color=INK,
                 ha="center")
        hud.text(1120, 36, "STOPS", family=self.num_font,
                 fontsize=15, color="#7a6a5e", ha="center")
        # headed to
        leg = st["leg"]
        if leg >= len(self.order) - 1 and st["frac"] > 0:
            town = "HOME"
            addr = self.order[0]["address"]
        else:
            nxt = self.order[(leg + 1) % len(self.order)]
            town, addr = nxt["city"].upper(), nxt["address"]
        hud.text(1330, 138, "HEADED TO", family=self.num_font,
                 fontsize=14.5, color=PINK)
        hud.text(1330, 92, town, family=self.num_font, fontsize=23,
                 color=INK)
        hud.text(1330, 48, addr, family=self.num_font, fontsize=15,
                 color="#7a6a5e")
        # metrics, right aligned so nothing can leave the frame
        day = int(st["hours"] // 24) + 1
        coffee = st["visited"] * COFFEE_PRICE
        gallons = st["miles"] / MPG
        gas = gallons * DIESEL_PRICE
        hud.text(1892, 130, f"DAY {day} · {st['hours']:.1f} HRS",
                 family=self.num_font, fontsize=15.5, color=INK,
                 ha="right")
        hud.text(1892, 82, f"ICED COFFEE  ${coffee:,.2f}",
                 family=self.num_font, fontsize=15.5, color=INK,
                 ha="right")
        hud.text(1892, 34, f"GAS  ${gas:,.2f} · {gallons:.1f} GAL",
                 family=self.num_font, fontsize=15.5, color=INK,
                 ha="right")

    def save(self, t_h, cam, name):
        self.draw(t_h, cam)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.fig.savefig(OUT_DIR / name, dpi=100,
                         facecolor=self.fig.get_facecolor())
        print(f"wrote {name}")


def main():
    title_font, num_font = setup_fonts()
    order, legs, leg_dist, leg_dur, stops_xy = load_tour()
    tl = Timeline(legs, leg_dist, leg_dur)
    print(f"tour: {tl.total_mi:,.1f} miles, {tl.total_h:.1f} hrs")
    frames = FPS * MOTION_S
    state_cam = state_camera(stops_xy)
    path = camera_path(tl, stops_xy, frames, state_cam)
    dash = Dashboard(tl, order, stops_xy, title_font, num_font)
    dash.save(0.0, state_cam, "still_opening.png")
    hall = next((i for i, r in enumerate(order)
                 if "City Hall" in r["address"]), None)
    if hall is None:
        downtown = np.array([-71.0589, 42.3601])
        hall = int(np.argmin(((stops_xy - downtown) ** 2)
                             .sum(axis=1)))
    t_boston = float(tl.cum_dur[hall])
    f_boston = int(round((len(path) - 1) * t_boston / tl.total_h))
    dash.save(t_boston, path[f_boston], "still_boston.png")
    dash.save(tl.total_h, state_cam, "still_final.png")
    print("dashboard stills ready")


# ---------------------------------------------------------------
# Render: frames -> mp4. "--test" renders the opening 10 s at
# half resolution (2 s hold + 8 s of motion); "--render" the
# full ~64 s at 1920x1080 (2 s hold + 60 s motion + 2 s settle).
# ---------------------------------------------------------------

def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def render(test=False):
    title_font, num_font = setup_fonts()
    order, legs, leg_dist, leg_dur, stops_xy = load_tour()
    tl = Timeline(legs, leg_dist, leg_dur)
    frames_motion = FPS * MOTION_S
    state_cam = state_camera(stops_xy)
    path = camera_path(tl, stops_xy, frames_motion, state_cam)
    dash = Dashboard(tl, order, stops_xy, title_font, num_font)
    dpi = TEST_DPI if test else FULL_DPI
    frames_dir = CLEAN / ("render_frames_test" if test
                          else "render_frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    head = STILL_S * FPS
    motion = (TEST_S - STILL_S) * FPS if test else frames_motion
    tail = 0 if test else STILL_S * FPS
    total = head + motion + tail
    print(f"rendering {total} frames at dpi {dpi} "
          f"({'test' if test else 'full'})...")
    t0 = time.time()
    made = 0

    def emit(t_h, cam):
        nonlocal made
        dash.draw(t_h, cam)
        p = frames_dir / f"frame_{made:05d}.png"
        dash.fig.savefig(p, dpi=dpi,
                         facecolor=dash.fig.get_facecolor())
        made += 1
        if made % 60 == 0 or made == total:
            el = time.time() - t0
            eta = el / made * (total - made)
            print(f"  {made}/{total} frames, {el:,.0f}s elapsed, "
                  f"~{eta:,.0f}s to go")

    emit(0.0, state_cam)
    first = frames_dir / "frame_00000.png"
    while made < head:
        shutil.copy(first, frames_dir / f"frame_{made:05d}.png")
        made += 1
    for f in range(motion):
        t_h = tl.total_h * f / (frames_motion - 1)
        emit(t_h, path[f])
    if tail:
        emit(tl.total_h, state_cam)
        last = frames_dir / f"frame_{made - 1:05d}.png"
        while made < total:
            shutil.copy(last,
                        frames_dir / f"frame_{made:05d}.png")
            made += 1
    exe = ffmpeg_exe()
    out = CLEAN / ("test_opening.mp4" if test
                   else "dunkin_tour.mp4")
    if exe is None:
        print("ffmpeg not found; frames are kept in "
              f"{frames_dir}. Install imageio-ffmpeg and the "
              "assembly can run without re-rendering.")
        return
    cmd = [exe, "-y", "-framerate", str(FPS), "-i",
           str(frames_dir / "frame_%05d.png"), "-c:v",
           "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           str(out)]
    subprocess.run(cmd, check=True)
    print(f"video written: {out}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        render(test=True)
    elif "--render" in sys.argv:
        render(test=False)
    else:
        main()
