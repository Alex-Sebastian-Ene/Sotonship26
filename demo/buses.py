"""Buses on the modelled roads: Bluestar, First and Unilink services through Southampton.

Routes and timetables come from the Bus Open Data Service (BODS) timetable download in GTFS
format for the South West region (Open Government Licence v3.0; Southampton's operators are in
that file, not the South East one). ``fetch`` downloads it once into
data/cache/bods (gitignored) and keeps the trips of the three operators that stop inside the study
area. If BODS cannot be reached, ``fetch --osm`` takes the operators' route=bus relations from
OpenStreetMap instead (ODbL): real stops in order but no timetable, so buses then run at an
assumed headway and "late" means late against free-flowing roads. The reduced file records which.

Each trip's stops are snapped to the model network and joined by the quickest free-flow path, and
the bus runs on the same link speeds and queues as the cars of the day it is simulated on
(daysim.traverse), slower than a car by BUS_SPEED and stopping DWELL_MIN at each stop. A bus that
reaches a stop early waits for its timetabled time. There are no bus lanes or bus gates in the
model, so buses sit in the same queues as everyone else.

    UV="uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas
        --with shapely --with pyproj"
    $UV python demo/buses.py fetch                  # once; needs internet
    $UV python demo/buses.py fetch --zip PATH       # reduce a GTFS zip saved by hand
    $UV python demo/buses.py fetch --osm            # fallback: OSM route relations
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "data" / "cache" / "bods"
REDUCED = CACHE / "southampton_buses.json"
BODS_URL = "https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/south_west/"
BODS_PAGE = "https://data.bus-data.dft.gov.uk/timetable/download/"
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
# Agency names in the BODS feed. Go South Coast runs Bluestar and Unilink (Unilink's routes are
# listed under Bluestar or its own name); First Solent appears as "First Portsmouth, Fareham &
# Gosport". Only trips that stop inside the study area are kept.
OPERATORS = re.compile(r"bluestar|unilink|go south coast|\bfirst\b", re.I)
BBOX = (-1.53, 50.855, -1.29, 50.975)  # synthetic_demo.BBOX, kept here so fetch needs no numpy
BUS_SPEED = 0.8  # assumed: a bus covers a link at 80% of a car's free-flow speed
DWELL_MIN = 20 / 60  # assumed: 20 seconds at each stop
SNAP_M = 250.0  # stops further than this from a modelled road are left out
DEFAULT_HEADWAY_MIN = 20  # OSM fallback only, when the relation has no interval tag
# Southampton City Council / WSP, Portswood Project Baseline Data Report (Jan 2025), Table 3-5:
# bus run times on Portswood Road, July 2024.
COUNCIL_BUS = ("In July 2024 services on Portswood Road ran 0:24 to 4:22 minutes behind "
               "timetable in the peaks, and a quarter of Bluestar 2 southbound buses were 5 or "
               "more minutes late (Southampton City Council / WSP, Portswood Project Baseline Data "
               "Report, Jan 2025, Table 3-5).")
COUNCIL_RANGE_MIN = (0.4, 4.37)


# --- fetching and reducing the timetable ---------------------------------------------------------

def _download(url: str, path: Path, log=print) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "sotonship26-demo (hackathon)"})
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        info = {"url": r.geturl(), "last_modified": r.headers.get("Last-Modified"),
                "bytes": int(r.headers.get("Content-Length") or 0)}
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)
    info["collected"] = datetime.now(UTC).isoformat(timespec="seconds")
    log(f"downloaded {url} -> {path} ({path.stat().st_size / 1e6:.0f} MB)")
    return info


def _seconds(hms: str) -> int:
    h, m, s = (int(v) for v in hms.strip().split(":"))
    return h * 3600 + m * 60 + s


def _inside(lat: float, lon: float) -> bool:
    w, s, e, n = BBOX
    return s <= lat <= n and w <= lon <= e


def reduce_gtfs(zpath: Path, source: dict, first: date, last: date, log=print) -> dict:
    """Keep the operators' trips that run between ``first`` and ``last`` and stop in the area."""
    z = zipfile.ZipFile(zpath)
    names = set(z.namelist())

    def rows(name):
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))

    agencies = {r["agency_id"]: r["agency_name"] for r in rows("agency.txt")}
    keep = {a for a, n in agencies.items() if OPERATORS.search(n)}
    log("operators kept: " + ", ".join(sorted(agencies[a] for a in keep)))
    routes = {}
    for r in rows("routes.txt"):
        a = r.get("agency_id") or (next(iter(agencies)) if len(agencies) == 1 else "")
        if a in keep:
            routes[r["route_id"]] = {"agency": agencies[a], "short": r.get("route_short_name", ""),
                                     "long": r.get("route_long_name", "")}
    stops = {}
    for r in rows("stops.txt"):
        try:
            lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
        except (KeyError, ValueError):
            continue
        if _inside(lat, lon):
            stops[r["stop_id"]] = [r.get("stop_name", ""), lat, lon]
    services: dict[str, dict] = {}
    if "calendar.txt" in names:
        for r in rows("calendar.txt"):
            services[r["service_id"]] = {
                "days": [int(r[d]) for d in ("monday", "tuesday", "wednesday", "thursday",
                                             "friday", "saturday", "sunday")],
                "start": r["start_date"], "end": r["end_date"], "add": [], "remove": []}
    if "calendar_dates.txt" in names:
        for r in rows("calendar_dates.txt"):
            s = services.setdefault(r["service_id"], {"days": [0] * 7, "start": "99999999",
                                                      "end": "00000000", "add": [], "remove": []})
            (s["add"] if r["exception_type"].strip() == "1" else s["remove"]).append(r["date"])
    window = [first.toordinal() + i for i in range(last.toordinal() - first.toordinal() + 1)]

    def runs_in_window(sid):
        s = services.get(sid)
        return s is not None and any(service_runs(s, date.fromordinal(o)) for o in window)

    trips = {}
    for r in rows("trips.txt"):
        if r["route_id"] in routes and runs_in_window(r["service_id"]):
            trips[r["trip_id"]] = {"id": r["trip_id"], "route": r["route_id"],
                                   "service": r["service_id"], "dir": r.get("direction_id", ""),
                                   "headsign": r.get("trip_headsign", ""), "stops": []}
    log(f"routes {len(routes)}, trips in the window {len(trips)}, stops in the area {len(stops)}")
    with z.open("stop_times.txt") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
        head = next(reader)
        it, ia, idp, isd, isq = (head.index(c) for c in ("trip_id", "arrival_time",
                                                          "departure_time", "stop_id",
                                                          "stop_sequence"))
        for row in reader:
            t = trips.get(row[it])
            if t is None or row[isd] not in stops:
                continue
            arr, dep = row[ia] or row[idp], row[idp] or row[ia]
            if not arr:
                continue  # untimed stop: GTFS allows it, this model needs a time
            t["stops"].append([int(row[isq]), row[isd], _seconds(arr), _seconds(dep)])
    kept = []
    for t in trips.values():
        if len(t["stops"]) >= 2:
            t["stops"] = [s[1:] for s in sorted(t["stops"])]
            kept.append(t)
    used_routes = {t["route"] for t in kept}
    used_services = {t["service"] for t in kept}
    used_stops = {s[0] for t in kept for s in t["stops"]}
    log(f"kept {len(kept)} trips on {len(used_routes)} routes, {len(used_stops)} stops")
    feed = next(rows("feed_info.txt"), {}) if "feed_info.txt" in names else {}
    return {"source": {**source, "kind": "bods_gtfs", "licence": "Open Government Licence v3.0",
                       "feed": {k: feed.get(k) for k in ("feed_publisher_name", "feed_version",
                                                         "feed_start_date", "feed_end_date")}},
            "timetable": "gtfs", "routes": {k: routes[k] for k in used_routes},
            "stops": {k: stops[k] for k in used_stops},
            "services": {k: services[k] for k in used_services}, "trips": kept}


