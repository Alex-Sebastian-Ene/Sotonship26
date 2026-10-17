"""Agents and the PPO layer reproduce the demo model exactly (demo/daysim.py, agents.py,
ppo_env.py).

Runs on a 3 x 3 toy network, so it needs no cached data. The demo's dependencies are not in the
project environment:

    uv run --with scipy --with shapely pytest tests/test_demo_agents_ppo.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
import scipy.sparse as sp  # noqa: E402
from scipy.sparse.csgraph import dijkstra  # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "demo"
sys.path.insert(0, str(DEMO))
import daysim  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

from sotonship26.demand.passengers import TurnaroundParams  # noqa: E402


def toy_ctx(cap_per_edge: float = 900.0) -> sd.Ctx:
    """A 3 x 3 grid, one centroid per node: three zones, two gateways, two dock gates, the
    station and the stadium."""
    nodes = [(x * 1000.0, y * 1000.0) for y in range(3) for x in range(3)]
    eu, ev = [], []
    for i, (x, y) in enumerate(nodes):
        for j, (x2, y2) in enumerate(nodes):
            if abs(x - x2) + abs(y - y2) == 1000.0:
                eu.append(i)
                ev.append(j)
    eu, ev = np.array(eu), np.array(ev)
    n_e = len(eu)
    length = np.full(n_e, 1000.0)
    t0 = length / (30 / 3.6)
    cls = ["primary"] * n_e
    xy = np.array(nodes)
    coords = [[tuple(xy[u]), tuple(xy[v])] for u, v in zip(eu, ev, strict=True)]
    kinds = [("Zone A", "zone"), ("Stadium", "stadium"), ("Zone B", "zone"), ("A1 west", "gateway"),
             ("Gate 1", "gate"), ("Gate 2", "gate"), ("Zone C", "zone"), ("Station", "station"),
             ("M1 east", "gateway")]
    cents = [tm.Centroid(nm, k, i, tuple(int(v) for v in xy[i]), homes=1.0, jobs=1.0,
                         retail=1.0, weight=6.0 if k == "gateway" else 0.0)
             for i, (nm, k) in enumerate(kinds)]
    Z = [i for i, c in enumerate(cents) if c.kind == "zone"]
    G_ = [i for i, c in enumerate(cents) if c.kind == "gateway"]
    gates = [i for i, c in enumerate(cents) if c.kind == "gate"]
    st = [7]
    pairs = [(a, b) for a in range(9) for b in range(9) if a != b]
    od_index = {p: j for j, p in enumerate(pairs)}
    edge_of = {(int(a), int(b)): k for k, (a, b) in enumerate(zip(eu, ev, strict=True))}

    def trace(pred, s, d):
        out, v = [], d
        while v != s:
            u = pred[v]
            out.append(edge_of[(int(u), int(v))])
            v = u
        return out[::-1]

    paths = []
    for a, b in pairs:
        found = []
        w = t0.copy()
        for _ in range(tm.ROUTES):
            _, pr = dijkstra(sp.csr_matrix((w, (eu, ev)), shape=(9, 9)), indices=a,
                             return_predecessors=True)
            p = trace(pr, a, b)
            if p not in found:
                found.append(p)
            w[p] *= 1.6
        while len(found) < tm.ROUTES:
            found.append(found[0])
        paths += found
    uniq = np.ones((len(pairs), tm.ROUTES), bool)
    for j in range(len(pairs)):
        for r in range(1, tm.ROUTES):
            if paths[j * tm.ROUTES + r] in paths[j * tm.ROUTES:j * tm.ROUTES + r]:
                uniq[j, r] = False
    rng = np.random.default_rng(1)
    purpose_od = {}
    for key, *_ in tm.PURPOSES:
        v = rng.random(len(pairs))
        purpose_od[key] = v / v.sum()
    zpos = {c: k for k, c in enumerate(Z)}
    od_zone = np.array([[zpos.get(a, -1), zpos.get(b, -1)] for a, b in pairs])
    kern = np.eye(len(Z))
    rows = np.concatenate([np.asarray(p) for p in paths])
    cols = np.repeat(np.arange(len(paths)), [len(p) for p in paths])
    A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n_e, len(paths)))
    col_ptr = np.concatenate([[0], np.cumsum([len(p) for p in paths])])[:-1]

    def norm(w):
        w = np.asarray(w, float)
        return w / w.sum()

    gw = norm([1.0, 1.0])
    homes = norm([1.0, 2.0, 1.0])
    sets = {"homes": (Z, homes), "jobs": (Z, homes), "retail": (Z, homes), "schools": (Z, homes),
            "gateway": (G_, gw), "county": (G_, gw),
            "car_from": (G_ + Z, norm(list(0.8 * gw) + list(0.2 * homes))),
            "taxi_rank": (st + [Z[0]], norm([0.7, 0.3])),
            "taxi_far": (st + G_ + Z, norm([0.5] + list(0.3 * gw) + list(0.2 * homes))),
            "coach_from": (G_, gw), "fans_from": (G_ + Z, norm(list(0.6 * gw) + list(0.4 * homes)))}
    m = tm.Model(xy=xy, eu=eu, ev=ev, t0=t0, cap=np.full(n_e, cap_per_edge), length=length,
                 cls=cls, name=[f"Road {k}" for k in range(n_e)], ref=[""] * n_e, coords=coords,
                 centroids=cents, ods=pairs, od_index=od_index, purpose_od=purpose_od,
                 paths=paths, A=A, AT=A.T.tocsr(), col_idx=rows, col_ptr=col_ptr, uniq=uniq,
                 od_zone=od_zone, zone_kernel=kern, scale=0.004, scale_ext=0.004, size=(2000, 2000),
                 sets=sets)
    corr = [("west", "West road", "Western approach", [0, 1]),
            ("city", "City road", "City centre", [4, 5, 6])]
    for g in gates:
        corr.append((f"gate{g}", f"{cents[g].name} access", "Dock gates",
                     [k for k in range(n_e) if eu[k] == g or ev[k] == g]))
    corr_idx = np.concatenate([c[3] for c in corr])
    corr_ptr = np.concatenate([[0], np.cumsum([len(c[3]) for c in corr])])[:-1]
    segs = [{"edges": [k], "links": [k], "name": m.name[k], "cls": "primary"} for k in range(n_e)]
    luts = {key: {g: {"in": np.array([od_index.get((o, g), -1) for o in sets[key][0]]),
                      "out": np.array([od_index.get((g, o), -1) for o in sets[key][0]])}
                  for g in gates}
            for key in ("car_from", "taxi_rank", "taxi_far", "coach_from")}
    gate_mask = np.zeros((len(pairs), len(gates)))
    for (o, d), j in od_index.items():
        for gi, g in enumerate(gates):
            if g in (o, d):
                gate_mask[j, gi] = 1.0
    gw_in = np.zeros((len(pairs), len(G_)))
    term_gate = {t: gates[i % 2] for i, t in enumerate(sd.TERMINALS)}
    return sd.Ctx(m=m, corr=corr, corr_idx=corr_idx, corr_ptr=corr_ptr,
                  seg_idx=np.arange(n_e), seg_ptr=np.arange(n_e), gates=gates,
                  terminal_gate=term_gate, luts=luts, gate_mask=gate_mask, gw_in=gw_in,
                  cruise_ods=np.flatnonzero(gate_mask.sum(axis=1) > 0),
                  extra={"segs": segs, "gateways": G_})


def calls():
    d = date(2026, 10, 24)
    return [sd.Call("Ship A", "Ocean", datetime(d.year, d.month, d.day, 6, 15),
                    datetime(d.year, d.month, d.day, 17, 0), 3200),
            sd.Call("Ship B", "Mayflower", datetime(d.year, d.month, d.day, 6, 0),
                    datetime(d.year, d.month, d.day, 16, 30), None)]


@pytest.fixture(scope="module")
def ctx():
    return toy_ctx()


def test_purposes_add_up_to_background(ctx):
    for dtype in (0, 1):
        a, ga = tm.background(ctx.m, dtype, np.random.default_rng(3), spread=1.3,
                              mult={"county": 1.1})
        parts, gb = daysim.background_by_purpose(ctx.m, dtype, np.random.default_rng(3), spread=1.3,
                                                 mult={"county": 1.1})
        np.testing.assert_array_equal(a, daysim.parts_matrix(ctx.m, parts))
        assert ga.keys() == gb.keys()


@pytest.mark.parametrize("shifts", [None, [[45, -45], [0, 30]]])
def test_cruise_vehicles_match_sample_cruise(ctx, shifts):
    p = TurnaroundParams()
    want = sd.sample_cruise(ctx, calls(), np.random.default_rng(5), p, shifts)
    veh = daysim.cruise_vehicles(ctx, calls(), np.random.default_rng(5), p)
    t = daysim.cruise_times(veh, p, dis_shift=[s[0] for s in shifts] if shifts else None,
                            emb_shift=[s[1] for s in shifts] if shifts else None)
    np.testing.assert_array_equal(want, daysim.vehicles_matrix(ctx.m.n_od, veh, t))
    assert want.sum() > 0


def test_daysim_reproduces_run_day(ctx):
    m = ctx.m
    task = {"date": "2026-10-24", "calls": calls(), "closed": [], "match": "15:00", "term": False}
    day = daysim.sample_day(ctx, task, np.random.default_rng(9), tm.initial_shares(m))
    day.events = [(np.array([0, 1, 2]), 10, 18, 0.55)]
    Dc = day.cruise_matrix(m.n_od)
    D = day.Dbg + day.Dm + Dc
    res, _ = tm.run_day(m, D, day.cap, day.shares0, 3, want=("x",), pre=day.pre, noise=day.noise,
                        events=day.events)
    sim = daysim.DaySim(m, day.shares0, day.pre, 3)
    for b in range(tm.N_BINS):
        out = sim.step((day.Dbg[b] + day.Dm[b]) + Dc[b], daysim.cap_at(day.cap, day.events, b),
                       day.noise)
        np.testing.assert_array_equal(out["x"], res["x"][b])
    assert res["x"].max() > 1.0  # the toy is congested, so the queue carry-over was exercised


def test_traverse_free_flow_and_queue(ctx):
    m = ctx.m
    edges = m.paths[0]
    X = np.zeros((tm.N_BINS, len(m.t0)))
    times, hold, extra = daysim.traverse(m, edges, 480.0, X, np.random.default_rng(0))
    assert hold is None and np.allclose(extra, 0)
    np.testing.assert_allclose(times[-1] - times[0], m.t0[edges].sum() / 60)
    X[:, edges[0]] = 50.0  # far over capacity: held almost surely
    times, hold, extra = daysim.traverse(m, edges, 480.0, X, np.random.default_rng(0))
    assert hold is not None and hold[2] > hold[1] and times[-1] > 490.0


def test_encoding_round_trip():
    import agents

    vals = [0, 1, -1, 31, 32, -33, 123456, -98765, 7]
    assert agents.dec(agents.enc(vals)) == vals


def test_times_at_boundaries():
    import agents

    bounds = agents.with_holds({0, 3, 5}, {3})
    assert bounds == [0, 3, 3, 5]
    enter = [1.0, 2.0, 3.0, 9.0, 10.0, 11.0]  # held before edge 3 from 4.0 to 9.0
    assert agents.times_at(bounds, enter, {3: 4.0}) == [1.0, 4.0, 9.0, 11.0]
    assert agents.times_at(bounds, enter, {}) == [1.0, 9.0, 9.0, 11.0]


def test_env_doing_nothing_costs_nothing(ctx):
    pytest.importorskip("gymnasium")
    import ppo_env as pe

    env = pe.CruiseDayEnv(ctx=ctx, shares={}, baseline=True)
    obs, _ = env.reset(seed=0)
    assert env.observation_space.contains(obs)
    done, total = False, 0.0
    while not done:
        obs, r, done, _, info = env.step(env.nothing())
        assert r == 0.0
        total += r
    assert info["day_costs"]["cost"] == pytest.approx(info["day_costs"]["nothing_cost"])


def test_env_levers_change_the_day(ctx):
    pytest.importorskip("gymnasium")
    import ppo_env as pe

    env = pe.CruiseDayEnv(ctx=ctx, shares={}, baseline=True)
    date_ = next(d for d in env.dates)
    env.reset(options={"date": date_, "day_seed": 1})
    held, done = 0.0, False
    while not done:
        a = env.nothing()
        a[: env.nT] = 2  # meter every terminal to 40%
        a[2 * env.nT + env.nS:] = 1  # marshals everywhere
        _, _, done, _, info = env.step(a)
        held = max(held, info["held_pax_hours"])
    c = info["day_costs"]
    assert c["marshal_hours"] == pytest.approx(15.0 * env.nG)
    assert held > 0 and c["cost"] != pytest.approx(c["nothing_cost"])
    env.reset(options={"date": date_, "day_seed": 1})
    assert env.rule().shape == env.action_space.shape


def test_env_passes_gymnasium_checks(ctx):
    pytest.importorskip("gymnasium")
    import ppo_env as pe
    from gymnasium.utils.env_checker import check_env

    check_env(pe.CruiseDayEnv(ctx=ctx, shares={}, baseline=False), skip_render_check=True)


def test_bus_queues_once_per_congested_stretch(ctx):
    import buses

    m = ctx.m
    edges = m.paths[m.od_index[(0, 8)] * tm.ROUTES]  # four links, all over capacity below
    X = np.full((tm.N_BINS, len(m.t0)), 3.0)
    n = len(edges)
    pos = [0, n // 2, n] if n > 1 else [0, n]
    sched = [480.0 + 2 * k for k in range(len(pos))]
    holds_seen = []
    for seed in range(40):
        _, _, late, holds, end = buses.run_bus(m, edges, pos, sched, sched, X,
                                               np.random.default_rng(seed))
        assert len(holds) <= 1  # one continuous stretch over capacity is one queue
        assert end >= sched[-1] and late[0] == 0.0
        holds_seen.append(len(holds))
    assert 0 < sum(holds_seen) < 40
