"""Southampton VTS planned ship movements and ships alongside, for port freight (SOT-24).

The VTS shipping-movements pages load two public XML feeds (robots.txt allows them):

* ``EXTRACT_URL`` (``sotextract.xml``): planned movements for about the next five days. One row per
  movement: ship, type ("Container Carrier (UCC)", "Ro/Ro (URR)", ...), ``eta_etd``,
  ``voyage_type`` (A = arrival from sea, D = departure to sea, M = move between berths inside the
  port), ``origin`` and ``destination`` (a berth for the port end, a place for the sea end), IMO
  (``lloyds_no.``), gt, dwt, loa, agent. Movements that already happened today are gone.
* ``BERTHED_URL`` (``sotberthed.xml``): ships alongside now, with berth, actual arrival time and
  estimated departure time.

ABP owns the content and does not permit redistribution, so the raw XML is cached under
``data/raw/vts_freight/`` (gitignored) and never committed; only aggregates leave this machine,
credited "Southampton VTS, ABP". ``collected_at`` is when we fetched it (UTC), from the file name.

``category`` groups the VTS type codes: ``container`` and ``roro`` are the lorry-relevant ones.
``area`` puts a berth in a dock area from public berth numbering (see ``berth_area``).
``daily_freight_calls`` turns the union of saved snapshots into one row per day: container and
ro-ro arrivals and departures and their gross tonnage, a per-day predictor of port lorry demand.

History only builds up from snapshots we take. Every 6 hours is enough (crontab, not installed):

    0 */6 * * * cd /path/to/Sotonship26 && uv run python -m sotonship26.data.vts_freight --snapshot

See ``notes/vts-freight.md`` for the type codes seen, the berth mapping and the limits.
"""

from __future__ import annotations

import argparse
import re
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd

from sotonship26.data.vts import TZ, USER_AGENT

EXTRACT_URL = "https://www.southamptonvts.co.uk/xml/sotextract.xml"
BERTHED_URL = "https://www.southamptonvts.co.uk/xml/sotberthed.xml"
SOURCE_PAGE = (
    "https://www.southamptonvts.co.uk/live_information/"
    "shipping_movements_and_cruise_ship_schedule/"
)
CREDIT = "Southampton VTS, ABP"
FEEDS = {"sotextract": EXTRACT_URL, "sotberthed": BERTHED_URL}

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "vts_freight"

# VTS type code -> category. Every code here was seen in the 17 Oct 2026 feeds.
CODE_CATEGORY = {
    "UCC": "container",  # Container Carrier
    "URR": "roro",  # Ro/Ro
    "URC": "roro",  # Ro/Ro/C.C. (ro-ro with container capacity)
    "MVE": "roro",  # Vehicle (car carriers)
    "PRR": "roro",  # Passenger Ro/Ro; Red Funnel's are caught by FERRY_AGENTS first
    "MPR": "cruise",  # Passenger
    "OFY": "ferry",  # Ferry (Red Jet)
    "TTA": "bulk_tanker",  # Tank
    "TCH": "bulk_tanker",  # Chemical Tank
    "LPG": "bulk_tanker",
    "LNG": "bulk_tanker",
    "BCE": "bulk_tanker",  # Cement
}
# Local Isle of Wight / Hythe operators: their lorries use Town Quay, not the docks.
FERRY_AGENTS = ("RED FUNNEL",)
# The excursion steamer SHIELDHALL is typed MPR (1,753 gt); the smallest cruise ship seen is 76,152.
CRUISE_MIN_GT = 10_000
LORRY_CATEGORIES = ("container", "roro")
CATEGORIES = ("container", "roro", "cruise", "ferry", "bulk_tanker", "other")

DIRECTIONS = {"A": "arrival", "D": "departure", "M": "shift"}