def service_runs(s: dict, d: date) -> bool:
    ymd = d.strftime("%Y%m%d")
    if ymd in s["remove"]:
        return False
    if ymd in s["add"]:
        return True
    return s["start"] <= ymd <= s["end"] and bool(s["days"][d.weekday()])


def fetch_osm(log=print) -> dict:
    """Fallback: the operators' bus route relations from OpenStreetMap, stops in order, no times."""
    w, s, e, n = BBOX
    q = (f'[out:json][timeout:180];relation["type"="route"]["route"="bus"]({s},{w},{n},{e});'
         "out body;node(r);out skel qt;")
    req = urllib.request.Request(OVERPASS_URL, data=("data=" + q).encode(),
                                 headers={"User-Agent": "sotonship26-demo (hackathon)"})
    with urllib.request.urlopen(req, timeout=240) as r:
        el = json.load(r)["elements"]
    nodes = {x["id"]: (x["lat"], x["lon"]) for x in el if x["type"] == "node"}
    routes, stops, trips = {}, {}, []
    for rel in (x for x in el if x["type"] == "relation"):
        tags = rel.get("tags", {})
        op = tags.get("operator", "") + " " + tags.get("network", "")
        if not OPERATORS.search(op):
            continue
        seq = [m["ref"] for m in rel["members"] if m["type"] == "node"
               and m.get("role", "").startswith(("stop", "platform")) and m["ref"] in nodes]
        seq = [v for i, v in enumerate(seq) if i == 0 or v != seq[i - 1]]
        seq = [v for v in seq if _inside(*nodes[v])]
        if len(seq) < 2:
            continue
        rid = str(rel["id"])
        routes[rid] = {"agency": tags.get("operator", "").strip(), "short": tags.get("ref", ""),
                       "long": tags.get("name", "")}
        for v in seq:
            stops[str(v)] = ["", *nodes[v]]
        iv = tags.get("interval", "")
        try:
            hw = (int(iv.split(":")[0]) * 60 + int(iv.split(":")[1])) if ":" in iv else int(iv)
        except ValueError:
            hw = DEFAULT_HEADWAY_MIN
        hw = hw or DEFAULT_HEADWAY_MIN
        for k, t0 in enumerate(range(6 * 60, 19 * 60 + 1, hw)):
            trips.append({"id": f"{rid}-{k}", "route": rid, "service": "all", "dir": "",
                          "headsign": tags.get("to", ""),
                          "stops": [[str(v), -1, -1] for v in seq], "first_min": t0})
    log(f"OSM fallback: {len(routes)} route relations, {len(trips)} trips at assumed headways")
    return {"source": {"kind": "osm_relations", "url": OVERPASS_URL, "licence": "ODbL",
                       "collected": datetime.now(UTC).isoformat(timespec="seconds")},
            "timetable": "assumed", "routes": routes, "stops": stops,
            "services": {"all": {"days": [1] * 7, "start": "00000000", "end": "99999999",
                                 "add": [], "remove": []}}, "trips": trips}


