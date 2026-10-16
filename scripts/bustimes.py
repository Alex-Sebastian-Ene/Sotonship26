"""Collect live bus lateness around Southampton from bustimes.org and export it to the frontend.

    uv run python scripts/bustimes.py collect --minutes 120 --every 60
    uv run python scripts/bustimes.py export

``collect`` polls the live vehicle positions in the city-centre box, matches each bus to its
timetabled trip and appends one row per sighting to data/raw/buses/lateness-<date>.csv (gitignored;
trips are cached under data/cache/bustimes). Leave it running through a cruise morning and an
ordinary one so the two can be compared.

``export`` turns every collected CSV into frontend/data/buses.observed.js, in the same shape as the
synthetic frontend/data/buses.js: lateness by line and hour, and each line's stops snapped to the
frontend's street graph. Point the import in frontend/js/core/transit.js at it to use real data.
Headways and service hours are estimated from the trips seen, so a short collection underestimates
both; the export prints what it inferred.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sotonship26.data.buses import (
    LONDON,
    SOUTHAMPTON_BBOX,
    BustimesClient,
    collect_once,
    delay_profiles,
    lateness_from_row,
    lateness_to_row,
    parse_trip,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "buses"
CACHE = ROOT / "data" / "cache" / "bustimes"
GRAPH = ROOT / "frontend" / "data" / "southampton.js"
OUT = ROOT / "frontend" / "data" / "buses.observed.js"
SNAP_M = 200
NODE_LINE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)",\s*kind:\s*"(?P<kind>[^"]+)"'
    r".*?lat:\s*(?P<lat>-?[\d.]+),\s*lon:\s*(?P<lon>-?[\d.]+)"
)


def cmd_collect(args) -> None:
    client = BustimesClient(cache_dir=CACHE, min_interval_s=args.min_interval)
    RAW.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + args.minutes * 60
    while True:
        started = time.monotonic()
        try:
            rows = collect_once(client, SOUTHAMPTON_BBOX)
        except OSError as e:  # network hiccup: log it and try again next round
            print(f"{datetime.now(LONDON):%H:%M:%S} request failed: {e}", file=sys.stderr)
            rows = []
        if rows:
            path = RAW / f"lateness-{datetime.now(LONDON):%Y-%m-%d}.csv"
            new = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(lateness_to_row(rows[0])))
                if new:
                    w.writeheader()
                w.writerows(lateness_to_row(r) for r in rows)
        late = [r.delay_s / 60 for r in rows]
        mean = sum(late) / len(late) if late else float("nan")
        print(f"{datetime.now(LONDON):%H:%M:%S} {len(rows)} buses matched, mean {mean:+.1f} min")
        if time.monotonic() >= end:
            break
        time.sleep(max(0.0, args.every - (time.monotonic() - started)))


def graph_nodes() -> list[tuple[str, float, float]]:
    out = []
    for line in GRAPH.read_text(encoding="utf-8").splitlines():
        m = NODE_LINE.search(line)
        if m and m["kind"] in ("junction", "gate", "exit"):
            out.append((m["id"], float(m["lat"]), float(m["lon"])))
    return out


def snap(lat: float, lon: float, nodes) -> str | None:
    k = 111320 * math.cos(math.radians(lat))
    best = min(nodes, key=lambda n: ((n[1] - lat) * 110540) ** 2 + ((n[2] - lon) * k) ** 2)
    d = math.hypot((best[1] - lat) * 110540, (best[2] - lon) * k)
    return best[0] if d <= SNAP_M else None


def cmd_export(args) -> None:
    rows = []
    for path in sorted(RAW.glob("lateness-*.csv")):
        with path.open(encoding="utf-8") as f:
            rows += [lateness_from_row(r) for r in csv.DictReader(f)]
    if not rows:
        sys.exit(f"No collected rows in {RAW}; run `collect` first.")

    profiles = delay_profiles(rows, min_n=args.min_n)
    nodes = graph_nodes()

    # One representative trip per line: the one whose stops snap to the most graph nodes.
    trips_seen: dict[str, set[str]] = defaultdict(set)
    hours_seen: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        trips_seen[r.line].add(r.trip_id)
        hours_seen[r.line][r.observed_at.astimezone(LONDON).hour] += 1
    lines = []
    for line, trip_ids in sorted(trips_seen.items()):
        best = None
        for tid in trip_ids:
            f = CACHE / "trips" / f"{tid}.json"
            if not f.exists():
                continue
            trip = parse_trip(
                json.loads(f.read_text(encoding="utf-8")), datetime.now(LONDON).date()
            )
            if not trip:
                continue
            seq = []
            for s in trip.stops:
                n = snap(s.lat, s.lon, nodes)
                if n and (not seq or seq[-1] != n):
                    seq.append(n)
            if len(seq) >= 2 and (not best or len(seq) > len(best[0])):
                best = (seq, trip)
        if not best:
            print(f"skip {line}: no trip passes within {SNAP_M} m of two graph nodes")
            continue
        seq, trip = best
        hours = sorted(hours_seen[line])
        span_h = max(1, hours[-1] - hours[0] + 1)
        # Distinct trips seen per hour, halved for two directions, gives a rough headway.
        headway = max(5, min(60, round(60 / max(0.5, len(trip_ids) / span_h / 2))))
        lines.append(
            {
                "id": line,
                "name": f"{trip.operator} {line}".strip(),
                "from": trip.stops[0].name,
                "to": trip.stops[-1].name,
                "stops": seq,
                "headwayMin": headway,
                "first": f"{hours[0]:02d}:00",
                "last": f"{hours[-1]:02d}:59",
            }
        )
        print(
            f"{line}: {len(seq)} graph stops, headway ~{headway} min, seen {hours[0]}-{hours[-1]}h"
        )

    profile_js: dict[str, dict] = defaultdict(dict)
    for p in profiles:
        profile_js[p.line][p.hour] = {"mean": round(p.mean_min, 1), "p90": round(p.p90_min, 1)}
    days = sorted({r.observed_at.astimezone(LONDON).date().isoformat() for r in rows})
    meta = {
        "source": f"bustimes.org positions matched to timetabled trips ({len(rows)} sightings)",
        "collected": f"{days[0]} to {days[-1]}" if len(days) > 1 else days[0],
        "licence": "Derived from Bus Open Data Service data (OGL v3.0) via bustimes.org",
        "synthetic": False,
    }
    OUT.write_text(
        "// GENERATED by scripts/bustimes.py export. Do not edit by hand.\n\n"
        f"export const BUS_META = {json.dumps(meta, indent=2)};\n\n"
        f"export const BUS_LINES = {json.dumps(lines, indent=2)};\n\n"
        "export const DEFAULT_DELAY = { mean: 1, p90: 4 };\n\n"
        f"export const DELAY_PROFILE = {json.dumps(profile_js, indent=2)};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}: {len(lines)} lines, {len(profiles)} line-hours")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="poll bustimes.org and append lateness rows")
    c.add_argument("--minutes", type=float, default=60, help="how long to keep polling")
    c.add_argument("--every", type=float, default=60, help="seconds between polls")
    c.add_argument("--min-interval", type=float, default=1.5, help="seconds between requests")
    c.set_defaults(fn=cmd_collect)
    e = sub.add_parser("export", help="write frontend/data/buses.observed.js")
    e.add_argument("--min-n", type=int, default=5, help="sightings needed per line-hour")
    e.set_defaults(fn=cmd_export)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
