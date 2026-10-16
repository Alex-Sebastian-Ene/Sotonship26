"""Dynamic traffic model on the real Southampton road network.

Structure comes from geography (OpenStreetMap, via osm_base.py):

* roads, junctions, one-way streets, lanes and speed limits;
* zones: OSM place points (suburbs, towns). Each zone's homes, jobs and shops come from the area of
  residential, commercial/retail/industrial/port and retail land use nearest to it;
* county gateways: where motorways, trunk and A roads cross the edge of the study area.

Demand has real structure and invented totals. Commuters come in from the rest of the county to the
area's jobs and go home again, residents commute out, people travel between zones (gravity model),
through traffic crosses between gateways, county visitors come to the shops, and on match days
fans travel to St Mary's. Cruise traffic is added per ship call.

Allocation is dynamic. Every 15 minutes all of that traffic shares the network. Each origin-
destination flow is split over up to three routes and shifted towards the routes drivers think are
quickest, given the congestion everyone else causes (method of successive averages with BPR travel
times). Drivers are not perfect: each sampled day they misjudge each road's speed, and everyone
using a road shares that misjudgement, so routes that overlap are misjudged together (correlated
perception noise), and they choose with a logit rule rather than all taking the single quickest.
Traffic that cannot get through a route's bottleneck in those 15 minutes waits and joins the next
15 minutes (a point queue), so queues build and clear through the day.

Demand is noisy in correlated ways: a day-wide factor shared by every kind of trip, a factor per
kind of trip, 15-minute noise that persists (a busy 08:00 is followed by a busy 08:15), and zone
factors that move together for neighbouring zones.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

N_BINS = 60  # 05:00-20:00 in 15-minute steps
DAY_START_H = 5
AT_RISK = 0.85
ROUTES = 3
CARRY = 0.8  # share of traffic stuck in a queue that is still waiting 15 minutes later
LOGIT_BETA = 6.0  # route choice: a route 10% slower than the best gets exp(-0.6) of its weight
NOISE = {"day": 0.04, "purpose": 0.04, "bin": 0.05, "rho": 0.8, "zone": 0.08, "zone_km": 2.0}
LOCAL = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
         "unclassified"}
GATEWAY_WEIGHT = {"motorway": 6.0, "trunk": 3.0, "primary": 2.0, "secondary": 1.0}
GATEWAY_HINT = {  # which part of the county each gateway road brings traffic from
    "M27 west": "New Forest, Bournemouth",
    "M27 east": "Fareham, Portsmouth",
    "M3 north": "Winchester, London",
    "M27 north": "Winchester, London",
    "M271 north": "Romsey, Test Valley",
}

# Hourly shapes (24 values, any scale) for each kind of trip
PROFILES = {
    "am_in": [0, 0, 0, 0, .3, 1.2, 4, 9, 10, 5, 2.2, 1.6, 1.6, 1.4, 1.2, 1.1, 1, .9, .6, .4, .3, .2, .1, 0],
    "pm_out": [0, 0, 0, 0, 0, .2, .4, .6, .8, 1, 1.2, 1.5, 1.8, 1.8, 2, 3.5, 8, 10, 6, 2.5, 1.2, .6, .3, .1],
    "internal_wk": [.2, .1, .1, .1, .3, 1, 3, 7, 8, 5, 4.5, 4.8, 5.2, 5, 5, 5.5, 7, 7.5, 6, 4, 3, 2, 1, .5],
    "internal_we": [.3, .2, .1, .1, .2, .5, 1, 2, 3.5, 5, 6.5, 7, 7, 6.8, 6.5, 6, 5.5, 5, 4.5, 3.5, 2.5, 1.8, 1, .5],
    "through": [1, .8, .7, .8, 1.5, 3, 5, 7, 7, 6, 5.5, 5.5, 5.5, 5.5, 5.8, 6.5, 7.5, 7.5, 6, 4.5, 3.5, 2.5, 1.8, 1.2],
    "visit_in": [0, 0, 0, 0, 0, .1, .3, .8, 2, 4.5, 7, 8, 7, 5, 3.5, 2.5, 1.5, 1, .6, .4, .2, .1, 0, 0],
    "visit_out": [0, 0, 0, 0, 0, 0, .1, .2, .5, 1, 2, 3.5, 5, 6.5, 7, 7, 6, 4.5, 3, 1.8, 1, .5, .2, 0],
    "school_am": [0, 0, 0, 0, 0, 0, 0, .6, 10, .4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "school_am_back": [0, 0, 0, 0, 0, 0, 0, .2, 8, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "school_pm": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, .8, 10, .8, 0, 0, 0, 0, 0, 0, 0],
    "school_pm_back": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, .2, 8, 3, .3, 0, 0, 0, 0, 0, 0],
}

# key, chart group, origins, destinations, daily car trips (weekday, Saturday, Sunday),
# profile (weekday, weekend). Totals are invented and scaled by calibrate().
PURPOSES = [
    ("county_in", "county", "gateway", "jobs", (42000, 11000, 6000), ("am_in", "visit_in")),
    ("county_home", "county", "jobs", "gateway", (42000, 11000, 6000), ("pm_out", "visit_out")),
    ("out", "outbound", "homes", "gateway", (22000, 8000, 6000), ("am_in", "visit_in")),
    ("out_home", "outbound", "gateway", "homes", (22000, 8000, 6000), ("pm_out", "visit_out")),
    ("internal", "internal", "zones", "zones", (150000, 140000, 110000), ("internal_wk", "internal_we")),
    ("through", "through", "gateway", "gateway", (60000, 48000, 42000), ("through", "through")),
    ("visit_in", "visitors", "gateway", "retail", (6000, 26000, 18000), ("visit_in", "visit_in")),
    ("visit_home", "visitors", "retail", "gateway", (6000, 26000, 18000), ("visit_out", "visit_out")),
    # school run: term-time weekdays only, parents driving children and driving back
    ("school_drop", "school", "homes", "schools", (9000, 0, 0), ("school_am", "school_am")),
    ("school_drop_home", "school", "schools", "homes", (6000, 0, 0), ("school_am_back", "school_am_back")),
    ("school_pick", "school", "homes", "schools", (6000, 0, 0), ("school_pm", "school_pm")),
    ("school_pick_home", "school", "schools", "homes", (9000, 0, 0), ("school_pm_back", "school_pm_back")),
]
SCHOOL_KEYS = {"school_drop", "school_drop_home", "school_pick", "school_pick_home"}
EXTERNAL = {"county", "outbound", "through", "visitors"}
GROUPS = {
    "county": "Commuters from the county",
    "outbound": "Residents working outside",
    "internal": "Trips within the area",
    "school": "School run",
    "through": "Through traffic",
    "visitors": "Visitors from the county",
    "match": "Match day",
    "cruise": "Cruise traffic",
}
MATCH_FANS_CARS = 9000
SHORT_TRIP_M = 1200  # internal trips shorter than this mostly use residential streets or walk
# Mid-link capacity per lane (vehicles/hour) by road class, replacing the junction-limited values
# osm_base.py stores; the model's links are road sections between junctions.
CAP_LANE = {"motorway": 2000, "motorway_link": 1600, "trunk": 1800, "trunk_link": 1400,
            "primary": 1400, "primary_link": 1200, "secondary": 1200, "secondary_link": 1000,
            "tertiary": 1000, "tertiary_link": 900, "unclassified": 800}


def bin_profile(shape) -> np.ndarray:
    """Share of a day's trips in each 15-minute bin from 05:00 to 20:00."""
    h = np.asarray(shape, float)
    h = h / h.sum()
    centres = DAY_START_H + (np.arange(N_BINS) + 0.5) / 4
    return np.interp(centres, np.arange(24) + 0.5, h) / 4


