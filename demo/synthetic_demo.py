"""Cruise-day traffic forecast demo on the real Southampton road network.

The map and road network are real (OpenStreetMap, built by osm_base.py). The traffic model
(traffic_model.py) builds zones, county gateways and routes from that geography and allocates
traffic dynamically every 15 minutes. Real inputs: the ABP Southampton VTS cruise schedule once
demo/collect_schedule.py has written data/raw/cruise_schedule.csv (else an invented one), Saints
home fixtures, the council's school term dates and Street Manager roadworks permits. County
commuters come from Census 2021 and traffic crossing the edge of the area is scaled to DfT counts
(external_data.py, run once). What is invented: trip totals within the area (scaled to council
counts) and of county visitors, and capacities per lane. Nothing here is observed cruise-day
traffic.

    uv run --no-project --python 3.12 --with osmnx --with scipy python demo/osm_base.py   # once
    uv run --no-project --python 3.12 python demo/collect_schedule.py   # VTS schedule, each run
    uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas \
        --with shapely --with pyproj python demo/synthetic_demo.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pickle
import sys
import time as clock
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import external_data as ext  # noqa: E402
import freight_days as fd  # noqa: E402
import traffic_model as tm  # noqa: E402

from sotonship26.demand.passengers import TurnaroundParams  # noqa: E402

CACHE = HERE.parent / "data" / "cache" / "southampton"
SCHEDULE_CSV = HERE.parent / "data" / "raw" / "cruise_schedule.csv"  # never committed
VTS_PAGE = ("https://www.southamptonvts.co.uk/live_information/"
            "shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/")
BIN_MIN = 15
N_BINS = tm.N_BINS
ISSUED = datetime(2026, 10, 16, 22, 30)
FIRST_DAY = date(2026, 10, 17)
HORIZON = date(2026, 11, 29)
CAL_END = date(2026, 12, 6)
SEED = 26
LANE_CLOSED = 0.75  # capacity left with one lane coned off under traffic management
CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"
BBOX = (-1.53, 50.855, -1.29, 50.975)

# Named corridors for the heatmap: (id, label, group, names, refs)
CORRIDORS = [
    ("m271", "M271", "Western approach", [], ["M271"]),
    ("redbridge", "A35 Redbridge Road", "Western approach", ["Redbridge Road"], []),
    ("millbrook", "A33 Millbrook Road", "Western approach", ["Millbrook Road West", "Millbrook Road East"], []),
    ("mountbatten", "Mountbatten Way", "Western approach", ["Mountbatten Way"], []),
    ("wqr", "West Quay Road", "Western approach", ["West Quay Road"], []),
    ("esplanade", "Western Esplanade", "Western approach", ["Western Esplanade"], []),
    ("platform", "Platform Road", "Town Quay and Eastern Docks", ["Platform Road"], []),
    ("canute", "Canute Road", "Town Quay and Eastern Docks", ["Canute Road"], []),
    ("terminus", "Terminus Terrace", "Town Quay and Eastern Docks", ["Terminus Terrace"], []),
    ("queensway", "Queensway", "Town Quay and Eastern Docks", ["Queensway"], []),
    ("civic", "Civic Centre Road", "City centre", ["Civic Centre Road"], []),
    ("dorset", "Dorset Street / Charlotte Place", "City centre", ["Dorset Street", "Charlotte Place"], []),
    ("kingsway", "Kingsway", "City centre", ["Kingsway"], []),
    ("avenue", "A33 The Avenue", "North and east", ["The Avenue"], []),
    ("northam", "Northam Road / Bridge", "North and east", ["Northam Road", "Northam Bridge"], []),
    ("britannia", "Britannia Road", "North and east", ["Britannia Road"], []),
    ("itchen", "Itchen Bridge", "North and east", ["Itchen Bridge"], []),
    ("shirley", "Shirley Road", "North and east", ["Shirley Road"], []),
    ("portswood", "Portswood Road", "Portswood", ["Portswood Road"], []),
    ("bevois", "Bevois Hill / Bevois Valley Road", "Portswood", ["Bevois Hill", "Bevois Valley Road"], []),
    ("stdenys", "St Denys Road", "Portswood", ["St Denys Road"], []),
    ("highfield", "Highfield Lane", "Portswood", ["Highfield Lane"], []),
    ("burgess", "Burgess Road", "Portswood", ["Burgess Road"], []),
    ("m27", "M27", "Motorway", [], ["M27"]),
]
SENSOR = {"m271": "Sensor planned: National Highways WebTRIS on the M271",
          "m27": "Sensor planned: National Highways WebTRIS on the M27"}
WATER_LABELS = [("Southampton Water", 50.872, -1.372), ("River Test", 50.906, -1.462),
                ("River Itchen", 50.913, -1.384)]
TERMINALS = ["Ocean", "QEII", "Mayflower", "City", "Horizon"]

MODE_MEAN = np.array([0.22, 0.28, 0.20, 0.25, 0.05])
MODE_CONC = 60.0
PEOPLE_PER = {"car": 2.4, "park": 2.4, "taxi": 2.0, "coach": 40.0}
COACH_PCU = 2.0
UNKNOWN_PAX_RANGE = (1800, 4500)
SHIPS = [
    ("Synthetic Seas", 3600), ("Demo Meridian", 2100), ("Sample Serenade", 4900),
    ("Mock Mariner", 2600), ("Trial Tern", 1900), ("Proxy Pearl", 3100), ("Model Majesty", 5200),
    ("Test Tide", 2400), ("Placeholder Spirit", 4200), ("Stub Starlight", 3000),
    ("Draft Dawn", 2800), ("Example Explorer", 3900),
]
# Roadworks on the corridors from DfT Street Manager open data (permit archives permit/2026/08.zip
# and 09.zip, i.e. permit events up to 30 Sep 2026; read 16 Oct 2026, OGL v3.0). Kept: permits
# granted for daytime works, or works with no hours given, that need signals or a lane closure,
# since the model closes a lane for the whole 05:00-20:00 day. Left out: overnight-only lane
# closures (M271, Millbrook Road West, Mountbatten Way, Redbridge Road, 4-7 Nov), a two-hour
# Sunday closure on Northam Bridge (18 Oct), applications not granted by 30 Sep and works that only
# encroach on the carriageway. Permits granted in October are not archived yet: a short list.
PERMITS = [
    {"id": "XW100W123852173-09829-01", "corridor": "platform",
     "from": "2026-10-19", "to": "2026-10-23",
     "what": "Multi-way signals for Southern Gas Networks repair works (no hours given)",
     "source": "Street Manager, granted 24 Sep 2026"},
    {"id": "LP709S30000746-02", "corridor": "portswood", "from": "2026-10-19", "to": "2026-10-30",
     "what": "Two-way signals, daytime, for SSEN electricity repair works",
     "source": "Street Manager, granted 29 Sep 2026"},
    {"id": "ZH00196278704-03", "corridor": "portswood", "from": "2026-10-20", "to": "2026-10-23",
     "what": "Multi-way signals 09:30-15:30 for NWP Street works",
     "source": "Street Manager, granted 9 Sep 2026"},
    {"id": "LQ003SWAT14673649-01", "corridor": "m271", "from": "2026-10-29", "to": "2026-10-30",
     "what": "Lane closure for Southern Water minor works (no hours given)",
     "source": "Street Manager, granted 7 Sep 2026"},
    {"id": "LQ002SWAT14500512-04", "corridor": "platform", "from": "2026-11-02", "to": "2026-11-06",
     "what": "Lane closure for Southern Water repair works (no hours given)",
     "source": "Street Manager, granted 21 Sep 2026"},
]
# Saints home league games at St Mary's in the forecast window. Dates and opponents: Southampton FC,
# "2026/27 fixtures: Saints start away to Watford" (25 Jun 2026). Moved kick-offs: "Six Saints
# fixtures selected for Sky Sports coverage" (30 Jul 2026). Other Saturdays keep the 15:00 slot.
# Checked 16 Oct 2026; TV picks can still move them. The model day ends at 20:00, so the Friday
# evening game adds arrivals only.
MATCHES = [
    {"date": "2026-10-17", "kickoff": "15:00", "opponent": "Bolton Wanderers"},
    {"date": "2026-10-31", "kickoff": "15:00", "opponent": "Queens Park Rangers"},
    {"date": "2026-11-21", "kickoff": "12:30", "opponent": "Derby County"},
    {"date": "2026-11-27", "kickoff": "20:00", "opponent": "Middlesbrough"},
]
WHATIF_ROADS = ["wqr", "mountbatten", "platform", "millbrook"]
# Southampton City Council school year calendar 2026-27 (maintained and voluntary-controlled
# schools; academies may differ), checked 16 Oct 2026: half-term 26-30 Oct, autumn two ends 18 Dec.
HALF_TERM = (date(2026, 10, 26), date(2026, 10, 30))
TERM_ENDS = date(2026, 12, 18)
SOURCES = {  # shown on the page; make_schedule() fills in "schedule"
    "permits": {"label": "DfT Street Manager permits granted by 30 Sep 2026, read 16 Oct 2026",
                "short": "permits granted by 30 Sep 2026", "synthetic": False,
                "url": "https://department-for-transport-streetmanager.github.io/"
                       "street-manager-docs/archived-notifications/",
                "files": ["permit/2026/08.zip", "permit/2026/09.zip"], "checked": "2026-10-16"},
    "matches": {"label": "Southampton FC fixtures, checked 16 Oct 2026",
                "url": "https://www.southamptonfc.com/en/news/article/"
                       "2026-27-fixtures-saints-start-away-to-watford",
                "tv_url": "https://www.southamptonfc.com/en/news/article/"
                          "six-saints-fixtures-selected-for-sky-sports-coverage",
                "checked": "2026-10-16"},
    "terms": {"label": "Southampton City Council 2026-27 term dates, checked 16 Oct 2026",
              "url": "https://www.southampton.gov.uk/schools-learning/school-information/"
                     "school-term-dates/school-year-calendar-2026-27/",
              "checked": "2026-10-16"},
}
DIS_OPTS = [-30, 45, 90, 150]  # minutes to move the start of disembarkation
EMB_OPTS = [-90, -45, 30]  # minutes to move the check-in window

# Observed two-direction counts (NB, SB) used to calibrate everyday traffic. Source: Southampton
# City Council / WSP, "Portswood Project Baseline Data Report", January 2025, Tables 3-8 and 3-9:
# automatic traffic counts 1-14 July 2024, totals for 07:00-10:00, 16:00-19:00 and the whole day.
# Portswood Road averages its four sites (ATC 4, 9, 10, 11).
COUNT_SOURCE = ("Southampton City Council / WSP, Portswood Project Baseline Data Report (Jan 2025), "
                "Tables 3-8 and 3-9: automatic traffic counts, 1-14 July 2024")
COUNT_SITES = [
    {"label": "Portswood Road (ATC 4, 9, 10, 11)", "names": ["Portswood Road"],
     "weekday": {"am": (738.5, 945.75), "pm": (1111.5, 1085.75), "day": (5206.0, 5498.25)},
     "speed": {"am": (21.1, 21.0), "pm": (18.6, 18.5)},
     "saturday": {"am": (539.0, 554.25), "pm": (950.5, 866.0), "day": (5006.25, 5175.25)}},
    {"label": "Highfield Lane (ATC 3)", "names": ["Highfield Lane"],
     "weekday": {"am": (727, 706), "pm": (858, 644), "day": (4253, 3600)},
     "speed": {"am": (24.5, 24.9), "pm": (21.0, 24.5)},
     "saturday": {"am": (500, 470), "pm": (663, 551), "day": (3820, 3139)}},
    {"label": "St Denys Road (ATC 14)", "names": ["St Denys Road"],
     "weekday": {"am": (750, 644), "pm": (692, 832), "day": (4105, 4339)},
     "speed": {"am": (18.4, 21.4), "pm": (18.1, 19.1)},
     "saturday": {"am": (589, 474), "pm": (647, 801), "day": (3834, 4296)}},
    {"label": "Bevois Hill (ATC 15)", "names": ["Bevois Hill"],
     "weekday": {"am": (444, 579), "pm": (623, 703), "day": (3233, 3584)},
     "speed": {"am": (15.8, 17.2), "pm": (14.6, 17.0)},
     "saturday": {"am": (314, 340), "pm": (563, 583), "day": (3059, 3417)}},
]


@dataclass(frozen=True)
class Call:
    ship: str
    terminal: str
    arrival: datetime
    departure: datetime
    pax: int | None
    times: str = "exact"  # or "typical (VTS lists TBA/TBA)" while the schedule has no clock times


@dataclass
class Ctx:
    m: tm.Model
    corr: list  # (id, label, group, edge indices)
    corr_idx: np.ndarray
    corr_ptr: np.ndarray
    seg_idx: np.ndarray
    seg_ptr: np.ndarray
    gates: list  # gate centroid indices
    terminal_gate: dict
    luts: dict  # set -> gate centroid -> direction -> OD index per origin
    gate_mask: np.ndarray  # n_od x n_gates (cruise OD ends at/starts from gate)
    gw_in: np.ndarray  # n_od x n_gateways (OD starts at gateway)
    cruise_ods: np.ndarray
    extra: dict = field(default_factory=dict)


# --- model context -----------------------------------------------------------------------------

def frame_origin():
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    w, s, e, n = BBOX
    xs, ys = zip(*[t.transform(x, y) for x, y in [(w, s), (e, s), (e, n), (w, n)]])
    return min(xs), max(ys), t


def segments_of(m: tm.Model):
    """Merge directed edges into display segments: both directions, chained through plain bends."""
    links: dict[tuple[int, int], list[int]] = defaultdict(list)
    for k, (u, v) in enumerate(zip(m.eu, m.ev, strict=True)):
        links[(min(u, v), max(u, v))].append(k)
    keys = list(links)
    parent = list(range(len(keys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_node = defaultdict(list)
    for i, (a, b) in enumerate(keys):
        by_node[a].append(i)
        by_node[b].append(i)
    label = [(m.name[links[k][0]], m.cls[links[k][0]].replace("_link", "")) for k in keys]
    for ids in by_node.values():
        if len(ids) == 2 and label[ids[0]] == label[ids[1]]:
            parent[find(ids[0])] = find(ids[1])
    groups = defaultdict(list)
    for i in range(len(keys)):
        groups[find(i)].append(i)
    segs = []
    for members in groups.values():
        edges = [e for i in members for e in links[keys[i]]]
        segs.append({"edges": edges, "links": [links[keys[i]][0] for i in members],
                     "name": label[members[0]][0], "cls": label[members[0]][1]})
    return segs


def build_ctx(log=print) -> tuple[Ctx, dict]:
    base = json.loads((CACHE / "base.json").read_text(encoding="utf-8"))
    gates = dict(base.get("gates") or {})
    lm = base["landmarks"]
    if "QEII" not in lm and "Ocean" in lm:  # Nominatim misses it; it sits beside Ocean Terminal
        lm["QEII"] = [lm["Ocean"][0] + 250, lm["Ocean"][1] + 350]
    if gates:  # route only to the gates a terminal uses (its nearest)
        used = {min(gates, key=lambda g: math.dist(lm[t], gates[g])) for t in TERMINALS if t in lm}
        gates = {g: p for g, p in gates.items() if g in used}
    if len(gates) < 2:  # fall back to points beside the terminals' road access
        log("dock gates not in OSM; placing one gate per dock beside its terminals")
        west = [lm[t] for t in ("Mayflower", "City", "Horizon") if t in lm]
        east = [lm[t] for t in ("Ocean", "QEII") if t in lm]
        if west:
            gates["Western Docks gate"] = tuple(np.mean(west, axis=0).round().astype(int))
        if east:
            gates["Eastern Docks gate"] = tuple(np.mean(east, axis=0).round().astype(int))
    m = tm.build(CACHE / "network.pkl", gates, log=log, port_gates=dict(base.get("gates") or {}))
    dft = ext.count_points(log=log)
    # county and city traffic both load the count points, so fit the two scales in turn
    for _ in range(2):
        tm.calibrate_external(m, dft["sites"], log=log, grid=(0.6, 0.8, 1.0, 1.25, 1.6))
        calibration = tm.calibrate_to_counts(m, COUNT_SITES, log=log)
    freight_rows = tm.calibrate_freight(m, dft["sites"], log=log)
    # the council-count grid steps by about 15%; settle the city scale more finely
    calibration = tm.calibrate_to_counts(m, COUNT_SITES, log=log, grid=(0.9, 0.95, 1.0, 1.05, 1.1))
    near =tuple(round(m.scale_ext * f, 3) for f in (0.85, 0.92, 1.0, 1.08, 1.17))
    dft_rows = tm.calibrate_external(m, dft["sites"], log=log, grid=near)
    capacity_notes = tm.anchor_counts(m, COUNT_SITES, calibration, log=log)
    for row in calibration:
        if row["period"] != "day" or row["day"] == "weekday":
            log(f"  {row['road']:36s} {row['day']:8s} {row['period']:3s} observed {row['observed']:6d}"
                f"  modelled {row['modelled']:6d}{'  (fitted)' if row['fitted'] else ''}")

    gate_ids = [i for i, c in enumerate(m.centroids) if c.kind == "gate"]
    terminal_gate = {}
    for t in TERMINALS:
        p = lm.get(t)
        if p is None:
            continue
        terminal_gate[t] = min(gate_ids, key=lambda g: math.dist(p, m.centroids[g].xy))

    corr = []
    for cid, label, group, names, refs in CORRIDORS:
        if refs:
            idx = [k for k in range(len(m.t0))
                   if any(r in m.ref[k].split(";") for r in refs) and m.length[k] >= 60
                   and not m.cls[k].endswith("_link")]
        else:
            idx = tm.road_edges(m, names, min_length=60.0)
        if idx:
            corr.append((cid, label, group, idx))
    for g in gate_ids:
        node = m.centroids[g].node
        idx = [k for k in range(len(m.t0)) if m.eu[k] == node or m.ev[k] == node]
        if idx:
            corr.append((f"gate{g}", f"{m.centroids[g].name} access", "Dock gates", idx))
    log("corridors: " + ", ".join(c[1] for c in corr))
    corr_idx = np.concatenate([c[3] for c in corr])
    corr_ptr = np.concatenate([[0], np.cumsum([len(c[3]) for c in corr])])[:-1]

    segs = segments_of(m)
    seg_idx = np.concatenate([s["edges"] for s in segs])
    seg_ptr = np.concatenate([[0], np.cumsum([len(s["edges"]) for s in segs])])[:-1]
    log(f"display segments: {len(segs)}")

    luts = {}
    for key in ("car_from", "taxi_rank", "taxi_far", "coach_from"):
        ids, _ = m.sets[key]
        luts[key] = {g: {"in": np.array([m.od_index.get((o, g), -1) for o in ids]),
                         "out": np.array([m.od_index.get((g, o), -1) for o in ids])}
                     for g in gate_ids}
    gate_mask = np.zeros((m.n_od, len(gate_ids)))
    for (o, d), j in m.od_index.items():
        for gi, g in enumerate(gate_ids):
            if o == g or d == g:
                gate_mask[j, gi] = 1.0
    gws = [i for i, c in enumerate(m.centroids) if c.kind == "gateway"]
    gw_in = np.zeros((m.n_od, len(gws)))
    for (o, _), j in m.od_index.items():
        if o in gws:
            gw_in[j, gws.index(o)] = 1.0
    cruise_ods = np.flatnonzero(gate_mask.sum(axis=1) > 0)
    ctx = Ctx(m=m, corr=corr, corr_idx=corr_idx, corr_ptr=corr_ptr, seg_idx=seg_idx,
              seg_ptr=seg_ptr, gates=gate_ids, terminal_gate=terminal_gate, luts=luts,
              gate_mask=gate_mask, gw_in=gw_in, cruise_ods=cruise_ods,
              extra={"segs": segs, "gateways": gws, "calibration": calibration,
                     "capacity": capacity_notes, "dft": {**dft, "rows": dft_rows},
                     "freight": freight_rows})
    return ctx, base


# --- cruise demand -----------------------------------------------------------------------------

def minutes(t: datetime) -> float:
    return t.hour * 60 + t.minute


CRUISE_DEFAULT = {"road": 1.0, "county": 0.8, "dis_shift": 0.0}
# Grid the M271 fit searches: road = multiplier on the car, park and taxi shares (coach and other
# take the rest); county = share of car and taxi trips from the county gateways rather than the
# city's zones; dis_shift = minutes added to when disembarkation traffic starts leaving.
CRUISE_GRID = {"road": (0.7, 0.85, 1.0, 1.15), "county": (0.6, 0.8, 0.95),
               "dis_shift": (0.0, 30.0, 60.0, 90.0)}


def cruise_sets(ctx: Ctx, county: float) -> dict:
    """Origin sets for cruise cars and taxis with ``county`` of them from the county gateways."""
    m, n_gw = ctx.m, len(ctx.extra["gateways"])
    out = {}
    for key, gw_part in (("car_from", 0.8), ("taxi_far", 0.3)):
        ids, probs = m.sets[key]
        probs = np.asarray(probs, float).copy()
        off = len(ids) - len(ctx.extra["gateways"]) - sum(1 for c in m.centroids if c.kind == "zone")
        g = slice(off, off + n_gw)
        z = slice(off + n_gw, len(ids))
        rest = 1.0 - probs[g].sum() - probs[z].sum()  # the station, for taxis
        local = probs[g].sum() + probs[z].sum()
        probs[g] *= county * local / max(probs[g].sum(), 1e-12)
        probs[z] *= (1 - county) * local / max(probs[z].sum(), 1e-12)
        out[key] = (ids, probs / (probs.sum() if rest >= 0 else 1.0))
    return out


def sample_cruise(ctx: Ctx, calls, rng, p: TurnaroundParams, shifts=None, cruise=None) -> np.ndarray:
    m = ctx.m
    D = np.zeros((N_BINS, m.n_od))
    cruise = {**CRUISE_DEFAULT, **(cruise or {})}
    mode_mean = MODE_MEAN.copy()
    mode_mean[:3] *= cruise["road"]
    mode_mean[3:] *= (1 - mode_mean[:3].sum()) / mode_mean[3:].sum()
    sets = {**m.sets, **cruise_sets(ctx, cruise["county"])}

    def add(t, key, gate, direction, pcu):
        n = len(t)
        if n == 0:
            return None
        ids, probs = sets[key]
        o = rng.choice(len(ids), size=n, p=probs)
        put(t, o, key, gate, direction, pcu)
        return o

    def put(t, o, key, gate, direction, pcu):
        b = np.floor((np.asarray(t) - 300) / BIN_MIN).astype(int)
        j = ctx.luts[key][gate][direction][o]
        ok = (b >= 0) & (b < N_BINS) & (j >= 0)
        np.add.at(D, (b[ok], j[ok]), pcu)

    for ci, c in enumerate(calls):
        gate = ctx.terminal_gate[c.terminal]
        berths = c.pax if c.pax else rng.uniform(*UNKNOWN_PAX_RANGE)
        arr, dep = minutes(c.arrival), minutes(c.departure)
        dis_shift, emb_shift = shifts[ci] if shifts else (0, 0)
        start = (arr + rng.normal(0.0, p.arrival_delay_sd_min) + p.disembark_start_min + dis_shift
                 + cruise["dis_shift"])
        lo = dep - p.embark_open_before_dep_min + emb_shift
        hi = dep - p.embark_close_before_dep_min + emb_shift
        for leg in ("dis", "emb"):
            people = int(round(berths * rng.beta(*p.load_factor_beta)))
            n_car, n_park, n_taxi, n_coach, _ = rng.multinomial(people, rng.dirichlet(mode_mean * MODE_CONC))
            cars, parks = round(n_car / PEOPLE_PER["car"]), round(n_park / PEOPLE_PER["park"])
            taxis, coaches = round(n_taxi / PEOPLE_PER["taxi"]), math.ceil(n_coach / PEOPLE_PER["coach"])
            if leg == "dis":
                def when(n):
                    return start + p.disembark_duration_min * rng.beta(2.0, 3.0, n)
                t = when(cars)
                o = add(t - 20, "car_from", gate, "in", 1.0)
                if o is not None:
                    put(t + 5, o, "car_from", gate, "out", 1.0)
                add(when(parks) + 10, "car_from", gate, "out", 1.0)
                t = when(taxis)
                add(t - 15, "taxi_rank", gate, "in", 1.0)
                add(t, "taxi_far", gate, "out", 1.0)
                o = add(start - 30 + 120 * rng.random(coaches), "coach_from", gate, "in", COACH_PCU)
                if o is not None:
                    put(when(coaches) + 20, o, "coach_from", gate, "out", COACH_PCU)
            else:
                def when(n):
                    return lo + (hi - lo) * rng.beta(2.0, 2.0, n)
                t = when(cars)
                o = add(t, "car_from", gate, "in", 1.0)
                if o is not None:
                    put(t + 15, o, "car_from", gate, "out", 1.0)
                add(when(parks) - 10, "car_from", gate, "in", 1.0)
                t = when(taxis)
                add(t, "taxi_far", gate, "in", 1.0)
                add(t + 10, "taxi_rank", gate, "out", 1.0)
                t = when(coaches)
                o = add(t, "coach_from", gate, "in", COACH_PCU)
                if o is not None:
                    put(t + 20, o, "coach_from", gate, "out", COACH_PCU)
    return D


# --- forecasting (runs in worker processes) ----------------------------------------------------

CTX: Ctx | None = None
_SHARES: dict = {}


def _init(path: str) -> None:
    global CTX
    with open(path, "rb") as f:
        CTX = pickle.load(f)


def capacity(ctx: Ctx, closed) -> np.ndarray:
    cap = ctx.m.cap.copy()
    for cid, _, _, idx in ctx.corr:
        if cid in closed:
            cap[idx] *= LANE_CLOSED
    return cap


def kickoff_hours(k):
    if not k:
        return None
    hh, mm = map(int, k.split(":"))
    return hh + mm / 60


def base_shares(ctx: Ctx, dtype: int, closed, kick, term=True):
    key = (dtype, tuple(sorted(closed)), kick, term)
    if key not in _SHARES:
        D, _ = tm.background(ctx.m, dtype, term=term)
        if kick:
            D = D + tm.match_demand(ctx.m, kickoff_hours(kick))
        _, sh = tm.run_day(ctx.m, D, capacity(ctx, closed), tm.initial_shares(ctx.m), 10, want=(),
                           pre=ctx.m.pre.get(dtype))
        _SHARES[key] = sh
    return _SHARES[key]


P_WET = {10: 0.50, 11: 0.55, 12: 0.55, 1: 0.55}  # share of rainy days (assumed climatology)
WET_CAPACITY = 0.93  # roads carry a little less in the wet
WET_DEMAND = 1.03  # and a few more people drive
INCIDENT_P = 0.15  # chance a day has a breakdown or crash on a main road
PERCEPTION_SD = 0.12  # how far drivers misjudge a road's travel time, shared by all its users
MAJOR_CLASSES = {"motorway", "trunk", "primary"}
# (month, day) -> traffic compared with a normal day over Christmas and New Year. Observed:
# daytime totals at WebTRIS M3 J14 (20025) and M271 (19974), 2024 and 2025, against the same
# weekday 2-6 weeks earlier (28 Dec-2 Jan rounded from ranges across both sites and years).
FESTIVE_DAYS = {(12, 24): 0.65, (12, 25): 0.30, (12, 26): 0.50, (12, 27): 0.70,
                (12, 28): 0.80, (12, 29): 0.80, (12, 30): 0.80, (12, 31): 0.60,
                (1, 1): 0.40, (1, 2): 0.75}
SHOPS_SHUT = {(12, 25), (1, 1)}


def lead_spread(d: date) -> float:
    """Uncertainty grows with how far ahead the date is: x1 tomorrow, x1.6 six weeks out."""
    return 1.0 + 0.6 * min(1.0, max(0, (d - ISSUED.date()).days) / 42)


def day_multipliers(d: date, wet: bool) -> dict:
    """Weekday pattern, Christmas shopping, Christmas to New Year and weather, per kind of trip."""
    wd = d.weekday()
    commute = {0: 0.97, 1: 1.02, 2: 1.03, 3: 1.02, 4: 0.93}.get(wd, 1.0)
    visitors = {4: 1.06}.get(wd, 1.0)
    start, peak = date(d.year, 11, 14), date(d.year, 12, 23)
    if start <= d <= peak:  # Christmas shopping builds week by week, then drops back
        visitors *= 1.10 + 0.05 * ((d - start).days // 7)
    # Christmas to New Year: commuting, local and through trips fall away; shops shut on
    # Christmas Day and New Year's Day
    hol = FESTIVE_DAYS.get((d.month, d.day), 1.0)
    if (d.month, d.day) in SHOPS_SHUT:
        visitors *= hol
    w = WET_DEMAND if wet else 1.0
    return {"county": commute * w * hol, "outbound": commute * w * hol, "internal": w * hol,
            "through": hol, "visitors": visitors * w, "school": w, "freight": hol}


def load_freight_days(log=print) -> tuple[dict, dict | None]:
    """Port lorry factors per day from the cached VTS freight snapshots (see freight_days.py),
    and their source for the page. Without snapshots every day keeps the DfT-fitted average."""
    try:
        import pandas as pd
        from sotonship26.data import vts_freight as vf
    except ImportError as exc:
        log(f"VTS freight: loader unavailable ({exc}); port lorries stay at the DfT-fitted average")
        return {}, None
    frames = [f for f in vf.load_extracts() if len(f)]
    if not frames:
        log(f"VTS freight: no snapshots in {vf.RAW_DIR}; "
            "port lorries stay at the DfT-fitted average")
        return {}, None
    factors = fd.freight_day_factors(vf.daily_freight_calls(frames))
    stamps = [pd.Timestamp(f["collected_at"].max()) for f in frames]
    taken = max(t if t.tzinfo else t.tz_localize("UTC") for t in stamps).tz_convert("Europe/London")
    for d, f in sorted(factors.items()):
        log(f"VTS freight {d}: {f['moves']} container and ro-ro movements (mean {f['mean_moves']}) "
            f"-> port lorries x{f['factor']:.2f}"
            + (f", {f['unconfirmed']} not confirmed" if f["unconfirmed"] else ""))
    when = taken.strftime("%d %b %Y %H:%M")
    return factors, {
        "label": f"{fd.CREDIT}: planned container and ro-ro movements, {len(frames)} snapshot"
                 f"{'s' if len(frames) > 1 else ''}, latest {when}",
        "short": f"latest snapshot {when}", "synthetic": False, "url": vf.SOURCE_PAGE,
        "checked": taken.date().isoformat(), "shrink": fd.SHRINK, "days": sorted(factors)}


def forecast(task: dict) -> dict:
    """Monte Carlo forecast for one day.

    Each sampled day draws correlated everyday-traffic noise, weather, maybe an incident, how
    drivers misjudge road speeds, and the cruise traffic. With ``paired`` the same draws are also
    run without the ships, so the cruise effect is measured day by day rather than between two
    unrelated sets of samples.
    """
    ctx = CTX
    m = ctx.m
    d = date.fromisoformat(task["date"])
    dtype = tm.daytype(d.weekday())
    calls = [Call(c["ship"], c["terminal"], datetime.fromisoformat(c["arrival"]),
                  datetime.fromisoformat(c["departure"]), c["pax"]) for c in task["calls"]]
    closed, kick, full = set(task["closed"]), task["match"], task["full"]
    paired = task.get("paired", False)
    term, shifts, pre = task.get("term", True), task.get("shifts"), m.pre.get(dtype)
    cap0 = capacity(ctx, closed)
    sh0 = base_shares(ctx, dtype, closed, kick, term)
    run_c = m.t0 * 0.15 / 60.0
    spread = lead_spread(d)
    params = replace(TurnaroundParams(),
                     arrival_delay_sd_min=TurnaroundParams().arrival_delay_sd_min * spread)
    segs = ctx.extra["segs"]
    major = [i for i, sg in enumerate(segs) if sg["cls"] in MAJOR_CLASSES]
    major_w = np.array([sum(m.length[e] for e in segs[i]["edges"]) for i in major], float)
    major_w /= major_w.sum()
    acc = defaultdict(lambda: 0.0)
    gates_s, delays, scores = [], [], []
    rng = np.random.default_rng([SEED, d.toordinal()])

    def corridor_stats(x):
        cx = np.maximum.reduceat(x[:, ctx.corr_idx], ctx.corr_ptr, axis=1)
        xc = x[:, ctx.corr_idx]
        slow = np.add.reduceat(run_c[ctx.corr_idx] * np.minimum(xc, 1.5) ** 4, ctx.corr_ptr, axis=1) / 2
        return cx, slow + 15.0 * np.maximum(cx - 1.0, 0.0)

    for _ in range(task["n"]):
        wet = rng.random() < P_WET.get(d.month, 0.5)
        cap = cap0 * (WET_CAPACITY if wet else 1.0)
        events = []
        if rng.random() < INCIDENT_P:
            seg = segs[major[rng.choice(len(major), p=major_w)]]
            b0 = int(rng.integers(0, N_BINS - 4))
            events.append((np.asarray(seg["edges"]), b0, b0 + int(rng.integers(4, 9)), 0.55))
        noise = rng.lognormal(-PERCEPTION_SD**2 / 2, PERCEPTION_SD, len(m.t0))
        mult = day_multipliers(d, wet)
        mult["freight"] = mult.get("freight", 1.0) * task.get("freight_f", 1.0)
        Dbg, groups = tm.background(m, dtype, rng, term=term, spread=spread, mult=mult)
        Dm = tm.match_demand(m, kickoff_hours(kick), rng) if kick else np.zeros_like(Dbg)
        Dc = sample_cruise(ctx, calls, rng, params, shifts, task.get("cruise")) if calls else np.zeros_like(Dbg)
        probe = task.get("probe") if paired and calls else None  # edges for the M271 fit
        want = base_want = ("x",) + (("count",) if probe is not None else ())
        if full:
            want += ("queue", "held")
            if calls:
                want += ("cruise_edge", "cruise_path", "path", "time")
        res, _ = tm.run_day(m, Dbg + Dm + Dc, cap, sh0, 3, cruise=Dc if calls else None, want=want,
                            pre=pre, noise=noise, events=events)
        x = res["x"]
        cx, delay = corridor_stats(x)
        acc["p85"] = acc["p85"] + (cx > tm.AT_RISK)
        acc["p100"] = acc["p100"] + (cx > 1.0)
        acc["vc"] = acc["vc"] + cx
        acc["delay"] = acc["delay"] + delay
        delays.append(delay.astype(np.float32))
        sc = float((cx > tm.AT_RISK).sum() * BIN_MIN / 60)
        if paired:
            if calls:
                rb, _ = tm.run_day(m, Dbg + Dm, cap, sh0, 3, want=base_want, pre=pre, noise=noise,
                                   events=events)
                cxb, _ = corridor_stats(rb["x"])
                if probe is not None:  # paired cruise flow on chosen edges, veh/h
                    # what a counter there sees, each vehicle once and at most capacity, as the
                    # WebTRIS site the learned uplift comes from (SOT-30)
                    pe = np.asarray(probe)
                    diff = (np.minimum(res["count"][:, pe], cap[pe])
                            - np.minimum(rb["count"][:, pe], cap[pe]))
                    acc["probe"] = acc["probe"] + diff.mean(axis=1)
            else:
                cxb = cx
            acc["bg85"] = acc["bg85"] + (cxb > tm.AT_RISK)
            scores.append((sc, float((cxb > tm.AT_RISK).sum() * BIN_MIN / 60), wet, bool(events)))
        if not full:
            continue
        acc["seg_x"] = acc["seg_x"] + np.maximum.reduceat(x[:, ctx.seg_idx], ctx.seg_ptr, axis=1)
        acc["seg_q"] = acc["seg_q"] + np.add.reduceat(res["queue"][:, ctx.seg_idx], ctx.seg_ptr, axis=1)
        acc["held"] = acc["held"] + res["held"]
        for g, v in groups.items():
            acc["mix_" + g] = acc["mix_" + g] + v * 4
        acc["mix_match"] = acc["mix_match"] + Dm.sum(axis=1) * 4
        acc["mix_cruise"] = acc["mix_cruise"] + Dc.sum(axis=1) * 4
        acc["gw_in"] = acc["gw_in"] + ((Dbg + Dm + Dc) @ ctx.gw_in) * 4
        if calls:
            acc["seg_c"] = acc["seg_c"] + np.maximum.reduceat(res["cruise_edge"][:, ctx.seg_idx], ctx.seg_ptr, axis=1)
            acc["path_c"] = acc["path_c"] + res["cruise_path"]
            acc["share"] = acc["share"] + res["path"][:, ctx.cruise_ods, :]
            acc["time"] = acc["time"] + res["time"][:, ctx.cruise_ods, :]
            gates_s.append((Dc @ ctx.gate_mask) * 4)
    n = task["n"]
    out = {k: v / n for k, v in acc.items()}
    dl = np.asarray(delays)
    out["delay50"] = np.percentile(dl, 50, axis=0)
    out["delay90"] = np.percentile(dl, 90, axis=0)
    out["scores"] = scores
    out["spread"] = spread
    if gates_s:
        gs = np.asarray(gates_s)
        out["gates"] = {"mean": gs.mean(0), "p10": np.percentile(gs, 10, axis=0),
                        "p90": np.percentile(gs, 90, axis=0)}
    out["date"], out["key"] = task["date"], task["key"]
    return out


def m271_probe(m: tm.Model) -> list[int]:
    """M271 northbound main-carriageway links between the A35 at Redbridge and junction 1, where
    WebTRIS 19974 counts: the two southernmost northbound links of 200 m or more."""
    ks = [k for k in range(len(m.t0))
          if "M271" in m.ref[k].split(";") and m.cls[k] == "motorway" and m.length[k] >= 200
          and m.coords[k][-1][1] < m.coords[k][0][1]]
    ks.sort(key=lambda k: -max(c[1] for c in m.coords[k]))
    return ks[:2]


CAL_DATE = "2026-10-24"  # an October term-time Saturday; no home match is needed for the fit


def cruise_fit_tasks(probe: list[int], n: int) -> list[dict]:
    """Paired runs of a calibration Saturday with 5,000 berths at each dock, for every grid point."""
    calls = [{"ship": "Calibration East", "terminal": "Ocean", "arrival": f"{CAL_DATE}T06:30",
              "departure": f"{CAL_DATE}T17:00", "pax": 5000},
             {"ship": "Calibration West", "terminal": "Mayflower", "arrival": f"{CAL_DATE}T06:30",
              "departure": f"{CAL_DATE}T17:00", "pax": 5000}]
    tasks = []
    for road in CRUISE_GRID["road"]:
        for county in CRUISE_GRID["county"]:
            for shift in CRUISE_GRID["dis_shift"]:
                tasks.append({"date": CAL_DATE, "key": f"fit {road} {county} {shift}",
                              "calls": calls, "full": False, "paired": True, "closed": [],
                              "match": None, "n": n, "term": True, "probe": probe,
                              "cruise": {"road": road, "county": county, "dis_shift": shift}})
    return tasks


def learned_target() -> np.ndarray | None:
    """The learned ships' part on the M271 northbound, Saturday with 5,000 berths at each dock,
    per 15 minutes from 05:00 to 20:00."""
    path = HERE / "out" / "backtest.json"
    if not path.exists():
        return None
    prof = json.loads(path.read_text(encoding="utf-8")).get("effect", {}).get("cruise_profiles")
    if not prof:
        return None
    full = np.asarray(prof["profiles"]["saturday"]["both_10k"], float)  # 96 bins from 00:00
    return full[20:20 + N_BINS]


def advise(task: dict) -> dict:
    """Try moving each ship's disembarkation start and check-in window; keep moves that cut risk.

    Coordinate descent, one pass, the same sampled days for every option (so differences come from
    the timing, not the sampling). A move is kept only if it lowers corridor-hours at risk by more
    than 0.15.
    """
    calls = task["calls"]
    shifts = [[0, 0] for _ in calls]

    def run(sh):
        return score(forecast({**task, "full": False, "shifts": sh})["p85"])

    base = best = run(shifts)
    options = []
    for i, c in enumerate(calls):
        opts = {"dis": {0: round(best, 2)}, "emb": {}}
        for kind, values in (("dis", DIS_OPTS), ("emb", EMB_OPTS)):
            j = 0 if kind == "dis" else 1
            opts[kind][0] = round(best, 2)
            for o in values:
                trial = [list(x) for x in shifts]
                trial[i][j] = o
                sc = run(trial)
                opts[kind][o] = round(sc, 2)
                if sc < best - 0.15:
                    best, shifts = sc, trial
        options.append(opts)
    return {"date": task["date"], "base": round(base, 2), "best": round(best, 2), "shifts": shifts,
            "options": options}


# --- output helpers ----------------------------------------------------------------------------

def ranges(scores) -> dict:
    """10th, 50th and 90th percentiles of the day's samples, plus the paired cruise effect."""
    a = np.asarray([[s[0], s[1]] for s in scores], float)
    up = a[:, 0] - a[:, 1]
    q = lambda v: [round(float(x), 1) for x in np.percentile(v, [10, 50, 90])]  # noqa: E731
    return {"score": q(a[:, 0]), "bg": q(a[:, 1]), "uplift": q(up),
            "samples": sorted(round(float(x), 1) for x in up),
            "wet": [bool(s[2]) for s in scores], "incident": [bool(s[3]) for s in scores],
            "pairs": [[round(float(s[0]), 1), round(float(s[1]), 1)] for s in scores]}