GTFS_ZIP = CACHE / "gtfs_south_west.zip"
GTFS_SOURCE = CACHE / "gtfs_south_west.source.json"  # where and when the zip was downloaded


def fetch(url: str = BODS_URL, zip_path: Path | None = None, osm: bool = False,
          download_only: bool = False, log=print) -> dict | None:
    """Download the BODS GTFS (unless already there) and reduce it to REDUCED. Compute nodes
    without internet can reduce a zip a login node downloaded (``download_only`` there)."""
    sys.path.insert(0, str(HERE))
    import synthetic_demo as sd  # the forecast window

    if osm:
        data = fetch_osm(log)
    else:
        if zip_path is None:
            zip_path = GTFS_ZIP
            if not zip_path.exists():
                GTFS_SOURCE.parent.mkdir(parents=True, exist_ok=True)
                GTFS_SOURCE.write_text(json.dumps(_download(url, zip_path, log)), encoding="utf-8")
        if download_only:
            return None
        if zip_path == GTFS_ZIP and GTFS_SOURCE.exists():
            info = json.loads(GTFS_SOURCE.read_text(encoding="utf-8"))
        else:
            info = {"url": url, "file": str(zip_path), "last_modified": None,
                    "collected": datetime.fromtimestamp(zip_path.stat().st_mtime,
                                                        UTC).isoformat(timespec="seconds")}
        data = reduce_gtfs(zip_path, {**info, "page": BODS_PAGE}, sd.FIRST_DAY, sd.HORIZON, log)
    REDUCED.parent.mkdir(parents=True, exist_ok=True)
    REDUCED.write_text(json.dumps(data), encoding="utf-8")
    log(f"wrote {REDUCED} ({REDUCED.stat().st_size / 1e6:.1f} MB)")
    return data