# Port of Southampton berth numbering (Wikipedia "Port of Southampton"; ABP Port Master Plan 2016,
# ch. 2; ABP Southampton Port Plan 2022 map): berths 20-49 are the Eastern (old) Docks, 101-110
# the Western Docks, 201-207 the container terminal, since renamed SCT1-4 (207-204) and SCT5
# (201/202) and run by DP World Southampton.
AREA_RANGES = (
    (20, 49, "eastern_docks"),
    (101, 110, "western_docks"),
    (201, 207, "container_terminal"),
)
UNKNOWN_AREA = "unknown"

# Stand-ins for times VTS hasn't fixed. Only the day feeds the daily counts.
VAGUE_TIMES = {"AM": time(9, 0), "PM": time(15, 0), "TBA": time(12, 0)}

EXTRACT_COLUMNS = [
    "ship",
    "imo",
    "category",
    "direction",
    "time",
    "time_confirmed",
    "berth",
    "area",
    "origin",
    "destination",
    "type",
    "type_code",
    "gt",
    "dwt",
    "loa",
    "draft",
    "agent",
    "approach",
    "abp_port",
    "lorry_relevant",
    "collected_at",
]
BERTHED_COLUMNS = [
    "ship",
    "imo",
    "category",
    "berth",
    "area",
    "arrival",
    "departure",
    "time_confirmed",
    "origin",
    "type",
    "type_code",
    "gt",
    "dwt",
    "loa",
    "agent",
    "lorry_relevant",
    "collected_at",
]
DAY_COLUMNS = [
    "date",
    *(f"{c}_{k}" for c in LORRY_CATEGORIES for k in ("arr", "dep", "arr_gt", "dep_gt")),
    "freight_moves",
    "freight_gt",
    "unconfirmed",
    "complete",
]

_CACHE_NAME = re.compile(r"(sotextract|sotberthed)_(\d{8}T\d{6}Z)\.xml$")
_TYPE_CODE = re.compile(r"\(([A-Z]{3})\)\s*$")