def daytype(weekday: int) -> int:
    return 1 if weekday == 5 else 2 if weekday == 6 else 0


@dataclass
class Centroid:
    name: str
    kind: str  # zone, gateway, gate, station, stadium
    node: int
    xy: tuple[int, int]
    homes: float = 0.0
    jobs: float = 0.0
    retail: float = 0.0
    schools: float = 0.0
    weight: float = 0.0
    hint: str = ""


@dataclass
class Model:
    xy: np.ndarray  # node positions on the page grid
    eu: np.ndarray  # edge from-node
    ev: np.ndarray  # edge to-node
    t0: np.ndarray  # free-flow seconds
    cap: np.ndarray  # vehicles per hour
    length: np.ndarray
    cls: list
    name: list
    ref: list
    coords: list
    centroids: list[Centroid]
    ods: list[tuple[int, int]]
    od_index: dict
    purpose_od: dict  # purpose -> OD weights (sum 1)
    paths: list[list[int]]  # ROUTES per OD, edge indices
    A: sp.csr_matrix = field(repr=False)
    AT: sp.csr_matrix = field(repr=False)
    col_idx: np.ndarray = field(repr=False)  # edge indices per path, concatenated
    col_ptr: np.ndarray = field(repr=False)
    uniq: np.ndarray = field(default=None, repr=False)  # n_od x ROUTES, False for padded duplicates
    od_zone: np.ndarray = field(default=None, repr=False)  # n_od x 2 zone index of origin/dest, -1 if none
    zone_kernel: np.ndarray = field(default=None, repr=False)  # zones x zones smoothing for zone noise
    scale: float = 1.0  # trips within the area (fitted to council counts)
    scale_ext: float = 1.0  # trips to, from and through the county (fitted to main-road loads)
    pre: dict = field(default_factory=dict)  # day type -> (bins, edges) local traffic on counted roads
    size: tuple[int, int] = (0, 0)
    sets: dict = field(default_factory=dict)  # named origin sets for cruise and match demand

    @property
    def n_od(self) -> int:
        return len(self.ods)

    def centroid(self, kind: str, name: str | None = None) -> int:
        for i, c in enumerate(self.centroids):
            if c.kind == kind and (name is None or c.name == name):
                return i
        raise KeyError((kind, name))


# --- building the model from the OSM network ---------------------------------------------------