def load(log=print) -> dict | None:
    if not REDUCED.exists():
        log(f"no bus timetable at {REDUCED}: run demo/buses.py fetch first; buses left out")
        return None
    return json.loads(REDUCED.read_text(encoding="utf-8"))


# --- buses on the network --------------------------------------------------------------------

class Network:
    """Stop snapping and quickest paths on the model network (built once per process)."""

    def __init__(self, ctx):
        import synthetic_demo as sd
        from scipy import sparse
        from scipy.spatial import cKDTree

        m = ctx.m
        self.m = m
        n = len(m.xy)
        motor = np.array([c in ("motorway", "motorway_link") for c in m.cls])
        w = m.t0 * np.where(motor, 3.0, 1.0)  # buses keep off motorways unless they must
        self.edge_of = {}
        for k, (u, v) in enumerate(zip(m.eu, m.ev, strict=True)):
            key = (int(u), int(v))
            if key not in self.edge_of or w[k] < w[self.edge_of[key]]:
                self.edge_of[key] = k
        self.csr = sparse.csr_matrix((w, (m.eu, m.ev)), shape=(n, n))
        ok = np.zeros(n, bool)
        ok[m.eu[~motor]] = ok[m.ev[~motor]] = True
        self.ids = np.flatnonzero(ok)
        self.tree = cKDTree(m.xy[self.ids])
        x0, y1, self.to_bng = sd.frame_origin()
        self.x0, self.y1 = x0, y1
        portswood = next((c[3] for c in ctx.corr if c[0] == "portswood"), [])
        self.portswood = set(int(k) for k in portswood)
        self._paths: dict[tuple[int, int], list[int] | None] = {}

    def snap(self, lat: float, lon: float):
        e, n_ = self.to_bng.transform(lon, lat)
        p = (e - self.x0, self.y1 - n_)
        d, i = self.tree.query(p)
        return (int(self.ids[i]), p) if d <= SNAP_M else (None, p)

    def paths(self, pairs) -> None:
        """Quickest paths for (from node, to node) pairs, cached."""
        from scipy.sparse.csgraph import dijkstra

        todo = sorted({p for p in pairs if p not in self._paths and p[0] != p[1]})
        for p in pairs:
            if p[0] == p[1]:
                self._paths[p] = []
        if not todo:
            return
        src = sorted({a for a, _ in todo})
        _, pred = dijkstra(self.csr, indices=src, return_predecessors=True)
        row = {s: i for i, s in enumerate(src)}
        for a, b in todo:
            pr, out, v = pred[row[a]], [], b
            while v != a:
                u = pr[v]
                if u < 0:
                    out = None
                    break
                out.append(self.edge_of[(int(u), int(v))])
                v = u
            self._paths[(a, b)] = out[::-1] if out is not None else None

    def path(self, a: int, b: int):
        return self._paths.get((a, b))


