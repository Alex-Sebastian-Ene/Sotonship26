"""Synthetic demo of the cruise-day traffic forecast described in docs/design.md.

Everything this script produces is invented: the cruise schedule, ship names, road capacities,
background traffic, roadworks permits and match days. Road names follow the Southampton dock area so
the demo reads naturally, but the network is a schematic (not to scale) and no number in it was
observed. It runs the designed pipeline end to end so the product can be shown before real data is
wired in:

    vehicles per dock gate per 15 min -> background load -> route choice over candidate paths
    (PathFinder negotiation) -> Monte Carlo over sampled days -> P(V/C > 0.85) per road per bin

Run it without the torch-heavy project environment:

    uv run --no-project --python 3.12 --with numpy --with networkx --with pandas \
        python demo/synthetic_demo.py --out demo/out/cruise-day-demo.html
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time as clock
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import islice
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sotonship26.demand.passengers import TurnaroundParams  # noqa: E402

BIN_MIN = 15
N_BINS = 60  # 05:00-20:00
DAY_START_MIN = 5 * 60
ISSUED = datetime(2026, 10, 16, 22, 30)
FIRST_DAY = date(2026, 10, 17)
HORIZON = date(2026, 11, 29)  # last day the synthetic schedule covers
CAL_END = date(2026, 12, 6)  # the calendar runs a week past it to show the refusal
AT_RISK = 0.85  # UK ratio-of-flow-to-capacity design threshold
PACKET_PCU = 20.0
SEED = 26

# Schematic positions, not to scale: id -> (label, x, y, kind)
NODES = {
    "W": ("M271 / A35 (west)", 2, 50, "approach"),
    "RB": ("Redbridge", 16, 50, "junction"),
    "MB": ("Millbrook roundabout", 34, 52, "junction"),
    "G20": ("Western Docks west gate", 34, 68, "gate"),
    "MW": ("Mountbatten Way junction", 52, 46, "junction"),
    "CS": ("Central station", 58, 32, "station"),
    "WE": ("Western Esplanade junction", 66, 56, "junction"),
    "G10": ("Western Docks east gate", 64, 70, "gate"),
    "TQ": ("Town Quay", 80, 64, "junction"),
    "PR": ("Platform Road junction", 94, 62, "junction"),
    "G4": ("Eastern Docks gate", 98, 76, "gate"),
    "CR": ("Canute Road", 106, 48, "junction"),
    "N": ("A33 The Avenue (north)", 72, 2, "approach"),
    "CP": ("Charlotte Place", 74, 18, "junction"),
    "CC": ("City centre", 78, 36, "centre"),
    "SD": ("Six Dials / St Mary's", 98, 24, "junction"),
    "E": ("A3024 Northam Bridge (east)", 120, 16, "approach"),
}


@dataclass(frozen=True)
class Corridor:
    id: str
    name: str
    a: str
    b: str
    km: float
    lanes: int
    lane_cap: float  # vehicles per hour per lane
    bg: float  # background V/C at the weekday peak
    kind: str  # approach, retail, urban or gate


CORRIDORS = [
    Corridor("a35", "A35 Redbridge Road / M271", "W", "RB", 1.5, 2, 1700, 0.62, "approach"),
    Corridor("a33w", "A33 Millbrook Road West", "RB", "MB", 2.0, 2, 1500, 0.62, "approach"),
    Corridor("g20", "Western Docks west gate access", "MB", "G20", 0.5, 1, 1000, 0.25, "gate"),
    Corridor("mountbatten", "Mountbatten Way", "MB", "MW", 1.6, 2, 1300, 0.62, "retail"),
    Corridor("wqr", "West Quay Road", "MW", "WE", 0.9, 2, 950, 0.55, "retail"),
    Corridor("g10", "Western Docks east gate access", "WE", "G10", 0.4, 1, 1000, 0.25, "gate"),
    Corridor("station", "Central station approach", "MW", "CS", 0.5, 1, 800, 0.50, "urban"),
    Corridor("esplanade", "Western Esplanade", "WE", "TQ", 0.8, 1, 1000, 0.50, "urban"),
    Corridor("platform", "Platform Road", "TQ", "PR", 0.8, 2, 900, 0.52, "urban"),
    Corridor("g4", "Eastern Docks gate access", "PR", "G4", 0.4, 1, 1000, 0.25, "gate"),
    Corridor("canute", "Canute Road", "PR", "CR", 0.6, 1, 850, 0.45, "urban"),
    Corridor("terminus", "Terminus Terrace", "CR", "SD", 1.1, 1, 900, 0.50, "urban"),
    Corridor("queensway", "Queensway", "CC", "TQ", 0.9, 2, 850, 0.50, "urban"),
    Corridor("civic", "Civic Centre Road", "CC", "CS", 0.9, 2, 900, 0.58, "retail"),
    Corridor("kingsway", "Kingsway", "CP", "CC", 0.8, 2, 900, 0.60, "retail"),
    Corridor("avenue", "A33 The Avenue", "N", "CP", 3.0, 2, 1300, 0.60, "approach"),
    Corridor("stmarys", "St Mary's Road", "SD", "CP", 1.0, 2, 900, 0.58, "urban"),
    Corridor("northam", "A3024 Northam Bridge", "E", "SD", 2.0, 2, 1300, 0.65, "approach"),
]
NC = len(CORRIDORS)
CORR_INDEX = {c.id: i for i, c in enumerate(CORRIDORS)}
SPEED_KMH = {"approach": 50, "retail": 30, "urban": 30, "gate": 15}
WEEKEND = {"approach": (0.85, 0.8), "retail": (1.08, 1.0), "urban": (0.9, 0.82), "gate": (0.8, 0.8)}
SENSOR = {"a35": "Sensor planned: National Highways WebTRIS on the M271"}

# Hourly traffic profiles for 05:00..19:00, peak = 1
PROFILES = {
    "weekday": [0.22, 0.48, 0.85, 1.0, 0.86, 0.72, 0.72, 0.76, 0.76, 0.76, 0.84, 0.95, 1.0, 0.84, 0.6],
    "saturday": [0.14, 0.24, 0.4, 0.56, 0.72, 0.86, 0.96, 1.0, 1.0, 0.95, 0.9, 0.84, 0.74, 0.6, 0.46],
    "sunday": [0.1, 0.17, 0.28, 0.4, 0.55, 0.7, 0.82, 0.9, 0.92, 0.9, 0.85, 0.8, 0.7, 0.55, 0.4],
}

GATES = ["G20", "G10", "G4"]
GATE_NAMES = {g: NODES[g][0] for g in GATES}
TERMINALS = ["Ocean", "QEII", "Mayflower", "City", "Horizon"]
TERMINAL_GATE = {  # assumed for the demo; verify against ABP's directions to each terminal
    "Ocean": "G4",
    "QEII": "G4",
    "Mayflower": "G10",
    "City": "G10",
    "Horizon": "G20",
}
ORIGINS = ["W", "N", "E", "CS", "CC"]

# Mode split (invented, to be learned from observed traffic): car drop-off/pick-up, park & cruise,
# taxi, coach, other (walk, shuttle)
MODE_MEAN = np.array([0.22, 0.28, 0.20, 0.25, 0.05])
MODE_CONC = 60.0
PEOPLE_PER = {"car": 2.4, "park": 2.4, "taxi": 2.0, "coach": 40.0}
COACH_PCU = 2.0
CAR_FROM = (["W", "N", "E", "CC"], np.array([0.45, 0.25, 0.20, 0.10]))
TAXI_RANK = (["CS", "CC"], np.array([0.6, 0.4]))
TAXI_FAR = (["CS", "CC", "W", "N"], np.array([0.55, 0.15, 0.2, 0.1]))
COACH_FROM = (["W", "N"], np.array([0.6, 0.4]))

SHIPS = [
    ("Synthetic Seas", 3600),
    ("Demo Meridian", 2100),
    ("Sample Serenade", 4900),
    ("Mock Mariner", 2600),
    ("Trial Tern", 1900),
    ("Proxy Pearl", 3100),
    ("Model Majesty", 5200),
    ("Test Tide", 2400),
    ("Placeholder Spirit", 4200),
    ("Stub Starlight", 3000),
    ("Draft Dawn", 2800),
    ("Example Explorer", 3900),
]
UNKNOWN_PAX_RANGE = (1800, 4500)

PERMITS = [
    {"id": "P1", "corridor": "wqr", "from": "2026-10-23", "to": "2026-10-25",
     "what": "Lane closure for utility works"},
    {"id": "P2", "corridor": "platform", "from": "2026-11-14", "to": "2026-11-15",
     "what": "Lane closure for resurfacing"},
    {"id": "P3", "corridor": "avenue", "from": "2026-11-03", "to": "2026-11-05",
     "what": "Lane closure for a gas main repair"},
]
MATCHES = [  # home matches at St Mary's (invented fixtures)
    {"date": "2026-10-24", "kickoff": "15:00"},
    {"date": "2026-11-03", "kickoff": "19:45"},
    {"date": "2026-11-21", "kickoff": "12:30"},
]
MATCH_ROADS = {"northam", "stmarys", "terminus", "kingsway"}
WHATIF_ROADS = ["wqr", "mountbatten", "platform", "a33w"]
LANE_CLOSED = 0.75  # capacity left with one lane coned off under traffic management


@dataclass(frozen=True)
class Call:
    ship: str
    terminal: str
    arrival: datetime
    departure: datetime
    pax: int | None


# --- network -------------------------------------------------------------------------------------

def build_network():
    graph = nx.DiGraph()
    t0 = np.empty(2 * NC)
    cap = np.empty(2 * NC)
    for i, c in enumerate(CORRIDORS):
        secs = c.km / SPEED_KMH[c.kind] * 3600
        for k, (u, v) in enumerate(((c.a, c.b), (c.b, c.a))):
            graph.add_edge(u, v, idx=2 * i + k, t0=secs)
            t0[2 * i + k] = secs
            cap[2 * i + k] = c.lanes * c.lane_cap
    return graph, t0, cap


GRAPH, T0, BASE_CAP = build_network()
ODS = [(o, g, d) for o in ORIGINS for g in GATES for d in ("in", "out")]
OD_INDEX = {od: j for j, od in enumerate(ODS)}
GATE_MATRIX = np.array([[1.0 if od[1] == g else 0.0 for g in GATES] for od in ODS])


def candidate_paths(src: str, dst: str, k: int = 4, slack: float = 1.6) -> list[list[int]]:
    """Up to ``k`` sensible routes: the fastest and alternatives within ``slack`` of it."""
    out: list[list[int]] = []
    best = None
    for path in islice(nx.shortest_simple_paths(GRAPH, src, dst, weight="t0"), 12):
        edges = list(zip(path, path[1:], strict=False))
        cost = sum(GRAPH[u][v]["t0"] for u, v in edges)
        best = best if best is not None else cost
        if cost > slack * best:
            break
        out.append([GRAPH[u][v]["idx"] for u, v in edges])
        if len(out) == k:
            break
    return out


CANDIDATES = [candidate_paths(o, g) if d == "in" else candidate_paths(g, o) for o, g, d in ODS]


def capacity(closed: set[str]) -> np.ndarray:
    """Capacity per directed edge with a lane coned off on each corridor in ``closed``."""
    cap = BASE_CAP.copy()
    for cid in closed:
        i = CORR_INDEX[cid]
        cap[2 * i : 2 * i + 2] *= LANE_CLOSED
    return cap


# --- background traffic --------------------------------------------------------------------------

BIN_HOURS = 5 + (np.arange(N_BINS) + 0.5) / 4


def background(d: date, rng: np.random.Generator) -> np.ndarray:
    """Vehicles per hour on each directed edge per bin, before any cruise traffic."""
    wd = d.weekday()
    kind = "saturday" if wd == 5 else "sunday" if wd == 6 else "weekday"
    profile = np.interp(BIN_HOURS, np.arange(5, 20) + 0.5, PROFILES[kind])
    day_noise = rng.lognormal(0.0, 0.05)
    match = next((m for m in MATCHES if m["date"] == d.isoformat()), None)
    bump = np.ones(N_BINS)
    if match:
        hh, mm = map(int, match["kickoff"].split(":"))
        ko = hh + mm / 60
        bump[(BIN_HOURS > ko - 2.5) & (BIN_HOURS < ko)] = 1.35
        bump[(BIN_HOURS > ko + 1.75) & (BIN_HOURS < ko + 3)] = 1.35
    out = np.empty((N_BINS, 2 * NC))
    for i, c in enumerate(CORRIDORS):
        weekend = WEEKEND[c.kind][wd - 5] if wd >= 5 else 1.0
        shape = profile * (bump if c.id in MATCH_ROADS else 1.0)
        for k in range(2):
            noise = rng.lognormal(0.0, 0.04, N_BINS)
            out[:, 2 * i + k] = c.lanes * c.lane_cap * c.bg * weekend * shape * day_noise * noise
    return out


# --- cruise vehicles -----------------------------------------------------------------------------

def minutes(t: datetime) -> float:
    return t.hour * 60 + t.minute


def _add(D, t, org_idx, origins, gate, direction, pcu):
    b = np.floor((np.asarray(t) - DAY_START_MIN) / BIN_MIN).astype(int)
    ok = (b >= 0) & (b < N_BINS)
    for i, org in enumerate(origins):
        m = ok & (org_idx == i)
        if m.any():
            np.add.at(D[:, OD_INDEX[(org, gate, direction)]], b[m], pcu)


def sample_demand(calls: list[Call], rng: np.random.Generator, p: TurnaroundParams) -> np.ndarray:
    """PCU per bin for each (origin, gate, direction) on one sampled day."""
    D = np.zeros((N_BINS, len(ODS)))

    def pick(n, choice):
        names, mean = choice
        return names, rng.choice(len(names), size=n, p=rng.dirichlet(mean * 40))

    for call in calls:
        gate = TERMINAL_GATE[call.terminal]
        berths = call.pax if call.pax else rng.uniform(*UNKNOWN_PAX_RANGE)
        arr, dep = minutes(call.arrival), minutes(call.departure)
        start = arr + rng.normal(0.0, p.arrival_delay_sd_min) + p.disembark_start_min
        lo = dep - p.embark_open_before_dep_min
        hi = dep - p.embark_close_before_dep_min
        for leg in ("dis", "emb"):
            people = int(round(berths * rng.beta(*p.load_factor_beta)))
            n_car, n_park, n_taxi, n_coach, _ = rng.multinomial(
                people, rng.dirichlet(MODE_MEAN * MODE_CONC)
            )
            cars = int(round(n_car / PEOPLE_PER["car"]))
            parks = int(round(n_park / PEOPLE_PER["park"]))
            taxis = int(round(n_taxi / PEOPLE_PER["taxi"]))
            coaches = math.ceil(n_coach / PEOPLE_PER["coach"])
            if leg == "dis":  # passengers come off the ship and leave the port

                def when(n):
                    return start + p.disembark_duration_min * rng.beta(2.0, 3.0, n)

                t = when(cars)
                names, o = pick(cars, CAR_FROM)
                _add(D, t - 20, o, names, gate, "in", 1.0)  # pick-up drives in empty
                _add(D, t + 5, o, names, gate, "out", 1.0)
                names, o = pick(parks, CAR_FROM)
                _add(D, when(parks) + 10, o, names, gate, "out", 1.0)
                t = when(taxis)
                names, o = pick(taxis, TAXI_RANK)
                _add(D, t - 15, o, names, gate, "in", 1.0)
                names, o = pick(taxis, TAXI_FAR)
                _add(D, t, o, names, gate, "out", 1.0)
                names, o = pick(coaches, COACH_FROM)
                _add(D, start - 30 + 120 * rng.random(coaches), o, names, gate, "in", COACH_PCU)
                _add(D, when(coaches) + 20, o, names, gate, "out", COACH_PCU)
            else:  # the next sailing's passengers arrive and board

                def when(n):
                    return lo + (hi - lo) * rng.beta(2.0, 2.0, n)

                t = when(cars)
                names, o = pick(cars, CAR_FROM)
                _add(D, t, o, names, gate, "in", 1.0)
                _add(D, t + 15, o, names, gate, "out", 1.0)  # drop-off leaves empty
                names, o = pick(parks, CAR_FROM)
                _add(D, when(parks) - 10, o, names, gate, "in", 1.0)
                t = when(taxis)
                names, o = pick(taxis, TAXI_FAR)
                _add(D, t, o, names, gate, "in", 1.0)
                names, o = pick(taxis, TAXI_RANK)
                _add(D, t + 10, o, names, gate, "out", 1.0)
                t = when(coaches)
                names, o = pick(coaches, COACH_FROM)
                _add(D, t, o, names, gate, "in", COACH_PCU)
                _add(D, t + 20, o, names, gate, "out", COACH_PCU)
    return D


# --- route choice (PathFinder negotiation over candidate paths) ---------------------------------

def assign(dem: np.ndarray, bg: list[float], cap: list[float], t0: list[float]) -> list[float]:
    """Load (vehicles/hour) per directed edge after cruise packets negotiate their routes."""
    load = list(bg)
    packets = []
    for j in np.flatnonzero(dem > 1e-9):
        k = max(1, math.ceil(dem[j] / PACKET_PCU))
        packets += [(int(j), float(dem[j]) * 4.0 / k)] * k  # PCU per bin -> per hour
    choice = [-1] * len(packets)
    hist = [0.0] * len(load)
    pres = 0.5
    for _ in range(8):
        for i, (j, size) in enumerate(packets):
            paths = CANDIDATES[j]
            if choice[i] >= 0:
                for e in paths[choice[i]]:
                    load[e] -= size
            best, best_cost = 0, math.inf
            for pi, path in enumerate(paths):
                cost = 0.0
                for e in path:
                    vc = (load[e] + size) / cap[e]
                    over = vc - 1.0 if vc > 1.0 else 0.0
                    cost += (t0[e] * (1.0 + 0.15 * vc**4) + hist[e]) * (1.0 + pres * over)
                if cost < best_cost:
                    best, best_cost = pi, cost
            choice[i] = best
            for e in paths[best]:
                load[e] += size
        over = [e for e in range(len(load)) if load[e] > cap[e]]
        if not over:
            break
        for e in over:
            hist[e] += 0.2 * t0[e] * (load[e] - cap[e]) / cap[e]
        pres *= 1.5
    return load


# --- forecast ------------------------------------------------------------------------------------

def corridor_max(vc: np.ndarray) -> np.ndarray:
    return np.maximum(vc[:, 0::2], vc[:, 1::2])


def forecast_day(d: date, calls: list[Call], n: int, closed: set[str]) -> dict:
    rng = np.random.default_rng([SEED, d.toordinal()])  # same draws for every what-if on this day
    params = TurnaroundParams()
    cap = capacity(closed)
    cap_l, t0_l = cap.tolist(), T0.tolist()
    p85 = np.zeros((N_BINS, NC))
    p100 = np.zeros((N_BINS, NC))
    vc_sum = np.zeros((N_BINS, NC))
    bg85 = np.zeros((N_BINS, NC))
    gates = np.zeros((n, N_BINS, len(GATES)))
    for s in range(n):
        bg = background(d, rng)
        vc = bg / cap
        bg85 += corridor_max(vc) > AT_RISK
        if calls:
            D = sample_demand(calls, rng, params)
            for b in np.flatnonzero(D.sum(axis=1) > 0):
                vc[b] = np.asarray(assign(D[b], bg[b].tolist(), cap_l, t0_l)) / cap
            gates[s] = D @ GATE_MATRIX * 4.0
        c = corridor_max(vc)
        p85 += c > AT_RISK
        p100 += c > 1.0
        vc_sum += c
    return {
        "p85": p85 / n,
        "p100": p100 / n,
        "vc": vc_sum / n,
        "bg85": bg85 / n,
        "gates": gates,
    }


def score(p85: np.ndarray) -> float:
    """Expected corridor-hours above 85% of capacity."""
    return float(p85.sum() * BIN_MIN / 60)


def pct(a: np.ndarray) -> list:
    return np.rint(np.asarray(a) * 100).astype(int).tolist()


def by_corridor(arr: np.ndarray) -> dict:
    return {c.id: pct(arr[:, i]) for i, c in enumerate(CORRIDORS)}


# --- synthetic schedule --------------------------------------------------------------------------

def make_schedule(rng: np.random.Generator) -> dict[date, list[Call]]:
    sched: dict[date, list[Call]] = {}
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
            n -= 1  # the season tails off
        terminals = rng.choice(TERMINALS, size=n, replace=False)
        ships = rng.choice(len(SHIPS), size=n, replace=False)
        calls = []
        for term, s in zip(terminals, ships, strict=True):
            arr = datetime.combine(d, time(5, 30)) + timedelta(minutes=15 * int(rng.integers(0, 7)))
            dep = datetime.combine(d, time(16, 0)) + timedelta(minutes=30 * int(rng.integers(0, 6)))
            calls.append(Call(SHIPS[s][0], str(term), arr, dep, SHIPS[s][1]))
        sched[d] = sorted(calls, key=lambda c: (c.arrival, c.ship))
        d += timedelta(days=1)
    # One call with no published passenger figure, to show the fallback and its wider range.
    d = date(2026, 11, 4)
    used = {c.terminal for c in sched[d]}
    term = next(t for t in TERMINALS if t not in used)
    sched[d].append(
        Call("Unlisted Voyager", term, datetime.combine(d, time(6, 0)),
             datetime.combine(d, time(17, 0)), None)
    )
    return sched


def permits_on(d: date) -> list[dict]:
    iso = d.isoformat()
    return [p for p in PERMITS if p["from"] <= iso <= p["to"]]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=100, help="sampled days per date")
    parser.add_argument("--whatif-days", type=int, default=6, help="busiest days given what-ifs")
    parser.add_argument("--template", type=Path, default=Path(__file__).with_name("page.html"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("out") / "demo.html")
    parser.add_argument("--json", type=Path, help="also write the raw data here")
    args = parser.parse_args(argv)

    started = clock.perf_counter()
    sched = make_schedule(np.random.default_rng(SEED))
    days, results = [], {}
    d = FIRST_DAY
    while d <= CAL_END:
        if d > HORIZON:
            days.append({"date": d.isoformat(), "beyond": True})
            d += timedelta(days=1)
            continue
        calls = sched[d]
        closed = {p["corridor"] for p in permits_on(d)}
        r = forecast_day(d, calls, args.n, closed)
        results[d] = r
        g = r["gates"]
        day = {
            "date": d.isoformat(),
            "calls": [
                {
                    "ship": c.ship,
                    "terminal": c.terminal,
                    "gate": TERMINAL_GATE[c.terminal],
                    "arr": c.arrival.strftime("%H:%M"),
                    "dep": c.departure.strftime("%H:%M"),
                    "pax": c.pax,
                }
                for c in calls
            ],
            "score": round(score(r["p85"]), 2),
            "bg_score": round(score(r["bg85"]), 2),
            "permits": [p["id"] for p in permits_on(d)],
            "match": next((m["kickoff"] for m in MATCHES if m["date"] == d.isoformat()), None),
            "p85": by_corridor(r["p85"]),
            "p100": by_corridor(r["p100"]),
            "vc": by_corridor(r["vc"]),
            "bg85": by_corridor(r["bg85"]),
            "gates": {
                gate: {
                    "mean": np.rint(g[:, :, k].mean(axis=0)).astype(int).tolist(),
                    "p10": np.rint(np.percentile(g[:, :, k], 10, axis=0)).astype(int).tolist(),
                    "p90": np.rint(np.percentile(g[:, :, k], 90, axis=0)).astype(int).tolist(),
                }
                for k, gate in enumerate(GATES)
            }
            if calls
            else {},
            "whatif": {},
        }
        days.append(day)
        print(f"{d} {d.strftime('%a')} calls={len(calls)} score={day['score']:.2f} "
              f"bg={day['bg_score']:.2f} ({clock.perf_counter() - started:.0f}s)", flush=True)
        d += timedelta(days=1)

    # What-ifs for the busiest days and every day a roadworks permit overlaps a turnaround.
    by_date = {x["date"]: x for x in days if not x.get("beyond")}
    busiest = sorted((x for x in by_date.values() if x["calls"]), key=lambda x: -x["score"])
    chosen = {x["date"] for x in busiest[: args.whatif_days]}
    chosen |= {x["date"] for x in by_date.values() if x["calls"] and x["permits"]}
    for iso in sorted(chosen):
        d = date.fromisoformat(iso)
        day = by_date[iso]
        permit_roads = {p["corridor"] for p in permits_on(d)}
        variants = {}
        if permit_roads:
            variants["move_permit"] = set()
        for road in WHATIF_ROADS:
            if road not in permit_roads:
                variants[f"close_{road}"] = permit_roads | {road}
        for key, closed in variants.items():
            r = forecast_day(d, sched[d], args.n, closed)
            day["whatif"][key] = {"score": round(score(r["p85"]), 2), "p85": by_corridor(r["p85"])}
            print(f"  what-if {iso} {key}: {day['score']:.2f} -> {score(r['p85']):.2f}", flush=True)

    data = {
        "meta": {
            "synthetic": True,
            "issued": ISSUED.strftime("%Y-%m-%dT%H:%M"),
            "first_day": FIRST_DAY.isoformat(),
            "horizon": HORIZON.isoformat(),
            "n": args.n,
            "seed": SEED,
            "bin_minutes": BIN_MIN,
            "day_start": "05:00",
            "at_risk": AT_RISK,
            "unknown_pax_range": UNKNOWN_PAX_RANGE,
            "model": "v0.1-demo",
            "assumptions": {
                "mode_share": dict(zip(["car", "park", "taxi", "coach", "other"],
                                       MODE_MEAN.tolist(), strict=True)),
                "people_per_vehicle": PEOPLE_PER,
                "coach_pcu": COACH_PCU,
                "packet_pcu": PACKET_PCU,
            },
        },
        "nodes": [
            {"id": k, "name": v[0], "x": v[1], "y": v[2], "kind": v[3]} for k, v in NODES.items()
        ],
        "corridors": [
            {
                "id": c.id,
                "name": c.name,
                "a": c.a,
                "b": c.b,
                "lanes": c.lanes,
                "cap": int(c.lanes * c.lane_cap),
                "kind": c.kind,
                "sensor": SENSOR.get(c.id),
            }
            for c in CORRIDORS
        ],
        "gates": [{"id": g, "name": GATE_NAMES[g]} for g in GATES],
        "terminal_gate": TERMINAL_GATE,
        "permits": PERMITS,
        "matches": MATCHES,
        "days": days,
    }
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload, encoding="utf-8")
    page = args.template.read_text(encoding="utf-8").replace("__DEMO_DATA__", payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"Wrote {args.out} ({len(page) / 1e6:.2f} MB) in {clock.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
