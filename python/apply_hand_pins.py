"""
Apply Nick's 25 hand-placed pins (Google Maps, verified on the
actual stores, 2026-10-18): the 24 eyeball stores plus
1 Horizon Way.

Reads  data/clean/dunkins_final_v7.csv
Writes data/clean/dunkins_final_v8.csv
"""

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "clean" / "dunkins_final_v7.csv"
OUT_PATH = ROOT / "data" / "clean" / "dunkins_final_v8.csv"

HAND_PINS = {
    ("6 gardner rd", "ashburnham"):
        (42.609040242011424, -71.94253506429136),
    ("80 chelmsford rd petrolex gas station", "billerica"):
        (42.58741038293724, -71.30725753933002),
    ("100 morrissey blvd, university of massachusetts boston",
     "boston"): (42.31282745086049, -71.03665982235265),
    ("551 granite st", "braintree"):
        (42.211747544079635, -71.02013617570914),
    ("69 middlesex tpke", "burlington"):
        (42.47526258936858, -71.21344202836812),
    ("425 meadow st", "chicopee"):
        (42.17184133681786, -72.61403801641885),
    ("285 old westport rd", "dartmouth"):
        (41.63089803523911, -71.006706757443),
    ("256 washington street", "hudson"):
        (42.375832066426945, -71.56386995046665),
    ("226 winthrop st", "lawrence"):
        (42.6850866768816, -71.13976712644653),
    ("45 chauncy st", "mansfield"):
        (42.032773172604074, -71.21604471719252),
    ("413 lakeside ave", "marlboro"):
        (42.34174447059422, -71.57908303000274),
    ("320 washington st", "north easton"):
        (42.04672521539565, -71.08011142318774),
    ("3086 south main st", "palmer"):
        (42.207755098075076, -72.34787989135238),
    ("134 samoset street", "plymouth"):
        (41.952726219363015, -70.68444210317887),
    ("23 commerce way", "plymouth"):
        (41.95010731050649, -70.71384940902901),
    ("160 south st", "plymouth"):
        (41.93911016378585, -70.65629420596613),
    ("227 winthrop st", "rehoboth"):
        (41.85493903933873, -71.23723882724913),
    ("419-423 main st", "southbridge"):
        (42.076846086839396, -72.03658180506686),
    ("50 leominster rd", "sterling"):
        (42.44450326287707, -71.75230054060157),
    ("2 lynn fells pkwy", "stoneham"):
        (42.4574390274487, -71.0828453034378),
    ("506 w center st shell station", "west bridgewater"):
        (42.01488870925362, -71.04014610734089),
    ("21 village inn rd", "westminster"):
        (42.544623978297636, -71.87444728479396),
    ("38 winter st", "weymouth"):
        (42.199745899226066, -70.95496905355299),
    ("195 main st", "wilmington"):
        (42.55829668905176, -71.18256298399889),
    ("1 horizon way", "everett"):
        (42.39598416468984, -71.06834946713568),
}


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def main():
    with open(IN_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    applied = 0
    for r in rows:
        key = (r["address"].lower().strip(),
               r["city"].lower().strip())
        if key in HAND_PINS:
            lat, lon = HAND_PINS[key]
            moved = haversine_m(float(r["lat"]), float(r["lon"]),
                                lat, lon)
            r["lat"], r["lon"] = f"{lat:.6f}", f"{lon:.6f}"
            r["pin_source"] = "hand_placed"
            applied += 1
            print(f"hand pin: {r['address']}, {r['city']} "
                  f"(moved {moved:,.0f} m)")
    print(f"\napplied {applied} of {len(HAND_PINS)} hand pins")
    cols = list(rows[0].keys())
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"final stops in {OUT_PATH.name}: {len(rows)}")


if __name__ == "__main__":
    main()