def build(net_path: Path, gates: dict[str, tuple[int, int]], log=print) -> Model:
    with open(net_path, "rb") as f:
        net = pickle.load(f)
    g = net["graph"]
    W, H = net["size"]
    nodes = list(g.nodes)
    nid = {n: i for i, n in enumerate(nodes)}
    xy = np.array([g.nodes[n]["xy"] for n in nodes], float)
    edges = list(g.edges(data=True))
    eu = np.array([nid[u] for u, _, _ in edges])
    ev = np.array([nid[v] for _, v, _ in edges])
    t0 = np.array([d["t0"] for *_, d in edges])
    cap = np.array([float(d["lanes"] * CAP_LANE.get(d["cls"], 800)) for *_, d in edges])
    length = np.array([d["length"] for *_, d in edges])
    cls = [d["cls"] for *_, d in edges]
    name = [d["name"] for *_, d in edges]
    ref = [d["ref"] for *_, d in edges]
    coords = [d["coords"] for *_, d in edges]
    n = len(nodes)
    log(f"network: {n} nodes, {len(edges)} directed edges")

    # nodes a local trip can start from (not motorway or trunk carriageways)
    local_nodes = np.zeros(n, bool)
    for k, c in enumerate(cls):
        if c in LOCAL:
            local_nodes[eu[k]] = local_nodes[ev[k]] = True
    local_ids = np.flatnonzero(local_nodes)
    local_tree = cKDTree(xy[local_ids])

    def snap(p) -> int:
        return int(local_ids[local_tree.query(p)[1]])

    # zones from OSM places, merged when closer than 700 m
    priority = {"town": 0, "suburb": 1, "quarter": 2, "neighbourhood": 3, "village": 4}
    places = sorted(net["places"], key=lambda p: priority.get(p["kind"], 9))
    zones: list[Centroid] = []
    for p in places:
        if any(math.dist((p["x"], p["y"]), z.xy) < 700 for z in zones):
            continue
        zones.append(Centroid(p["name"], "zone", snap((p["x"], p["y"])), (p["x"], p["y"])))
    tree = cKDTree([z.xy for z in zones])
    for kind, x, y, area in net["samples"]:
        d, i = tree.query((x, y))
        if d > 3000:
            continue
        z = zones[i]
        if kind == "residential":
            z.homes += area
        elif kind == "commercial":
            z.jobs += area
            z.retail += area
        elif kind == "industrial":
            z.jobs += 0.6 * area
        elif kind == "port":
            z.jobs += 0.4 * area
        elif kind == "campus":
            z.jobs += 1.2 * area
        elif kind == "airport":
            z.jobs += 0.3 * area
        elif kind == "school":
            z.schools += area
    total = sum(z.homes + z.jobs for z in zones)
    zones = [z for z in zones if z.homes + z.jobs > 0.002 * total]
    log(f"zones: {len(zones)} (from {len(places)} OSM places)")

    # county gateways: major roads near the edge of the study area
    rank = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3}
    node_class = {}
    for k, c in enumerate(cls):
        base = c.replace("_link", "")
        if base in rank:
            for v in (eu[k], ev[k]):
                if v not in node_class or rank[base] < rank[node_class[v][0]]:
                    node_class[v] = (base, ref[k] or name[k])
    edge_dist = np.minimum.reduce([xy[:, 0], xy[:, 1], W - xy[:, 0], H - xy[:, 1]])
    cands = sorted((i for i in node_class if edge_dist[i] < 1500),
                   key=lambda i: (rank[node_class[i][0]], edge_dist[i]))
    gateways: list[Centroid] = []
    for i in cands:
        if any(math.dist(xy[i], gw.xy) < 2200 for gw in gateways):
            continue
        base, road = node_class[i]
        side = ["west", "north", "east", "south"][int(np.argmin(
            [xy[i, 0], xy[i, 1], W - xy[i, 0], H - xy[i, 1]]))]
        label = f"{road.split(';')[0]} {side}".strip()
        gateways.append(Centroid(label, "gateway", int(i), tuple(int(v) for v in xy[i]),
                                 weight=GATEWAY_WEIGHT[base],
                                 hint=GATEWAY_HINT.get(label, "rest of Hampshire")))
    log("gateways: " + ", ".join(f"{gw.name} ({gw.weight:g})" for gw in gateways))

    specials = []
    for gname, p in gates.items():
        specials.append(Centroid(gname, "gate", snap(p), tuple(p)))
    lm = net["landmarks"]
    if "station" in lm:
        specials.append(Centroid("Southampton Central", "station", snap(lm["station"]), tuple(lm["station"])))
    if "stadium" in lm:
        specials.append(Centroid("St Mary's Stadium", "stadium", snap(lm["stadium"]), tuple(lm["stadium"])))
    centroids = zones + gateways + specials
    Z = [i for i, c in enumerate(centroids) if c.kind == "zone"]
    G_ = [i for i, c in enumerate(centroids) if c.kind == "gateway"]

    def norm(w):
        w = np.asarray(w, float)
        return w / w.sum()

    homes = norm([centroids[i].homes for i in Z])
    jobs = norm([centroids[i].jobs for i in Z])
    retail = norm([centroids[i].retail + 1e-9 for i in Z])
    if sum(centroids[i].schools for i in Z) > 0:
        schools = norm([centroids[i].schools + 1e-9 for i in Z])
    else:  # no school locations available: schools roughly follow where people live
        log("schools: no OSM school locations, using homes as a stand-in")
        schools = homes
    gw = norm([centroids[i].weight for i in G_])
    sets = {"homes": (Z, homes), "jobs": (Z, jobs), "retail": (Z, retail), "gateway": (G_, gw),
            "schools": (Z, schools)}
    zxy = np.array([centroids[i].xy for i in Z], float)
    zdist = np.hypot(*(zxy[:, None, :] - zxy[None, :, :]).transpose(2, 0, 1))

    # OD weights per purpose
    od_weight: dict[str, dict[tuple[int, int], float]] = {}
    for key, _, o_set, d_set, _, _ in PURPOSES:
        w: dict[tuple[int, int], float] = {}
        if key == "internal" or key in SCHOOL_KEYS:
            dist = zdist
            if key == "internal":
                T = homes[:, None] * (jobs + 0.5 * homes + 0.8 * retail)[None, :] * np.exp(-dist / 3000.0)
            elif o_set == "homes":
                T = homes[:, None] * schools[None, :] * np.exp(-dist / 1800.0)
            else:
                T = schools[:, None] * homes[None, :] * np.exp(-dist / 1800.0)
            T[dist < SHORT_TRIP_M] = 0
            flat = np.sort(T.ravel())[::-1]
            cut = flat[np.searchsorted(np.cumsum(flat), 0.92 * flat.sum())]
            for a, b in zip(*np.nonzero(T >= cut), strict=True):
                w[(Z[a], Z[b])] = T[a, b]
        elif key == "through":
            for a in range(len(G_)):
                for b in range(len(G_)):
                    if a != b and math.dist(centroids[G_[a]].xy, centroids[G_[b]].xy) > 6000:
                        strategic = min(centroids[G_[a]].weight, centroids[G_[b]].weight) >= 3
                        w[(G_[a], G_[b])] = gw[a] * gw[b] * (1.0 if strategic else 0.15)
        else:
            oi, ow = sets[o_set]
            di, dw = sets[d_set]
            for a, wa in zip(oi, ow, strict=True):
                for b, wb in zip(di, dw, strict=True):
                    if a != b and wa * wb > 1e-5:
                        w[(a, b)] = wa * wb
        s = sum(w.values())
        od_weight[key] = {k: v / s for k, v in w.items()}

    # cruise and match origins
    st = [i for i, c in enumerate(centroids) if c.kind == "station"]
    centre = Z[int(np.argmin([math.dist(centroids[i].xy, lm.get("westquay", centroids[i].xy))
                              for i in Z]))]
    motor = [i for i in G_ if centroids[i].weight >= GATEWAY_WEIGHT["trunk"]]
    sets["car_from"] = (G_ + Z, norm(list(0.8 * gw) + list(0.2 * homes)))
    sets["taxi_rank"] = (st + [centre], norm([0.7] * len(st) + [0.3]))
    sets["taxi_far"] = (st + G_ + Z, norm([0.5] * len(st) + list(0.3 * gw) + list(0.2 * homes)))
    sets["coach_from"] = (motor, norm([centroids[i].weight for i in motor]))
    sets["fans_from"] = (G_ + Z, norm(list(0.6 * gw) + list(0.4 * homes)))

    pairs = set()
    for w in od_weight.values():
        pairs |= set(w)
    gate_ids = [i for i, c in enumerate(centroids) if c.kind == "gate"]
    for gate in gate_ids:
        for key in ("car_from", "taxi_rank", "taxi_far", "coach_from"):
            for o in sets[key][0]:
                pairs |= {(o, gate), (gate, o)}
    stadium = [i for i, c in enumerate(centroids) if c.kind == "stadium"]
    for s_ in stadium:
        for o in sets["fans_from"][0]:
            pairs |= {(o, s_), (s_, o)}
    pairs = sorted(p for p in pairs if centroids[p[0]].node != centroids[p[1]].node)
    od_index = {p: j for j, p in enumerate(pairs)}
    purpose_od = {}
    for key, w in od_weight.items():
        vec = np.zeros(len(pairs))
        for p, v in w.items():
            if p in od_index:
                vec[od_index[p]] = v
        purpose_od[key] = vec / vec.sum()
    log(f"origin-destination pairs: {len(pairs)}")

    # candidate routes: quickest, then two alternatives that avoid the earlier ones
    csr = sp.csr_matrix((t0, (eu, ev)), shape=(n, n))
    edge_of = {(int(a), int(b)): k for k, (a, b) in enumerate(zip(eu, ev, strict=True))}
    important = np.zeros(len(pairs), bool)
    total_w = sum(purpose_od.values())
    important[total_w >= np.quantile(total_w, 0.5)] = True
    for p, j in od_index.items():
        if centroids[p[0]].kind in ("gate", "stadium") or centroids[p[1]].kind in ("gate", "stadium"):
            important[j] = True

    def trace(pred, src, dst):
        out, v = [], dst
        while v != src:
            u = pred[v]
            if u < 0:
                return None
            out.append(edge_of[(int(u), int(v))])
            v = u
        return out[::-1]

    origins = sorted({centroids[o].node for o, _ in pairs})
    _, pred0 = dijkstra(csr, indices=origins, return_predecessors=True)
    row = {o: r for r, o in enumerate(origins)}
    paths: list[list[int]] = []
    for (o, d), j in od_index.items():
        src, dst = centroids[o].node, centroids[d].node
        base = trace(pred0[row[src]], src, dst)
        if base is None:
            raise RuntimeError(f"no route {centroids[o].name} -> {centroids[d].name}")
        found = [base]
        if important[j]:
            w = t0.copy()
            limit = 1.5 * t0[base].sum()
            for _ in range(ROUTES - 1):
                w[found[-1]] *= 1.6
                _, pr = dijkstra(sp.csr_matrix((w, (eu, ev)), shape=(n, n)), indices=src,
                                 return_predecessors=True)
                alt = trace(pr, src, dst)
                if alt and alt not in found and t0[alt].sum() <= limit:
                    found.append(alt)
        while len(found) < ROUTES:
            found.append(found[0])
        paths += found
    log(f"candidate routes: {len(paths)} ({important.sum()} pairs with alternatives)")

    uniq = np.ones((len(pairs), ROUTES), bool)
    for j in range(len(pairs)):
        for r in range(1, ROUTES):
            if paths[j * ROUTES + r] in paths[j * ROUTES: j * ROUTES + r]:
                uniq[j, r] = False
    zpos = {ci: k for k, ci in enumerate(Z)}
    od_zone = np.array([[zpos.get(o, -1), zpos.get(d, -1)] for o, d in pairs])
    kern = np.exp(-(zdist / (NOISE["zone_km"] * 1000.0)) ** 2)
    kern /= np.sqrt((kern ** 2).sum(axis=1, keepdims=True))
    rows = np.concatenate([np.asarray(p) for p in paths])
    cols = np.repeat(np.arange(len(paths)), [len(p) for p in paths])
    A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(t0), len(paths)))
    col_ptr = np.concatenate([[0], np.cumsum([len(p) for p in paths])])[:-1]
    return Model(xy=xy, eu=eu, ev=ev, t0=t0, cap=cap, length=length, cls=cls, name=name, ref=ref,
                 coords=coords, centroids=centroids, ods=pairs, od_index=od_index,
                 purpose_od=purpose_od, paths=paths, A=A, AT=A.T.tocsr(), col_idx=rows,
                 col_ptr=col_ptr, size=(W, H), sets=sets, uniq=uniq, od_zone=od_zone,
                 zone_kernel=kern)


