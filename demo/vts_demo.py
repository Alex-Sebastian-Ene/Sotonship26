"""The cruise-day traffic demo run on the real Southampton VTS cruise schedule.

``demo/synthetic_demo.py`` runs the traffic model on the real OpenStreetMap network with an invented
schedule. This script swaps in real inputs and leaves the rest of the demo as it is:

* Real: the ship calls (``sotonship26.data.vts.load_schedule()``: VTS feed, collected at run time,
  lower-berth capacities with sources) and Southampton FC home fixtures
  (``sotonship26.data.clashes``), plus the demo's OSM network and council count calibration.
* Synthetic: trip totals behind general traffic, capacities per lane, mode split, timing and the
  terminal-to-gate guess. The demo's invented roadworks permits are switched off, because they
  would sit on real dates and read as real.

The VTS feed can't be redistributed, so the built page goes to ``demo/out/`` (gitignored) and is
never committed. Build the network once with ``demo/osm_base.py`` (see synthetic_demo.py), then:

    PYTHONPATH=src uv run --no-project --python 3.12 --with numpy --with scipy --with networkx \
        --with pandas --with shapely --with pyproj --with tzdata python demo/vts_demo.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import synthetic_demo as sd  # noqa: E402

from sotonship26.data import vts  # noqa: E402
from sotonship26.data.clashes import load_fixtures  # noqa: E402

# vts.py terminal names -> the demo's short names
SHORT = {
    "Ocean Cruise Terminal": "Ocean",
    "QEII Cruise Terminal": "QEII",
    "Mayflower Cruise Terminal": "Mayflower",
    "City Cruise Terminal": "City",
    "Horizon Cruise Terminal": "Horizon",
}
# School holidays the demo doesn't know past its own horizon. Assumed; check SCC 2026/27 term dates.
CHRISTMAS = (date(2026, 12, 19), date(2027, 1, 4))
DATA_TAG = re.compile(r'(<script id="demo-data" type="application/json">)(.*?)(</script>)', re.S)


def real_schedule(df: pd.DataFrame) -> tuple[dict[date, list], dict[date, list[dict]]]:
    """Calls per day in the demo's ``Call`` shape, plus per-call extras in the same order."""
    outside = df[~df["terminal"].isin(SHORT)]
    if len(outside):
        warnings.warn(
            f"{len(outside)} call(s) at a berth outside the gate table, left out: "
            + ", ".join(sorted(set(outside["ship"]))),
            stacklevel=2,
        )
    rows = []
    for r in df[df["terminal"].isin(SHORT)].itertuples():
        call = sd.Call(
            r.ship,
            SHORT[r.terminal],
            r.arrival.tz_localize(None).to_pydatetime(),
            r.departure.tz_localize(None).to_pydatetime(),
            None if pd.isna(r.passengers) else int(r.passengers),
        )
        rows.append((call, {"confirmed": bool(r.time_confirmed), "pax_src": r.passengers_source}))
    sched: dict[date, list] = {}
    extras: dict[date, list[dict]] = {}
    # The demo's own order, so extras line up with each day's calls in its output.
    for call, extra in sorted(rows, key=lambda x: (x[0].arrival, x[0].ship)):
        sched.setdefault(call.arrival.date(), []).append(call)
        extras.setdefault(call.arrival.date(), []).append(extra)
    return sched, extras


def in_term(d: date) -> bool:
    if CHRISTMAS[0] <= d <= CHRISTMAS[1]:
        return False
    return d.weekday() < 5 and not (sd.HALF_TERM[0] <= d <= sd.HALF_TERM[1])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--refresh", action="store_true", help="fetch the VTS feed again")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "vts-demo.html")
    args, passthrough = parser.parse_known_args(argv)

    df = vts.load_schedule(refresh=args.refresh)
    collected = df["collected_at"].iloc[0].tz_convert(vts.TZ)
    sched, extras = real_schedule(df)
    first, horizon = min(sched), vts.schedule_horizon(df)
    d = first
    while d <= horizon:
        sched.setdefault(d, [])
        d += timedelta(days=1)
    fixtures = load_fixtures()
    fixtures = fixtures[(fixtures["date"] >= first) & (fixtures["date"] <= horizon)]

    sd.make_schedule = lambda rng: sched
    sd.in_term = in_term
    sd.ISSUED = collected.tz_localize(None).to_pydatetime()
    sd.FIRST_DAY, sd.HORIZON, sd.CAL_END = first, horizon, horizon + timedelta(days=7)
    sd.PERMITS = []
    sd.MATCHES = [{"date": r.date.isoformat(), "kickoff": r.kickoff} for r in fixtures.itertuples()]
    sd.main([*passthrough, "--out", str(args.out)])

    # Label the page: which inputs are real, per-call flags, and the day to open on.
    page = args.out.read_text(encoding="utf-8")
    head, body, tail = DATA_TAG.search(page).groups()
    data = json.loads(body)
    for day in data["days"]:
        calls = day.get("calls", [])
        for call, extra in zip(calls, extras.get(date.fromisoformat(day["date"]), []), strict=True):
            call.update(extra)
    clash = [d["date"] for d in data["days"] if d.get("calls") and d.get("match")]
    n_tbc = int((~df["time_confirmed"]).sum())
    data["meta"].update(
        {
            "synthetic": False,
            "schedule_label": "VTS",
            "generator": "demo/vts_demo.py",
            "open_day": clash[0] if clash else None,
            "fixtures": [
                {
                    "date": r.date.isoformat(),
                    "opponent": r.opponent,
                    "competition": r.competition,
                    "source": "southamptonfc.com, 16 Oct 2026",
                }
                for r in fixtures.itertuples()
            ],
            "inputs": {
                "title": "Real ships and real roads, modelled traffic",
                "real": [
                    f"Cruise schedule: Southampton VTS, collected "
                    f"{collected:%a %d %b %Y %H:%M}. {len(df)} calls to {horizon:%d %b %Y}; "
                    f"{n_tbc} still have provisional times (VTS fixes them about 6 days ahead).",
                    "Passengers: each ship's lower-berth capacity from public sources, not the "
                    "booked load.",
                    "Home matches: Southampton FC fixtures, retrieved 16 Oct 2026.",
                    "Road network: OpenStreetMap. Everyday traffic fitted to council counts "
                    "(Portswood, July 2024).",
                ],
                "synthetic": [
                    "Trip totals for general traffic away from the counted roads",
                    "Capacity per lane, mode split, people per vehicle and arrival timing",
                    "Which dock gate each terminal uses (nearest-gate guess)",
                ],
                "note": "Roadworks permits are not loaded, so no works show. Road risk is a "
                "model output, not observed traffic.",
            },
        }
    )
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    args.out.write_text(page.replace(head + body + tail, head + payload + tail), encoding="utf-8")
    print(
        f"Labelled {args.out}: real VTS schedule ({len(df)} calls, {first} to {horizon}), "
        f"{len(fixtures)} home matches, clash days: {', '.join(clash) or 'none'}"
    )


if __name__ == "__main__":
    main()