def day_trips(net: Network, data: dict, d: date, log=print) -> tuple[list, list]:
    """Patterns (route, snapped stops, edges, stop positions) and trips running on date d."""
    run = {sid for sid, s in data["services"].items() if service_runs(s, d)}
    snapped = {sid: net.snap(lat, lon) for sid, (_, lat, lon) in data["stops"].items()}
    trips, pairs = [], set()
    for t in data["trips"]:
        if t["service"] not in run:
            continue
        st = [s for s in t["stops"] if snapped[s[0]][0] is not None]
        if len(st) < 2:
            continue
        first = st[0][2] / 60 if st[0][2] >= 0 else t.get("first_min", -1)
        if not 300 <= first < 1200:
            continue
        nodes = [snapped[s[0]][0] for s in st]
        pairs |= set(zip(nodes[:-1], nodes[1:], strict=True))
        trips.append((t, st, nodes))
    net.paths(pairs)
    patterns, index, out = [], {}, []
    for t, st, nodes in trips:
        key = (t["route"], tuple(s[0] for s in st))
        if key not in index:
            edges, pos, ok = [], [0], True
            for a, b in zip(nodes[:-1], nodes[1:], strict=True):
                seg = net.path(a, b)
                if seg is None:
                    ok = False
                    break
                edges += seg
                pos.append(len(edges))
            if not ok:
                continue
            index[key] = len(patterns)
            patterns.append({"route": t["route"], "stops": [s[0] for s in st], "edges": edges,
                             "pos": pos})
        out.append({"trip": t, "stops": st, "pattern": index[key]})
    log(f"buses on {d}: {len(out)} trips on {len(patterns)} stopping patterns")
    return patterns, out


def run_bus(m, e, pos, sched_arr, sched_dep, X, rng):
    """One bus along its pattern's edges ``e`` with stop k at edge position pos[k].

    Links take the cars' congested running time (at BUS_SPEED). Queues: the same carry-over rule
    as a car (daysim.traverse), but a bus route is many car trips long, so the bus gets one chance
    of being held at the start of each continuous stretch of links over capacity (one queue),
    judged on the worst link of that stretch. At each stop it dwells DWELL_MIN and does not leave
    before its timetabled time. Returns (minute it enters each edge plus the end, extra seconds
    per edge from traffic, minutes late at each stop, holds, end minute).
    """
    import daysim

    n, n_st = len(e), len(pos)
    enter, extra, late = np.empty(n + 1), np.zeros(n), np.zeros(n_st)
    holds, k, tau, in_queue = [], 1, float(sched_dep[0]), False
    for i in range(n + 1):
        while k < n_st and pos[k] == i:  # stops at this point
            late[k] = tau - sched_arr[k]
            if k < n_st - 1:
                tau = max(tau + DWELL_MIN, sched_dep[k])
            k += 1
        if i == n:
            break
        b = daysim.bin_of(tau)
        x = float(X[b, e[i]])
        if x > 1.0 and not in_queue:
            in_queue = True
            j = i
            while j + 1 < n and X[b, e[j + 1]] > 1.0:
                j += 1
            ahead = e[i:j + 1]
            xb = float(X[b, ahead].max())
            if rng.random() < daysim.tm.CARRY * (1.0 - 1.0 / xb):
                arrive = tau
                tau = daysim.wait_in_queue(X, ahead, tau, rng)
                extra[i] += (tau - arrive) * 60.0
                holds.append((i, arrive, tau))
                x = float(X[daysim.bin_of(tau), e[i]])
        elif x <= 1.0:
            in_queue = False
        enter[i] = tau
        ff = m.t0[e[i]] / BUS_SPEED
        run = ff * (1.0 + 0.15 * min(x, 1.5) ** 4)
        extra[i] += run - ff
        tau += run / 60.0
    enter[n] = tau
    return enter, extra, late, holds, tau


