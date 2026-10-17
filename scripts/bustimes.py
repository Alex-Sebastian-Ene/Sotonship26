"""Collect observed bus lateness around Southampton from bustimes.org and summarise it for the page.

    uv run --no-project --python 3.12 python scripts/bustimes.py collect --minutes 480
    uv run --no-project --python 3.12 python scripts/bustimes.py export

``collect`` polls the live vehicle positions in the city box every ``--every`` seconds (at least
30) and appends one row per bus to data/raw/buses/bustimes-<date>.csv (gitignored). Run it through
a cruise turnaround and an ordinary day so the two can be compared.

``export`` reads every collected day and writes demo/out/bus_lateness.json: lateness per line and
hour, and per area (docks, city centre, Portswood) and hour, with the collection window and counts.
demo/page_extras.py puts it on the forecast page. See src/sotonship26/data/bus_lateness.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sotonship26.data.bus_lateness import (  # noqa: E402
    AREAS,
    LONDON,
    SOUTHAMPTON_BBOX,
    BustimesClient,
    append_csv,
    clean,
    profiles,
    read_csv,
)

RAW = ROOT / "data" / "raw" / "buses"
OUT = ROOT / "demo" / "out" / "bus_lateness.json"


def cmd_collect(args) -> None:
    client = BustimesClient(min_interval_s=max(30.0, args.every))
    end = time.monotonic() + args.minutes * 60
    while time.monotonic() < end:
        started = time.monotonic()
        try:
            rows = client.vehicles(SOUTHAMPTON_BBOX)
            day = datetime.now(LONDON).date().isoformat()
            n = append_csv(RAW / f"bustimes-{day}.csv", rows)
            late = [r.delay_s for r in rows if r.delay_s is not None]
            mean = sum(late) / len(late) / 60 if late else float("nan")
            print(f"{datetime.now(LONDON):%H:%M:%S} {n} buses, mean {mean:+.1f} min", flush=True)
        except Exception as err:  # keep collecting through a dropped request
            print(f"{datetime.now(LONDON):%H:%M:%S} failed: {err}", flush=True)
        time.sleep(max(0.0, args.every - (time.monotonic() - started)))


def summarise(rows: list) -> dict:
    coll = sorted(r.collected_at for r in rows)
    kept, left_out = clean(rows)
    return {
        "collected_from": coll[0].astimezone(LONDON).isoformat(timespec="minutes"),
        "collected_to": coll[-1].astimezone(LONDON).isoformat(timespec="minutes"),
        "polls": len({r.collected_at for r in rows}),
        "sightings": len(rows),
        "kept": len(kept),
        "left_out": left_out,
        "journeys": len({r.journey or r.vehicle for r in kept}),
        "all": [asdict(p) for p in profiles(kept, by="all", min_n=1, hourly=False)],
        "lines": [asdict(p) for p in profiles(kept, by="line")],
        "areas": [asdict(p) for p in profiles(kept, by="area")],
        "day_lines": [asdict(p) for p in profiles(kept, by="line", min_n=5, hourly=False)],
    }


def cmd_export(args) -> None:
    days = {}
    for path in sorted(RAW.glob("bustimes-*.csv")):
        rows = read_csv(path)
        if rows:
            days[path.stem.removeprefix("bustimes-")] = summarise(rows)
    data = {
        "source": "bustimes.org live vehicle positions (Bus Open Data Service, OGL v3.0); delay "
                  "against the timetable as bustimes.org reports it, less readings that can't be "
                  "lateness (buses laid over, stale positions, buses switched to another trip)",
        "made": datetime.now(LONDON).isoformat(timespec="minutes"),
        "areas": {k: list(v) for k, v in AREAS.items()},
        "days": days,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data), encoding="utf-8")
    for d, s in days.items():
        print(f"{d}: {s['collected_from'][11:]}-{s['collected_to'][11:]}, {s['polls']} polls, "
              f"{s['journeys']} journeys; kept {s['kept']} of {s['sightings']} readings, left out "
              f"{s['left_out']}")
        for p in s["all"]:
            print(f"  all buses: median {p['p50_min']:+5.1f}  mean {p['mean_min']:+5.1f}  "
                  f"p90 {p['p90_min']:+5.1f}  >=5 min {p['share_over_5_min']:.0%}")
        for p in s["areas"]:
            print(f"  {p['key']:12s} {p['hour']:02d}:00  n {p['n']:3d}  median {p['p50_min']:+5.1f}"
                  f"  p90 {p['p90_min']:+5.1f}  >=5 min {p['share_over_5_min']:.0%}")
    print(f"wrote {args.out}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--minutes", type=float, default=60)
    c.add_argument("--every", type=float, default=60, help="seconds between polls (min 30)")
    e = sub.add_parser("export")
    e.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    {"collect": cmd_collect, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
