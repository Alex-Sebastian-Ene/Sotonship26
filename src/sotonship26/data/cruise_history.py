"""Past Southampton cruise calls, to label training days for the cruise-uplift model (SOT-6).

The backtest needs to know, for every day, whether ships turned around and how many passengers
they carried. Just as important, it needs to know which days we *don't* know about: a day missing
from every source is unknown, not a day without cruises. ``cruise_days`` carries that as
``covered``, and the model must only use covered days.

Sources, checked 2026-10-16 (details in ``notes/cruise-history.md``):

* **Official VTS feed** (``vts.FEED_URL``, ABP). It lists about 15 weeks ahead and drops calls
  once they happen, and the Wayback Machine has no copy of it (CDX returns nothing; archived
  copies of the schedule page loaded the table server-side, so they hold no rows). History
  therefore only builds up from snapshots we take ourselves: ``snapshot_feed`` saves one under
  ``data/raw/cruise_history/vts_snapshots/``. ABP doesn't permit redistribution, so the raw XML
  stays out of git.
* **Third-party schedule sites** were ruled out for automated collection. cruisetimetables.com's
  robots.txt disallows ClaudeBot. CruiseMapper's terms forbid "systematic or automated data
  collection ... without our express written consent" and its archive starts in Jan 2026.
  CruiseDig only shows future months. gangwaze.com and crew-center.com sit behind bot
  challenges (Vercel and Sucuri). We don't get around any of these.
* **Manual import.** History obtained with permission (from the council, ABP, or a site that
  agrees) goes in ``data/raw/cruise_history/manual_calls.csv``. The days it fully covers go in
  ``manual_coverage.csv``. Both are gitignored and both formats are documented on
  ``load_manual``.

Feed parsing is ``vts.parse_feed``. ``vts.py`` and ``ship_capacity.csv`` are copied unchanged
from Ed's PR #5 (branch ``edward/SOT-11-vts-schedule``) so this branch runs on its own; drop the
copies once that PR merges. Historic ships missing from ``ship_capacity.csv`` can be added to
``ship_capacity_history.csv`` (same columns), which is read on top of it.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from sotonship26.data import vts

TZ = vts.TZ
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "cruise_history"
SNAPSHOT_DIR = RAW_DIR / "vts_snapshots"
MANUAL_CALLS = RAW_DIR / "manual_calls.csv"
MANUAL_COVERAGE = RAW_DIR / "manual_coverage.csv"
CAPACITY_HISTORY_CSV = Path(__file__).resolve().parent / "ship_capacity_history.csv"

WESTERN_TERMINALS = {
    "City Cruise Terminal",
    "Horizon Cruise Terminal",
    "Mayflower Cruise Terminal",
}
EASTERN_TERMINALS = {"QEII Cruise Terminal", "Ocean Cruise Terminal"}

CALL_COLUMNS = [
    "ship",
    "imo",
    "arrival",
    "departure",
    "berth",
    "terminal",
    "dock_side",
    "turnaround",
    "passengers",
    "passengers_source",
    "source",
    "snapshot_ts",
]
DAY_COLUMNS = [
    "date",
    "n_calls",
    "pax_total",
    "pax_western",
    "pax_eastern",
    "pax_unknown",
    "first_arrival",
    "last_departure",
    "covered",
]

Window = tuple[date, date]


def dock_side(terminal: str) -> str:
    """'western' for City/Horizon/Mayflower, 'eastern' for QEII/Ocean, else 'unknown'."""
    if terminal in WESTERN_TERMINALS:
        return "western"
    if terminal in EASTERN_TERMINALS:
        return "eastern"
    return "unknown"


def load_capacities() -> dict[str, tuple[int, str]]:
    """IMO -> (lower berth, source): Ed's ``ship_capacity.csv`` plus our history additions."""
    caps = vts.load_capacities()
    if CAPACITY_HISTORY_CSV.exists():
        extra = pd.read_csv(CAPACITY_HISTORY_CSV, dtype={"imo": str})
        for row in extra.dropna(subset=["lower_berth"]).itertuples():
            caps.setdefault(row.imo, (int(row.lower_berth), "lower_berth_history"))
    return caps