def backtest_summary() -> dict | None:
    """The page's slice of demo/out/backtest.json (written by demo/webtris_backtest.py), if run."""
    path = HERE / "out" / "backtest.json"
    if not path.exists():
        return None
    bt = json.loads(path.read_text(encoding="utf-8"))
    keep = ("title", "generated", "observable", "models", "split", "card", "effect", "limits",
            "sources", "thresholds")
    out = {k: bt[k] for k in keep if k in bt}
    out["results"] = {"per_day": bt["results"]["per_day"]["all"],
                      "per_15min": bt["results"]["per_15min"]["all"]}
    return out


def pct(a) -> list:
    return np.rint(np.asarray(a) * 100).astype(int).tolist()


def half_hour(a: np.ndarray) -> np.ndarray:
    return a.reshape(N_BINS // 2, 2, *a.shape[1:]).mean(axis=1)


def code(levels: np.ndarray) -> str:
    return "".join(CHARS[int(v)] for v in np.clip(levels, 0, 35))


def score(p85: np.ndarray) -> float:
    return float(np.asarray(p85).sum() * BIN_MIN / 60)


def path_d(points, tol: float) -> str:
    from shapely.geometry import LineString

    pts = []
    for p in points:
        if not pts or tuple(p) != pts[-1]:
            pts.append(tuple(p))
    if len(pts) < 2:
        return ""
    line = LineString(pts).simplify(tol)
    c = [(round(x), round(y)) for x, y in line.coords]
    rel = " ".join(f"{b[0] - a[0]} {b[1] - a[1]}" for a, b in zip(c, c[1:], strict=False))
    return f"M{c[0][0]} {c[0][1]}l{rel}"


def edge_chain(m: tm.Model, edges) -> list:
    pts = []
    for e in edges:
        pts += [tuple(p) for p in m.coords[e]]
    return pts


# --- cruise schedule: VTS when collected, else synthetic --------------------------------------

def make_schedule(rng):
    """The VTS schedule in SCHEDULE_CSV when it has been collected, else the invented one."""
    if SCHEDULE_CSV.exists():
        return vts_schedule(SCHEDULE_CSV)
    SOURCES["schedule"] = {"label": "Synthetic schedule", "short": "synthetic", "synthetic": True,
                           "note": "Invented ships, terminals and times"}
    return synthetic_schedule(rng)


def vts_schedule(path: Path) -> dict:
    """Calls per day from the CSV demo/collect_schedule.py writes (load_schedule's columns)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    sched = {FIRST_DAY + timedelta(days=i): [] for i in range((HORIZON - FIRST_DAY).days + 1)}
    for r in rows:
        arr, dep = datetime.fromisoformat(r["arrival"]), datetime.fromisoformat(r["departure"])
        if arr.date() not in sched:
            continue
        pax = int(r["passengers"]) if (r.get("passengers") or "").strip() else None
        # one model day per call: an overnight stay counts as a turnaround on its arrival day
        times = r.get("times") or "exact"
        sched[arr.date()].append(Call(r["ship"], r["terminal"], arr, dep, pax, times))
    for calls in sched.values():
        calls.sort(key=lambda c: (c.arrival, c.ship))
    stamps = [r["collected"] for r in rows if r.get("collected")]
    got = datetime.fromisoformat(max(stamps)) if stamps else None
    when = f"{got.day} {got:%b %Y %H:%M}" if got else "date not recorded"
    used = [c for v in sched.values() for c in v]
    SOURCES["schedule"] = {
        "label": f"VTS schedule, collected {when}", "short": f"VTS, collected {when}",
        "synthetic": False, "collected": got.isoformat() if got else None, "url": VTS_PAGE,
        "calls": len(used), "typical_times": sum(c.times != "exact" for c in used),
        "note": ("ABP Southampton VTS provisional cruise ship schedule; lower-berth capacity from "
                 "each cruise line's ship facts. Where VTS lists TBA, AM or PM the typical times "
                 "in the same feed are used.")}
    return sched


def synthetic_schedule(rng):
    sched = {}
    d = FIRST_DAY
    while d <= HORIZON:
        wd = d.weekday()
        if wd == 5:
            n = rng.choice([3, 4, 5], p=[0.25, 0.45, 0.30])
        elif wd == 6:
            n = rng.choice([2, 3, 4], p=[0.3, 0.45, 0.25])
        elif wd == 4:
            n = rng.choice([1, 2, 3], p=[0.3, 0.5, 0.2])
        else:
            n = rng.choice([0, 1, 2], p=[0.35, 0.45, 0.2])
        if d >= date(2026, 11, 9) and n > 0 and rng.random() < 0.35:
            n -= 1
        terminals = rng.choice(TERMINALS, size=n, replace=False)
        ships = rng.choice(len(SHIPS), size=n, replace=False)
        calls = []
        for term, s in zip(terminals, ships, strict=True):
            arr = datetime.combine(d, time(5, 30)) + timedelta(minutes=15 * int(rng.integers(0, 7)))
            dep = datetime.combine(d, time(16, 0)) + timedelta(minutes=30 * int(rng.integers(0, 6)))
            calls.append(Call(SHIPS[s][0], str(term), arr, dep, SHIPS[s][1]))
        sched[d] = sorted(calls, key=lambda c: (c.arrival, c.ship))
        d += timedelta(days=1)
    d = date(2026, 11, 4)
    used = {c.terminal for c in sched[d]}
    term = next(t for t in TERMINALS if t not in used)
    sched[d].append(Call("Unlisted Voyager", term, datetime.combine(d, time(6, 0)),
                         datetime.combine(d, time(17, 0)), None))
    return sched


def in_term(d: date) -> bool:
    return d.weekday() < 5 and not (HALF_TERM[0] <= d <= HALF_TERM[1]) and d <= TERM_ENDS


def permits_on(d: date):
    iso = d.isoformat()
    return [p for p in PERMITS if p["from"] <= iso <= p["to"]]


def match_on(d: date):
    return next((x["kickoff"] for x in MATCHES if x["date"] == d.isoformat()), None)


# --- main --------------------------------------------------------------------------------------

def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=30, help="sampled days per date (each run with and without ships)")
    parser.add_argument("--n-bg", type=int, default=15, help="sampled days without cruise traffic")
    parser.add_argument("--whatif-days", type=int, default=6)
    parser.add_argument("--advise-days", type=int, default=10)
    parser.add_argument("--n-fit", type=int, default=8, help="sampled days per grid point in the M271 fit")
    parser.add_argument("--no-fit", action="store_true", help="skip fitting cruise assumptions")
    parser.add_argument("--n-advise", type=int, default=16)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--days", type=int, help="only the first N days (for testing)")
    parser.add_argument("--template", type=Path, default=HERE / "page.html")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "demo.html")
    args = parser.parse_args(argv)
    started = clock.perf_counter()

    def log(msg):
        print(f"[{clock.perf_counter() - started:6.0f}s] {msg}", flush=True)

    ctx, base = build_ctx(log)
    m = ctx.m
    ctx_path = CACHE / "ctx.pkl"
    with open(ctx_path, "wb") as f:
        pickle.dump(ctx, f)

    sched = make_schedule(np.random.default_rng(SEED))
    freight_f, freight_src = load_freight_days(log)
    if freight_src:
        SOURCES["freight"] = freight_src
    tasks = []
    d = FIRST_DAY
    while d <= HORIZON and (args.days is None or len(tasks) < args.days):
        calls = [{"ship": c.ship, "terminal": c.terminal, "arrival": c.arrival.isoformat(),
                  "departure": c.departure.isoformat(), "pax": c.pax, "times": c.times}
                 for c in sched[d]]
        tasks.append({"date": d.isoformat(), "key": "base", "calls": calls, "full": True,
                      "closed": [p["corridor"] for p in permits_on(d)], "match": match_on(d),
                      "n": args.n, "term": in_term(d), "paired": True,
                      "freight_f": fd.factor_on(freight_f, d)})
        d += timedelta(days=1)
    log(f"forecasting {len(tasks)} days on {args.workers} workers")
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(str(ctx_path),)) as pool:
        cruise_fit = None
        target = learned_target()
        if target is not None and not args.no_fit:
            probe = m271_probe(m)
            log(f"fitting cruise assumptions to the learned M271 uplift (probe links {probe})")
            fits = list(pool.map(forecast, cruise_fit_tasks(probe, args.n_fit)))
            best = None
            for t, r in zip(cruise_fit_tasks(probe, args.n_fit), fits, strict=True):
                sim = r["probe"] / 4.0  # vehicles per 15 minutes
                err = float(np.sqrt(np.mean((sim - target) ** 2)))
                log(f"  {t['cruise']}: simulated {sim.sum():6.0f} vs learned {target.sum():6.0f} "
                    f"vehicles 05-20, RMSE {err:5.1f} per 15 min")
                if best is None or err < best[0]:
                    best = (err, t["cruise"], sim)
            default = next(r for t, r in zip(cruise_fit_tasks(probe, args.n_fit), fits, strict=True)
                           if t["cruise"] == {"road": 1.0, "county": 0.8, "dis_shift": 0.0})
            d_sim = default["probe"] / 4.0
            cruise_fit = {"params": best[1], "rmse": round(best[0], 1),
                          "rmse_before": round(float(np.sqrt(np.mean((d_sim - target) ** 2))), 1),
                          "learned": np.round(target, 1).tolist(),
                          "fitted": np.round(best[2], 1).tolist(),
                          "before": np.round(d_sim, 1).tolist(),
                          "grid": CRUISE_GRID, "default": CRUISE_DEFAULT, "date": CAL_DATE,
                          "n": args.n_fit}
            log(f"chose {best[1]} (RMSE {best[0]:.1f} per 15 min, was {cruise_fit['rmse_before']})")
            for t in tasks:
                t["cruise"] = best[1]
        results = {}
        for r in pool.map(forecast, tasks):
            results[r["date"]] = r
            log(f"{r['date']} score {score(r['p85']):.2f}")
        busiest = sorted((t for t in tasks if t["calls"]), key=lambda t: -score(results[t["date"]]["p85"]))
        chosen = {t["date"] for t in busiest[: args.whatif_days]}
        chosen |= {t["date"] for t in tasks if t["calls"] and t["closed"]}
        wtasks = []
        for t in tasks:
            if t["date"] not in chosen:
                continue
            if t["closed"]:
                wtasks.append({**t, "key": "move_permit", "closed": [], "full": False})
            for road in WHATIF_ROADS:
                if road not in t["closed"] and any(c[0] == road for c in ctx.corr):
                    wtasks.append({**t, "key": f"close_{road}", "closed": t["closed"] + [road],
                                   "full": False, "seg": True})
        log(f"what-ifs: {len(wtasks)}")
        wres = defaultdict(dict)
        for r in pool.map(forecast, [{**w, "full": True, "paired": False} for w in wtasks]):
            wres[r["date"]][r["key"]] = r
            log(f"  what-if {r['date']} {r['key']}: {score(results[r['date']]['p85']):.2f} -> {score(r['p85']):.2f}")
        uplift = {t["date"]: score(results[t["date"]]["p85"]) - score(results[t["date"]]["bg85"]) for t in tasks}
        atasks = sorted((t for t in tasks if t["calls"] and uplift[t["date"]] >= 1.0),
                        key=lambda t: -uplift[t["date"]])[: args.advise_days]
        log(f"ship-timing advice for {len(atasks)} days")
        advice = {}
        for r in pool.map(advise, [{**t, "n": args.n_advise, "paired": False} for t in atasks]):
            advice[r["date"]] = r
            log(f"  advice {r['date']}: {r['base']:.2f} -> {r['best']:.2f} with shifts {r['shifts']}")

    # --- assemble page data --------------------------------------------------------------------
    segs = ctx.extra["segs"]
    seg_out = []
    for s in segs:
        dpath = "".join(path_d(m.coords[k], 2.0) for k in s["links"])
        seg_out.append({"n": s["name"], "c": s["cls"], "d": dpath})
    corr_segs = {}
    edge_seg = np.empty(len(m.t0), int)
    for i, s in enumerate(segs):
        edge_seg[s["edges"]] = i
    for cid, label, group, idx in ctx.corr:
        corr_segs[cid] = sorted({int(edge_seg[k]) for k in idx})
    gws = ctx.extra["gateways"]
    paths_out: dict[int, str] = {}

    def day_json(task, r):
        day = {"date": task["date"], "calls": [
            {"ship": c["ship"], "terminal": c["terminal"],
             "gate": m.centroids[ctx.terminal_gate[c["terminal"]]].name,
             "arr": c["arrival"][11:16], "dep": c["departure"][11:16], "pax": c["pax"],
             "times": c.get("times", "exact")}
            for c in task["calls"]],
            "score": round(score(r["p85"]), 2), "bg_score": round(score(r["bg85"]), 2),
            "permits": [p["id"] for p in permits_on(date.fromisoformat(task["date"]))],
            "match": task["match"], "term": task["term"], "freight": freight_f.get(task["date"]),
            "delay": {c[0]: np.rint(r["delay50"][:, i]).astype(int).tolist() for i, c in enumerate(ctx.corr)},
            "delay90": {c[0]: np.rint(r["delay90"][:, i]).astype(int).tolist() for i, c in enumerate(ctx.corr)},
            "range": ranges(r["scores"]), "spread": round(r["spread"], 2),
            "wet": P_WET.get(date.fromisoformat(task["date"]).month, 0.5), "incident": INCIDENT_P,
            "lead": (date.fromisoformat(task["date"]) - ISSUED.date()).days,
            "timing": advice.get(task["date"]),
            "p85": {c[0]: pct(r["p85"][:, i]) for i, c in enumerate(ctx.corr)},
            "p100": {c[0]: pct(r["p100"][:, i]) for i, c in enumerate(ctx.corr)},
            "vc": {c[0]: pct(r["vc"][:, i]) for i, c in enumerate(ctx.corr)},
            "bg85": {c[0]: pct(r["bg85"][:, i]) for i, c in enumerate(ctx.corr)},
            "seg": code(np.rint(half_hour(r["seg_x"]) / 0.05).T.ravel()),
            "queue": {}, "cruise": {}, "routes": [], "whatif": {},
            "mix": {g: np.rint(r.get("mix_" + g, np.zeros(N_BINS))).astype(int).tolist()
                    for g in tm.GROUPS},
            "held": np.rint(r["held"]).astype(int).tolist(),
            "gw_in": {m.centroids[g].name: np.rint(r["gw_in"][:, i]).astype(int).tolist()
                      for i, g in enumerate(gws)},
            "gates": {}}
        q = half_hour(r["seg_q"])
        for i in np.flatnonzero(q.max(axis=0) >= 5):
            day["queue"][int(i)] = code(np.rint(q[:, i] / 10))
        if task["calls"]:
            c = half_hour(r["seg_c"])
            for i in np.flatnonzero(c.max(axis=0) >= 10):
                day["cruise"][int(i)] = code(np.rint(c[:, i] / 20))
            for gi, g in enumerate(ctx.gates):
                gname = m.centroids[g].name
                if r["gates"]["mean"][:, gi].max() > 0:
                    day["gates"][gname] = {k: np.rint(r["gates"][k][:, gi]).astype(int).tolist()
                                           for k in ("mean", "p10", "p90")}
            # route choice for the busiest cruise origin-destination pairs
            veh = r["path_c"].reshape(N_BINS, m.n_od, tm.ROUTES).sum(axis=(0, 2)) / 4
            picks = []
            for gi, g in enumerate(ctx.gates):
                for direction in ("in", "out"):
                    js = [j for j in ctx.cruise_ods
                          if (m.ods[j][1] == g if direction == "in" else m.ods[j][0] == g)]
                    js = sorted(js, key=lambda j: -veh[j])[: (3 if direction == "in" else 2)]
                    picks += [j for j in js if veh[j] >= 15]
            pos = {int(j): k for k, j in enumerate(ctx.cruise_ods)}
            for j in picks:
                o, dd = m.ods[j]
                routes, seen = [], []
                for rr in range(tm.ROUTES):
                    pid = j * tm.ROUTES + rr
                    if m.paths[pid] in seen:
                        continue
                    seen.append(m.paths[pid])
                    if pid not in paths_out:
                        paths_out[pid] = path_d(edge_chain(m, m.paths[pid]), 6.0)
                    names = []
                    for e in m.paths[pid]:
                        nm = m.ref[e] or m.name[e]
                        if nm and nm not in names and m.length[e] > 150:
                            names.append(nm)
                    routes.append({"pid": pid, "via": names[:4],
                                   "share": pct(r["share"][:, pos[j], rr]),
                                   "min": np.rint(r["time"][:, pos[j], rr] / 6).astype(int).tolist(),
                                   "veh": int(round(r["path_c"][:, pid].sum() / 4))})
                day["routes"].append({"from": m.centroids[o].name, "to": m.centroids[dd].name,
                                      "fromKind": m.centroids[o].kind, "toKind": m.centroids[dd].kind,
                                      "hint": m.centroids[o].hint or m.centroids[dd].hint,
                                      "veh": int(round(veh[j])), "routes": routes})
        base_lv = np.rint(half_hour(r["seg_x"]) / 0.05)
        for key, w in wres.get(task["date"], {}).items():
            entry = {"score": round(score(w["p85"]), 2),
                     "p85": {c[0]: pct(w["p85"][:, i]) for i, c in enumerate(ctx.corr)}, "seg": {}}
            lv = np.rint(half_hour(w["seg_x"]) / 0.05)
            for i in np.flatnonzero(np.abs(lv - base_lv).max(axis=0) >= 1):
                entry["seg"][int(i)] = code(lv[:, i])
            day["whatif"][key] = entry
        return day

    days = [day_json(t, results[t["date"]]) for t in tasks]
    d = HORIZON + timedelta(days=1)
    while d <= CAL_END:
        days.append({"date": d.isoformat(), "beyond": True})
        d += timedelta(days=1)

    x0, y1, to_bng = frame_origin()
    water_labels = []
    for name, lat, lon in WATER_LABELS:
        x, y = to_bng.transform(lon, lat)
        water_labels.append({"name": name, "x": round(x - x0), "y": round(y1 - y)})
    data = {
        "meta": {"synthetic": True, "sources": SOURCES, "issued": ISSUED.strftime("%Y-%m-%dT%H:%M"),
                 "horizon": HORIZON.isoformat(), "n": args.n, "seed": SEED, "bin_minutes": BIN_MIN,
                 "at_risk": tm.AT_RISK, "unknown_pax_range": UNKNOWN_PAX_RANGE, "model": "v0.2-demo",
                 "scale": round(m.scale, 3), "scale_ext": round(m.scale_ext, 3),
                 "scale_freight": round(m.scale_freight, 3),
                 "capacity_notes": ctx.extra["capacity"], "uni_term": tm.UNI_TERM,
                 "count_headroom": tm.COUNT_HEADROOM,
                 "uncertainty": {"p_wet": P_WET, "wet_capacity": WET_CAPACITY, "wet_demand": WET_DEMAND,
                                 "incident_p": INCIDENT_P, "perception_sd": PERCEPTION_SD,
                                 "logit_beta": tm.LOGIT_BETA, "noise": tm.NOISE,
                                 "arrival_sd": TurnaroundParams().arrival_delay_sd_min}, "half_term": [x.isoformat() for x in HALF_TERM],
                 "turnaround": {"disembark_start": TurnaroundParams().disembark_start_min,
                                "disembark_minutes": TurnaroundParams().disembark_duration_min,
                                "embark_open": TurnaroundParams().embark_open_before_dep_min,
                                "embark_close": TurnaroundParams().embark_close_before_dep_min},
                 "lane_closed": LANE_CLOSED,
                 "calibration": {"source": COUNT_SOURCE, "rows": ctx.extra["calibration"],
                                 "day_window_share": tm.DAY_WINDOW_SHARE,
                                 "dft": {"source": ctx.extra["dft"]["source"],
                                         "collected": ctx.extra["dft"]["collected"],
                                         "rows": ctx.extra["dft"]["rows"],
                                         "day_weights": tm.DAY_WEIGHTS,
                                         "estimated_weight": tm.ESTIMATED_WEIGHT},
                                 "freight": {"rows": ctx.extra["freight"], "hgv_pcu": tm.HGV_PCU,
                                             "port_share_m271": tm.PORT_SHARE_M271,
                                             "hgv_limit": tm.FREIGHT_HGV_LIMIT,
                                             "gate_share": tm.PORT_GATE_SHARE,
                                             "day_ratio": tm.FREIGHT_DAYS,
                                             "lorries_each_way":
                                                 round(tm.FREIGHT_LORRIES * m.scale_freight)}},
                 "census": m.census,
                 "counts": {"zones": sum(c.kind == "zone" for c in m.centroids),
                            "gateways": len(gws), "ods": m.n_od, "routes": len(m.paths),
                            "edges": len(m.t0), "segments": len(segs)},
                 "purposes": [{"key": k, "group": g, "totals": t} for k, g, _, _, t, _ in tm.PURPOSES],
                 "groups": tm.GROUPS,
                 "assumptions": {"mode_share": dict(zip(["car", "park", "taxi", "coach", "other"],
                                                        MODE_MEAN.tolist(), strict=True)),
                                 "people_per_vehicle": PEOPLE_PER, "coach_pcu": COACH_PCU}},
        "map": {"size": base["size"], "attribution": base["attribution"], "layers": base["layers"],
                "places": base["places"], "landmarks": base["landmarks"], "water": water_labels},
        "segments": seg_out,
        "corridors": [{"id": c[0], "name": c[1], "group": c[2], "segs": corr_segs[c[0]],
                       "sensor": SENSOR.get(c[0])} for c in ctx.corr],
        "gateways": [{"name": m.centroids[g].name, "hint": m.centroids[g].hint,
                      "x": m.centroids[g].xy[0], "y": m.centroids[g].xy[1]} for g in gws],
        "gates": [{"name": m.centroids[g].name, "x": m.centroids[g].xy[0], "y": m.centroids[g].xy[1]}
                  for g in ctx.gates],
        "zones": [{"name": c.name, "x": c.xy[0], "y": c.xy[1]} for c in m.centroids if c.kind == "zone"],
        "terminal_gate": {t: m.centroids[g].name for t, g in ctx.terminal_gate.items()},
        "paths": {str(k): v for k, v in paths_out.items()},
        "permits": PERMITS, "matches": MATCHES, "days": days,
        "backtest": backtest_summary(),
        "cruise_fit": cruise_fit,
    }
    payload = json.dumps(data, separators=(",", ":"),
                         default=lambda o: o.item() if hasattr(o, "item") else str(o))
    payload = payload.replace("</", "<\\/")
    page = args.template.read_text(encoding="utf-8").replace("__DEMO_DATA__", payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    log(f"wrote {args.out} ({len(page) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
