"""Demand for the SUMO microsimulation: one sampled day of the forecast as individual trips.

The day is drawn exactly as the forecast draws its samples (daysim.sample_day, with the seed
agents.py uses), so the microsimulation and the macro model carry the same traffic:

* everyday trips of each kind (daysim.background_by_purpose) and match fans, per 15 minutes and
  origin-destination pair, rounded to whole vehicles at random so the totals are kept; port
  lorries become lorries (car-equivalents / traffic_model.HGV_PCU);
* every cruise vehicle the day draws (daysim.cruise_vehicles), at its own minute; coaches are
  coaches;
* the local traffic the macro model adds on the counted roads (traffic_model.anchor_counts) as
  trips along those roads;
* the day's buses from the BODS timetable (demo/buses.py), stopping 20 s at each stop and never
  leaving a stop before its timetabled time.

Origins and destinations are sets of SUMO edges near the model's centroids. A zone gets the local
roads nearer to it than to any other zone; a county gateway gets the stretch of its main road
near the edge of the area, inbound for trips that start there and outbound for trips that end
there; dock gates, the station and the stadium get the roads within 250 m. Each trip leaves from
a random edge of its origin set (weighted by length) at a random second of its 15 minutes and
ends on a random edge of its destination set. Routes are SUMO's own (see sumo.slurm).

Drivers want to go at a share of the limit drawn per vehicle, normc(0.92, 0.06, 0.75, 1.0) for
cars (lorries and coaches also capped at 56 mph, buses at 45 mph).

The macro model is run on the same sampled day (traffic_model.run_day) for sumo_compare.py,
on dry roads with no incident so both models see the same roads; its buses run as in agents.py.

    python demo/sumo_demand.py --date 2026-11-16 [--scale 1.0]
writes runs/sumo/<date>/: trips.xml.gz, busstops.add.xml, micro.sumocfg, meso.sumocfg,
edges.json (corridor and road mapping), buses.json, macro.npz, macro.json, meta.json.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import subprocess
import sys
import time as clock
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import buses  # noqa: E402
import daysim  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

ROOT = HERE.parent
NET = ROOT / "data" / "cache" / "sumo" / "southampton.net.xml.gz"
RUNS = ROOT / "runs" / "sumo"
PAGE = HERE / "out" / "demo.html"
SEED = 7  # agents.AGENT_SEED: the same sampled day as the agents on the page
DAY_START_S = tm.DAY_START_H * 3600
END_S = DAY_START_S + tm.N_BINS * 900  # 20:00: no trip leaves later
SIM_END_S = END_S + 2 * 3600  # run on to 22:00 so the last trips can finish
LOCAL_TYPES = {"primary", "secondary", "tertiary", "unclassified"}
MAJOR_RANK = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"]
MIN_EDGE_M = 25.0
ZONE_MAX_M = 2500.0
POINT_M = 250.0  # dock gates, station, stadium
GATEWAY_M = 600.0
MATCH_TOL_M = 20.0
MATCH_ANGLE = 40.0
VTYPES = {
    # id: attributes. speedFactor: drivers' wanted speed as a share of the limit, drawn per vehicle
    "car": 'vClass="passenger" length="4.6" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" '
           'tau="1.0" speedFactor="normc(0.92,0.06,0.75,1.0)"',
    "taxi": 'vClass="taxi" length="4.8" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" '
            'tau="1.0" speedFactor="normc(0.92,0.06,0.75,1.0)"',
    "hgv": 'vClass="trailer" length="16.5" minGap="3.0" accel="1.0" decel="4.0" sigma="0.5" '
           'tau="1.2" maxSpeed="25.0" speedFactor="normc(0.95,0.04,0.8,1.0)"',
    "coach": 'vClass="coach" length="13.0" minGap="3.0" accel="1.2" decel="4.0" sigma="0.5" '
             'tau="1.2" maxSpeed="25.0" speedFactor="normc(0.95,0.04,0.8,1.0)"',
    "bus": 'vClass="bus" length="12.0" minGap="3.0" accel="1.2" decel="4.0" sigma="0.5" '
           'tau="1.2" maxSpeed="20.0" speedFactor="normc(0.92,0.05,0.75,1.0)"',
}
CRUISE_TYPE = {0: "car", 1: "car", 2: "taxi", 3: "coach"}  # daysim.KINDS: car, park, taxi, coach
BUS_DWELL_S = round(buses.DWELL_MIN * 60)


# --- network and geometry --------------------------------------------------------------------

class Net:
    """The SUMO network's normal edges as arrays, with the page-grid <-> SUMO coordinate map."""

    def __init__(self, path: Path):
        import sumolib
        from pyproj import Transformer
        from scipy.spatial import cKDTree

        self.net = sumolib.net.readNet(str(path), withInternal=False)
        self.edges = [e for e in self.net.getEdges()
                      if e.getFunction() == "" and e.allows("passenger")]
        self.ix = {e.getID(): i for i, e in enumerate(self.edges)}
        self.ids = [e.getID() for e in self.edges]
        self.kind = [e.getType().replace("highway.", "") for e in self.edges]
        self.length = np.array([e.getLength() for e in self.edges])
        self.shape = [np.asarray(e.getShape(), float) for e in self.edges]
        self.mid = np.array([s[len(s) // 2] if len(s) > 2 else s.mean(axis=0) for s in self.shape])
        self.start = np.array([s[0] for s in self.shape])
        self.end = np.array([s[-1] for s in self.shape])
        self.tree = cKDTree(self.mid)
        x0, y1, _ = sd.frame_origin()
        self.x0, self.y1 = x0, y1
        self.to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
        self.proj = self.net.getGeoProj()
        self.offset = np.asarray(self.net.getLocationOffset(), float)
        self._reach()

    def page_to_xy(self, pts) -> np.ndarray:
        """Model page-grid points (x = easting - x0, y = y1 - northing) to SUMO x, y."""
        p = np.asarray(pts, float).reshape(-1, 2)
        lon, lat = self.to_ll.transform(self.x0 + p[:, 0], self.y1 - p[:, 1])
        return self.ll_to_xy(lon, lat)

    def ll_to_xy(self, lon, lat) -> np.ndarray:
        x, y = self.proj(np.asarray(lon, float), np.asarray(lat, float))
        return np.column_stack([x, y]) + self.offset

    def _reach(self) -> None:
        """Edges that can reach the network's main strongly connected part (can start a trip)
        and edges it can reach (can end one)."""
        from scipy import sparse
        from scipy.sparse.csgraph import breadth_first_order, connected_components

        rows, cols = [], []
        for i, e in enumerate(self.edges):
            for o in e.getOutgoing():
                j = self.ix.get(o.getID())
                if j is not None:
                    rows.append(i)
                    cols.append(j)
        n = len(self.edges)
        _, lab = connected_components(sparse.csr_matrix((np.ones(len(rows)), (rows, cols)),
                                                        shape=(n, n)), connection="strong")
        main = lab == np.bincount(lab).argmax()
        # BFS from a virtual node joined to every edge of the main part
        r2, c2 = rows + [n] * int(main.sum()), cols + np.flatnonzero(main).tolist()
        fwd = sparse.csr_matrix((np.ones(len(r2)), (r2, c2)), shape=(n + 1, n + 1))
        r3, c3 = cols + [n] * int(main.sum()), rows + np.flatnonzero(main).tolist()
        bwd = sparse.csr_matrix((np.ones(len(r3)), (r3, c3)), shape=(n + 1, n + 1))
        def reached(g):
            seen = np.zeros(n, bool)
            order = breadth_first_order(g, n, return_predecessors=False)
            seen[order[order < n]] = True
            return seen

        self.can_end, self.can_start, self.main = reached(fwd), reached(bwd), main


def densify(xy: np.ndarray, step: float = 10.0):
    """Points every ``step`` metres along a polyline, with the heading (radians) of each."""
    pts, hd = [], []
    for a, b in zip(xy[:-1], xy[1:], strict=True):
        d = b - a
        L = float(np.hypot(*d))
        if L < 1e-6:
            continue
        k = max(1, int(L // step))
        for t in np.arange(k) / k:
            pts.append(a + t * d)
            hd.append(math.atan2(d[1], d[0]))
    if not pts and len(xy):
        pts, hd = [xy[0]], [0.0]
    return np.asarray(pts).reshape(-1, 2), np.asarray(hd)


def match_edges(net: Net, m: tm.Model, macro_edges, tol: float = MATCH_TOL_M,
                angle: float = MATCH_ANGLE, share: float = 0.6) -> dict[str, int]:
    """SUMO edges lying along the given macro-model edges in the same direction:
    {SUMO edge id: macro edge index it follows}. An edge matches when at least ``share`` of its
    length is within ``tol`` metres of a macro edge heading within ``angle`` degrees."""
    from scipy.spatial import cKDTree

    macro_edges = sorted(set(int(k) for k in macro_edges))
    if not macro_edges:
        return {}
    P, H, K = [], [], []
    for k in macro_edges:
        p, h = densify(net.page_to_xy(m.coords[k]))
        P.append(p)
        H.append(h)
        K.append(np.full(len(p), k))
    P, H, K = np.concatenate(P), np.concatenate(H), np.concatenate(K)
    tree = cKDTree(P)
    near = set()
    for hits in net.tree.query_ball_point(P, r=400.0):
        near.update(hits)
    out = {}
    cos_lim = math.cos(math.radians(angle))
    for i in sorted(near):
        q, qh = densify(net.shape[i])
        if not len(q):
            continue
        votes = defaultdict(int)
        for h, hits in zip(qh, tree.query_ball_point(q, r=tol), strict=True):
            ok = [K[j] for j in hits if math.cos(H[j] - h) >= cos_lim]
            if ok:
                votes[max(set(ok), key=ok.count)] += 1
        if votes and sum(votes.values()) >= share * len(q):
            out[net.ids[i]] = int(max(votes, key=votes.get))
    return out


# --- origins and destinations ----------------------------------------------------------------

def catchments(net: Net, m: tm.Model) -> tuple[list, list, dict]:
    """Per centroid: (edge indices, weights) to start from and to end on, and a summary."""
    n_c = len(m.centroids)
    cxy = net.page_to_xy([c.xy for c in m.centroids])
    centre = net.mid.mean(axis=0)
    long_enough = net.length >= MIN_EDGE_M
    local = np.array([k in LOCAL_TYPES for k in net.kind]) & long_enough
    zones = [i for i, c in enumerate(m.centroids) if c.kind == "zone"]
    starts, ends, info = [None] * n_c, [None] * n_c, {}

    # zones: Voronoi split of the local roads
    li = np.flatnonzero(local)
    zxy = cxy[zones]
    dist = np.hypot(*(net.mid[li, None, :] - zxy[None, :, :]).transpose(2, 0, 1))
    owner = dist.argmin(axis=1)
    for zi, ci in enumerate(zones):
        sel = li[(owner == zi) & (dist[np.arange(len(li)), owner] <= ZONE_MAX_M)]
        if len(sel) < 3:
            d = np.hypot(*(net.mid[li] - cxy[ci]).T)
            sel = li[np.argsort(d)[:5]]
        starts[ci] = sel[net.can_start[sel]]
        ends[ci] = sel[net.can_end[sel]]

    for ci, c in enumerate(m.centroids):
        if c.kind == "zone":
            continue
        d = np.hypot(*(net.mid - cxy[ci]).T)
        if c.kind == "gateway":
            # the gateway's road class: the best class among the macro edges at its node
            cls = [m.cls[k].replace("_link", "") for k in range(len(m.cls))
                   if m.eu[k] == c.node or m.ev[k] == c.node]
            best = min((MAJOR_RANK.index(x) for x in cls if x in MAJOR_RANK), default=2)
            road = np.array([k in MAJOR_RANK[: best + 1] for k in net.kind]) & long_enough
            near = np.flatnonzero(road & (d <= GATEWAY_M))
            if not len(near):
                near = np.flatnonzero(road)[np.argsort(d[road])[:4]]
            inward = (net.end[near] - net.start[near]) @ (centre - cxy[ci]) > 0
            s, e = near[inward], near[~inward]
            starts[ci] = s[net.can_start[s]] if len(s) else near[net.can_start[near]]
            ends[ci] = e[net.can_end[e]] if len(e) else near[net.can_end[near]]
        else:
            ok = np.array([k not in ("motorway", "motorway_link") for k in net.kind]) & long_enough
            near = np.flatnonzero(ok & (d <= POINT_M))
            if len(near) < 2:
                near = np.flatnonzero(ok)[np.argsort(d[ok])[:3]]
            starts[ci] = near[net.can_start[near]]
            ends[ci] = near[net.can_end[near]]
    for ci, c in enumerate(m.centroids):
        info[c.name + ("" if c.kind == "zone" else f" ({c.kind})")] = {
            "start_edges": len(starts[ci]), "end_edges": len(ends[ci])}
    return starts, ends, info


class Picker:
    """Random edges from each centroid's set, weighted by length."""

    def __init__(self, net: Net, sets: list):
        self.sets = sets
        self.cum = []
        for s in sets:
            w = net.length[s] if len(s) else np.zeros(0)
            self.cum.append(np.cumsum(w) / w.sum() if len(s) else w)

    def draw(self, c: int, n: int, rng) -> np.ndarray:
        s = self.sets[c]
        if not len(s):
            return np.full(n, -1)
        return s[np.minimum(np.searchsorted(self.cum[c], rng.random(n)), len(s) - 1)]


def whole(lam: np.ndarray, rng) -> np.ndarray:
    """Random rounding: floor plus one with the fractional part's chance (keeps the expectation)."""
    base = np.floor(lam)
    return (base + (rng.random(lam.shape) < lam - base)).astype(int)


# --- trips -----------------------------------------------------------------------------------

def od_trips(m, picks_s, picks_e, rng, D, key, vtype, scale):
    """Whole trips from a bins x OD matrix of vehicles: (depart s, key, vtype, from, to, od)."""
    n = whole(D * scale, rng)
    b, j = np.nonzero(n)
    cnt = n[b, j]
    b, j = np.repeat(b, cnt), np.repeat(j, cnt)
    dep = DAY_START_S + 900.0 * (b + rng.random(len(b)))
    ods = np.asarray(m.ods, int).reshape(-1, 2)
    o, d = ods[j, 0], ods[j, 1]
    fr, to = np.full(len(j), -1), np.full(len(j), -1)
    for c in np.unique(o):
        k = o == c
        fr[k] = picks_s.draw(c, int(k.sum()), rng)
    for c in np.unique(d):
        k = d == c
        to[k] = picks_e.draw(c, int(k.sum()), rng)
    return [(float(t), key, vtype, int(f), int(e), int(x))
            for t, f, e, x in zip(dep, fr, to, j, strict=True)]


def local_road_trips(net: Net, m: tm.Model, pre: np.ndarray, rng, scale: float):
    """The macro model's local traffic on the counted roads (anchor_counts) as trips from one
    end of each road to the other, per direction; returns (trips, mapping per road)."""
    trips, roads = [], {}
    for site in sd.COUNT_SITES:
        edges = tm.road_edges(m, site["names"])
        for north in (True, False):
            ks = [k for k in edges if tm.heading_north(m, k) == north]
            if not ks:
                continue
            per_bin = np.median(pre[:, ks], axis=1) / 4.0  # veh/h -> vehicles per 15 min
            mapped = match_edges(net, m, ks)
            idx = [net.ix[e] for e in mapped]
            if not idx or per_bin.sum() <= 0:
                continue
            axis = np.array([0.0, 1.0 if north else -1.0])
            first = min(idx, key=lambda i: float(net.start[i] @ axis))
            last = max(idx, key=lambda i: float(net.end[i] @ axis))
            label = f"{site['label']} {'NB' if north else 'SB'}"
            roads[label] = {"from": net.ids[first], "to": net.ids[last], "edges": len(idx),
                            "vehicles": round(float(per_bin.sum()), 1)}
            n = whole(per_bin * scale, rng)
            for b in np.flatnonzero(n):
                for t in DAY_START_S + 900.0 * (b + rng.random(n[b])):
                    trips.append((float(t), "local", "car", first, last, -1))
    return trips, roads


def bus_trips(net: Net, d: date, rng, log=print):
    """The day's BODS bus trips with their stops on SUMO lanes. Returns (bus stops
    {id: (edge index, start, end, name)}, trips [(depart s, id, from, to, stops, route)])."""
    import sumolib

    data = buses.load(log)
    if data is None:
        return {}, [], None
    run = {sid for sid, s in data["services"].items() if buses.service_runs(s, d)}
    bus_ok = np.array([e.allows("bus") and k not in ("motorway", "motorway_link")
                       for e, k in zip(net.edges, net.kind, strict=True)])
    stop_xy = {sid: net.ll_to_xy([lon], [lat])[0] for sid, (_, lat, lon) in data["stops"].items()}
    stops, out = {}, []
    timed = data.get("timetable") == "gtfs"

    geo = sumolib.geomhelper

    def candidates(p):
        """(distance, edge, position along it) for bus edges within SNAP_M of a stop."""
        res = []
        for i in net.tree.query_ball_point(p, r=buses.SNAP_M + 300):
            if not bus_ok[i]:
                continue
            shape = [tuple(x) for x in net.shape[i]]
            pos = geo.polygonOffsetWithMinimumDistanceToPoint(tuple(p), shape, perpendicular=False)
            dist = float(np.hypot(*(np.asarray(geo.positionAtShapeOffset(shape, pos)) - p)))
            if dist <= buses.SNAP_M:
                res.append((dist, i, min(pos, float(net.length[i]))))
        return sorted(res)

    cand_cache = {}
    for t in data["trips"]:
        if t["service"] not in run:
            continue
        st = t["stops"]
        first = st[0][2] if timed else t.get("first_min", -1) * 60
        if not DAY_START_S <= first < END_S:
            continue
        pts = []
        for sid, arr, dep in st:
            if sid not in cand_cache:
                cand_cache[sid] = candidates(stop_xy[sid])
            if cand_cache[sid]:
                pts.append((sid, arr, dep))
        if len(pts) < 2:
            continue
        chosen = []
        for k, (sid, arr, dep) in enumerate(pts):
            a = stop_xy[pts[max(k - 1, 0)][0]]
            b = stop_xy[pts[min(k + 1, len(pts) - 1)][0]]
            way = b - a
            best = None
            for dist, i, pos in cand_cache[sid][:8]:
                hd = net.end[i] - net.start[i]
                align = float(hd @ way) / (np.hypot(*hd) * np.hypot(*way) + 1e-9)
                score = dist - 40.0 * align  # prefer the carriageway heading the bus's way
                if best is None or score < best[0]:
                    best = (score, i, pos)
            _, i, pos = best
            if chosen and chosen[-1][1] == i and pos <= chosen[-1][2] + 1.0:
                continue  # a later stop behind an earlier one on the same edge: skip it
            chosen.append((sid, i, pos, arr, dep))
        if len(chosen) < 2:
            continue
        seq = []
        for sid, i, pos, arr, dep in chosen:
            L = float(net.length[i])
            a, b = max(0.0, pos - 10.0), min(L, pos + 10.0)
            if b - a < 5.0:
                a, b = max(0.0, b - 5.0), min(L, a + 5.0)
            bs = f"bs_{sid}_{net.ids[i]}"
            a, b = math.floor(a * 10) / 10, math.floor(b * 10) / 10  # never past the lane's end
            stops.setdefault(bs, (i, a, b, data["stops"][sid][0]))
            seq.append((bs, arr if timed else -1, dep if timed else -1))
        dep0 = chosen[0][4] if timed else first
        out.append((float(dep0 - BUS_DWELL_S), f"bus.{t['route']}.{t['id']}", chosen[0][1],
                    chosen[-1][1], seq, t["route"]))
    log(f"buses on {d}: {len(out)} trips, {len(stops)} stops on SUMO lanes")
    return stops, out, data


def write_trips(path: Path, net: Net, trips, bus_list) -> dict:
    """Trips sorted by departure, with the vehicle types; returns counts per kind."""
    rows = [(t, 0, i) for i, (t, *_rest) in enumerate(trips)]
    rows += [(b[0], 1, i) for i, b in enumerate(bus_list)]
    rows.sort()
    counts = defaultdict(int)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write("<routes>\n")
        for k, v in VTYPES.items():
            f.write(f'  <vType id="{k}" {v}/>\n')
        n = 0
        for _, which, i in rows:
            if which == 0:
                t, key, vtype, fr, to, j = trips[i]
                if fr < 0 or to < 0:
                    counts["dropped_no_edge"] += 1
                    continue
                start = "base" if net.kind[fr] in ("motorway", "trunk") else "random_free"
                end = "random"
                if fr == to or key == "local":  # drive the edge (or road) from end to end,
                    start, end = "base", "max"  # never round a loop back to a spot behind
                    counts["same_edge"] += fr == to
                f.write(f'  <trip id="{key}.{j}.{n}" type="{vtype}" depart="{t:.1f}" '
                        f'from="{net.ids[fr]}" to="{net.ids[to]}" departLane="best" '
                        f'departSpeed="max" departPos="{start}" arrivalPos="{end}"/>\n')
                counts[key] += 1
            else:
                t, vid, fr, to, seq, _ = bus_list[i]
                f.write(f'  <trip id="{vid}" type="bus" depart="{t:.1f}" from="{net.ids[fr]}" '
                        f'to="{net.ids[to]}" departLane="best" departPos="base">\n')
                for bs, arr, dep in seq:
                    timing = f' until="{dep:.0f}" arrival="{arr:.0f}"' if dep >= 0 else ""
                    f.write(f'    <stop busStop="{bs}" duration="{BUS_DWELL_S}"{timing}/>\n')
                f.write("  </trip>\n")
                counts["bus"] += 1
            n += 1
        f.write("</routes>\n")
    return dict(counts)


def write_configs(run_dir: Path, net_path: Path, threads: int, seed: int,
                  sim_threads: int = 1) -> None:
    """micro.sumocfg and meso.sumocfg: the same trips, one-shot assignment with every vehicle
    rerouting every 5 minutes on travel times smoothed over the last 3 minutes, and route costs
    disturbed by up to 20% per routing call so drivers do not all take the one quickest road.
    ``sim_threads`` > 1 runs the microsimulation's steps in parallel (SUMO --threads)."""
    for mode in ("micro", "meso"):
        (run_dir / f"{mode}.edgedata.add.xml").write_text(
            "<additional>\n"
            f'  <edgeData id="ed15" period="900" begin="{DAY_START_S}" end="{END_S}" '
            f'file="{mode}.edgedata.xml.gz" excludeEmpty="true"/>\n'
            "</additional>\n", encoding="utf-8", newline="\n")
        meso = ("    <mesosim value=\"true\"/>\n    <meso-junction-control value=\"true\"/>\n"
                if mode == "meso" else
                f'    <threads value="{sim_threads}"/>\n' if sim_threads > 1 else "")
        cfg = f"""<configuration>
  <input>
    <net-file value="{net_path}"/>
    <route-files value="trips.xml.gz"/>
    <additional-files value="busstops.add.xml,{mode}.edgedata.add.xml"/>
  </input>
  <time>
    <begin value="{DAY_START_S}"/>
    <end value="{SIM_END_S}"/>
    <step-length value="1"/>
  </time>
  <processing>
{meso}    <ignore-route-errors value="true"/>
    <time-to-teleport value="300"/>
    <ignore-junction-blocker value="60"/>
    <max-depart-delay value="3600"/>
    <routing-algorithm value="astar"/>
    <collision.action value="warn"/>
  </processing>
  <routing>
    <device.rerouting.probability value="1"/>
    <device.rerouting.period value="300"/>
    <device.rerouting.adaptation-interval value="10"/>
    <device.rerouting.adaptation-steps value="18"/>
    <device.rerouting.threads value="{threads}"/>
    <weights.random-factor value="1.2"/>
  </routing>
  <output>
    <summary-output value="{mode}.summary.xml"/>
    <summary-output.period value="60"/>
    <statistic-output value="{mode}.stats.xml"/>
    <tripinfo-output value="{mode}.tripinfo.xml.gz"/>
    <tripinfo-output.write-unfinished value="true"/>
    <stop-output value="{mode}.stops.xml.gz"/>
  </output>
  <report>
    <verbose value="true"/>
    <duration-log.statistics value="true"/>
    <no-step-log value="true"/>
    <log value="{mode}.log"/>
  </report>
  <random_number>
    <seed value="{seed}"/>
  </random_number>
</configuration>
"""
        (run_dir / f"{mode}.sumocfg").write_text(cfg, encoding="utf-8", newline="\n")


# --- the macro model on the same day ----------------------------------------------------------

def macro_reference(ctx: sd.Ctx, task: dict, day: daysim.SampledDay, Dc: np.ndarray, log=print):
    """run_day on the sampled day's demand, dry and with no incident, plus its buses."""
    m = ctx.m
    cap = sd.capacity(ctx, set(task["closed"]))
    D = day.Dbg + day.Dm + Dc
    res, _ = tm.run_day(m, D, cap, day.shares0, 3, want=("x", "queue", "held"), pre=day.pre,
                        noise=day.noise, events=())
    x = res["x"]
    log(f"macro: {D.sum():.0f} vehicles (car-equivalents), held at 17:00 {res['held'][48]:.0f}, "
        f"peak V/C {x.max():.2f}")
    bus = None
    data = buses.load(log)
    if data is not None:
        net = buses.Network(ctx)
        bus = buses.simulate(ctx, net, data, day.date, x,
                             np.random.default_rng([SEED, day.date.toordinal(), 2]), log)
    return cap, res, bus


def git_head() -> str:
    """The commit the code came from: git, or GIT_COMMIT for a copy without .git (Iridis)."""
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return os.environ.get("GIT_COMMIT", "unknown")


def page_cruise_fit(path: Path) -> dict | None:
    """The page's fitted cruise assumptions (top-level ``cruise_fit``; older pages kept it in
    ``meta``)."""
    page = daysim.page_data(path)
    if not page:
        return None
    fit = page.get("cruise_fit") or (page.get("meta") or {}).get("cruise_fit") or {}
    return fit.get("params")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--scale", type=float, default=1.0, help="share of the trips written")
    ap.add_argument("--net", type=Path, default=NET)
    ap.add_argument("--page", type=Path, default=PAGE)
    ap.add_argument("--out", type=Path, default=RUNS)
    ap.add_argument("--threads", type=int, default=8, help="routing threads per run")
    ap.add_argument("--sim-threads", type=int, default=1, help="micro: SUMO --threads")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-buses", action="store_true")
    args = ap.parse_args(argv)
    started = clock.perf_counter()

    def log(msg):
        print(f"[{clock.perf_counter() - started:6.0f}s] {msg}", flush=True)

    run_dir = args.out / args.date
    run_dir.mkdir(parents=True, exist_ok=True)
    if not daysim.CTX_PATH.exists():  # build and cache the model as synthetic_demo.main() does
        ctx, _ = sd.build_ctx(log)
        with open(daysim.CTX_PATH, "wb") as f:
            pickle.dump(ctx, f)
    ctx = daysim.load_ctx(log=log)
    m = ctx.m
    cruise = page_cruise_fit(args.page)
    task = daysim.day_tasks(cruise)[args.date]
    d = date.fromisoformat(args.date)
    rng = np.random.default_rng([args.seed, d.toordinal()])
    day = daysim.sample_day(ctx, task, rng)
    t_c = daysim.cruise_times(day.veh, day.params)
    Dc = daysim.vehicles_matrix(m.n_od, day.veh, t_c)
    log(f"{args.date}: {len(task['calls'])} calls, cruise assumptions {cruise or 'default'}, "
        f"wet {day.wet}, incident {bool(day.events)}")

    cap, res, macro_bus = macro_reference(ctx, task, day, Dc, log)

    net = Net(args.net)
    log(f"SUMO network: {len(net.edges)} edges, {int(net.main.sum())} in its main part")
    starts, ends, cinfo = catchments(net, m)
    ps, pe = Picker(net, starts), Picker(net, ends)
    trng = np.random.default_rng([args.seed, d.toordinal(), 3])
    trips = []
    for key, (bins, odw) in day.parts.items():
        Dk = np.outer(bins, odw)
        lorry = key in getattr(tm, "FREIGHT_KEYS", set())
        trips += od_trips(m, ps, pe, trng, Dk / tm.HGV_PCU if lorry else Dk, key,
                          "hgv" if lorry else "car", args.scale)
    if day.Dm.sum() > 0:
        trips += od_trips(m, ps, pe, trng, day.Dm, "match", "car", args.scale)
    v = day.veh
    vb = daysim.bin_index(t_c)
    ok = (vb >= 0) & (vb < tm.N_BINS) & (v["j"] >= 0) & (trng.random(len(t_c)) < args.scale)
    for i in np.flatnonzero(ok):
        o, dd = m.ods[v["j"][i]]
        trips.append((float(t_c[i] * 60.0), f"cruise_{daysim.KINDS[v['kind'][i]]}",
                      CRUISE_TYPE[int(v["kind"][i])], int(ps.draw(o, 1, trng)[0]),
                      int(pe.draw(dd, 1, trng)[0]), int(v["j"][i])))
    local, roads = (local_road_trips(net, m, day.pre, trng, args.scale) if day.pre is not None
                    else ([], {}))
    trips += local
    stops, bus_list, bus_data = ([], [], None) if args.no_buses else bus_trips(net, d, trng, log)
    stops = stops or {}

    # bus stops and the trips file
    with open(run_dir / "busstops.add.xml", "w", encoding="utf-8", newline="\n") as f:
        f.write("<additional>\n")
        for bs, (i, a, b, name) in stops.items():
            nm = name.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
            f.write(f'  <busStop id="{bs}" lane="{net.ids[i]}_0" startPos="{a}" endPos="{b}" '
                    f'name="{nm}"/>\n')
        f.write("</additional>\n")
    counts = write_trips(run_dir / "trips.xml.gz", net, trips, bus_list)
    write_configs(run_dir, args.net.resolve(), args.threads, args.seed, args.sim_threads)
    log(f"trips: {sum(v for k, v in counts.items() if k not in ('dropped_no_edge', 'same_edge'))} "
        f"written ({counts})")

    # corridor mapping and the macro reference for sumo_compare.py
    corr = {}
    for cid, label, group, idx in ctx.corr:
        mapped = match_edges(net, m, idx)
        corr[cid] = {"label": label, "group": group, "macro_edges": [int(k) for k in idx],
                     "sumo": mapped,
                     "north": {str(int(k)): bool(tm.heading_north(m, int(k))) for k in idx}}
        log(f"corridor {label}: {len(idx)} macro edges -> {len(mapped)} SUMO edges")
    probe = sd.m271_probe(m)
    (run_dir / "edges.json").write_text(json.dumps({
        "corridors": corr, "local_roads": roads, "catchments": cinfo,
        "m271_probe": {"macro_edges": probe, "sumo": match_edges(net, m, probe)},
    }, indent=1), encoding="utf-8")
    np.savez_compressed(run_dir / "macro.npz", x=res["x"].astype(np.float32),
                        queue=res["queue"].astype(np.float32), held=res["held"],
                        cap=cap, t0=m.t0, length=m.length,
                        pre=(day.pre if day.pre is not None
                             else np.zeros_like(res["x"])).astype(np.float32))
    bus_rows = []
    for _t, vid, _fr, _to, seq, route in bus_list:
        bus_rows.append({"id": vid, "route": route, "stops": seq})
    (run_dir / "buses.json").write_text(json.dumps({
        "stops": {bs: {"edge": net.ids[i], "name": nm} for bs, (i, a, b, nm) in stops.items()},
        "trips": bus_rows,
        "routes": (bus_data or {}).get("routes", {}),
        "source": (bus_data or {}).get("source"),
    }), encoding="utf-8")
    groups = {g: np.round(val * 4).astype(int).tolist() for g, val in day.groups.items()}
    (run_dir / "macro.json").write_text(json.dumps({
        "groups_veh_per_h": groups,
        "cruise_veh_per_h": np.round(Dc.sum(axis=1) * 4).astype(int).tolist(),
        "match_veh_per_h": np.round(day.Dm.sum(axis=1) * 4).astype(int).tolist(),
        "bus_table": (macro_bus or {}).get("table"),
    }), encoding="utf-8")
    meta = {"date": args.date, "seed": args.seed, "scale": args.scale, "git": git_head(),
            "calls": [{"ship": c.ship, "terminal": c.terminal, "pax": c.pax, "times": c.times,
                       "arrival": c.arrival.isoformat(), "departure": c.departure.isoformat()}
                      for c in task["calls"]],
            "closed": task["closed"], "match": task["match"], "term": task["term"],
            "freight_f": task.get("freight_f"), "cruise": cruise,
            "sampled": {"wet": day.wet, "incident": bool(day.events),
                        "note": "macro reference and SUMO run on dry roads with no incident"},
            "counts": counts, "vtypes": VTYPES, "made": clock.strftime("%Y-%m-%dT%H:%M")}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"wrote {run_dir}")


if __name__ == "__main__":
    main()