def snapshot_feed(raw_dir: str | Path = SNAPSHOT_DIR) -> Path:
    """Save today's VTS feed so history accumulates. Run it daily during the season."""
    return vts.fetch_feed(raw_dir)


def snapshot_window(calls: pd.DataFrame, collected: pd.Timestamp) -> Window:
    """Days a snapshot speaks for: from the day it was taken to its last listed arrival.

    Inside that window, a day with no listed call really had no call (as far as ABP knew then).
    """
    start = pd.Timestamp(collected).tz_convert(TZ).date()
    end = calls["arrival"].max().date() if len(calls) else start
    return start, end


def load_snapshots(
    raw_dir: str | Path = SNAPSHOT_DIR,
    capacities: dict[str, tuple[int, str]] | None = None,
) -> tuple[pd.DataFrame, list[Window]]:
    """Every saved VTS snapshot, unioned, with the latest snapshot's version of each visit."""
    capacities = load_capacities() if capacities is None else capacities
    frames, windows = [], []
    for path in sorted(Path(raw_dir).glob("sotcruiseship_*.xml")):
        collected = vts.collected_at(path)
        df = vts.parse_feed(path, collected, capacities=capacities)
        frames.append(df)
        windows.append(snapshot_window(df, collected))
    if not frames:
        return _empty_calls(), []
    return union_snapshots(frames), windows