# --- demand ------------------------------------------------------------------------------------

def ar1(rng: np.random.Generator, n: int, sd: float, rho: float) -> np.ndarray:
    """Multiplicative noise that persists from one 15-minute bin to the next."""
    e = np.empty(n)
    e[0] = rng.normal(0.0, sd)
    for i in range(1, n):
        e[i] = rho * e[i - 1] + math.sqrt(1 - rho**2) * rng.normal(0.0, sd)
    return np.exp(e - sd**2 / 2)


def background(m: Model, dtype: int, rng: np.random.Generator | None = None, term: bool = True,
               spread: float = 1.0, mult: dict | None = None):
    """Vehicles per bin for each OD pair, and per chart group, for one day type.

    With ``rng`` the day is noisy in correlated ways (see the module docstring); ``spread`` widens
    the noise for dates further ahead, and ``mult`` scales chosen purposes (season, weather).
    """
    D = np.zeros((N_BINS, m.n_od))
    groups = {}
    od_mult = 1.0
    day = 1.0
    if rng is not None:
        day = rng.lognormal(0.0, NOISE["day"] * spread)
        z = m.zone_kernel @ rng.normal(0.0, NOISE["zone"] * spread, m.zone_kernel.shape[0])
        zf = np.exp(z)
        oz, dz = m.od_zone[:, 0], m.od_zone[:, 1]
        od_mult = np.where(oz >= 0, zf[np.maximum(oz, 0)], 1.0) * np.where(dz >= 0, zf[np.maximum(dz, 0)], 1.0)
    for key, group, _, _, totals, profiles in PURPOSES:
        if key in SCHOOL_KEYS and not (term and dtype == 0):
            continue
        prof = bin_profile(PROFILES[profiles[0 if dtype == 0 else 1]])
        total = totals[dtype] * (m.scale_ext if group in EXTERNAL else m.scale) * day
        if mult:
            total *= mult.get(group, mult.get("all", 1.0))
        if rng is not None:
            total *= rng.lognormal(0.0, NOISE["purpose"] * spread)
            prof = prof * ar1(rng, N_BINS, NOISE["bin"] * spread, NOISE["rho"])
        D += np.outer(prof * total, m.purpose_od[key] * od_mult)
        groups[group] = groups.get(group, 0) + prof * total
    return D, groups