def _download(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def snapshot(raw_dir: str | Path = RAW_DIR, timeout: float = 30) -> list[Path]:
    """Fetch both feeds once and cache them as ``<feed>_<UTC time>.xml``; return the paths."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bodies = {}
    for name, url in FEEDS.items():
        body = _download(url, timeout)
        ET.fromstring(body)  # refuse to cache an error page
        bodies[name] = body
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, body in bodies.items():
        path = raw_dir / f"{name}_{stamp}.xml"
        path.write_bytes(body)
        paths.append(path)
    return paths


def collected_at(path: str | Path) -> pd.Timestamp:
    """When a cached feed was fetched: from its file name, else its modification time."""
    path = Path(path)
    m = _CACHE_NAME.search(path.name)
    if m:
        return pd.Timestamp(datetime.strptime(m.group(2), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)


def type_code(vts_type: str) -> str:
    """'Container Carrier (UCC)' -> 'UCC'; '' when there is no three-letter code."""
    m = _TYPE_CODE.search(vts_type or "")
    return m.group(1) if m else ""


def category(vts_type: str, agent: str = "", gt: float | None = None) -> str:
    """Group a VTS ship type into one of ``CATEGORIES``."""
    code = type_code(vts_type)
    if code == "OFY" or any(a in (agent or "").upper() for a in FERRY_AGENTS):
        return "ferry"
    cat = CODE_CATEGORY.get(code)
    if cat == "cruise" and gt is not None and not pd.isna(gt) and gt < CRUISE_MIN_GT:
        return "other"
    if cat:
        return cat
    if code[:1] in ("T", "B"):  # unseen tanker / bulk codes follow the same first letter
        return "bulk_tanker"
    return "other"


def berth_area(berth: str) -> str:
    """Dock area of a VTS berth name; ``UNKNOWN_AREA`` when public numbering doesn't settle it.

    '38/9', '46 O/S' (outside 46) and '104W' go by their leading number. 'SCT1/2' is the container
    terminal, 'Esso Berth 4' the Fawley refinery jetty, 'KGV Dock West Side' the King George V
    dry dock in the Western Docks.
    """
    b = (berth or "").strip().upper()
    if re.match(r"SCT\s*\d", b):
        return "container_terminal"
    if b.startswith("ESSO"):
        return "fawley"
    if b.startswith(("WESTERN DOCKS", "KGV")):
        return "western_docks"
    if b.startswith("EASTERN DOCKS"):
        return "eastern_docks"
    m = re.match(r"(\d+)(?:\D|$)", b)
    if m:
        n = int(m.group(1))
        for lo, hi, area in AREA_RANGES:
            if lo <= n <= hi:
                return area
    return UNKNOWN_AREA


def _parse_time(value: str | None) -> tuple[pd.Timestamp, bool]:
    """'17-Oct-2026 09:30' -> (local time, True); '17-Oct-2026 PM' -> (stand-in, False).

    No date at all ('' or a bare 'TBA') -> (NaT, False).
    """
    text = (value or "").strip()
    day_text, _, clock = text.partition(" ")
    try:
        day = datetime.strptime(day_text, "%d-%b-%Y").date()
    except ValueError:
        return pd.NaT, False
    clock = clock.strip().upper()
    try:
        t, confirmed = datetime.strptime(clock, "%H:%M").time(), True
    except ValueError:
        t, confirmed = VAGUE_TIMES.get(clock, VAGUE_TIMES["TBA"]), False
    # Same DST handling as vts._parse_time: first pass of a repeated hour, skip a missing one.
    local = pd.Timestamp(datetime.combine(day, t)).tz_localize(
        TZ, ambiguous=True, nonexistent="shift_forward"
    )
    return local, confirmed


def _rows(xml: str | bytes | Path) -> list[dict[str, str]]:
    root = ET.parse(xml).getroot() if isinstance(xml, Path) else ET.fromstring(xml)
    return [{c.tag: (c.text or "").strip() for c in r} for r in root.iter("row")]


def _ship_fields(f: dict[str, str]) -> dict:
    gt = pd.to_numeric(f.get("gt"), errors="coerce")
    cat = category(f.get("type", ""), f.get("agent", ""), gt)
    return {
        "ship": f.get("ship_name", ""),
        "imo": f.get("lloyds_no.", ""),
        "category": cat,
        "type": f.get("type", ""),
        "type_code": type_code(f.get("type", "")),
        "gt": gt,
        "dwt": pd.to_numeric(f.get("dwt"), errors="coerce"),
        "loa": pd.to_numeric(f.get("loa"), errors="coerce"),
        "agent": f.get("agent", ""),
        "lorry_relevant": cat in LORRY_CATEGORIES,
    }


def _finish(rows: list[dict], columns: list[str], sort: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in ("gt", "dwt", "loa", "draft"):
        if col in df:
            df[col] = df[col].astype("Float64")
    for col in ("time_confirmed", "lorry_relevant"):
        df[col] = df[col].astype(bool)
    return df.sort_values(sort, na_position="last").reset_index(drop=True)


def parse_extract(
    xml: str | bytes | Path, collected: pd.Timestamp | datetime | None = None
) -> pd.DataFrame:
    """One row per planned movement (``EXTRACT_COLUMNS``), sorted by time.

    ``berth`` is the port end: ``destination`` for arrivals and shifts, ``origin`` for departures.
    A row without a readable date is skipped with a warning (``df.attrs["skipped_rows"]``).
    """
    if collected is None:
        collected = collected_at(xml) if isinstance(xml, Path) else pd.Timestamp.now(UTC)
    collected = pd.Timestamp(collected).tz_convert(UTC)
    rows, skipped = [], []
    for f in _rows(xml):
        when, confirmed = _parse_time(f.get("eta_etd"))
        if pd.isna(when):
            skipped.append(f.get("ship_name") or "?")
            continue
        direction = DIRECTIONS.get(f.get("voyage_type", ""), "unknown")
        berth = f.get("origin", "") if direction == "departure" else f.get("destination", "")
        rows.append(
            {
                **_ship_fields(f),
                "direction": direction,
                "time": when,
                "time_confirmed": confirmed,
                "berth": berth,
                "area": berth_area(berth),
                "origin": f.get("origin", ""),
                "destination": f.get("destination", ""),
                "draft": pd.to_numeric(f.get("draft"), errors="coerce"),
                "approach": f.get("dir", ""),
                "abp_port": f.get("abp_port", ""),
                "collected_at": collected,
            }
        )
    df = _finish(rows, EXTRACT_COLUMNS, ["time", "ship"])
    df.attrs["skipped_rows"] = len(skipped)
    if skipped:
        warnings.warn(
            f"VTS extract: skipped {len(skipped)} row(s) with no date: " + ", ".join(skipped),
            stacklevel=2,
        )
    return df


def parse_berthed(
    xml: str | bytes | Path, collected: pd.Timestamp | datetime | None = None
) -> pd.DataFrame:
    """Ships alongside at ``collected`` (``BERTHED_COLUMNS``).

    ``arrival`` is VTS's actual arrival time. ``departure`` is its estimate: NaT when blank,
    a stand-in with ``time_confirmed=False`` when it reads "AM", "PM" or "TBA".
    """
    if collected is None:
        collected = collected_at(xml) if isinstance(xml, Path) else pd.Timestamp.now(UTC)
    collected = pd.Timestamp(collected).tz_convert(UTC)
    rows = []
    for f in _rows(xml):
        arrival, _ = _parse_time(f.get("actual_arrival_time"))
        departure, confirmed = _parse_time(f.get("estimated_departure_time"))
        berth = f.get("berth", "")
        rows.append(
            {
                **_ship_fields(f),
                "berth": berth,
                "area": berth_area(berth),
                "arrival": arrival,
                "departure": departure,
                "time_confirmed": confirmed,
                "origin": f.get("origin", ""),
                "collected_at": collected,
            }
        )
    df = _finish(rows, BERTHED_COLUMNS, ["arrival", "ship"])
    for col in ("arrival", "departure"):
        df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert(TZ)
    return df


def _cached(raw_dir: str | Path, feed: str) -> list[Path]:
    return sorted(Path(raw_dir).glob(f"{feed}_*.xml"))


def load_extracts(raw_dir: str | Path = RAW_DIR) -> list[pd.DataFrame]:
    """Every cached extract snapshot, parsed, oldest first."""
    return [parse_extract(p) for p in _cached(raw_dir, "sotextract")]


def load_latest_berthed(raw_dir: str | Path = RAW_DIR) -> pd.DataFrame | None:
    files = _cached(raw_dir, "sotberthed")
    return parse_berthed(files[-1]) if files else None


def union_extracts(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge snapshots, one row per (ship, direction, local day), from the newest snapshot.

    The key is the IMO, or the ship name when the IMO is blank (barges).
    """
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=EXTRACT_COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    key = df["imo"].where(df["imo"] != "", "name:" + df["ship"])
    df = df.assign(_key=key, _day=df["time"].dt.date).sort_values("collected_at", kind="stable")
    df = df.drop_duplicates(["_key", "direction", "_day"], keep="last")
    return df.drop(columns=["_key", "_day"]).sort_values(["time", "ship"]).reset_index(drop=True)


def snapshot_window(df: pd.DataFrame) -> tuple[date, date] | None:
    """Days a snapshot lists in full: the day after it was taken to its last listed day.

    The day it was taken is partial: movements already made that day have left the feed.
    """
    if not len(df):
        return None
    start = df["collected_at"].iloc[0].tz_convert(TZ).date() + pd.Timedelta(days=1)
    end = df["time"].max().date()
    return (start, end) if start <= end else None


def daily_freight_calls(extract_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per local day (``DAY_COLUMNS``) from the union of extract snapshots.

    ``{container,roro}_{arr,dep}`` count arrivals from / departures to sea (shifts between berths
    excluded); ``*_gt`` sum their gross tonnage. ``complete`` is True when some snapshot listed the
    whole day ahead of time; other days (the day a snapshot was taken) undercount.
    """
    moves = union_extracts(extract_frames)
    windows = [w for w in map(snapshot_window, extract_frames) if w]
    if not len(moves):
        return pd.DataFrame(columns=DAY_COLUMNS)
    # Every day any snapshot lists, so a day with no freight call shows as zero, not missing.
    first, last = moves["time"].min().date(), moves["time"].max().date()
    days = pd.date_range(first, last, freq="D").date
    out = pd.DataFrame({"date": days})
    lorry = moves["category"].isin(LORRY_CATEGORIES)
    sea = moves["direction"].isin(["arrival", "departure"])
    freight = moves[lorry & sea].assign(day=lambda d: d["time"].dt.date)
    for cat in LORRY_CATEGORIES:
        for short, direction in (("arr", "arrival"), ("dep", "departure")):
            sel = freight[(freight["category"] == cat) & (freight["direction"] == direction)]
            g = sel.groupby("day")
            out[f"{cat}_{short}"] = out["date"].map(g.size()).fillna(0).astype(int)
            out[f"{cat}_{short}_gt"] = out["date"].map(g["gt"].sum()).fillna(0).astype(float)
    count_cols = [c for c in DAY_COLUMNS if c.endswith(("_arr", "_dep"))]
    gt_cols = [c for c in DAY_COLUMNS if c.endswith("_gt") and c != "freight_gt"]
    out["freight_moves"] = out[count_cols].sum(axis=1)
    out["freight_gt"] = out[gt_cols].sum(axis=1)
    unconf = freight[~freight["time_confirmed"]].groupby("day").size()
    out["unconfirmed"] = out["date"].map(unconf).fillna(0).astype(int)
    out["complete"] = [any(a <= d <= b for a, b in windows) for d in out["date"]]
    return out[DAY_COLUMNS]


def summarise(frames: list[pd.DataFrame], berthed: pd.DataFrame | None = None) -> str:
    """Snapshot count, category counts and the daily freight table, for the CLI."""
    if not frames:
        return f"no cached snapshots in {RAW_DIR}; run with --snapshot"
    latest = frames[-1]
    collected = latest["collected_at"].iloc[0] if len(latest) else None
    lines = [
        f"Source: {SOURCE_PAGE} ({CREDIT})",
        f"{len(frames)} extract snapshot(s); latest collected "
        + (f"{collected:%Y-%m-%d %H:%M %Z}" if collected is not None else "(empty feed)"),
        "latest extract movements by category: "
        + ", ".join(f"{k}: {v}" for k, v in latest["category"].value_counts().items()),
    ]
    if berthed is not None and len(berthed):
        alongside = berthed[berthed["lorry_relevant"]]
        lines.append(
            f"alongside now: {len(berthed)} ships, {len(alongside)} container/ro-ro "
            f"({', '.join(sorted(alongside['ship']))})"
        )
    days = daily_freight_calls(frames)
    cols = ["date", "container_arr", "container_dep", "roro_arr", "roro_dep", "freight_gt"]
    lines.append(days[[*cols, "unconfirmed", "complete"]].to_string(index=False))
    return "\n".join(line for line in lines if line)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Port freight ship calls from Southampton VTS.")
    p.add_argument("--snapshot", action="store_true", help="fetch both feeds first")
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = p.parse_args(argv)
    if args.snapshot:
        for path in snapshot(args.raw_dir):
            print(f"saved {path}")
    print(summarise(load_extracts(args.raw_dir), load_latest_berthed(args.raw_dir)))


if __name__ == "__main__":
    main()


__all__ = [
    "BERTHED_URL",
    "CATEGORIES",
    "DAY_COLUMNS",
    "EXTRACT_URL",
    "berth_area",
    "category",
    "daily_freight_calls",
    "load_extracts",
    "parse_berthed",
    "parse_extract",
    "snapshot",
    "union_extracts",
]
