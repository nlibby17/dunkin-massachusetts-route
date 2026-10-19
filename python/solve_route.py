"""
Solve the loop: shortest road tour of all 1,019 stops,
anchored at the original Quincy store (543 Southern Artery).

Reads  data/clean/distance_matrix.npy (meters)
       data/clean/duration_matrix.npy (seconds)
       data/clean/matrix_index.csv
Writes data/clean/route_order.csv (the tour, leg by leg)
       data/clean/route_plot.png

Method: OR-Tools routing, PATH_CHEAPEST_ARC first solution,
GUIDED_LOCAL_SEARCH improvement, time-boxed. Objective is
road distance; duration is reported for the same tour.
A longer time box buys a shorter tour; 600 s is the first
pass, not the ceiling.
"""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = ROOT / "data" / "clean" / "distance_matrix.npy"
DUR_PATH = ROOT / "data" / "clean" / "duration_matrix.npy"
INDEX_PATH = ROOT / "data" / "clean" / "matrix_index.csv"
ORDER_PATH = ROOT / "data" / "clean" / "route_order.csv"
PLOT_PATH = ROOT / "data" / "clean" / "route_plot.png"

TIME_LIMIT_S = 600
M_PER_MILE = 1609.344


def main():
    dist = np.load(DIST_PATH)
    dur = np.load(DUR_PATH)
    with open(INDEX_PATH, newline="", encoding="utf-8") as f:
        index = list(csv.DictReader(f))
    n = len(index)

    anchor = None
    for r in index:
        if r["city"] == "Quincy" and \
                "543 Southern Artery" in r["address"]:
            anchor = int(r["idx"])
    if anchor is None:
        print("anchor store not found in the index")
        return
    print(f"anchor: idx {anchor} "
          f"({index[anchor]['address']}, Quincy)")

    manager = pywrapcp.RoutingIndexManager(n, 1, anchor)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return int(dist[i, j])

    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic
        .GUIDED_LOCAL_SEARCH)
    params.time_limit.FromSeconds(TIME_LIMIT_S)
    print(f"solving (time box {TIME_LIMIT_S} s)...")
    solution = routing.SolveWithParameters(params)
    if solution is None:
        print("no solution found in the time box")
        return

    order = []
    node = routing.Start(0)
    while not routing.IsEnd(node):
        order.append(manager.IndexToNode(node))
        node = solution.Value(routing.NextVar(node))
    assert len(order) == n, f"visited {len(order)} of {n}"

    legs = [(order[k], order[(k + 1) % n]) for k in range(n)]
    total_m = sum(dist[i, j] for i, j in legs)
    total_s = sum(dur[i, j] for i, j in legs)
    miles = total_m / M_PER_MILE
    hours = total_s / 3600

    with open(ORDER_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seq", "idx", "address", "city", "lat", "lon",
                    "leg_miles", "cumulative_miles"])
        cum = 0.0
        for k, (i, j) in enumerate(legs):
            leg_mi = dist[i, j] / M_PER_MILE
            cum += leg_mi
            r = index[i]
            w.writerow([k + 1, i, r["address"], r["city"],
                        r["lat"], r["lon"],
                        f"{leg_mi:.2f}", f"{cum:.1f}"])

    lons = [float(index[i]["lon"]) for i in order]
    lats = [float(index[i]["lat"]) for i in order]
    plt.figure(figsize=(12, 9))
    plt.plot(lons + [lons[0]], lats + [lats[0]],
             linewidth=0.5, alpha=0.8)
    plt.scatter(lons, lats, s=2)
    plt.scatter([lons[0]], [lats[0]], s=140, marker="*",
                color="red", zorder=5)
    plt.gca().set_aspect(1.35)
    plt.title(f"Dunkin' Massachusetts loop: {n} stops, "
              f"{miles:,.0f} miles, {hours:,.1f} driving hours")
    plt.savefig(PLOT_PATH, dpi=150, bbox_inches="tight")

    print(f"\nstops visited: {n}")
    print(f"total distance: {miles:,.1f} miles")
    print(f"total driving time: {hours:,.1f} hours "
          f"({int(hours) // 24} d {int(hours) % 24} h)")
    print("benchmark (DataDork): 2,308 miles, 65 h, 1,028 stops")
    print(f"wrote {ORDER_PATH.name} and {PLOT_PATH.name}")


if __name__ == "__main__":
    main()
