"""Portswood Road bus check: the model's Bluestar 2 and 20 run times on Portswood Road against the
council's July 2024 figures, over several sampled days of one date.

The council's figure (Southampton City Council / WSP, Portswood Project Baseline Data Report, Jan
2025, Table 3-5) is each service's run time over its Portswood section minus the timetabled run
time, by peak, plus the share of buses 5 or more minutes slower than timetabled. The check
measures the same thing on the model: each Bluestar trip through the day's link loads
(buses.run_bus, the rule the agents page uses), from the last stop before Portswood Road to the
first stop after it, against the BODS timetable for those two stops. One sampled day is noisy
(weather, an incident, everyday-traffic noise), so it averages ``--n`` of them.

The July 2024 counts and bus times were out of university term; the model adds UNI_TERM local
traffic for term on the counted roads. ``--uni-term 1`` rebuilds that local traffic without the
uplift, for a like-for-like July weekday.

    .venv-demo/bin/python demo/bus_check.py --date 2026-11-16 --n 12 [--uni-term 1] [--json out]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import buses  # noqa: E402
import daysim  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

# Table 3-5, weekday: (route, direction) -> minutes different to the timetable in the AM peak
# (07-10) and PM peak (16-19), and the share of buses 5+ minutes slower over the whole day.
# S-N is northbound. Bluestar 2's section runs from Stag Gates (Banister's Park), Bluestar 20's
# from Spring Crescent to Belmont Road.
COUNCIL = {("2", "northbound"): (53 / 60, 68 / 60, 0.023),
           ("2", "southbound"): (262 / 60, 250 / 60, 0.251),
           ("20", "northbound"): (-10 / 60, 107 / 60, 0.024),
           ("20", "southbound"): (23 / 60, 70 / 60, 0.033)}
PERIODS = {"am": (7, 10), "pm": (16, 19)}
CORRIDORS = ("portswood", "highfield", "bevois", "stdenys")
CTX = None


def section_trips(ctx, net, data, d: date, X: np.ndarray, rng) -> list[dict]:
    """Every Bluestar 2 and 20 trip of date d through link loads X, with its Portswood section."""
    m = ctx.m
    patterns, trips = buses.day_trips(net, data, d, log=lambda *_: None)
    out = []
    for tr in trips:
        pat = patterns[tr["pattern"]]
        short = data["routes"].get(pat["route"], {}).get("short", "")
        if short not in ("2", "20"):
            continue
        e, pos, st = pat["edges"], pat["pos"], tr["stops"]
        ps = [i for i, k in enumerate(e) if k in net.portswood]
        if not ps:
            continue
        before = max(k for k, p in enumerate(pos) if p <= ps[0])
        after = next((k for k, p in enumerate(pos) if p > ps[-1]), None)
        if after is None or min(st[before][2], st[after][1]) < 0:
            continue
        arr = [s[1] / 60 for s in st]
        dep = [s[2] / 60 for s in st]
        enter, extra, late, _, _ = buses.run_bus(m, e, pos, arr, dep, X, rng)
        left = max(arr[before] + late[before] + buses.DWELL_MIN, dep[before])
        run = arr[after] + late[after] - left
        north = tm.heading_north(m, e[ps[0]])
        out.append({"route": short, "dir": "northbound" if north else "southbound",
                    "enter": float(enter[ps[0]]), "diff": float(run - (arr[after] - dep[before])),
                    "extra": float(extra[ps].sum() / 60), "late": float(late[after])})
    return out


def corridor_loads(ctx, X: np.ndarray, pre: np.ndarray | None, cap: np.ndarray) -> dict:
    """Per counted corridor and direction, per bin: worst V/C, median flow, local traffic and
    capacity."""
    m = ctx.m
    out = {}
    for cid, _, _, idx in ctx.corr:
        if cid not in CORRIDORS:
            continue
        for north in (True, False):
            ks = [k for k in idx if tm.heading_north(m, k) == north]
            if not ks:
                continue
            v = X[:, ks] * cap[ks]
            out[f"{cid} {'NB' if north else 'SB'}"] = {
                "x": X[:, ks].max(axis=1), "v": np.median(v, axis=1),
                "pre": np.median(pre[:, ks], axis=1) if pre is not None else np.zeros(len(X)),
                "cap": float(np.median(cap[ks]))}
    return out


def one(args):
    task, seed, net, data = args
    ctx = CTX
    m = ctx.m
    d = date.fromisoformat(task["date"])
    rng = np.random.default_rng([seed, d.toordinal()])
    day = daysim.sample_day(ctx, task, rng)
    Dc = daysim.vehicles_matrix(m.n_od, day.veh, daysim.cruise_times(day.veh, day.params))
    res, _ = tm.run_day(m, day.Dbg + day.Dm + Dc, day.cap, day.shares0, 3,
                        cruise=Dc if task["calls"] else None, want=("x", "held"), pre=day.pre,
                        noise=day.noise, events=day.events)
    X = res["x"]
    trips = section_trips(ctx, net, data, d, X, np.random.default_rng([seed, d.toordinal(), 2]))
    return {"trips": trips, "loads": corridor_loads(ctx, X, day.pre, day.cap),
            "held": float(res["held"].sum()), "wet": day.wet, "incident": bool(day.events)}


def period(t_min: float) -> str | None:
    h = t_min / 60
    return next((p for p, (a, b) in PERIODS.items() if a <= h < b), None)


def summarise(results: list[dict]) -> dict:
    trips = [t for r in results for t in r["trips"]]
    rows = []
    for (route, dirn), (am, pm, five) in COUNCIL.items():
        sel = [t for t in trips if t["route"] == route and t["dir"] == dirn]
        row = {"route": route, "dir": dirn, "council": {"am": am, "pm": pm, "five": five},
               "five": float(np.mean([t["diff"] >= 5 for t in sel])) if sel else None}
        for p in PERIODS:
            ps = [t for t in sel if period(t["enter"]) == p]
            row[p] = ({"n": len(ps), "diff": float(np.mean([t["diff"] for t in ps])),
                       "extra": float(np.mean([t["extra"] for t in ps])),
                       "late": float(np.mean([t["late"] for t in ps])),
                       "five": float(np.mean([t["diff"] >= 5 for t in ps]))} if ps else None)
        rows.append(row)
    loads = {}
    for key in results[0]["loads"]:
        ls = [r["loads"][key] for r in results]
        loads[key] = {"cap": ls[0]["cap"],
                      **{f: np.mean([x[f] for x in ls], axis=0).round(3).tolist()
                         for f in ("x", "v", "pre")}}
    return {"rows": rows, "loads": loads, "held": float(np.mean([r["held"] for r in results])),
            "n": len(results)}


def show(s: dict, log=print) -> None:
    log(f"Portswood Road section, minutes different to the timetable (model mean over {s['n']} "
        "sampled days; council July 2024 in brackets)")
    log(f"{'service':16s} {'AM 07-10':>22s} {'PM 16-19':>22s} {'5+ min, day':>18s}   "
        "AM / PM extra over free flow")
    for r in s["rows"]:
        cells = []
        for p in PERIODS:
            c = r[p]
            cells.append(f"{c['diff']:6.1f} ({r['council'][p]:5.1f}) n={c['n']:3d}" if c else "-")
        ext = " / ".join(f"{r[p]['extra']:.1f}" if r[p] else "-" for p in PERIODS)
        five = (f"{100 * r['five']:5.1f}% ({100 * r['council']['five']:4.1f}%)"
                if r["five"] is not None else "-")
        log(f"Bluestar {r['route']:3s} {r['dir'][:2].upper():3s} {cells[0]:>22s} {cells[1]:>22s} "
            f"{five:>18s}   {ext}")
    log("worst V/C on the counted corridors, mean over sampled days (hourly, 07-10 and 16-19):")
    hours = [(a, b) for a, b in ((8, 12), (12, 16), (16, 20), (44, 48), (48, 52), (52, 56))]
    for key, ld in s["loads"].items():
        x = np.asarray(ld["x"])
        v, pre = np.asarray(ld["v"]), np.asarray(ld["pre"])
        cells = " ".join(f"{x[a:b].mean():4.2f}" for a, b in hours)
        flows = " ".join(f"{v[a:b].mean():4.0f}" for a, b in hours)
        loc = " ".join(f"{pre[a:b].mean():4.0f}" for a, b in hours)
        log(f"  {key:14s} cap {ld['cap']:5.0f}  V/C {cells}  flow {flows}  local {loc}")
    log(f"vehicles held over a bin, summed over the day: {s['held']:.0f}")


def main(argv=None) -> None:
    global CTX
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", default="2026-11-16")
    ap.add_argument("--n", type=int, default=12, help="sampled days")
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--uni-term", type=float, help="rebuild local traffic with this term uplift")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--ctx", type=Path, default=daysim.CTX_PATH)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    CTX = daysim.load_ctx(args.ctx)
    if args.uni_term is not None:
        tm.UNI_TERM = args.uni_term
        tm.anchor_counts(CTX.m, sd.COUNT_SITES, CTX.extra["calibration"], log=lambda *_: None)
        sd._SHARES.clear()
    page = daysim.page_data(daysim.HERE / "out" / "demo.html")
    task = daysim.day_tasks(daysim.fitted_cruise(page))[args.date]
    data = buses.load()
    net = buses.Network(CTX)
    print(f"{args.date}: {len(task['calls'])} ship calls, roadworks {task['closed'] or 'none'}, "
          f"school term {task['term']}, UNI_TERM {tm.UNI_TERM:g}, CARRY {tm.CARRY:g}", flush=True)
    daysim.base_shares(CTX, task)  # once, before forking
    jobs = [(task, args.seed + i, net, data) for i in range(args.n)]
    with mp.get_context("fork").Pool(min(args.workers, args.n)) as pool:
        results = pool.map(one, jobs)
    s = summarise(results)
    show(s)
    if args.json:
        args.json.write_text(json.dumps({"date": args.date, "uni_term": tm.UNI_TERM, **s}),
                             encoding="utf-8")


if __name__ == "__main__":
    main()