def match_demand(m: Model, kickoff_h: float, rng: np.random.Generator | None = None):
    D = np.zeros((N_BINS, m.n_od))
    s = m.centroid("stadium")
    o_ids, o_w = m.sets["fans_from"]
    centres = DAY_START_H + (np.arange(N_BINS) + 0.5) / 4
    arrive = np.clip(1 - np.abs(centres - (kickoff_h - 1.0)) / 1.5, 0, None)
    leave = np.clip(1 - np.abs(centres - (kickoff_h + 2.25)) / 0.6, 0, None)
    cars = MATCH_FANS_CARS * (rng.lognormal(0, 0.08) if rng is not None else 1.0)
    for prof, to_stadium in ((arrive, True), (leave, False)):
        if prof.sum() == 0:
            continue
        prof = prof / prof.sum() * cars
        for o, w in zip(o_ids, o_w, strict=True):
            j = m.od_index.get((o, s) if to_stadium else (s, o))
            if j is not None:
                D[:, j] += prof * w
    return D


# --- dynamic assignment ------------------------------------------------------------------------

def equilibrium_bin(m: Model, rate: np.ndarray, cap: np.ndarray, shares: np.ndarray, iters: int,
                    pre=0.0, noise: np.ndarray | None = None):
    """Split each OD's flow (veh/h) over its routes, moving towards the routes drivers think are
    quickest. ``noise`` multiplies each road's perceived travel time (shared by everyone on it).
    Returns path flows."""
    f = (shares * rate[:, None]).ravel()
    for k in range(iters):
        v = m.A @ f + pre
        t = m.t0 * (1.0 + 0.15 * (v / cap) ** 4)
        if noise is not None:
            t = t * noise
        c = (m.AT @ t).reshape(m.n_od, ROUTES)
        rel = c / np.maximum(c.min(axis=1, keepdims=True), 30.0)
        w = np.exp(-LOGIT_BETA * (rel - 1.0)) * m.uniq
        y = w / w.sum(axis=1, keepdims=True) * rate[:, None]
        f += (y.ravel() - f) / (k + 2)
    return f