def union_snapshots(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge parsed snapshots, keeping each visit from the newest snapshot that lists it.

    Times are confirmed only close to the call, so the newest version is the most accurate.
    """
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("collected_at").drop_duplicates("visit_id", keep="last")
    out = pd.DataFrame(
        {
            "ship": df["ship"],
            "imo": df["imo"],
            "arrival": df["arrival"],
            "departure": df["departure"],
            "berth": df["berth"],
            "terminal": df["terminal"],
            "dock_side": df["terminal"].map(dock_side),
            # The feed has no call type; Southampton calls are overwhelmingly turnarounds.
            "turnaround": True,
            "passengers": df["passengers"],
            "passengers_source": df["passengers_source"],
            "source": "vts_feed",
            "snapshot_ts": df["collected_at"],
        }
    )
    return out[CALL_COLUMNS].sort_values(["arrival", "ship"]).reset_index(drop=True)


def load_manual(
    calls_path: str | Path = MANUAL_CALLS,
    coverage_path: str | Path = MANUAL_COVERAGE,
    capacities: dict[str, tuple[int, str]] | None = None,
) -> tuple[pd.DataFrame, list[Window]]:
    """History obtained with permission, entered by hand.

    ``manual_calls.csv`` needs columns ``ship, arrival, source`` (arrival: ISO local time, or a
    date). It can also have ``imo, departure, berth, terminal, passengers, source_url``.
    ``manual_coverage.csv`` has ``start, end, source``: the date ranges the source lists *every*
    call for. Without coverage rows, manual calls still count but no day is marked covered.
    """
    calls_path, coverage_path = Path(calls_path), Path(coverage_path)
    if not calls_path.exists():
        return _empty_calls(), []
    capacities = load_capacities() if capacities is None else capacities
    raw = pd.read_csv(calls_path, dtype={"imo": str, "berth": str})
    arrival = pd.to_datetime(raw["arrival"], format="ISO8601").dt.tz_localize(TZ)
    if "departure" in raw:
        departure = pd.to_datetime(raw["departure"], format="ISO8601").dt.tz_localize(TZ)
    else:
        departure = arrival + pd.Timedelta(hours=11)
    berth = raw["berth"] if "berth" in raw else pd.Series("", index=raw.index)
    berth = berth.fillna("")
    terminal = raw["terminal"] if "terminal" in raw else berth.map(vts.BERTH_TERMINAL)
    terminal = terminal.fillna(vts.UNKNOWN_TERMINAL)
    imo = raw["imo"].fillna("") if "imo" in raw else pd.Series("", index=raw.index)
    passengers, pax_source = _manual_passengers(raw, imo, capacities)
    out = pd.DataFrame(
        {
            "ship": raw["ship"].str.upper(),
            "imo": imo,
            "arrival": arrival,
            "departure": departure,
            "berth": berth,
            "terminal": terminal,
            "dock_side": terminal.map(dock_side),
            "turnaround": True,
            "passengers": passengers,
            "passengers_source": pax_source,
            "source": raw["source"],
            "snapshot_ts": pd.NaT,
        }
    )
    windows: list[Window] = []
    if coverage_path.exists():
        cov = pd.read_csv(coverage_path)
        windows = [
            (pd.Timestamp(r.start).date(), pd.Timestamp(r.end).date()) for r in cov.itertuples()
        ]
    return out[CALL_COLUMNS], windows


def _manual_passengers(
    raw: pd.DataFrame, imo: pd.Series, capacities: dict[str, tuple[int, str]]
) -> tuple[pd.Series, pd.Series]:
    """Passengers as given; else lower berth by IMO; else missing."""
    given = raw["passengers"] if "passengers" in raw else pd.Series(pd.NA, index=raw.index)
    from_cap = imo.map(lambda i: capacities.get(i, (pd.NA, "missing"))[0])
    cap_src = imo.map(lambda i: capacities.get(i, (pd.NA, "missing"))[1])
    passengers = given.where(given.notna(), from_cap).astype("Int64")
    source = pd.Series("manual", index=raw.index).where(given.notna(), cap_src)
    return passengers, source


def _empty_calls() -> pd.DataFrame:
    return pd.DataFrame(columns=CALL_COLUMNS)


def load_calls(
    start: date,
    end: date,
    refresh: bool = False,
    raw_dir: str | Path = RAW_DIR,
) -> pd.DataFrame:
    """All known calls arriving between ``start`` and ``end`` (inclusive), columns ``CALL_COLUMNS``.

    ``refresh`` takes a new VTS snapshot first. The result carries ``attrs["windows"]``, the
    covered date ranges, and ``attrs["start"]``/``attrs["end"]`` for ``cruise_days``.
    """
    raw_dir = Path(raw_dir)
    snap_dir = raw_dir / "vts_snapshots"
    if refresh:
        snapshot_feed(snap_dir)
    vts_calls, vts_windows = load_snapshots(snap_dir)
    manual_calls, manual_windows = load_manual(
        raw_dir / "manual_calls.csv", raw_dir / "manual_coverage.csv"
    )
    frames = [f for f in (vts_calls, manual_calls) if len(f)]
    calls = pd.concat(frames, ignore_index=True) if frames else _empty_calls()
    if len(calls):
        # A visit in both sources: keep the official feed's row.
        calls["_day"] = calls["arrival"].dt.date
        calls["_rank"] = (calls["source"] != "vts_feed").astype(int)
        calls = calls.sort_values("_rank").drop_duplicates(["ship", "_day"], keep="first")
        calls = calls[(calls["_day"] >= start) & (calls["_day"] <= end)]
        calls = calls.drop(columns=["_day", "_rank"]).sort_values(["arrival", "ship"])
    calls = calls.reset_index(drop=True)
    calls.attrs.update(windows=vts_windows + manual_windows, start=start, end=end)
    return calls


def cruise_days(
    calls: pd.DataFrame,
    start: date | None = None,
    end: date | None = None,
    windows: list[Window] | None = None,
) -> pd.DataFrame:
    """One row per date from ``start`` to ``end``, including days with no calls.

    ``covered`` is True only when some source lists every call for that day. Use only covered
    days as training data: an uncovered zero means "unknown", not "no cruise".
    """
    start = start or calls.attrs["start"]
    end = end or calls.attrs["end"]
    windows = calls.attrs.get("windows", []) if windows is None else windows
    days = pd.date_range(start, end, freq="D").date
    out = pd.DataFrame({"date": days})
    if len(calls):
        c = calls.assign(date=calls["arrival"].dt.date)
        pax = c["passengers"].astype("Float64")
        g = c.assign(
            pax=pax,
            pax_w=pax.where(c["dock_side"] == "western", 0),
            pax_e=pax.where(c["dock_side"] == "eastern", 0),
            pax_u=pax.where(c["dock_side"] == "unknown", 0),
        ).groupby("date")
        agg = pd.DataFrame(
            {
                "n_calls": g.size(),
                "pax_total": g["pax"].sum(min_count=1),
                "pax_western": g["pax_w"].sum(),
                "pax_eastern": g["pax_e"].sum(),
                "pax_unknown": g["pax_u"].sum(),
                "first_arrival": g["arrival"].min(),
                "last_departure": g["departure"].max(),
            }
        ).reset_index()
        out = out.merge(agg, on="date", how="left")
    else:
        for col in DAY_COLUMNS[1:-1]:
            out[col] = pd.NA
    out["n_calls"] = out["n_calls"].fillna(0).astype(int)
    pax_cols = ["pax_total", "pax_western", "pax_eastern", "pax_unknown"]
    for col in pax_cols:
        out[col] = out[col].astype("Float64").fillna(0)
    # a day with any call of unknown size has unknown passengers, not fewer passengers
    if len(calls):
        unsized = set(calls.loc[calls["passengers"].isna(), "arrival"].dt.date)
        out.loc[out["date"].isin(unsized), pax_cols] = pd.NA
    out["covered"] = [any(a <= d <= b for a, b in windows) for d in out["date"]]
    return out[DAY_COLUMNS]


def summarise(calls: pd.DataFrame, days: pd.DataFrame) -> str:
    """Calls per year, cruise days per month and coverage, for the CLI."""
    lines = [f"{len(calls)} calls, {calls['ship'].nunique() if len(calls) else 0} ships"]
    if len(calls):
        per_year = calls["arrival"].dt.year.value_counts().sort_index()
        lines.append("calls per year: " + ", ".join(f"{y}: {n}" for y, n in per_year.items()))
        missing = calls["passengers"].isna().sum()
        lines.append(f"calls without a passenger figure: {missing}")
    cov = days["covered"].mean() * 100 if len(days) else 0.0
    lines.append(f"coverage: {days['covered'].sum()} of {len(days)} days ({cov:.1f}%)")
    cruise = days[days["covered"] & (days["n_calls"] > 0)]
    if len(cruise):
        month = pd.to_datetime(cruise["date"]).dt.to_period("M").value_counts().sort_index()
        lines.append("cruise days per month (covered): " + ", ".join(
            f"{p}: {n}" for p, n in month.items()
        ))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Build the past cruise-call table (SOT-6).")
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    p.add_argument("--snapshot", action="store_true", help="save today's VTS feed first")
    args = p.parse_args(argv)
    calls = load_calls(args.start, args.end, refresh=args.snapshot)
    days = cruise_days(calls)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    calls.to_csv(RAW_DIR / "calls.csv", index=False)
    days.to_csv(RAW_DIR / "days.csv", index=False)
    print(f"{args.start} to {args.end}")
    print(summarise(calls, days))
    print(f"wrote {RAW_DIR / 'calls.csv'} and {RAW_DIR / 'days.csv'}")


if __name__ == "__main__":
    main()


__all__ = [
    "CALL_COLUMNS",
    "DAY_COLUMNS",
    "cruise_days",
    "dock_side",
    "load_calls",
    "load_manual",
    "load_snapshots",
    "snapshot_feed",
    "union_snapshots",
]
