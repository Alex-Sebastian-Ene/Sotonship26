"""Compare the SUMO microsimulation of a sampled day with the macro model on the same day.

Reads runs/sumo/<date>/ (sumo_demand.py, then SUMO's micro and meso runs) and compares, per
corridor, direction and 15 minutes:

* flow: the median link flow along the corridor (vehicles per hour; the macro model counts lorries
  as 2.5 and coaches as 2 car-equivalents, SUMO counts vehicles);
* delay: minutes over free flow to drive the corridor. Macro: BPR running time plus the point-queue
  wait the page uses (15 min x (V/C - 1) at the worst link). SUMO: measured travel time over each
  link minus its length at 92% of the limit (the mean wanted speed);
* queue: macro, the most vehicles a link of the corridor could not pass in the 15 minutes
  (traffic_model.run_day's queue); SUMO, the mean number of vehicles standing still on the
  corridor (waiting time / 900 s);
* congested or not: macro V/C over 0.85 and over 1, SUMO speed under 70% and 50% of free flow.

Also the M271 northbound at WebTRIS site 19974 against the observed counts for the same weekday
in autumn 2024 and 2025, and buses on Portswood Road against the council's Table 3-5 (Southampton
City Council / WSP, Portswood Project Baseline Data Report, Jan 2025: 0:24 to 4:22 behind
timetable in the July 2024 peaks).

    python demo/sumo_compare.py --date 2026-11-16
writes runs/sumo/<date>/compare.json and compare.md.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sumo_demand as sdm  # noqa: E402

BINS = 60
PERIODS = {"am": (8, 20), "inter": (20, 44), "pm": (44, 56)}  # 07-10, 10-16, 16-19
WANT = 0.92  # mean wanted speed as a share of the limit (sumo_demand.VTYPES)
COUNCIL_LATE_MIN = (0.4, 4.37)  # buses.COUNCIL_RANGE_MIN


def opener(path: Path):
    return gzip.open(path, "rb") if path.suffix == ".gz" else open(path, "rb")


def edgedata(path: Path, ids: set[str] | None = None) -> dict[str, np.ndarray]:
    """Per edge and 15-minute bin: entered, left, traveltime, waitingTime, timeLoss,
    sampledSeconds (SUMO meanData)."""
    keys = ("entered", "left", "traveltime", "waitingTime", "timeLoss", "sampledSeconds",
            "departed", "arrived")
    out: dict[str, np.ndarray] = {}
    b = -1
    with opener(path) as f:
        for ev, el in ET.iterparse(f, events=("start", "end")):
            if ev == "start" and el.tag == "interval":
                b = int(round((float(el.get("begin")) - sdm.DAY_START_S) / 900))
            elif ev == "end" and el.tag == "edge":
                eid = el.get("id")
                if (ids is None or eid in ids) and 0 <= b < BINS:
                    row = out.setdefault(eid, np.full((BINS, len(keys)), np.nan))
                    for i, k in enumerate(keys):
                        v = el.get(k)
                        if v is not None:
                            row[b, i] = float(v)
                el.clear()
            elif ev == "end" and el.tag == "interval":
                el.clear()
    return {k: v for k, v in out.items()}, keys


def stats(path: Path) -> dict:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    return {child.tag: dict(child.attrib) for child in root}


def tripinfo(path: Path) -> dict:
    """Trip counts and mean minutes (duration, time loss, departure delay) per kind of trip."""
    acc = defaultdict(lambda: np.zeros(5))
    unfinished = defaultdict(int)
    with opener(path) as f:
        for _, el in ET.iterparse(f):
            if el.tag != "tripinfo":
                continue
            key = el.get("id").split(".")[0]
            if float(el.get("arrival", -1)) < 0:
                unfinished[key] += 1
            else:
                acc[key] += [1, float(el.get("duration")), float(el.get("timeLoss")),
                             float(el.get("departDelay")), float(el.get("routeLength"))]
            el.clear()
    rows = {}
    for k, a in sorted(acc.items()):
        n = a[0]
        rows[k] = {"n": int(n), "unfinished": unfinished.get(k, 0),
                   "duration_min": round(a[1] / n / 60, 2),
                   "time_loss_min": round(a[2] / n / 60, 2),
                   "depart_delay_min": round(a[3] / n / 60, 2), "km": round(a[4] / n / 1000, 2)}
    return rows


def summary_series(path: Path) -> dict:
    """Vehicles running, waiting to enter and standing, per 15 minutes (means of 1-min steps)."""
    run, wait, halt = (defaultdict(list) for _ in range(3))
    if not path.exists():
        return {}
    for _, el in ET.iterparse(str(path)):
        if el.tag == "step":
            b = int((float(el.get("time")) - sdm.DAY_START_S) // 900)
            if 0 <= b < BINS:
                run[b].append(float(el.get("running")))
                wait[b].append(float(el.get("waiting")))
                halt[b].append(float(el.get("halting", 0)))
            el.clear()
    return {k: [round(float(np.mean(d[b])), 1) if d[b] else None for b in range(BINS)]
            for k, d in (("running", run), ("waiting", wait), ("halting", halt))}


# --- corridors -------------------------------------------------------------------------------

def macro_corridor(mac, edges, north_of):
    """Per direction: per-bin V/C (worst link), flow (median link, veh/h), delay (min), queue."""
    x, cap, t0, q = mac["x"], mac["cap"], mac["t0"], mac["queue"]
    out = {}
    for d in ("NB", "SB"):
        ks = [k for k in edges if north_of[str(k)] == (d == "NB")]
        if not ks:
            continue
        xc = x[:, ks]
        vc = xc.max(axis=1)
        run = (t0[ks] * 0.15 * np.minimum(xc, 1.5) ** 4).sum(axis=1) / 60.0
        out[d] = {"vc": vc, "flow": np.median(np.minimum(xc, 1.0) * cap[ks], axis=1),
                  "demand": np.median(xc * cap[ks], axis=1),
                  "delay": run + 15.0 * np.maximum(vc - 1.0, 0.0),
                  "free": float(t0[ks].sum() / 60.0), "queue": q[:, ks].max(axis=1),
                  "km": float(mac["length"][ks].sum() / 1000), "links": len(ks)}
    return out


def sumo_corridor(ed, keys, net, mapped, north_of):
    """The same per direction from SUMO edge data."""
    ki = {k: i for i, k in enumerate(keys)}
    out = {}
    for d in ("NB", "SB"):
        es = [e for e, k in mapped.items() if north_of[str(k)] == (d == "NB") and e in net.ix]
        if not es:
            continue
        L = np.array([net.length[net.ix[e]] for e in es])
        vmax = np.array([net.edges[net.ix[e]].getSpeed() for e in es]) * WANT
        tff = L / vmax
        tt = np.full((BINS, len(es)), np.nan)
        flow = np.full((BINS, len(es)), 0.0)
        wait = np.zeros((BINS, len(es)))
        for j, e in enumerate(es):
            row = ed.get(e)
            if row is None:
                continue
            tt[:, j] = row[:, ki["traveltime"]]
            flow[:, j] = np.nan_to_num(row[:, ki["left"]]) * 4.0
            wait[:, j] = np.nan_to_num(row[:, ki["waitingTime"]])
        seen = ~np.isnan(tt)
        ttf = np.where(seen, tt, tff[None, :])  # an empty link in a bin: free flow
        delay = np.maximum(ttf - tff[None, :], 0.0).sum(axis=1) / 60.0
        out[d] = {"flow": np.median(flow, axis=1), "delay": delay,
                  "speed_ratio": tff.sum() / ttf.sum(axis=1), "queue": wait.sum(axis=1) / 900.0,
                  "free": float(tff.sum() / 60.0), "km": float(L.sum() / 1000), "links": len(es),
                  "seen": seen.any(axis=1)}
    return out


def agreement(pairs) -> dict:
    """Counts of corridor-direction-bins by macro and SUMO congestion classes."""
    out = {}
    for name, mthr, sthr in (("busy", 0.85, 0.7), ("jammed", 1.0, 0.5)):
        n = {"both": 0, "macro_only": 0, "sumo_only": 0, "neither": 0}
        for vc, sr in pairs:
            a, b = vc > mthr, sr < sthr
            n["both" if a and b else "macro_only" if a else "sumo_only" if b else "neither"] += 1
        out[name] = {"macro": f"V/C > {mthr}",
                     "sumo": f"speed < {int(sthr * 100)}% of free flow", **n}
    return out


def spearman(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return round(float(np.corrcoef(ra, rb)[0, 1]), 2)


def period_mean(a, per) -> float:
    lo, hi = PERIODS[per]
    return float(np.mean(a[lo:hi]))


# --- M271 against WebTRIS --------------------------------------------------------------------

def webtris_reference(d: date) -> dict | None:
    """Observed 15-min counts at 19974 (M271 NB, A35 to J1): median and 10-90% over the same
    weekday, term time, September to November 2024 and 2025."""
    try:
        import webtris_backtest as wb
    except ImportError:
        return None
    try:
        df, meta = wb.load_webtris()
    except Exception as exc:  # noqa: BLE001  (no cache and no internet on a compute node)
        print("WebTRIS unavailable:", exc)
        return None
    df = df[df["site"] == 19974]
    days = sorted({x for x in df["date"].unique()
                   if x.month in (9, 10, 11) and x.weekday() == d.weekday()
                   and not wb.school_holiday(x)})
    if not days:
        return None
    sub = df[df["date"].isin(days)]
    mat = sub.pivot_table(index="date", columns="bin", values="flow").reindex(columns=range(96))
    mat = mat.iloc[:, 20:20 + BINS].to_numpy() * 4.0  # 05:00-20:00, vehicles per hour
    return {"days": len(days), "first": str(days[0]), "last": str(days[-1]),
            "median": np.nanmedian(mat, axis=0), "p10": np.nanpercentile(mat, 10, axis=0),
            "p90": np.nanpercentile(mat, 90, axis=0), "source": meta.get("source"),
            "retrieved": meta.get("retrieved")}


# --- buses on Portswood Road ------------------------------------------------------------------

def stop_events(path: Path) -> dict[str, list]:
    out = defaultdict(list)
    if not path.exists():
        return out
    with opener(path) as f:
        for _, el in ET.iterparse(f):
            if el.tag == "stopinfo" and el.get("id", "").startswith("bus."):
                out[el.get("id")].append((el.get("busStop"), float(el.get("started")),
                                          float(el.get("ended"))))
            el.clear()
    return out


def portswood_buses(bus: dict, events: dict, ps_dir: dict[str, str]) -> dict:
    """Lateness at the first stop past the Portswood Road section, per route, direction and peak,
    as buses.route_table measures it for the macro model."""
    rows = defaultdict(list)
    for t in bus["trips"]:
        ev = events.get(t["id"])
        if not ev:
            continue
        seq = t["stops"]
        idx = [i for i, (bs, *_r) in enumerate(seq) if bus["stops"][bs]["edge"] in ps_dir]
        if not idx or idx[-1] + 1 >= len(seq):
            continue
        nxt = idx[-1] + 1
        done = {bs: (st, en) for bs, st, en in ev}
        bs_n, arr_n, _ = seq[nxt]
        bs_0, _, dep_0 = seq[idx[0]]
        if bs_n not in done or arr_n < 0:
            continue
        late = (done[bs_n][0] - arr_n) / 60.0
        h = dep_0 / 3600
        per = "am" if 7 <= h < 10 else "pm" if 16 <= h < 19 else None
        if per is None:
            continue
        dirn = ps_dir[bus["stops"][seq[idx[0]][0]]["edge"]]
        rows[(t["route"], dirn, per)].append(late)
    table = []
    for (route, dirn, per), v in sorted(rows.items()):
        info = bus["routes"].get(route, {})
        table.append({"route": route, "name": info.get("short", ""),
                      "operator": info.get("agency", ""), "dir": dirn, "period": per,
                      "n": len(v), "late": round(float(np.mean(v)), 2),
                      "late5": round(float(np.mean(np.asarray(v) >= 5)), 3)})
    return table


def macro_portswood(bus_table) -> list:
    out = []
    for r in bus_table or []:
        for k, v in r.get("portswood", {}).items():
            dirn, per = k.split("_")
            out.append({"route": r["route"], "name": r["name"], "operator": r["operator"],
                        "dir": "NB" if dirn == "northbound" else "SB", "period": per, **v})
    return out


# --- report ----------------------------------------------------------------------------------

def fmt(v, nd=1):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def corridor_rows(emap, mac, ed_all, keys, net):
    """Peak means per corridor and direction, the per-bin series, and the (V/C, speed ratio)
    and (macro delay, SUMO delay) pairs for every corridor-direction-bin from 06:00."""
    rows, pairs, delays, series = [], [], [], {}
    for cid, c in emap["corridors"].items():
        mc = macro_corridor(mac, c["macro_edges"], c["north"])
        sc = sumo_corridor(ed_all, keys, net, c["sumo"], c["north"])
        for dirn in ("NB", "SB"):
            if dirn not in mc or dirn not in sc:
                continue
            a, b = mc[dirn], sc[dirn]
            for t in range(4, BINS):  # SUMO starts with empty roads at 05:00
                pairs.append((a["vc"][t], b["speed_ratio"][t]))
                delays.append((a["delay"][t], b["delay"][t]))
            row = {"corridor": cid, "label": c["label"], "dir": dirn,
                   "macro_km": round(a["km"], 2), "sumo_km": round(b["km"], 2),
                   "macro_free_min": round(a["free"], 1), "sumo_free_min": round(b["free"], 1)}
            for per in ("am", "inter", "pm"):
                row[per] = {"macro_vc": round(period_mean(a["vc"], per), 2),
                            "macro_flow": round(period_mean(a["flow"], per)),
                            "macro_demand": round(period_mean(a["demand"], per)),
                            "sumo_flow": round(period_mean(b["flow"], per)),
                            "macro_delay": round(period_mean(a["delay"], per), 2),
                            "sumo_delay": round(period_mean(b["delay"], per), 2),
                            "macro_queue": round(period_mean(a["queue"], per), 1),
                            "sumo_queue": round(period_mean(b["queue"], per), 1),
                            "sumo_speed": round(period_mean(b["speed_ratio"], per), 2)}
            rows.append(row)
            s = {k: np.round(a[k], 3).tolist() for k in ("vc", "flow", "delay", "queue")}
            s.update({f"sumo_{k}": np.round(b[k], 3).tolist()
                      for k in ("flow", "delay", "queue", "speed_ratio")})
            series[f"{cid}_{dirn}"] = s
    return rows, pairs, delays, series


def m271_flows(emap, mac, ed_all, keys, wt) -> dict:
    """Vehicles per hour at the WebTRIS 19974 links: macro (car-equivalents), SUMO, observed."""
    ki = {k: i for i, k in enumerate(keys)}
    probe = emap["m271_probe"]
    ks = probe["macro_edges"]
    served = np.minimum(mac["x"][:, ks], 1.0) * mac["cap"][ks]
    mflow = np.median(served, axis=1)
    mdemand = np.median(mac["x"][:, ks] * mac["cap"][ks], axis=1)
    pe = [e for e in probe["sumo"] if e in ed_all]
    sflow = (np.median(np.stack([np.nan_to_num(ed_all[e][:, ki["left"]]) * 4 for e in pe]),
                       axis=0) if pe else np.zeros(BINS))
    out = {"macro": np.round(mflow).tolist(), "macro_demand": np.round(mdemand).tolist(),
           "sumo": np.round(sflow).tolist(), "sumo_edges": pe}
    if wt:
        out["webtris"] = {k: (np.round(v).tolist() if isinstance(v, np.ndarray) else v)
                          for k, v in wt.items()}
    return out


def markdown(mode, res, macro_vh, mp, d) -> list[str]:
    veh, tel = res["stats"].get("vehicles", {}), res["stats"].get("teleports", {})
    md = [f"\n### {mode}\n",
          f"Vehicles loaded {veh.get('loaded')}, inserted {veh.get('inserted')}, still running at "
          f"the end {veh.get('running')}, never inserted {veh.get('waiting')}; teleports "
          f"{tel.get('total')} (jam {tel.get('jam')}, yield {tel.get('yield')}, wrong lane "
          f"{tel.get('wrongLane')}).\n",
          f"Delay on the network, vehicle-hours: SUMO {res['delay_veh_h']:,} time lost on the "
          f"roads plus {res['depart_delay_veh_h']:,} waiting to enter; macro "
          f"{macro_vh['running']:,} slower running plus {macro_vh['queues']:,} in point queues "
          f"(car-equivalents).\n"]
    for per, name in (("am", "07:00-10:00"), ("pm", "16:00-19:00")):
        md += [f"\n{name}, means of the 15-minute values:\n",
               "| corridor | dir | macro V/C | macro demand | flow veh/h macro / SUMO "
               "| delay min macro / SUMO | queue veh macro / SUMO | SUMO speed % of free |",
               "|---|---|---|---|---|---|---|---|"]
        for r in res["corridors"]:
            a = r[per]
            md.append(f"| {r['label']} | {r['dir']} | {a['macro_vc']} | {a['macro_demand']} | "
                      f"{a['macro_flow']} / {a['sumo_flow']} | {a['macro_delay']} / "
                      f"{a['sumo_delay']} | {a['macro_queue']} / {a['sumo_queue']} | "
                      f"{round(a['sumo_speed'] * 100)} |")
    md += [f"\nCorridor-direction-bins 06:00-20:00: {res['n_pairs']}; Spearman rank correlation "
           f"of delay {res['spearman_delay']}.\n",
           "| class | both | macro only | SUMO only | neither |", "|---|---|---|---|---|"]
    for name, g in res["agreement"].items():
        md.append(f"| {name}: {g['macro']} / {g['sumo']} | {g['both']} | {g['macro_only']} | "
                  f"{g['sumo_only']} | {g['neither']} |")
    m271 = res["m271"]
    wt = m271.get("webtris")
    if wt:
        md += [f"\nM271 northbound at WebTRIS 19974, vehicles per hour (observed: median and "
               f"10-90% of {wt['days']} term-time {d.strftime('%A')}s, Sep-Nov "
               f"{wt['first'][:4]}-{wt['last'][:4]}):\n",
               "| hour | observed | macro served (demand), car-equivalents | SUMO |",
               "|---|---|---|---|"]
        for h in range(6, 20):
            sl = slice((h - 5) * 4, (h - 4) * 4)
            obs = [np.mean(wt[k][sl]) for k in ("median", "p10", "p90")]
            md.append(f"| {h:02d}:00 | {obs[0]:.0f} ({obs[1]:.0f}-{obs[2]:.0f}) | "
                      f"{np.mean(m271['macro'][sl]):.0f} ({np.mean(m271['macro_demand'][sl]):.0f})"
                      f" | {np.mean(m271['sumo'][sl]):.0f} |")
    md += ["\nBuses on Portswood Road, minutes late at the first stop past the section "
           f"(council, July 2024 peaks: {COUNCIL_LATE_MIN[0]:.1f} to {COUNCIL_LATE_MIN[1]:.1f}):\n",
           "| route | dir | peak | SUMO buses | SUMO late | macro buses | macro late |",
           "|---|---|---|---|---|---|---|"]
    mk = {(r["route"], r["dir"], r["period"]): r for r in mp}
    for r in res["buses"]:
        o = mk.get((r["route"], r["dir"], r["period"]), {})
        md.append(f"| {r['operator']} {r['name']} | {r['dir']} | {r['period']} | {r['n']} | "
                  f"{r['late']} | {o.get('n', '-')} | {o.get('late', '-')} |")
    if res["tripinfo"]:
        md += ["\n| trips | finished | unfinished | minutes | time loss | waiting to enter | km |",
               "|---|---|---|---|---|---|---|"]
        for k, r in res["tripinfo"].items():
            md.append(f"| {k} | {r['n']} | {r['unfinished']} | {r['duration_min']} | "
                      f"{r['time_loss_min']} | {r['depart_delay_min']} | {r['km']} |")
    return md


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", type=Path, default=sdm.RUNS)
    ap.add_argument("--net", type=Path, default=sdm.NET)
    ap.add_argument("--modes", default="micro,meso")
    args = ap.parse_args(argv)
    R = args.out / args.date

    def load(name):
        return json.loads((R / name).read_text(encoding="utf-8"))

    meta, emap, mj, bus = (load(n) for n in ("meta.json", "edges.json", "macro.json", "buses.json"))
    mac = dict(np.load(R / "macro.npz"))
    net = sdm.Net(args.net)
    d = date.fromisoformat(args.date)
    calls = ", ".join(f"{c['ship']} ({c['terminal']}, {c['pax']})" for c in meta["calls"])
    md = [f"## {args.date}: SUMO against the macro model on the same sampled day\n",
          f"Ships: {calls or 'none'}. Trips written: {meta['counts']}. Scale {meta['scale']}. "
          f"Model commit {meta['git']}.\n"]
    ps = emap["corridors"].get("portswood", {})
    ps_dir = {e: ("NB" if ps["north"][str(k)] else "SB") for e, k in ps.get("sumo", {}).items()}

    # macro network total, vehicle-hours: slower running on every link (BPR, capped as in
    # delay_minutes) plus 15 minutes for every vehicle the point queues carry into the next bin
    x, cap, t0 = mac["x"], mac["cap"], mac["t0"]
    run_vh = float((x * cap / 4.0 * t0 * 0.15 * np.minimum(x, 1.5) ** 4 / 3600.0).sum())
    queue_vh = float(mac["held"].sum() * 0.25)
    macro_vh = {"running": round(run_vh), "queues": round(queue_vh),
                "total": round(run_vh + queue_vh)}
    report = {"date": args.date, "meta": meta, "modes": {},
              "macro": {"delay_veh_h": macro_vh,
                        "held": np.round(mac["held"]).astype(int).tolist()}}
    wt = webtris_reference(d)
    mp = macro_portswood(mj.get("bus_table"))

    for mode in args.modes.split(","):
        edf = R / f"{mode}.edgedata.xml.gz"
        if not edf.exists():
            md.append(f"\n{mode}: no edge data (the run did not finish)\n")
            continue
        ed_all, keys = edgedata(edf)
        lost = keys.index("timeLoss")
        rows, pairs, delays, series = corridor_rows(emap, mac, ed_all, keys, net)
        tip = R / f"{mode}.tripinfo.xml.gz"
        res = {"stats": stats(R / f"{mode}.stats.xml"),
               "delay_veh_h": round(sum(float(np.nansum(r[:, lost])) for r in ed_all.values())
                                    / 3600),
               "corridors": rows, "agreement": agreement(pairs), "n_pairs": len(pairs),
               "spearman_delay": spearman([a for a, _ in delays], [b for _, b in delays]),
               "series": series, "m271": m271_flows(emap, mac, ed_all, keys, wt),
               "buses": portswood_buses(bus, stop_events(R / f"{mode}.stops.xml.gz"), ps_dir),
               "tripinfo": tripinfo(tip) if tip.exists() else {},
               "summary": summary_series(R / f"{mode}.summary.xml")}
        trips = res["stats"].get("vehicleTripStatistics", {})
        res["depart_delay_veh_h"] = round(float(trips.get("totalDepartDelay", 0)) / 3600)
        report["modes"][mode] = res
        md += markdown(mode, res, macro_vh, mp, d)

    def default(o):
        return o.tolist() if hasattr(o, "tolist") else str(o)

    (R / "compare.json").write_text(json.dumps(report, default=default), encoding="utf-8")
    (R / "compare.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
