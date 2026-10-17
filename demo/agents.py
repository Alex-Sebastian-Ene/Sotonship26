"""Individual vehicles for chosen days: the model's 15-minute flows as agents on their routes.

For each chosen day this draws one sampled day exactly as the forecast draws its samples
(daysim.sample_day), allocates it with traffic_model.run_day, and then samples agents from what
was allocated:

* everyday traffic (each kind of trip in PURPOSES, and match fans) is sampled at a fixed rate from
  the day's origin-destination flows per 15 minutes (``--everyday`` agents in all); each agent
  leaves at a random minute of its bin;
* cruise vehicles are the sampler's own vehicles (car drop-offs and pick-ups, park and cruise,
  taxis, coaches) with their own minutes, kept at rate ``--cruise-rate``;
* each agent takes one of its pair's candidate routes with the shares the model gave that pair in
  that bin, and drives it through the day's link loads and queues (daysim.traverse);
* each driver keeps their own speed, SPEED (a share of the free-flow speed, so below the limit),
  with the link's congestion on top; agents going from or to a zone start or end on a random
  modelled road within STREET_M of the zone's point, reached by the quickest short leg to or from
  the zone's node (the model loads each zone at that one node);
* buses (demo/buses.py) run on the same link loads.

An agent stands for 1 / rate vehicles like it, so the agents added up give the model's flows
back (the page shows that check). Everything here is one sampled day: the page's other views are
the average of many.

    uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas \
        --with shapely --with pyproj python demo/agents.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time as clock
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import buses  # noqa: E402
import daysim  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

OUT = HERE / "out" / "agents.json"
PAGE = HERE / "out" / "demo.html"
AGENT_SEED = 7
CHUNK_S = 45.0  # a position is stored about every 45 s of free-flow driving
# Each driver's speed as a share of the free-flow speed (speed limit): mean, sd, lowest, highest.
# Assumed. Cars still do not interact: a slow driver does not hold up the one behind.
SPEED = (0.92, 0.06, 0.75, 1.0)
STREET_M = 900.0  # zone trips start or end on a random modelled road this close to the zone
LEG_LIMIT_S = 400.0  # longest access or egress leg, free-flow seconds
SIMPLIFY_M = 4.0
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# purpose key -> (page group, label)
PURPOSES = {
    "county_in": ("county", "County commuter, to work"),
    "county_home": ("county", "County commuter, going home"),
    "out": ("outbound", "Resident working outside the area, to work"),
    "out_home": ("outbound", "Resident working outside the area, going home"),
    "internal": ("internal", "Resident, trip within the area"),
    "through": ("through", "Through traffic"),
    "other_in": ("visitors", "Other trip from the county (business, freight, leisure)"),
    "other_home": ("visitors", "Other trip back to the county (business, freight, leisure)"),
    "visit_in": ("visitors", "County visitor to the shops"),
    "visit_home": ("visitors", "County visitor going home"),
    "school_drop": ("school", "School run, dropping off"),
    "school_drop_home": ("school", "School run, driving back"),
    "school_pick": ("school", "School run, picking up"),
    "school_pick_home": ("school", "School run, driving home"),
    "freight_in": ("freight", "Port freight lorry, to the port"),
    "freight_out": ("freight", "Port freight lorry, from the port"),
    "match": ("match", "Match fan"),
    "cruise_car": ("cruise", "Cruise drop-off or pick-up car"),
    "cruise_park": ("cruise", "Park and cruise"),
    "cruise_taxi": ("cruise", "Cruise taxi"),
    "cruise_coach": ("cruise", "Cruise coach"),
}
CRUISE_KEYS = ["cruise_car", "cruise_park", "cruise_taxi", "cruise_coach"]  # daysim.KINDS order


def enc(values) -> str:
    """Integers as a compact string: zigzag, 5 bits per character, URL-safe base64 alphabet."""
    out = []
    for v in values:
        v = int(v)
        z = v * 2 if v >= 0 else -v * 2 - 1
        while z >= 32:
            out.append(ALPHA[32 | (z & 31)])
            z >>= 5
        out.append(ALPHA[z])
    return "".join(out)


def dec(s: str) -> list[int]:
    """Inverse of enc (the page has the same decoder)."""
    out, z, sh = [], 0, 0
    for ch in s:
        c = ALPHA.index(ch)
        z += (c & 31) << sh
        if c & 32:
            sh += 5
        else:
            out.append(z // 2 if z % 2 == 0 else -(z + 1) // 2)
            z, sh = 0, 0
    return out


def simplify(points, tol: float) -> list[tuple[int, int]]:
    from shapely.geometry import LineString

    pts = [tuple(map(float, p)) for p in points]
    if len(pts) > 2:
        pts = list(LineString(pts).simplify(tol, preserve_topology=False).coords)
    out = [(round(x), round(y)) for x, y in pts]
    return out if len(out) >= 2 else out + out[-1:]


def geometry(m: tm.Model, edges, bounds) -> tuple[list, list]:
    """Polyline of an edge list with a vertex at every boundary position (start of an edge)."""
    distinct = sorted(set(bounds))
    pts, vert = [], {}
    for a, b in zip(distinct[:-1], distinct[1:], strict=True):
        chunk = [p for e in edges[a:b] for p in m.coords[e]]
        chunk = simplify(chunk, SIMPLIFY_M) if chunk else [pts[-1], pts[-1]]
        if not pts:
            pts.append(chunk[0])
            vert[a] = 0
        pts += chunk[1:]
        vert[b] = len(pts) - 1
    if len(distinct) == 1:  # an empty path (both ends on one node)
        p = m.xy[m.eu[edges[0]]] if edges else (0, 0)
        pts, vert = [(round(p[0]), round(p[1]))] * 2, {distinct[0]: 0}
    return pts, [vert[p] for p in bounds]


def regular_bounds(m: tm.Model, edges, every_s: float) -> set[int]:
    n, out, acc = len(edges), {0, len(edges)}, 0.0
    for i, e in enumerate(edges):
        acc += m.t0[e]
        if acc >= every_s and i + 1 < n:
            out.add(i + 1)
            acc = 0.0
    return out


def with_holds(reg: set[int], holds: set[int]) -> list[int]:
    out = []
    for p in sorted(reg | holds):
        out += [p, p] if p in holds else [p]
    return out


def times_at(bounds, enter, holds: dict) -> list[float]:
    """An agent's minute at each boundary; at a queue it reached the first copy on arrival and
    left at the second."""
    out, prev = [], None
    for p in bounds:
        out.append(holds[p] if p in holds and prev != p else enter[p])
        prev = p
    return out


def enc_times(ts) -> str:
    s = np.rint((np.asarray(ts) - daysim.DAY_START_MIN) * 60).astype(int)
    return enc(np.concatenate([s[:1], np.maximum(np.diff(s), 0)]))


def via(m: tm.Model, edges, names_index) -> list[int]:
    out = []
    for e in edges:
        nm = m.ref[e] or m.name[e]
        if nm and nm not in out and m.length[e] > 150:
            out.append(nm)
    return [names_index(n) for n in out[:4]]


class Names:
    def __init__(self):
        self.list, self.pos = [], {}

    def __call__(self, name) -> int:
        key = json.dumps(name)
        if key not in self.pos:
            self.pos[key] = len(self.list)
            self.list.append(name)
        return self.pos[key]


class Streets:
    """Random start and end points within each zone and the short legs to and from its node."""

    def __init__(self, m: tm.Model):
        from scipy import sparse
        from scipy.sparse.csgraph import dijkstra
        from scipy.spatial import cKDTree

        n = len(m.xy)
        self.edge_of = {}
        for k, (u, v) in enumerate(zip(m.eu, m.ev, strict=True)):
            key = (int(u), int(v))
            if key not in self.edge_of or m.t0[k] < m.t0[self.edge_of[key]]:
                self.edge_of[key] = k
        csr = sparse.csr_matrix((m.t0, (m.eu, m.ev)), shape=(n, n))
        local = np.zeros(n, bool)
        for k, c in enumerate(m.cls):
            if c in tm.LOCAL:
                local[m.eu[k]] = local[m.ev[k]] = True
        ids = np.flatnonzero(local)
        tree = cKDTree(m.xy[ids])
        zones = [i for i, c in enumerate(m.centroids) if c.kind == "zone"]
        src = sorted({m.centroids[z].node for z in zones})
        _, fwd = dijkstra(csr, indices=src, return_predecessors=True, limit=LEG_LIMIT_S)
        _, bwd = dijkstra(csr.T.tocsr(), indices=src, return_predecessors=True, limit=LEG_LIMIT_S)
        row = {s_: r for r, s_ in enumerate(src)}
        self.options = {}  # zone centroid -> [(node, access edges, egress edges)]
        for z in zones:
            c = m.centroids[z]
            r = row[c.node]
            opts = []
            for i in tree.query_ball_point(c.xy, STREET_M):
                v = int(ids[i])
                if v == c.node:
                    continue
                access = self._trace(bwd[r], c.node, v, forward=False)
                egress = self._trace(fwd[r], c.node, v, forward=True)
                if access and egress:
                    opts.append((v, access, egress))
            self.options[z] = opts

    def _trace(self, pred, s_, v, forward):
        """Edges from v to the zone node s_ (access, on the reversed tree) or from s_ to v."""
        out, cur = [], v
        for _ in range(500):
            if cur == s_:
                return out[::-1] if forward else out
            p = pred[cur]
            if p < 0:
                return None
            out.append(self.edge_of[(int(p), int(cur))] if forward
                       else self.edge_of[(int(cur), int(p))])
            cur = p
        return None

    def pick(self, m: tm.Model, centroid: int, rng):
        opts = self.options.get(centroid) if m.centroids[centroid].kind == "zone" else None
        return opts[int(rng.integers(len(opts)))] if opts else None


# --- one day ----------------------------------------------------------------------------------

def simulate_day(ctx: sd.Ctx, task: dict, n_everyday: int, cruise_rate: float, seed: int,
                 net, bus_data, streets: Streets, log=print) -> dict:
    m = ctx.m
    d = date.fromisoformat(task["date"])
    rng = np.random.default_rng([seed, d.toordinal()])
    day = daysim.sample_day(ctx, task, rng)
    t_c = daysim.cruise_times(day.veh, day.params)
    Dc = daysim.vehicles_matrix(m.n_od, day.veh, t_c)
    D = day.Dbg + day.Dm + Dc
    calls = task["calls"]
    res, _ = tm.run_day(m, D, day.cap, day.shares0, 3, cruise=Dc if calls else None,
                        want=("x", "path", "held"), pre=day.pre, noise=day.noise,
                        events=day.events)
    X, S = res["x"], res["path"]
    arng = np.random.default_rng([seed, d.toordinal(), 1])

    # everyday agents: Poisson per bin from each purpose's flows
    totals = {k: float(bins.sum() * odw.sum()) for k, (bins, odw) in day.parts.items()}
    total = sum(totals.values()) + float(day.Dm.sum())
    rate = n_everyday / max(total, 1.0)
    picks = []  # (purpose, bin or None, od, minute or None, pcu, call)
    for key, (bins, odw) in day.parts.items():
        p = odw / odw.sum()
        counts = arng.poisson(rate * bins * odw.sum())
        for b in np.flatnonzero(counts):
            for j in arng.choice(len(p), size=int(counts[b]), p=p):
                picks.append((key, int(b), int(j), None, 1.0, -1))
    for b in np.flatnonzero(day.Dm.sum(axis=1) > 0):
        row = day.Dm[b]
        for j in arng.choice(len(row), size=int(arng.poisson(rate * row.sum())), p=row / row.sum()):
            picks.append(("match", int(b), int(j), None, 1.0, -1))
    # cruise agents: the sampler's own vehicles
    v = day.veh
    vb = daysim.bin_index(t_c)
    ok = (vb >= 0) & (vb < daysim.N_BINS) & (v["j"] >= 0)
    for i in np.flatnonzero(ok & (arng.random(len(t_c)) < cruise_rate)):
        picks.append((CRUISE_KEYS[v["kind"][i]], int(vb[i]), int(v["j"][i]), float(t_c[i]),
                      float(v["pcu"][i]), int(v["call"][i])))
    log(f"{task['date']}: {len(picks)} agents ({rate:.5f} of everyday trips, {cruise_rate:g} of "
        f"cruise vehicles); {int(ok.sum())} cruise vehicles, {total:.0f} everyday vehicles")

    agents = []
    for key, b, j, minute, pcu, call in picks:
        dep = minute if minute is not None else daysim.DAY_START_MIN + daysim.BIN_MIN * (b + arng.random())
        sh = np.nan_to_num(S[b, j], nan=0.0)
        sh = sh / sh.sum() if sh.sum() > 0 else np.array([1.0, 0.0, 0.0])
        r = int(arng.choice(tm.ROUTES, p=sh))
        pid = j * tm.ROUTES + r
        o, dd = m.ods[j]
        speed = float(np.clip(arng.normal(SPEED[0], SPEED[1]), SPEED[2], SPEED[3]))
        leg_a, leg_e = streets.pick(m, o, arng), streets.pick(m, dd, arng)
        t = dep
        enter_a = enter_e = None
        if leg_a:
            enter_a, _, _ = daysim.traverse(m, leg_a[1], t, X, arng, speed=speed, hold=False)
            t = enter_a[-1]
        enter, hold, _ = daysim.traverse(m, m.paths[pid], t, X, arng, speed=speed)
        if leg_e:
            enter_e, _, _ = daysim.traverse(m, leg_e[2], enter[-1], X, arng, speed=speed,
                                            hold=False)
        agents.append({"key": key, "od": j, "pid": pid, "enter": enter, "hold": hold,
                       "pcu": pcu, "call": call, "dep": dep, "bin": b, "speed": speed,
                       "leg_a": (("a", o, leg_a[0]), leg_a[1], enter_a) if leg_a else None,
                       "leg_e": (("e", dd, leg_e[0]), leg_e[2], enter_e) if leg_e else None,
                       "w": 1.0 / (cruise_rate if key in CRUISE_KEYS else rate)})

    # check: agents added up against the model's flows, by group and hour
    model, sampled = defaultdict(lambda: np.zeros(daysim.N_BINS)), defaultdict(lambda: np.zeros(daysim.N_BINS))
    for k, (bins, odw) in day.parts.items():
        model[PURPOSES[k][0]] += bins * odw.sum()
    model["match"] += day.Dm.sum(axis=1)
    model["cruise"] += Dc.sum(axis=1)
    for a in agents:
        sampled[PURPOSES[a["key"]][0]][a["bin"]] += a["w"] * a["pcu"]
    check = {g: {"model": np.rint(model[g] * 4).astype(int).tolist(),
                 "agents": np.rint(sampled[g] * 4).astype(int).tolist()}
             for g in model if model[g].sum() > 0}
    seg_x = np.maximum.reduceat(X[:, ctx.seg_idx], ctx.seg_ptr, axis=1)
    out = {"date": task["date"], "seed": [seed, d.toordinal()], "wet": day.wet,
           "incident": bool(day.events), "rates": {"everyday": rate, "cruise": cruise_rate},
           "vehicles": {"everyday": round(total), "cruise": int(ok.sum())},
           "agents": agents, "check": check,
           "seg": sd.code(np.rint(sd.half_hour(seg_x) / 0.05).T.ravel()),
           "calls": [{"ship": c.ship, "terminal": c.terminal} for c in calls],
           "held": round(float(np.sum(res["held"]))), "X": X}
    if net is not None and bus_data is not None:
        out["buses"] = buses.simulate(ctx, net, bus_data, d, X, np.random.default_rng([seed, d.toordinal(), 2]), log)
    return out


# --- page data ---------------------------------------------------------------------------------

def page_json(ctx: sd.Ctx, days: list[dict], bus_data, log=print) -> dict:
    """Shared path tables (one boundary set per path, so the queues of every day fit) and per-day
    agent and bus columns."""
    m = ctx.m
    names = Names()  # road and stop names; origins and destinations index "centroids"
    holds = defaultdict(set)
    for day in days:
        for a in day["agents"]:
            if a["hold"]:
                holds[a["pid"]].add(a["hold"][0])
    path_ix, paths = {}, []

    def path_entry(pid):
        if pid not in path_ix:
            edges = m.paths[pid]
            bounds = with_holds(regular_bounds(m, edges, CHUNK_S), holds[pid])
            pts, bv = geometry(m, edges, bounds)
            flat = [pts[0][0], pts[0][1]] + [c for a, b in zip(pts[:-1], pts[1:], strict=True)
                                             for c in (b[0] - a[0], b[1] - a[1])]
            path_ix[pid] = len(paths)
            paths.append({"g": enc(flat), "b": enc([bv[0]] + np.diff(bv).tolist()),
                          "v": via(m, edges, names), "ff": round(float(m.t0[edges].sum()) / 6),
                          "bounds": bounds})
        return path_ix[pid]

    leg_ix, legs = {}, []

    def leg_entry(key, edges):
        if key not in leg_ix:
            bounds = sorted(regular_bounds(m, edges, CHUNK_S))
            pts, bv = geometry(m, edges, bounds)
            flat = [pts[0][0], pts[0][1]] + [c for a, b in zip(pts[:-1], pts[1:], strict=True)
                                             for c in (b[0] - a[0], b[1] - a[1])]
            leg_ix[key] = len(legs)
            legs.append({"g": enc(flat), "b": enc([bv[0]] + np.diff(bv).tolist()),
                         "ff": round(float(m.t0[edges].sum()) / 6), "bounds": bounds})
        return leg_ix[key]

    keys = list(PURPOSES)
    out_days = {}
    for day in days:
        cols = {k: [] for k in ("k", "o", "d", "p", "q", "c", "a", "e", "s")}
        tt = []
        for a in sorted(day["agents"], key=lambda a: a["dep"]):
            pi = path_entry(a["pid"])
            o, dd = m.ods[a["od"]]
            hd = {a["hold"][0]: a["hold"][1]} if a["hold"] else {}
            ts, ia, ie = [], -1, -1
            if a["leg_a"]:  # from a street in the zone to the zone's node
                ia = leg_entry(a["leg_a"][0], a["leg_a"][1])
                ts += times_at(legs[ia]["bounds"], a["leg_a"][2], {})
            ts += times_at(paths[pi]["bounds"], a["enter"], hd)
            if a["leg_e"]:  # from the zone's node to a street in the zone
                ie = leg_entry(a["leg_e"][0], a["leg_e"][1])
                ts += times_at(legs[ie]["bounds"], a["leg_e"][2], {})
            tt.append(enc_times(ts))
            q = (a["hold"][2] - a["hold"][1]) if a["hold"] else 0.0
            for k, val in (("k", keys.index(a["key"])), ("o", o), ("d", dd), ("p", pi),
                           ("q", round(q * 10)), ("c", a["call"]), ("a", ia), ("e", ie),
                           ("s", round(a["speed"] * 100))):
                cols[k].append(val)
        entry = {k: day[k] for k in ("date", "seed", "wet", "incident", "rates", "vehicles",
                                     "check", "seg", "calls", "held")}
        entry["agents"] = {**cols, "t": "".join(tt), "n": len(cols["k"])}
        entry["weights"] = {"everyday": round(1 / day["rates"]["everyday"], 1),
                            "cruise": round(1 / day["rates"]["cruise"], 1)}
        out_days[day["date"]] = entry
    for p in paths + legs:
        del p["bounds"]

    bus = None
    if any("buses" in d for d in days):
        bus = bus_json(ctx, days, bus_data, names)
        for dd, b in bus.pop("days").items():
            out_days[dd]["buses"] = b
    purposes = [{"key": k, "group": g, "label": lab, "cruise": k in CRUISE_KEYS}
                for k, (g, lab) in PURPOSES.items()]
    return {"centroids": [[c.name, c.kind, c.hint] for c in m.centroids], "names": names.list,
            "purposes": purposes, "paths": paths, "legs": legs, "days": out_days,
            "bus": bus, "method": {"chunk_s": CHUNK_S, "carry": tm.CARRY, "speed": SPEED,
                                   "street_m": STREET_M,
                                   "max_hold_min": daysim.MAX_HOLD_BINS * daysim.BIN_MIN,
                                   "bus_speed": buses.BUS_SPEED, "dwell_s": buses.DWELL_MIN * 60}}


def bus_json(ctx, days, bus_data, names) -> dict:
    m = ctx.m
    pat_ix, pats, holds = {}, [], defaultdict(set)
    for day in days:
        b = day.get("buses")
        if not b:
            continue
        for tr in b["trips"]:
            p = b["patterns"][tr["pattern"]]
            key = (p["route"], tuple(p["stops"]))
            for pos, _, _ in tr["holds"]:
                holds[key].add(pos)
    routes = sorted({p["route"] for d in days if d.get("buses") for p in d["buses"]["patterns"]})
    route_ix = {r: i for i, r in enumerate(routes)}
    out_days = {}
    for day in days:
        b = day.get("buses")
        if not b:
            continue
        local = []
        for p in b["patterns"]:
            key = (p["route"], tuple(p["stops"]))
            if key not in pat_ix:
                bounds = with_holds(set(p["pos"]), holds[key])
                pts, bv = geometry(m, p["edges"], bounds)
                flat = [pts[0][0], pts[0][1]] + [c for a, q in zip(pts[:-1], pts[1:], strict=True)
                                                 for c in (q[0] - a[0], q[1] - a[1])]
                stop_names = [names(bus_data["stops"][s][0]) for s in p["stops"]]
                pat_ix[key] = len(pats)
                pats.append({"g": enc(flat), "b": enc([bv[0]] + np.diff(bv).tolist()),
                             "r": route_ix[p["route"]], "s": stop_names,
                             "v": via(m, p["edges"], names), "bounds": bounds})
            local.append(pat_ix[key])
        cols = {k: [] for k in ("p", "r", "dep", "late", "x", "px", "pl")}
        tt = []
        for tr in sorted(b["trips"], key=lambda t: t["dep"]):
            gi = local[tr["pattern"]]
            hd = {pos: arr for pos, arr, _ in tr["holds"]}
            tt.append(enc_times(times_at(pats[gi]["bounds"], tr["enter"], hd)))
            for k, val in (("p", gi), ("r", route_ix[tr["route"]]), ("dep", round(tr["dep"] * 10)),
                           ("late", round(tr["late_end"] * 10)), ("x", round(tr["extra"] * 10)),
                           ("px", round(tr["ps_extra"] * 10) if "ps_extra" in tr else None),
                           ("pl", round(tr["ps_late"] * 10) if "ps_late" in tr else None)):
                cols[k].append(val)
        out_days[day["date"]] = {"trips": {**cols, "t": "".join(tt), "n": len(cols["p"])},
                                 "table": b["table"]}
    for p in pats:
        del p["bounds"]
    info = bus_data["routes"]
    return {"source": bus_data["source"], "timetable": bus_data.get("timetable"),
            "routes": [{"id": r, "operator": info.get(r, {}).get("agency", ""),
                        "name": info.get(r, {}).get("short", ""),
                        "long": info.get(r, {}).get("long", "")} for r in routes],
            "patterns": pats, "days": out_days, "council": buses.COUNCIL_BUS,
            "council_range_min": buses.COUNCIL_RANGE_MIN,
            "assumptions": {"bus_speed": buses.BUS_SPEED, "dwell_s": round(buses.DWELL_MIN * 60)}}


# --- choosing the days ---------------------------------------------------------------------------

def pick_days(page: dict | None, tasks: dict, n_busiest: int) -> list[str]:
    """The days with the most cruise traffic added (from the built page), plus the busiest
    weekday with ships and no roadworks on Portswood Road if none of those is one (the
    council's bus figures are weekday peaks without works)."""
    def uplift(dd):
        r = dd.get("range")
        return r["uplift"][1] if r else dd.get("score", 0) - dd.get("bg_score", 0)

    if page:
        cand = [dd for dd in page["days"] if not dd.get("beyond") and dd.get("calls")]
        ranked = [dd["date"] for dd in sorted(cand, key=lambda dd: -uplift(dd))]
    else:  # no page yet: most passengers
        ranked = sorted((k for k, t in tasks.items() if t["calls"]),
                        key=lambda k: -sum(c.pax or 3000 for c in tasks[k]["calls"]))
    chosen = ranked[:n_busiest]

    def bus_check_day(x):  # a weekday without roadworks on Portswood Road
        return date.fromisoformat(x).weekday() < 5 and "portswood" not in tasks[x]["closed"]

    if not any(bus_check_day(x) for x in chosen):
        wk = next((x for x in ranked if bus_check_day(x)), None)
        if wk:
            chosen.append(wk)
    return chosen


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", help="comma-separated dates (default: the busiest, from the page)")
    ap.add_argument("--n-busiest", type=int, default=2)
    ap.add_argument("--everyday", type=int, default=6000, help="everyday agents per day")
    ap.add_argument("--cruise-rate", type=float, default=0.25, help="share of cruise vehicles kept")
    ap.add_argument("--seed", type=int, default=AGENT_SEED)
    ap.add_argument("--page", type=Path, default=PAGE)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-buses", action="store_true")
    args = ap.parse_args(argv)
    started = clock.perf_counter()

    def log(msg):
        print(f"[{clock.perf_counter() - started:6.0f}s] {msg}", flush=True)

    ctx = daysim.load_ctx(log=log)
    page = daysim.page_data(args.page)
    cruise = daysim.fitted_cruise(page)
    tasks = daysim.day_tasks(cruise)
    chosen = args.days.split(",") if args.days else pick_days(page, tasks, args.n_busiest)
    log(f"days: {', '.join(chosen)}; cruise assumptions {cruise or 'default'}")
    bus_data = None if args.no_buses else buses.load(log)
    net = buses.Network(ctx) if bus_data else None
    streets = Streets(ctx.m)
    log(f"street legs: {sum(len(v) for v in streets.options.values())} start or end points in "
        f"{sum(bool(v) for v in streets.options.values())} zones")
    days = [simulate_day(ctx, tasks[x], args.everyday, args.cruise_rate, args.seed, net, bus_data,
                         streets, log) for x in chosen]
    data = page_json(ctx, days, bus_data, log)
    data["meta"] = {"days": chosen, "cruise": cruise, "everyday": args.everyday,
                    "cruise_rate": args.cruise_rate, "seed": args.seed,
                    "made": clock.strftime("%Y-%m-%dT%H:%M")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"))
    args.out.write_text(text, encoding="utf-8")
    log(f"wrote {args.out} ({len(text) / 1e6:.2f} MB, {len(data['paths'])} paths)")


if __name__ == "__main__":
    main()