def run_day(m: Model, D: np.ndarray, cap: np.ndarray, shares0: np.ndarray, iters: int,
            cruise: np.ndarray | None = None, want=("x",), pre: np.ndarray | None = None,
            noise: np.ndarray | None = None, events=()):
    """Route one day bin by bin, carrying unserved traffic forward as queues.

    D: vehicles per bin per OD (all traffic), cruise: the cruise part of D (or None).
    Returns a dict of per-bin arrays and the route shares to warm-start from next time.
    """
    queue = np.zeros(m.n_od)
    cruise_queue = np.zeros(m.n_od)
    out = {k: [] for k in want}
    shares = np.empty_like(shares0)
    for b in range(N_BINS):
        veh = D[b] + queue
        rate = veh * 4.0
        pb = pre[b] if pre is not None else 0.0
        capb = cap
        for edges, b0, b1, factor in events:  # incidents: capacity drops for a while
            if b0 <= b < b1:
                capb = capb.copy() if capb is cap else capb
                capb[edges] *= factor
        f = equilibrium_bin(m, rate, capb, shares0[b], iters, pb, noise)
        v = m.A @ f + pb
        x = v / capb
        bottleneck = np.maximum.reduceat(x[m.col_idx], m.col_ptr)
        if "delay" in out:
            out["delay"].append(delay_minutes(m, x))
        served = f / np.maximum(bottleneck, 1.0)
        unserved = CARRY * (f - served).reshape(m.n_od, ROUTES).sum(axis=1) / 4.0
        cap_now = capb
        with np.errstate(invalid="ignore", divide="ignore"):
            sh = np.where(rate[:, None] > 0, f.reshape(m.n_od, ROUTES) / rate[:, None], shares0[b])
        shares[b] = sh
        if "x" in out:
            out["x"].append(x)
        if "queue" in out:
            out["queue"].append(np.maximum(v - cap_now, 0.0) / 4.0)
        if cruise is not None:
            c_veh = cruise[b] + cruise_queue
            frac = np.divide(c_veh, veh, out=np.zeros_like(veh), where=veh > 0)
            fc = f * np.repeat(frac, ROUTES)
            if "cruise_edge" in out:
                out["cruise_edge"].append(m.A @ fc)
            if "cruise_path" in out:
                out["cruise_path"].append(fc)
            cruise_queue = unserved * frac
        if "path" in out:
            out["path"].append(sh)
        if "time" in out:
            t = m.t0 * (1.0 + 0.15 * x**4)
            out["time"].append((m.AT @ t).reshape(m.n_od, ROUTES))
        if "held" in out:
            out["held"].append(unserved.sum())
        queue = unserved
    return {k: np.asarray(v) for k, v in out.items()}, shares


def initial_shares(m: Model) -> np.ndarray:
    s = np.zeros((N_BINS, m.n_od, ROUTES))
    s[:, :, 0] = 1.0
    return s


