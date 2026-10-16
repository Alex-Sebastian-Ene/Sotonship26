"""Southampton VTS cruise schedule, fetched from the public XML feed behind the VTS cruise page.

The cruise ship schedule page (``SOURCE_PAGE``) loads ``FEED_URL``: every planned cruise call with
ship, IMO number, berth, arrival and departure, usually three months or more ahead. ABP owns the
content and does not permit redistribution, so the raw XML is cached under ``data/raw/vts/``
(gitignored) and never committed. ``collected_at`` is when we fetched it, taken from the cache
file name.

VTS fixes exact times only within about six days of a call. Before that a time reads "AM", "PM"
or "TBA"; those get a typical turnaround time from ``VAGUE_TIMES`` and ``time_confirmed=False``.
The feed has no passenger numbers. ``passengers`` comes from ``ship_capacity.csv`` (lower-berth
capacity: a fact per ship with its public source, gathered by the research desk in SOT-17), matched
on IMO. ``passengers_source`` is "lower_berth", "lower_berth_uncertain" (sources disagree or the
IMO wasn't confirmed), or "missing" when the ship isn't listed. Capacity is not actual load; the
demand model samples a load factor on top.
"""

from __future__ import annotations

import re
import sys
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from sotonship26.data.cruise import CruiseCall

FEED_URL = "https://www.southamptonvts.co.uk/xml/sotcruiseship.xml"
SOURCE_PAGE = (
    "https://www.southamptonvts.co.uk/live_information/"
    "shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/"
)
USER_AGENT = "sotonship26/0.1 (SotonShip 2026 hackathon; cruise-day traffic forecast)"
TZ = "Europe/London"

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "vts"
CAPACITY_CSV = Path(__file__).resolve().parent / "ship_capacity.csv"

# Berth -> terminal, as listed on the VTS cruise ship schedule page (checked 16 Oct 2026).
BERTH_TERMINAL = {
    "38/9": "QEII Cruise Terminal",
    "46": "Ocean Cruise Terminal",
    "101": "City Cruise Terminal",
    "102": "Horizon Cruise Terminal",
    "106": "Mayflower Cruise Terminal",
}
UNKNOWN_TERMINAL = "unknown"

# Stand-in clock times for calls VTS hasn't fixed yet. Confirmed calls in the 16 Oct feed arrive
# 05:45-07:30 (mostly 06:00-06:15) and sail 16:00-20:30 (most often 17:00).
VAGUE_TIMES = {
    "arrival": {"AM": time(6, 0), "PM": time(13, 0), "TBA": time(6, 0)},
    "departure": {"AM": time(11, 0), "PM": time(17, 0), "TBA": time(17, 0)},
}

COLUMNS = [
    "ship",
    "terminal",
    "arrival",
    "departure",
    "passengers",
    "collected_at",
    "berth",
    "imo",
    "visit_id",
    "time_confirmed",
    "passengers_source",
]

_CACHE_NAME = re.compile(r"sotcruiseship_(\d{8}T\d{6}Z)\.xml$")