def simulate(ctx, net: Network, data: dict, d: date, X: np.ndarray, rng: np.random.Generator,
             log=print) -> dict:
    """Run every bus trip of date d through the day's link loads X (bins x edges)."""
    import traffic_model as tm

    m = ctx.m
    patterns, trips = day_trips(net, data, d, log)
    timed = data.get("timetable") == "gtfs"
    for pat in patterns:
        e = pat["edges"]
        pat["ps"] = [i for i, k in enumerate(e) if k in net.portswood]
        pat["north"] = bool(tm.heading_north(m, e[pat["ps"][0]])) if pat["ps"] else None
    rec = []
    for tr in trips:
        pat = patterns[tr["pattern"]]
        e, pos, st = pat["edges"], pat["pos"], tr["stops"]
        n_st = len(st)
        free = [0.0]
        for k in range(n_st - 1):  # free-flow schedule, used when there is no timetable
            ff = sum(m.t0[x] for x in e[pos[k]:pos[k + 1]]) / BUS_SPEED / 60
            free.append(free[-1] + ff + DWELL_MIN)
        # st rows: [stop id, arrival s, departure s] (seconds after midnight; -1 when untimed)
        t0_ = st[0][2] / 60 if timed else tr["trip"]["first_min"]
        sched_arr = [s[1] / 60 if timed else t0_ + free[k] for k, s in enumerate(st)]
        sched_dep = [s[2] / 60 if timed else t0_ + free[k] for k, s in enumerate(st)]
        enter, extra, late, holds, t = run_bus(m, e, pos, sched_arr, sched_dep, X, rng)
        ps = pat["ps"]
        r = {"pattern": tr["pattern"], "route": pat["route"], "dep": sched_dep[0],
             "end": float(t), "late_end": float(late[-1]), "extra": float(extra.sum() / 60),
             "enter": enter, "holds": holds, "stop_times": [float(enter[p]) for p in pos]}
        if ps:
            after = next(k for k, p in enumerate(pos) if p > ps[-1])  # first stop past the section
            r.update(ps_extra=float(extra[ps].sum() / 60), ps_enter=float(enter[ps[0]]),
                     ps_late=float(late[after]), ps_dir="northbound" if pat["north"] else "southbound")
        rec.append(r)
    return {"patterns": patterns, "trips": rec, "table": route_table(data, rec)}


def _period(t_min: float) -> str | None:
    h = t_min / 60
    return "am" if 7 <= h < 10 else "pm" if 16 <= h < 19 else "inter" if 10 <= h < 16 else None


def route_table(data: dict, rec: list) -> list[dict]:
    """Per route: trips, modelled extra minutes from congestion and lateness by period, and on
    the Portswood Road section by direction."""
    by = defaultdict(list)
    for r in rec:
        by[r["route"]].append(r)
    rows = []
    for rid, rs in by.items():
        info = data["routes"].get(rid, {})
        row = {"route": rid, "operator": info.get("agency", ""), "name": info.get("short", ""),
               "long": info.get("long", ""), "trips": len(rs), "extra": {}, "late": {},
               "portswood": {}}
        for per in ("am", "inter", "pm"):
            sel = [r for r in rs if _period(r["dep"]) == per]
            if sel:
                row["extra"][per] = round(float(np.mean([r["extra"] for r in sel])), 2)
                row["late"][per] = round(float(np.mean([r["late_end"] for r in sel])), 2)
        for dirn in ("northbound", "southbound"):
            for per in ("am", "pm"):
                sel = [r for r in rs if r.get("ps_dir") == dirn and _period(r["ps_enter"]) == per]
                if sel:
                    row["portswood"][f"{dirn}_{per}"] = {
                        "n": len(sel), "extra": round(float(np.mean([r["ps_extra"] for r in sel])), 2),
                        "late": round(float(np.mean([r["ps_late"] for r in sel])), 2),
                        "late5": round(float(np.mean([r["ps_late"] >= 5 for r in sel])), 3)}
        rows.append(row)
    rows.sort(key=lambda r: (-bool(r["portswood"]), -r["trips"]))
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download and reduce the timetable")
    f.add_argument("--url", default=BODS_URL)
    f.add_argument("--zip", type=Path, help="reduce a GTFS zip you downloaded yourself")
    f.add_argument("--osm", action="store_true", help="use OSM route relations instead of BODS")
    f.add_argument("--download-only", action="store_true",
                   help="download the zip and stop (on a login node; reduce on a compute node)")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        try:
            fetch(args.url, args.zip, args.osm, args.download_only)
        except OSError as err:
            if args.osm or args.zip:
                raise
            print(f"BODS download failed ({err}); falling back to OSM route relations")
            fetch(osm=True)


if __name__ == "__main__":
    main()