def calibrate(m: Model, target: float = 0.8, log=print) -> None:
    """Scale the invented trip totals so weekday peak loads on main roads look like a busy city."""
    main = np.array([c.replace("_link", "") in ("motorway", "trunk", "primary") for c in m.cls])
    for _ in range(3):
        D, _ = background(m, 0)
        x_peaks = []
        for b in (12, 48):  # 08:00 and 17:00
            f = equilibrium_bin(m, D[b] * 4.0, m.cap, initial_shares(m)[b], 25)
            x_peaks.append((m.A @ f) / m.cap)
        x = np.max(x_peaks, axis=0)[main]
        w = m.length[main]
        live = x > 0.05
        order = np.argsort(x[live])
        cum = np.cumsum(w[live][order]) / w[live].sum()
        p85 = x[live][order][np.searchsorted(cum, 0.85)]
        m.scale *= (target / p85) ** 0.8
        log(f"calibrate: weighted 85th percentile peak load {p85:.2f} -> scale {m.scale:.2f}")


# --- calibration against observed counts -------------------------------------------------------

DAY_WINDOW_SHARE = 0.88  # assumed share of 24-hour traffic between 05:00 and 20:00
PERIODS = {"am": (8, 20), "pm": (44, 56), "day": (0, N_BINS)}  # 07-10, 16-19, 05-20


def flows(m: Model, D: np.ndarray, cap: np.ndarray, iters: int = 8, pre=None) -> np.ndarray:
    """Vehicles per hour on every edge in every bin for a deterministic day."""
    res, _ = run_day(m, D, cap, initial_shares(m), iters, want=("x",), pre=pre)
    return res["x"] * cap


def road_edges(m: Model, names, min_length: float = 40.0) -> list[int]:
    """Edges of a named road, keeping only its main class (drops slip roads and service stubs)."""
    idx = [k for k in range(len(m.t0)) if m.name[k] in names and m.length[k] >= min_length]
    by: dict[str, float] = {}
    for k in idx:
        by[m.cls[k]] = by.get(m.cls[k], 0.0) + m.length[k]
    if not by:
        return []
    main = max(by, key=by.get)
    return [k for k in idx if m.cls[k] == main]


def two_way(m: Model, v: np.ndarray, edges, q: float = 50) -> np.ndarray:
    """A percentile (median by default) over a road's links of the two-way flow, per bin."""
    pair: dict[tuple[int, int], list[int]] = {}
    for k in edges:
        pair.setdefault((min(m.eu[k], m.ev[k]), max(m.eu[k], m.ev[k])), []).append(k)
    cols = [v[:, ks].sum(axis=1) for ks in pair.values()]
    return np.percentile(np.stack(cols, axis=1), q, axis=1)


def calibrate_to_counts(m: Model, sites: list[dict], log=print,
                        grid=(0.35, 0.5, 0.65, 0.8, 0.95, 1.1, 1.3, 1.5)) -> list[dict]:
    """Pick the trip-total scale whose weekday 07-10 and 16-19 flows, summed over the count sites,
    best match the observed sums.

    Flows on any one local road depend on route choice (traffic spills onto it as the main roads
    fill), so the fit uses the total across sites, and is a grid search rather than a proportional
    update. Per-road, Saturday and all-day figures are not fitted; they are reported as checks.
    """
    base = m.scale
    best = None
    for g in grid:
        m.scale = base * g
        v = {dt: flows(m, background(m, dt)[0], m.cap) for dt in (0, 1)}
        rows = []
        tot = {"am": [0.0, 0.0], "pm": [0.0, 0.0]}
        for s_ in sites:
            edges = road_edges(m, s_["names"])
            if not edges:
                continue
            for dt, key in ((0, "weekday"), (1, "saturday")):
                tw = two_way(m, v[dt], edges, q=80) / 4.0
                for per, (a, b) in PERIODS.items():
                    obs = float(sum(s_[key][per])) * (DAY_WINDOW_SHARE if per == "day" else 1.0)
                    mod = float(tw[a:b].sum())
                    rows.append({"road": s_["label"], "day": key, "period": per,
                                 "observed": round(obs), "modelled": round(mod),
                                 "fitted": dt == 0 and per != "day"})
                    if dt == 0 and per in tot:
                        tot[per][0] += obs
                        tot[per][1] += mod
        err = math.sqrt(np.mean([math.log((o + 1) / (md + 1)) ** 2 for o, md in tot.values()]))
        log(f"calibrate: scale {m.scale:.2f} -> sum AM {tot['am'][1]:.0f}/{tot['am'][0]:.0f}, "
            f"PM {tot['pm'][1]:.0f}/{tot['pm'][0]:.0f} (log error {err:.2f})")
        if best is None or err < best[0]:
            best = (err, m.scale, rows)
    m.scale = best[1]
    log(f"calibrate: chose scale {m.scale:.2f} (log error on site totals {best[0]:.2f})")
    return best[2]