def fetch_feed(raw_dir: str | Path = RAW_DIR, url: str = FEED_URL, timeout: float = 30) -> Path:
    """Download the feed once and cache it as ``sotcruiseship_<UTC time>.xml``; return the path."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    ET.fromstring(body)  # refuse to cache an error page
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"sotcruiseship_{stamp}.xml"
    path.write_bytes(body)
    return path


def collected_at(path: str | Path) -> pd.Timestamp:
    """When a cached feed was fetched: from its file name, else its modification time."""
    path = Path(path)
    m = _CACHE_NAME.search(path.name)
    if m:
        return pd.Timestamp(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)


def latest_cached(raw_dir: str | Path = RAW_DIR) -> Path | None:
    files = sorted(Path(raw_dir).glob("sotcruiseship_*.xml"))
    return files[-1] if files else None


def _parse_time(value: str | None, kind: str) -> tuple[pd.Timestamp, bool]:
    """'17-Oct-26 05:45' -> (local time, True); '21-Oct-26 TBA' -> (stand-in time, False)."""
    day_part, _, clock = (value or "").strip().partition(" ")
    day = datetime.strptime(day_part, "%d-%b-%y").date()
    clock = clock.strip().upper()
    try:
        t, confirmed = datetime.strptime(clock, "%H:%M").time(), True
    except ValueError:
        t, confirmed = VAGUE_TIMES[kind].get(clock, VAGUE_TIMES[kind]["TBA"]), False
    return pd.Timestamp(datetime.combine(day, t)).tz_localize(TZ), confirmed


def load_capacities(path: str | Path = CAPACITY_CSV) -> dict[str, tuple[int, str]]:
    """IMO -> (lower-berth capacity, passengers_source), from ``ship_capacity.csv``."""
    path = Path(path)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"imo": str})
    return {
        row.imo: (
            int(row.lower_berth),
            "lower_berth_uncertain" if row.capacity_uncertain else "lower_berth",
        )
        for row in df.itertuples()
        if pd.notna(row.lower_berth)
    }


def parse_feed(
    xml: str | bytes | Path,
    collected: pd.Timestamp | datetime,
    capacities: dict[str, tuple[int, str]] | None = None,
) -> pd.DataFrame:
    """Turn the VTS XML into one row per call, sorted by arrival. See ``COLUMNS``."""
    root = ET.parse(xml).getroot() if isinstance(xml, Path) else ET.fromstring(xml)
    capacities = load_capacities() if capacities is None else capacities
    collected = pd.Timestamp(collected).tz_convert(TZ)
    rows = []
    for r in root.iter("row"):
        f = {c.tag: (c.text or "").strip() for c in r}
        arrival, arr_ok = _parse_time(f.get("arrival"), "arrival")
        departure, dep_ok = _parse_time(f.get("departure"), "departure")
        if departure <= arrival:  # a stand-in time can land before a confirmed one
            departure = arrival + timedelta(hours=10)
            dep_ok = False
        imo = f.get("lloyds_no.", "")
        passengers, passengers_source = capacities.get(imo, (None, "missing"))
        berth = f.get("berth", "")
        rows.append(
            {
                "ship": f.get("ship_name", ""),
                "terminal": BERTH_TERMINAL.get(berth, UNKNOWN_TERMINAL),
                "arrival": arrival,
                "departure": departure,
                "passengers": passengers,
                "collected_at": collected,
                "berth": berth,
                "imo": imo,
                "visit_id": f.get("visit_id", ""),
                "time_confirmed": arr_ok and dep_ok,
                "passengers_source": passengers_source,
            }
        )
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["passengers"] = df["passengers"].astype("Int64")
    df["time_confirmed"] = df["time_confirmed"].astype(bool)
    df = df.drop_duplicates("visit_id", keep="last")
    return df.sort_values(["arrival", "ship"]).reset_index(drop=True)


def load_schedule(
    path: str | Path | None = None,
    refresh: bool = False,
    max_age: timedelta = timedelta(hours=12),
    raw_dir: str | Path = RAW_DIR,
) -> pd.DataFrame:
    """The VTS cruise schedule as a DataFrame (columns in ``COLUMNS``, times tz-aware London).

    With ``path``, parse that cached file. Otherwise use the newest cache in ``raw_dir``, fetching
    a fresh copy if there is none, it is older than ``max_age``, or ``refresh`` is set. If the
    fetch fails and a cache exists, fall back to it with a warning; ``collected_at`` then shows
    its age, so the app can show the stale-data banner.
    """
    if path is None:
        path = latest_cached(raw_dir)
        too_old = path is None or pd.Timestamp.now(UTC) - collected_at(path) > max_age
        if refresh or too_old:
            try:
                path = fetch_feed(raw_dir)
            except (OSError, ET.ParseError) as e:
                if path is None:
                    raise
                warnings.warn(f"VTS fetch failed ({e}); using cache {path.name}", stacklevel=2)
    path = Path(path)
    return parse_feed(path, collected_at(path))


def schedule_horizon(df: pd.DataFrame) -> date:
    """Last day the schedule covers. Forecasts beyond it are refused."""
    return df["arrival"].max().date()


def to_cruise_calls(df: pd.DataFrame, day: date | None = None) -> list[CruiseCall]:
    """Adapt to the ``CruiseCall`` list the demand code takes (naive London times).

    Calls without a passenger figure are skipped with a warning, not guessed.
    """
    if day is not None:
        df = df[df["arrival"].dt.date == day]
    missing = df[df["passengers"].isna()]
    if len(missing):
        warnings.warn(
            f"{len(missing)} call(s) skipped, no passenger figure: "
            + ", ".join(sorted(set(missing["ship"]))),
            stacklevel=2,
        )
    return [
        CruiseCall(
            ship=row.ship,
            terminal=row.terminal,
            arrival=row.arrival.tz_localize(None).to_pydatetime(),
            departure=row.departure.tz_localize(None).to_pydatetime(),
            passengers=int(row.passengers),
        )
        for row in df.dropna(subset=["passengers"]).itertuples()
    ]


def main() -> None:
    df = load_schedule(refresh="--refresh" in sys.argv)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)
    print(f"Source: {SOURCE_PAGE}")
    print(f"Collected: {df['collected_at'].iloc[0]:%Y-%m-%d %H:%M %Z}")
    print(
        f"{len(df)} calls, {df['ship'].nunique()} ships, "
        f"{df['arrival'].min():%d %b %Y} to {schedule_horizon(df):%d %b %Y}; "
        f"{(~df['time_confirmed']).sum()} with unconfirmed times, "
        f"{df['passengers'].isna().sum()} without a passenger figure"
    )
    print(df[["ship", "terminal", "arrival", "departure", "passengers", "time_confirmed"]].head(15))


if __name__ == "__main__":
    main()
