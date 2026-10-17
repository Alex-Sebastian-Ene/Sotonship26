"""Dynamic traffic model on the real Southampton road network.

Structure comes from geography (OpenStreetMap, via osm_base.py):

* roads, junctions, one-way streets, lanes and speed limits;
* zones: OSM place points (suburbs, towns). Each zone's homes, jobs and shops come from the area of
  residential, commercial/retail/industrial/port and retail land use nearest to it;
* county gateways: where motorways, trunk and A roads cross the edge of the study area.

Commuters come in from the rest of the county and go home again, and residents commute out: Census
2021 car drivers per MSOA pair, each given the gateway that is quickest for its home and workplace
(census_od). People travel between zones (gravity model), through traffic crosses between gateways,
county visitors come to the shops, and on match days fans travel to St Mary's: real structure,
invented totals. Trips within the area are scaled to council counts; everything crossing the edge
of the area is scaled to DfT counts. Cruise traffic is added per ship call.

Allocation is dynamic. Every 15 minutes all of that traffic shares the network. Each origin-
destination flow is split over up to three routes and shifted towards the routes drivers think are
quickest, given the congestion everyone else causes (method of successive averages with BPR travel
times). Drivers are not perfect: each sampled day they misjudge each road's speed, and everyone
using a road shares that misjudgement, so routes that overlap are misjudged together (correlated
perception noise), and they choose with a logit rule rather than all taking the single quickest.
Traffic that cannot get through a route's bottleneck in those 15 minutes waits and joins the next
15 minutes (a point queue), so queues build and clear through the day.

Demand is noisy in correlated ways: a day-wide factor shared by every kind of trip, a factor per
kind of trip, 15-minute noise that persists (a busy 08:00 is followed by a busy 08:15), both
shared by all trips and per kind of trip, and zone factors that move together for neighbouring
zones.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import external_data as ext
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
# Log-scale noise. shared_bin/shared_rho: 15-minute swings every kind of trip shares, sized so a
# main road shows the 15-min sd ~0.065-0.08 and lag-1 rho ~0.75 seen at WebTRIS M3 J14 / M271
# (the per-purpose "bin" terms are independent, so they partly cancel on a road).
NOISE = {"day": 0.04, "purpose": 0.04, "bin": 0.05, "rho": 0.8, "zone": 0.08, "zone_km": 2.0,
         "shared_bin": 0.072, "shared_rho": 0.8}
LOCAL = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
         "unclassified"}
# Class weights still split through traffic, cruise passengers and match fans between gateways;
# commuters and county visitors use the census (census_od).
GATEWAY_WEIGHT = {"motorway": 6.0, "trunk": 3.0, "primary": 2.0, "secondary": 1.0}
# A gateway is a major-road node this close to the edge of the study area. A motorway that ends gets
# a wider band, because OSM's M27 stops at junction 8, 1.6 km short of the east edge.
GATEWAY_EDGE_M = {"motorway": 2000.0}
GATEWAY_EDGE_DEFAULT_M = 1500.0
# Motorway links absent from the OSM network osm_base.py builds: (what, from (lat, lon), motorway
# there, to (lat, lon), motorway there, lanes). Each end snaps to the nearest node of that motorway.
MISSING_LINKS = [
    ("M3 southbound to M27 eastbound", (50.96128, -1.38826), "M3", (50.94885, -1.39472), "M27", 2),
]
# Census commuters pick a gateway by time: straight line outside the area (times GATEWAY_CIRCUITY,
# at the speed of the gateway's road class) plus the quickest free-flow route inside it, shared
# over gateways by a logit with GATEWAY_LOGIT_S spread. Assumed values.
GATEWAY_KMH = {"motorway": 90.0, "trunk": 70.0, "primary": 55.0, "secondary": 45.0}
GATEWAY_CIRCUITY = 1.3
GATEWAY_LOGIT_S = 300.0

# Car or van drivers commuting into the study area and out of it, Census 2021, MSOA flows within
# 60 km (demo/external_data.py; build() recomputes them and warns if the data differ). Census day
# fell in lockdown, so calibrate_external() rescales all county traffic to DfT counts.
CENSUS_DRIVERS = {"county": 20904, "outbound": 27201}
COMMUTE_DAY = 0.85  # assumed share of commuters travelling on an average weekday (leave, part-time)
WEEKEND = {"county": (0.26, 0.14), "outbound": (0.36, 0.27)}  # assumed Saturday, Sunday vs weekday


DAY_WEIGHTS = (5 / 7, 1 / 7, 1 / 7)  # weekday, Saturday, Sunday in an average day of the year

# The cordon (cordon_od): at each gateway, the DfT count on its road (nearest count point within
# GATEWAY_COUNT_M) minus census commuters and county visitors crossing there is split into through
# traffic (THROUGH_SHARE; gateway pairs balanced to it) and other trips between the gateway and
# the area's zones (business, freight, the port, shopping and leisure; bigger, nearer zones first).
# THROUGH_SHARE and OTHER_T_S were chosen by fitting the DfT count points on 17 Oct 2026: shares
# of 0.2 and 0.3 fitted equally (0.5 and 0.7 worse), and 0.3 is the more plausible for the M27.
GATEWAY_COUNT_M = 3500.0
GATEWAY_COUNT_DEPTH_M = 1000.0
THROUGH_SHARE = 0.3
OTHER_T_S = 900.0  # other county trips: zone weight falls by e for every 15 free-flow minutes
# Trips these give on an average day (both directions); build() recomputes them and warns.
CORDON_DAILY = {"through": 57720, "other": 269361}
CORDON_DAYS = (1.0, 0.8, 0.7)  # assumed weekday, Saturday, Sunday ratio


def commute_totals(group: str) -> tuple[int, int, int]:
    n = CENSUS_DRIVERS[group] * COMMUTE_DAY
    return tuple(int(round(n * f, -2)) for f in (1.0, *WEEKEND[group]))


def cordon_totals(kind: str, share: float = 1.0) -> tuple[int, int, int]:
    avg = sum(w * f for w, f in zip(DAY_WEIGHTS, CORDON_DAYS, strict=True))
    return tuple(int(round(CORDON_DAILY[kind] * share / avg * f, -2)) for f in CORDON_DAYS)

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
# profile (weekday, weekend). County and outbound totals and origin-destination pairs come from
# the census (census_od), through traffic and other county trips from DfT counts at the gateways
# (cordon_od); the others are invented. Trips within the area are scaled to council counts
# (calibrate_to_counts), everything crossing the edge to DfT counts (calibrate_external).
PURPOSES = [
    ("county_in", "county", "gateway", "jobs", commute_totals("county"), ("am_in", "visit_in")),
    ("county_home", "county", "jobs", "gateway", commute_totals("county"), ("pm_out", "visit_out")),
    ("out", "outbound", "homes", "gateway", commute_totals("outbound"), ("am_in", "visit_in")),
    ("out_home", "outbound", "gateway", "homes", commute_totals("outbound"), ("pm_out", "visit_out")),
    ("internal", "internal", "zones", "zones", (150000, 140000, 110000), ("internal_wk", "internal_we")),
    ("through", "through", "gateway", "gateway", cordon_totals("through"), ("through", "through")),
    ("other_in", "visitors", "gateway", "zones", cordon_totals("other", 0.5), ("through", "through")),
    ("other_home", "visitors", "zones", "gateway", cordon_totals("other", 0.5), ("through", "through")),
    ("visit_in", "visitors", "county", "retail", (6000, 26000, 18000), ("visit_in", "visit_in")),
    ("visit_home", "visitors", "retail", "county", (6000, 26000, 18000), ("visit_out", "visit_out")),
    # school run: term-time weekdays only, parents driving children and driving back
    ("school_drop", "school", "homes", "schools", (9000, 0, 0), ("school_am", "school_am")),
    ("school_drop_home", "school", "schools", "homes", (6000, 0, 0), ("school_am_back", "school_am_back")),
    ("school_pick", "school", "homes", "schools", (6000, 0, 0), ("school_pm", "school_pm")),
    ("school_pick_home", "school", "schools", "homes", (9000, 0, 0), ("school_pm_back", "school_pm_back")),
]
SCHOOL_KEYS = {"school_drop", "school_drop_home", "school_pick", "school_pick_home"}
CENSUS_KEYS = {"county_in", "county_home", "out", "out_home"}
EXTERNAL = {"county", "outbound", "through", "visitors"}
GROUPS = {
    "county": "Commuters from the county",
    "outbound": "Residents working outside",
    "internal": "Trips within the area",
    "school": "School run",
    "through": "Through traffic",
    "visitors": "Visitors and other trips from the county",
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
    census: dict = field(default_factory=dict)  # census commuters per gateway and district

    @property
    def n_od(self) -> int:
        return len(self.ods)

    def centroid(self, kind: str, name: str | None = None) -> int:
        for i, c in enumerate(self.centroids):
            if c.kind == kind and (name is None or c.name == name):
                return i
        raise KeyError((kind, name))


# --- building the model from the OSM network ---------------------------------------------------

def _seg_dist(p, coords) -> float:
    c = np.asarray(coords, float)
    a, b = c[:-1], c[1:]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
    return float(np.hypot(*(a + t[:, None] * ab - p).T).min())


def repair_motorways(g, size, log=print) -> set:
    """Mend the motorways where cutting OSM to the study area broke them at the edge.

    1. M27 east of junction 8 and M3 north of junction 13 end in slip roads, so all gateway
       traffic squeezed through one-lane slips and a local roundabout. The end of the outbound
       slip is joined to the start of the inbound one within 500 m, and both get the motorway's
       lanes.
    2. West of M27 junction 3 only the westbound carriageway survives, so traffic from the M27 west
       gateway could not head east on the motorway and detoured through Totton and over Redbridge.
       A carriageway that still ends near the edge with no motorway onwards and no opposite
       carriageway of the same road within 150 m is reversed back to the first junction (all with
       the lanes of its widest part), and if nothing leads on from there, joined to the nearest
       motorway node within 800 m.
    3. Links in MISSING_LINKS (M3 southbound to M27 eastbound at junction 14 / 4, without which
       that traffic cut through Eastleigh's side streets) are added.

    Returns the motorway ends found at the edge: gateway candidates, though they now have links
    both ways.
    """
    W, H = size

    def mw(d):
        return d["cls"] in ("motorway", "motorway_link")

    def opposite_near(u, v, d) -> bool:
        c = np.asarray(d["coords"], float)
        head = c[-1] - c[0]
        mid = c[len(c) // 2]
        refs = set(d["ref"].split(";")) - {""}
        for a, b, e in g.edges(data=True):
            if (a, b) == (u, v) or not mw(e) or not refs & set(e["ref"].split(";")):
                continue
            ce = np.asarray(e["coords"], float)
            if float((ce[-1] - ce[0]) @ head) < 0 and _seg_dist(mid, ce) < 150:
                return True
        return False

    added, cut = [], set()

    # 1. Carriageways ending in slip roads at the edge: join the ends.
    def stub(n, inbound):
        """Slip-road chain from a carriageway end back to a motorway that stops there."""
        chain = []
        while len(chain) < 10:
            nxt = ([(p, n) for p in g.predecessors(n) if mw(g.edges[p, n])] if inbound
                   else [(n, q) for q in g.successors(n) if mw(g.edges[n, q])])
            if len(nxt) != 1:
                return None
            e = nxt[0]
            if g.edges[e]["cls"] == "motorway":  # reached the main carriageway: does it go on?
                m_ = e[1] if inbound else e[0]
                goes_on = (g.successors(m_) if inbound else g.predecessors(m_))
                main = [q for q in goes_on
                        if g.edges[(m_, q) if inbound else (q, m_)]["cls"] == "motorway"]
                return (chain, g.edges[e]["lanes"]) if not main else None
            chain.append(e)
            n = e[0] if inbound else e[1]
        return None

    ends = {"sink": [], "source": []}
    for s in g.nodes:
        x, y = g.nodes[s]["xy"]
        if min(x, y, W - x, H - y) > GATEWAY_EDGE_M["motorway"]:
            continue
        ins = [p for p in g.predecessors(s) if mw(g.edges[p, s])]
        outs = [q for q in g.successors(s) if mw(g.edges[s, q])]
        kind = "sink" if ins and not outs else "source" if outs and not ins else None
        found = stub(s, kind == "sink") if kind else None
        if found:
            ends[kind].append((s, *found))
    for s, chain_in, lanes_in in ends["sink"]:
        ref = g.edges[chain_in[0]]["ref"] if chain_in else ""
        best = None
        for t, chain_out, lanes_out in ends["source"]:
            ref_t = g.edges[chain_out[0]]["ref"] if chain_out else ""
            d = math.dist(g.nodes[s]["xy"], g.nodes[t]["xy"])
            if ref == ref_t and d < 500 and (best is None or d < best[0]):
                best = (d, t, chain_out, lanes_out)
        if best is None:
            continue
        d, t, chain_out, lanes_out = best
        lanes = max(lanes_in, lanes_out)
        for e in chain_in + chain_out:
            g.edges[e]["lanes"] = max(g.edges[e]["lanes"], lanes)
        g.add_edge(s, t, length=d, cls="motorway_link", name="", ref=ref, lanes=lanes,
                   cap=CAP_LANE["motorway_link"] * lanes, t0=d / (60 / 3.6),
                   coords=[tuple(g.nodes[s]["xy"]), tuple(g.nodes[t]["xy"])])
        added.append(f"{ref} end joined")
        cut |= {s, t}

    # 2. A carriageway still ending alone at the edge gets its missing direction.
    for s in list(g.nodes):
        x, y = g.nodes[s]["xy"]
        if min(x, y, W - x, H - y) > GATEWAY_EDGE_M["motorway"]:
            continue
        ins = [(p, s) for p in g.predecessors(s) if mw(g.edges[p, s])]
        if len(ins) != 1 or any(mw(g.edges[s, q]) for q in g.successors(s)):
            continue
        if opposite_near(*ins[0], g.edges[ins[0]]):
            continue
        chain, (p, v) = [], ins[0]
        while len(chain) < 20:
            chain.append((p, v))
            ins = [(q, p) for q in g.predecessors(p) if mw(g.edges[q, p]) and q != v]
            if len(ins) != 1 or any(mw(g.edges[p, q]) for q in g.successors(p) if q != v):
                break
            p, v = ins[0]
        lanes = max(g.edges[e]["lanes"] for e in chain)  # a cut-off slip stands for the motorway
        cut.add(s)
        for a, b in chain:
            g.edges[a, b]["lanes"] = lanes
            d = dict(g.edges[a, b])
            d["coords"] = list(d["coords"])[::-1]
            g.add_edge(b, a, **d)
            added.append(d["ref"] or d["name"])
        j, inner = chain[-1][0], {n for e in chain for n in e}
        if not any(mw(g.edges[j, q]) for q in g.successors(j) if q not in inner):
            pj = np.asarray(g.nodes[j]["xy"], float)
            near = [(math.dist(pj, g.nodes[q]["xy"]), q) for q in g.nodes
                    if q not in inner and any(mw(g.edges[q, r]) for r in g.successors(q))]
            dist, q = min(near)
            if dist < 800:
                ref = g.edges[chain[0]]["ref"]
                g.add_edge(j, q, length=dist, cls="motorway_link", name="", ref=ref, lanes=2,
                           cap=CAP_LANE["motorway_link"] * 2, t0=dist / (60 / 3.6),
                           coords=[tuple(g.nodes[j]["xy"]), tuple(g.nodes[q]["xy"])])
                added.append(f"{ref} connector")
    # 3. Motorway links missing from the network altogether.
    x0, y1, *_, to_bng = ext.frame_origin()
    for what, a, ref_a, b, ref_b, lanes in MISSING_LINKS:
        pts = []
        for (lat, lon), ref, out in ((a, ref_a, True), (b, ref_b, False)):
            e, n = to_bng.transform(lon, lat)
            p = (e - x0, y1 - n)
            on = [u for u in g.nodes
                  if any(mw(g.edges[(u, q) if out else (q, u)])
                         and ref in g.edges[(u, q) if out else (q, u)]["ref"].split(";")
                         for q in (g.successors(u) if out else g.predecessors(u)))]
            pts.append(min(on, key=lambda u: math.dist(p, g.nodes[u]["xy"])))
        u, v = pts
        if not g.has_edge(u, v):
            d = 1.3 * math.dist(g.nodes[u]["xy"], g.nodes[v]["xy"])  # slip roads curve
            g.add_edge(u, v, length=d, cls="motorway_link", name="", ref=ref_a, lanes=lanes,
                       cap=CAP_LANE["motorway_link"] * lanes, t0=d / (70 / 3.6),
                       coords=[tuple(g.nodes[u]["xy"]), tuple(g.nodes[v]["xy"])])
            added.append(what)
    if added:
        log(f"network repair: added {len(added)} links where cutting OSM to the area broke a "
            f"motorway or OSM lacks one ({'; '.join(sorted(set(added)))})")
    return cut


def build(net_path: Path, gates: dict[str, tuple[int, int]], log=print) -> Model:
    with open(net_path, "rb") as f:
        net = pickle.load(f)
    g = net["graph"]
    W, H = net["size"]
    cut_ends = repair_motorways(g, (W, H), log)
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
    cut = {nid[n] for n in cut_ends}

    def near_edge(i: int) -> bool:
        base = node_class[i][0]
        return edge_dist[i] < (GATEWAY_EDGE_M.get(base, GATEWAY_EDGE_DEFAULT_M) if i in cut
                               else GATEWAY_EDGE_DEFAULT_M)

    cands = sorted((i for i in node_class if near_edge(i)),
                   key=lambda i: (rank[node_class[i][0]], edge_dist[i]))
    gateways: list[Centroid] = []
    gw_class: list[str] = []
    for i in cands:
        if any(math.dist(xy[i], gw.xy) < 2200 for gw in gateways):
            continue
        base, road = node_class[i]
        road = road.split(";")[0]
        side = ["west", "north", "east", "south"][int(np.argmin(
            [xy[i, 0], xy[i, 1], W - xy[i, 0], H - xy[i, 1]]))]
        gateways.append(Centroid(f"{road} {side}".strip(), "gateway", int(i),
                                 tuple(int(v) for v in xy[i]), weight=GATEWAY_WEIGHT[base]))
        gw_class.append(base)
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
    csr = sp.csr_matrix((t0, (eu, ev)), shape=(n, n))
    census = census_od(centroids, Z, G_, gw_class, csr, (W, H), log)
    cordon = cordon_od(centroids, Z, G_, gw_class, census, ext.count_points(log)["cordon"],
                       norm(jobs + 0.8 * retail + 0.5 * homes), csr, (W, H), log)
    census["summary"]["cordon"] = cordon["summary"]
    sets = {"homes": (Z, homes), "jobs": (Z, jobs), "retail": (Z, retail), "gateway": (G_, gw),
            "schools": (Z, schools), "county": (G_, census["gw_share"])}
    zxy = np.array([centroids[i].xy for i in Z], float)
    zdist = np.hypot(*(zxy[:, None, :] - zxy[None, :, :]).transpose(2, 0, 1))

    # OD weights per purpose
    od_weight: dict[str, dict[tuple[int, int], float]] = {}
    for key, _, o_set, d_set, _, _ in PURPOSES:
        w: dict[tuple[int, int], float] = {}
        if key in CENSUS_KEYS:
            w = dict(census["od"][key])
        elif key == "internal" or key in SCHOOL_KEYS:
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
        elif key in cordon["od"]:
            w = dict(cordon["od"][key])
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
    edge_of ={(int(a), int(b)): k for k, (a, b) in enumerate(zip(eu, ev, strict=True))}
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
                 zone_kernel=kern, census=census["summary"])


def _crosses(p: np.ndarray, q: np.ndarray, a, b) -> np.ndarray:
    """(len(p), len(q)) mask: does the segment from p[i] to q[j] cross the segment a-b?"""
    def side(u, v, w):
        return np.sign((v[..., 0] - u[..., 0]) * (w[..., 1] - u[..., 1])
                       - (v[..., 1] - u[..., 1]) * (w[..., 0] - u[..., 0]))

    a, b = np.asarray(a, float), np.asarray(b, float)
    P, Q = p[:, None, :], q[None, :, :]
    return (side(a, b, P) * side(a, b, Q) < 0) & (side(P, Q, a) * side(P, Q, b) < 0)


def census_od(centroids, Z, G_, gw_class, csr, size, log=print) -> dict:
    """Census 2021 commuters crossing the edge of the area, as gateway-zone trips.

    Each MSOA flow (car or van drivers) is put on the zone nearest its inside end and shared over
    gateways by time: straight line from its outside end to the gateway at the gateway road's speed,
    plus the quickest free-flow route between gateway and zone. No approach crosses Southampton
    Water or cuts across the area. Returns OD weights for the four commuter purposes, the inbound
    share per gateway (also used for county visitors) and a summary per gateway and district for
    the log and the page.
    """
    data = ext.commute_flows(log)
    rows = data["rows"]
    inbound = np.array([r["inbound"] for r in rows])
    drivers = np.array([r["n"] * r["car"] for r in rows])
    home = np.array([(r["hx"], r["hy"]) for r in rows], float)
    work = np.array([(r["wx"], r["wy"]) for r in rows], float)
    outside = np.where(inbound[:, None], home, work)
    inside = np.where(inbound[:, None], work, home)
    district = np.array([r["home_la"] if r["inbound"] else r["work_la"] for r in rows])

    zone = cKDTree([centroids[i].xy for i in Z]).query(inside)[1]
    gxy = np.array([centroids[i].xy for i in G_], float)
    gnode = [centroids[i].node for i in G_]
    znode = np.array([centroids[i].node for i in Z])
    t_from = dijkstra(csr, indices=gnode)[:, znode]  # gateway -> zone, seconds
    t_to = dijkstra(csr.T.tocsr(), indices=gnode)[:, znode]  # zone -> gateway
    kmh = np.array([GATEWAY_KMH[c] for c in gw_class])
    approach = (np.hypot(*(outside[:, None, :] - gxy[None, :, :]).transpose(2, 0, 1)) / 1000
                * GATEWAY_CIRCUITY / kmh * 3600)
    cost = approach + np.where(inbound[:, None], t_from[:, zone].T, t_to[:, zone].T)
    barrier = np.asarray(ext.water_barrier(), float)
    for a, b in zip(barrier[:-1], barrier[1:], strict=True):
        cost[_crosses(outside, gxy, a, b)] = np.inf
    # nor through the area itself: traffic whose straight line cuts across it enters elsewhere
    W, H = size
    m_ = GATEWAY_EDGE_M["motorway"] + 500
    for s in np.linspace(0.05, 0.95, 19):
        pt = (1 - s) * outside[:, None, :] + s * gxy[None, :, :]
        x, y = pt[..., 0], pt[..., 1]
        cost[(x > m_) & (x < W - m_) & (y > m_) & (y < H - m_)] = np.inf
    ok = np.isfinite(cost).any(axis=1)
    if not ok.all():
        log(f"census: {drivers[~ok].sum():.0f} drivers have no reachable gateway; left out")
    cost, drivers, inbound = cost[ok], drivers[ok], inbound[ok]
    zone, district = zone[ok], district[ok]
    p = np.exp(-(cost - cost.min(axis=1, keepdims=True)) / GATEWAY_LOGIT_S)
    flow = drivers[:, None] * p / p.sum(axis=1, keepdims=True)  # drivers per row and gateway

    tot = {"county": float(drivers[inbound].sum()), "outbound": float(drivers[~inbound].sum())}
    log(f"census: {tot['county']:.0f} car or van drivers commute into the area, "
        f"{tot['outbound']:.0f} out of it (Census 2021, MSOA flows within {data['max_km']:g} km)")
    for g, v in tot.items():
        if abs(v / CENSUS_DRIVERS[g] - 1) > 0.01:
            log(f"census: WARNING {g} drivers {v:.0f} differ from CENSUS_DRIVERS "
                f"{CENSUS_DRIVERS[g]}; update the constant")

    w_in = np.zeros((len(Z), len(G_)))
    w_out = np.zeros((len(Z), len(G_)))
    np.add.at(w_in, zone[inbound], flow[inbound])
    np.add.at(w_out, zone[~inbound], flow[~inbound])
    od: dict[str, dict] = {k: {} for k in CENSUS_KEYS}
    for zi in range(len(Z)):
        for gi in range(len(G_)):
            if w_in[zi, gi] > 2e-5 * tot["county"]:
                od["county_in"][(G_[gi], Z[zi])] = od["county_home"][(Z[zi], G_[gi])] = w_in[zi, gi]
            if w_out[zi, gi] > 2e-5 * tot["outbound"]:
                od["out"][(Z[zi], G_[gi])] = od["out_home"][(G_[gi], Z[zi])] = w_out[zi, gi]

    by_district = {}
    for d in np.unique(district):
        mask = district == d
        by_district[str(d)] = (flow[mask & inbound].sum(axis=0), flow[mask & ~inbound].sum(axis=0))
    gw_in, gw_out = w_in.sum(axis=0), w_out.sum(axis=0)
    summary = {"source": data["source"], "collected": data["collected"], "drivers": tot,
               "commute_day": COMMUTE_DAY, "gateways": [], "districts": []}
    log("census commuters per gateway (car or van drivers, both directions on a weekday "
        f"= x{COMMUTE_DAY:g} before calibration):")
    for gi, g in enumerate(G_):
        both = {d: v[0][gi] + v[1][gi] for d, v in by_district.items()}
        top = [d for d, v in sorted(both.items(), key=lambda kv: -kv[1])
               if v >= 0.1 * (gw_in[gi] + gw_out[gi])][:3]
        centroids[g].hint = ", ".join(top) or "rest of Hampshire"
        summary["gateways"].append({"name": centroids[g].name, "in": round(gw_in[gi]),
                                    "out": round(gw_out[gi]), "from": top})
        log(f"  {centroids[g].name:14s} in {gw_in[gi]:6.0f}  out {gw_out[gi]:6.0f}  "
            f"({centroids[g].hint})")
    log("census commuters per district (car or van drivers) and their main gateways:")
    names = [centroids[g].name for g in G_]
    for d, (a, b) in sorted(by_district.items(), key=lambda kv: -(kv[1][0].sum() + kv[1][1].sum())):
        total = a + b
        main = [f"{names[i]} {100 * total[i] / total.sum():.0f}%" for i in np.argsort(-total)[:3]
                if total[i] >= 0.1 * total.sum()]
        summary["districts"].append({"name": d, "in": round(a.sum()), "out": round(b.sum()),
                                     "via": main})
        if a.sum() + b.sum() >= 150:
            log(f"  {d:34s} in {a.sum():6.0f}  out {b.sum():6.0f}  via {', '.join(main)}")
    return {"od": od, "gw_share": gw_in / gw_in.sum(), "summary": summary}


def cordon_od(centroids, Z, G_, gw_class, census: dict, cordon: list[dict], attract, csr, size,
              log=print) -> dict:
    """Through traffic and other county trips from DfT counts on the gateway roads.

    Each gateway takes the nearest count point on its road within GATEWAY_COUNT_M that lies outside
    the area or less than GATEWAY_COUNT_DEPTH_M inside it (deeper ones count local traffic too);
    one gateway per count point, and gateways without one get neither. What the count leaves after
    census commuters and county visitors crossing there (average day, before calibration) is split:

    * THROUGH_SHARE is through traffic: gateway pairs more than 6 km apart are seeded 1, or 0.15
      unless both ends are motorway or trunk, then balanced to each gateway's through crossings
      by iterative proportional fitting;
    * the rest is other trips, half in and half out, to zones by ``attract`` times
      exp(-free-flow time / OTHER_T_S).
    """
    W, H = size
    cand = []
    for gi, g in enumerate(G_):
        road = centroids[g].name.rsplit(" ", 1)[0]
        for c in cordon:
            d = math.dist(centroids[g].xy, (c["x"], c["y"]))
            depth = min(c["x"], c["y"], W - c["x"], H - c["y"])  # how far inside the area
            if c["road"] == road and d < GATEWAY_COUNT_M and depth < GATEWAY_COUNT_DEPTH_M:
                cand.append((d, gi, c))
    count: dict[int, dict] = {}
    for _, gi, c in sorted(cand, key=lambda t: t[0]):
        if gi not in count and all(c is not v for v in count.values()):
            count[gi] = c

    totals = {k: t for k, _, _, _, t, _ in PURPOSES}

    def average(key):
        return sum(w * t for w, t in zip(DAY_WEIGHTS, totals[key], strict=True))

    crossing = np.zeros(len(G_))  # census commuters and visitors over each gateway, both ways
    pos = {g: gi for gi, g in enumerate(G_)}
    for key, w in census["od"].items():
        s = sum(w.values())
        for (o, d), v in w.items():
            crossing[pos[o] if o in pos else pos[d]] += average(key) * v / s
    crossing += (average("visit_in") + average("visit_home")) * census["gw_share"]
    rest = np.zeros(len(G_))
    for gi, c in count.items():
        rest[gi] = max(c["aadf"] - crossing[gi], 0.0)
    target, other = THROUGH_SHARE * rest, (1 - THROUGH_SHARE) * rest

    gxy = np.array([centroids[g].xy for g in G_], float)
    far = np.hypot(*(gxy[:, None, :] - gxy[None, :, :]).transpose(2, 0, 1)) > 6000
    strategic = np.array([c in ("motorway", "trunk") for c in gw_class])
    S = far * np.where(strategic[:, None] & strategic[None, :], 1.0, 0.15)
    S *= (target[:, None] > 0) & (target[None, :] > 0)
    a = np.where(target > 0, 1.0, 0.0)
    for _ in range(200):
        made = 2 * a * (S @ a)
        a = np.where(made > 0, a * np.sqrt(target / np.maximum(made, 1e-9)), 0.0)
    T = a[:, None] * a[None, :] * S  # through trips per average day, from row to column gateway
    made = T.sum(axis=0) + T.sum(axis=1)
    daily = {"through": float(T.sum()), "other": float(other.sum())}
    od: dict[str, dict] = {"other_in": {}, "other_home": {}}
    od["through"] = {(G_[i], G_[j]): T[i, j]
                     for i, j in zip(*np.nonzero(T > 1e-4 * daily["through"]), strict=True)}
    gnode = [centroids[g].node for g in G_]
    znode = np.array([centroids[z].node for z in Z])
    for key, t in (("other_in", dijkstra(csr, indices=gnode)[:, znode]),
                   ("other_home", dijkstra(csr.T.tocsr(), indices=gnode)[:, znode])):
        for gi in np.flatnonzero(other > 0):
            w = attract * np.exp(-t[gi] / OTHER_T_S)
            w = 0.5 * other[gi] * w / w.sum()
            for zi in np.flatnonzero(w > 1e-4 * w.sum()):
                od[key][(G_[gi], Z[zi]) if key == "other_in" else (Z[zi], G_[gi])] = w[zi]

    log(f"cordon from DfT counts at the gateways (average day, before calibration): through "
        f"{daily['through']:.0f} trips ({THROUGH_SHARE:g} of what census commuters and visitors "
        f"leave), other county trips {daily['other']:.0f}")
    summary = []
    for gi, g in enumerate(G_):
        c = count.get(gi)
        row = {"gateway": centroids[g].name, "commuters_visitors": round(crossing[gi]),
               "through": round(made[gi]), "other": round(other[gi])}
        if c:
            row.update(count_point=c["count_point"], year=c["year"], method=c["method"],
                       aadf=c["aadf"])
        summary.append(row)
        log(f"  {centroids[g].name:14s} DfT "
            + (f"{c['aadf']:7d} ({c['count_point']}, {c['year']} {c['method'].lower()})" if c
               else "   none" + " " * 21)
            + f"  commuters+visitors {crossing[gi]:6.0f}  through {made[gi]:7.0f}"
            f"  other {other[gi]:6.0f}")
    for k, v in daily.items():
        if abs(v / max(CORDON_DAILY[k], 1) - 1) > 0.03:
            log(f"cordon: WARNING {k} {v:.0f} trips differ from CORDON_DAILY {CORDON_DAILY[k]}; "
                "update the constant")
    return {"od": od, "daily": daily, "summary": summary}


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
    shared = 1.0
    if rng is not None:
        day = rng.lognormal(0.0, NOISE["day"] * spread)
        shared = ar1(rng, N_BINS, NOISE["shared_bin"] * spread, NOISE["shared_rho"])
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
            prof = prof * ar1(rng, N_BINS, NOISE["bin"] * spread, NOISE["rho"]) * shared
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


ESTIMATED_WEIGHT = 0.5  # DfT "Estimated" AADF (factored from an older count) counts half in the fit


def count_point_edges(m: Model, site: dict, radius: float = 250.0) -> list[int]:
    """Model links at a DfT count point: the nearest link of the counted road in each direction.

    A site with names (a bridge) takes the nearest links with those names at any distance: DfT
    counts hold for the whole link between junctions, and the count point can sit away from the
    bridge on the same link.
    """
    p = np.array([site["x"], site["y"]], float)
    names = site.get("names")
    found = []
    for k in range(len(m.t0)):
        if names:
            if m.name[k] not in names:
                continue
        elif site["road"] not in m.ref[k].split(";") or m.cls[k].endswith("_link"):
            continue
        c = np.asarray(m.coords[k], float)
        a, b = c[:-1], c[1:]
        ab = b - a
        t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
        d = float(np.hypot(*(a + t[:, None] * ab - p).T).min())
        if d < radius or names:
            head = c[-1] - c[0]
            found.append((d, k, head / max(np.hypot(*head), 1e-9)))
    if not found:
        return []
    found.sort(key=lambda f: f[0])
    _, k1, h1 = found[0]
    back = [k for _, k, h in found if float(h @ h1) < -0.3]
    return [k1] + back[:1]


def modelled_aadf(m: Model, sites: list[dict], edges: list[list[int]]) -> np.ndarray:
    """Average daily two-way vehicles past each count point (weekday, Saturday and Sunday flows
    over 05:00-20:00, at most capacity, weighted by DAY_WEIGHTS and grossed up to 24 hours by
    DAY_WINDOW_SHARE)."""
    out = np.zeros(len(sites))
    for dt, wd in enumerate(DAY_WEIGHTS):
        v = flows(m, background(m, dt)[0], m.cap, pre=m.pre.get(dt))
        v = np.minimum(v, m.cap)  # a counter sees what gets through, not queued traffic re-trying
        out += wd * np.array([v[:, ks].sum() / 4.0 for ks in edges]) / DAY_WINDOW_SHARE
    return out


def calibrate_external(m: Model, sites: list[dict], log=print,
                       grid=(0.6, 0.8, 1.0, 1.25, 1.5, 1.8, 2.1, 2.5, 3.0)) -> list[dict]:
    """Scale everything that crosses the edge of the area (census commuters, county visitors and
    through traffic) so modelled average daily two-way flows match DfT AADF at the count points.

    Grid search on the weighted root-mean-square log error, like calibrate_to_counts: route choice
    makes flows at one point non-linear in the scale. Returns one row per count point.
    """
    edges = [count_point_edges(m, s) for s in sites]
    use = [i for i, e in enumerate(edges) if e]
    for i, s in enumerate(sites):
        if not edges[i]:
            log(f"calibrate DfT: no model link found for {s['label']} "
                f"(count point {s['count_point']})")
    sites_u, edges_u = [sites[i] for i in use], [edges[i] for i in use]
    obs = np.array([s["aadf"] for s in sites_u], float)
    wts = np.array([(1.0 if s["method"] == "Counted" else ESTIMATED_WEIGHT) * s.get("fit", True)
                    for s in sites_u])
    best = None
    for g in grid:
        m.scale_ext = g
        mod = modelled_aadf(m, sites_u, edges_u)
        err = math.sqrt(float((wts * np.log((obs + 1) / (mod + 1)) ** 2).sum() / wts.sum()))
        log(f"calibrate DfT: scale {g:.2f} -> modelled/observed AADF {mod.sum() / obs.sum():.2f} "
            f"overall (log error {err:.3f})")
        if best is None or err < best[0]:
            best = (err, g, mod)
    err, m.scale_ext, mod = best
    log(f"calibrate DfT: chose scale {m.scale_ext:.2f} for traffic crossing the edge "
        f"(log error {err:.3f})")
    rows = []
    for s, ks, md in zip(sites_u, edges_u, mod, strict=True):
        rows.append({"road": s["label"], "count_point": s["count_point"], "year": s["year"],
                     "method": s["method"], "link": s["link"], "observed": s["aadf"],
                     "modelled": round(float(md)), "links": len(ks),
                     "fitted": bool(s.get("fit", True))})
        log(f"  DfT {s['count_point']:6d} {s['label']:42s} {s['year']} {s['method']:9s} "
            f"observed {s['aadf']:7d}  modelled {md:7.0f}  ({100 * (md / s['aadf'] - 1):+.0f}%)"
            + ("" if s.get("fit", True) else "  (check, not fitted)"))
    return rows



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