def calibrate_external(m: Model, target: float = 0.85, log=print,
                       grid=(0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 1.0, 1.2)) -> float:
    """Scale county and through trips so weekday peak-hour loads on motorway and trunk roads put
    their length-weighted 85th percentile near ``target``. A stand-in until WebTRIS counts are used.
    """
    strategic = np.array([c in ("motorway", "trunk") for c in m.cls])
    peak = list(range(12, 16)) + list(range(48, 52))  # 08:00-09:00 and 17:00-18:00
    best = None
    for g in grid:
        m.scale_ext = g
        v = flows(m, background(m, 0)[0], m.cap)
        x = (v[peak] / m.cap).max(axis=0)[strategic]
        w = m.length[strategic]
        order = np.argsort(x)
        cum = np.cumsum(w[order]) / w.sum()
        p85 = float(x[order][np.searchsorted(cum, 0.85)])
        log(f"calibrate county traffic: scale {g:.2f} -> motorway/trunk peak load p85 {p85:.2f}")
        if best is None or abs(p85 - target) < best[0]:
            best = (abs(p85 - target), g, p85)
    m.scale_ext = best[1]
    log(f"calibrate county traffic: chose {m.scale_ext:.2f} (p85 {best[2]:.2f})")
    return best[2]



# --- delay, local capacity and local traffic on counted roads -----------------------------------

def delay_minutes(m: Model, x: np.ndarray) -> np.ndarray:
    """Extra minutes per edge: slower running (BPR, capped) plus waiting in a queue at the edge."""
    run = m.t0 * 0.15 * np.minimum(x, 1.5) ** 4 / 60.0
    wait = 15.0 * np.maximum(x - 1.0, 0.0)
    return run + wait


MIN_CAP = 350.0  # floor for a high street with parking, bus stops and crossings (veh/h each way)
UNI_TERM = 1.2  # assumed: July counts miss university term traffic around Highfield and Portswood


def heading_north(m: Model, k: int) -> bool:
    c = m.coords[k]
    return c[-1][1] < c[0][1]  # page y grows southwards


def anchor_counts(m: Model, sites: list[dict], fit_rows: list[dict], log=print) -> list[dict]:
    """Use the counts where we have them.

    1. Capacity: measured peak speeds (16-20 mph on 30 mph roads) show these roads are at their
       limit in the peaks, so the counted peak-hour flow is taken as the throughput per direction
       (floor MIN_CAP). Skipped where the zones alone already put far more traffic on the road
       than was counted, since a lower capacity there would only create a false jam.
    2. Local traffic: traffic the zones do not generate (side streets, short hops) is added to the
       counted roads so their flows match the counts, raised by UNI_TERM for university term.
    """
    over = {}
    for r in fit_rows:
        if r["day"] == "weekday" and r["period"] in ("am", "pm") and r["observed"]:
            over[r["road"]] = max(over.get(r["road"], 0.0), r["modelled"] / r["observed"])
    notes = []
    for s_ in sites:
        edges = road_edges(m, s_["names"])
        if not edges:
            continue
        if over.get(s_["label"], 0.0) > 1.5:
            log(f"capacity {s_['label']}: left at road-class value (model already over the counts)")
            continue
        for d, north in ((0, True), (1, False)):
            peak = max(s_["weekday"][per][d] / 3.0 * 1.15 for per in ("am", "pm"))
            cap = max(MIN_CAP, 0.95 * peak)
            ks = [k for k in edges if heading_north(m, k) == north]
            for k in ks:
                m.cap[k] = min(m.cap[k], cap)
            notes.append({"road": s_["label"], "dir": "northbound" if north else "southbound",
                          "cap": round(cap)})
            log(f"capacity {s_['label']} {'NB' if north else 'SB'}: {cap:.0f} veh/h")

    m.pre = {}
    for dt, key in ((0, "weekday"), (1, "saturday")):
        v = flows(m, background(m, dt)[0], m.cap)
        pre = np.zeros_like(v)
        prof = bin_profile(PROFILES["internal_wk" if dt == 0 else "internal_we"]) * 4  # per hour share
        for s_ in sites:
            edges = road_edges(m, s_["names"])
            if not edges:
                continue
            for d, north in ((0, True), (1, False)):
                ks = [k for k in edges if heading_north(m, k) == north]
                if not ks:
                    continue
                target = np.zeros(N_BINS)
                am, pm = PERIODS["am"], PERIODS["pm"]
                rest = np.ones(N_BINS, bool)
                rest[am[0]:am[1]] = rest[pm[0]:pm[1]] = False
                for (a, b), total in ((am, s_[key]["am"][d]), (pm, s_[key]["pm"][d]),
                                      ((0, N_BINS), None)):
                    if total is None:
                        left = s_[key]["day"][d] * DAY_WINDOW_SHARE - s_[key]["am"][d] - s_[key]["pm"][d]
                        w = prof * rest
                        target += w / w.sum() * max(left, 0) * 4
                    else:
                        w = np.zeros(N_BINS)
                        w[a:b] = prof[a:b]
                        target += w / w.sum() * total * 4
                target *= UNI_TERM
                modelled = np.median(v[:, ks], axis=1)
                extra = np.maximum(target - modelled, 0.0)
                pre[:, ks] += extra[:, None]
        m.pre[dt] = pre
    m.pre[2] = m.pre[1] * 0.85  # Sunday: no count, take Saturday a little lower
    log("local traffic added on counted roads")
    return notes
