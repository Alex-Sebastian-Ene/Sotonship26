"""DfT road traffic counts for Southampton: AADF by direction and hourly manual counts.

The Department for Transport publishes road traffic statistics at https://roadtraffic.dft.gov.uk
under the Open Government Licence v3.0. We use two endpoints, both filtered to Southampton
(``local_authority_id`` 137) and fetched page by page:

- ``AADF_URL``: Annual Average Daily Flow (AADF) per count point, direction of travel and year.
- ``RAW_COUNTS_URL``: the manual counts behind it, one row per count point, direction, count day
  and hour. ``hour`` 7 is 07:00-08:00; counts run 07:00-19:00 (hours 7 to 18) on one weekday per
  counted year. Only years marked "Counted" have raw counts; "Estimated" years have none.

Each pull is cached as one combined JSON file under ``data/raw/dft/`` (gitignored, never
committed): ``aadf_by_direction_la137_<UTC time>.json`` and ``raw_counts_la137_<UTC time>.json``.
``collected_at`` is when we fetched it, taken from that file name.

AADF is a yearly average for an average day, so it gives the background traffic on counted roads,
not the extra load on a cruise turnaround day. Rows are either counted on the day ("Counted") or
estimated by DfT from earlier years or nearby links ("Estimated"); ``estimation_method`` says
which. ``load_aadf`` keeps count points within ``radius_km`` of ``TOWN_QUAY`` and, by default, only
each count point's most recent year (every direction counted that year). It goes by the point's
latest year, not the latest year per direction, because DfT sometimes changes a point's direction
codes between years (E/W one year, N/S or C later). Keeping the latest year per direction would
mix years and count those points twice. ``load_hourly_counts`` gives the hourly profile for those
count points (or any others), every counted day.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

API_BASE = "https://roadtraffic.dft.gov.uk/api"
AADF_URL = f"{API_BASE}/average-annual-daily-flow-by-direction"
RAW_COUNTS_URL = f"{API_BASE}/raw-counts"
LICENCE = "Open Government Licence v3.0"
USER_AGENT = "sotonship26/0.1 (SotonShip 2026 hackathon)"
LOCAL_AUTHORITY_ID = 137  # Southampton
# The API accepts this. On 16 Oct 2026 Southampton had 3,334 AADF rows (1 page) and 15,648 raw
# count rows (4 pages).
PAGE_SIZE = 5000

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "dft"
AADF_PREFIX = "aadf_by_direction"
RAW_COUNTS_PREFIX = "raw_counts"

# Town Quay, Southampton. Matches streets.centre in configs/default.yaml, the centre of the road
# graph. Distances are measured from here.
TOWN_QUAY = (50.8966, -1.4044)
EARTH_RADIUS_KM = 6371.0088

COLUMNS = [
    "count_point_id",
    "year",
    "road_name",
    "road_category",
    "road_type",
    "start_junction_road_name",
    "end_junction_road_name",
    "latitude",
    "longitude",
    "direction_of_travel",
    "all_motor_vehicles",
    "cars_and_taxis",
    "buses_and_coaches",
    "lgvs",
    "all_hgvs",
    "estimation_method",
    "link_length_km",
    "distance_km",
    "collected_at",
]
HOURLY_COLUMNS = [
    "count_point_id",
    "count_date",
    "hour",
    "direction_of_travel",
    "all_motor_vehicles",
    "collected_at",
]
_FLOAT_COLUMNS = ["latitude", "longitude", "link_length_km"]
_INT_COLUMNS = [
    "count_point_id",
    "year",
    "all_motor_vehicles",
    "cars_and_taxis",
    "buses_and_coaches",
    "lgvs",
    "all_hgvs",
]

_CACHE_NAME = re.compile(r"(?:aadf_by_direction|raw_counts)_la\d+_(\d{8}T\d{6}Z)\.json$")


def page_url(
    page: int, local_authority_id: int = LOCAL_AUTHORITY_ID, endpoint: str = AADF_URL
) -> str:
    """API URL for one page of an endpoint's rows for a local authority."""
    query = urllib.parse.urlencode(
        {
            "filter[local_authority_id]": local_authority_id,
            "page[size]": PAGE_SIZE,
            "page[number]": page,
        }
    )
    return f"{endpoint}?{query}"


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _fetch_all(
    endpoint: str, prefix: str, raw_dir: str | Path, local_authority_id: int, timeout: float
) -> Path:
    """Download every page (sequentially) and cache the rows as one JSON file; return its path."""
    rows: list[dict] = []
    page, last_page = 1, 1
    while page <= last_page:
        body = _get_json(page_url(page, local_authority_id, endpoint), timeout)
        if not isinstance(body.get("data"), list):
            raise ValueError(f"unexpected DfT API response on page {page}: {list(body)[:5]}")
        rows.extend(body["data"])
        last_page = int(body.get("last_page") or page)
        page += 1
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"{prefix}_la{local_authority_id}_{stamp}.json"
    source = page_url(1, local_authority_id, endpoint)
    path.write_text(
        json.dumps({"source": source, "licence": LICENCE, "data": rows}), encoding="utf-8"
    )
    return path


def fetch_aadf(
    raw_dir: str | Path = RAW_DIR, local_authority_id: int = LOCAL_AUTHORITY_ID, timeout: float = 60
) -> Path:
    """Download all AADF-by-direction rows for the local authority and cache them."""
    return _fetch_all(AADF_URL, AADF_PREFIX, raw_dir, local_authority_id, timeout)


def fetch_raw_counts(
    raw_dir: str | Path = RAW_DIR, local_authority_id: int = LOCAL_AUTHORITY_ID, timeout: float = 60
) -> Path:
    """Download all hourly manual count rows for the local authority and cache them."""
    return _fetch_all(RAW_COUNTS_URL, RAW_COUNTS_PREFIX, raw_dir, local_authority_id, timeout)


def collected_at(path: str | Path) -> pd.Timestamp:
    """When a cached file was fetched: from its file name, else its modification time."""
    path = Path(path)
    m = _CACHE_NAME.search(path.name)
    if m:
        return pd.Timestamp(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)


def latest_cached(raw_dir: str | Path = RAW_DIR, prefix: str = AADF_PREFIX) -> Path | None:
    files = sorted(Path(raw_dir).glob(f"{prefix}_la*.json"))
    return files[-1] if files else None


def _cached_or_fetch(
    prefix: str, fetch: Callable[[str | Path], Path], refresh: bool, raw_dir: str | Path
) -> Path:
    """Newest cache, fetched first if there is none or ``refresh``; on failure warn and use it."""
    path = latest_cached(raw_dir, prefix)
    if refresh or path is None:
        try:
            path = fetch(raw_dir)
        except (OSError, ValueError) as e:
            if path is None:
                raise
            warnings.warn(f"DfT fetch failed ({e}); using cache {path.name}", stacklevel=3)
    return Path(path)


def haversine_km(
    lat: pd.Series, lon: pd.Series, origin: tuple[float, float] = TOWN_QUAY
) -> pd.Series:
    """Great-circle distance in km from ``origin`` to each (lat, lon)."""
    lat0, lon0 = np.radians(origin[0]), np.radians(origin[1])
    lat_r, lon_r = np.radians(lat.astype(float)), np.radians(lon.astype(float))
    a = (
        np.sin((lat_r - lat0) / 2) ** 2
        + np.cos(lat0) * np.cos(lat_r) * np.sin((lon_r - lon0) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _rows(raw: dict | list) -> list[dict]:
    return raw["data"] if isinstance(raw, dict) else raw


def parse_aadf(raw: dict | list, collected: pd.Timestamp | datetime) -> pd.DataFrame:
    """Turn cached AADF rows into a typed DataFrame with every column in ``COLUMNS``."""
    df = pd.DataFrame(_rows(raw))
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    for col in _FLOAT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in _INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df = df.dropna(subset=["latitude", "longitude"])
    df["distance_km"] = haversine_km(df["latitude"], df["longitude"])
    df["collected_at"] = pd.Timestamp(collected).tz_convert(UTC)
    return df[COLUMNS].reset_index(drop=True)


def parse_raw_counts(raw: dict | list, collected: pd.Timestamp | datetime) -> pd.DataFrame:
    """Turn cached raw-count rows into a typed DataFrame with every column in ``HOURLY_COLUMNS``.

    ``count_date`` is the calendar day of the count (naive datetime64, local day).
    """
    df = pd.DataFrame(_rows(raw))
    for col in HOURLY_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    for col in ["count_point_id", "hour", "all_motor_vehicles"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["count_date"] = pd.to_datetime(df["count_date"], format="%Y-%m-%d", errors="coerce")
    df["collected_at"] = pd.Timestamp(collected).tz_convert(UTC)
    return df[HOURLY_COLUMNS].reset_index(drop=True)


def load_aadf(
    radius_km: float = 4.0,
    refresh: bool = False,
    raw_dir: str | Path = RAW_DIR,
    latest_only: bool = True,
) -> pd.DataFrame:
    """AADF by direction for count points within ``radius_km`` of ``TOWN_QUAY`` (see ``COLUMNS``).

    Uses the newest cache in ``raw_dir``, fetching from the API if there is none or ``refresh`` is
    set. If the fetch fails and a cache exists, falls back to it with a warning; ``collected_at``
    then shows its age. With ``latest_only``, keeps per ``count_point_id`` only the rows from that
    point's most recent year, all of its directions in that year (see the module docstring for
    why). Sorted by distance from Town Quay.
    """
    path = _cached_or_fetch(AADF_PREFIX, fetch_aadf, refresh, raw_dir)
    df = parse_aadf(json.loads(path.read_text(encoding="utf-8")), collected_at(path))
    df = df[df["distance_km"] <= radius_km]
    if latest_only:
        latest = df.groupby("count_point_id")["year"].transform("max")
        df = df[df["year"] == latest]
    return df.sort_values(
        ["distance_km", "count_point_id", "direction_of_travel", "year"]
    ).reset_index(drop=True)


def load_hourly_counts(
    count_point_ids: Iterable[int] | None = None,
    refresh: bool = False,
    raw_dir: str | Path = RAW_DIR,
) -> pd.DataFrame:
    """Hourly manual counts (see ``HOURLY_COLUMNS``), every counted day, for the given count points.

    With no ``count_point_ids``, uses the count points ``load_aadf()`` returns (within 4 km of
    Town Quay, from the AADF cache). Caching and fallback work as in ``load_aadf``; ``refresh``
    re-fetches the raw counts only. Sorted by count point, day, direction and hour.
    """
    if count_point_ids is None:
        count_point_ids = load_aadf(raw_dir=raw_dir)["count_point_id"].unique()
    ids = {int(i) for i in count_point_ids}
    path = _cached_or_fetch(RAW_COUNTS_PREFIX, fetch_raw_counts, refresh, raw_dir)
    df = parse_raw_counts(json.loads(path.read_text(encoding="utf-8")), collected_at(path))
    df = df[df["count_point_id"].isin(ids)]
    return df.sort_values(
        ["count_point_id", "count_date", "direction_of_travel", "hour"]
    ).reset_index(drop=True)


def main() -> None:
    radius_km = 4.0
    refresh = "--refresh" in sys.argv
    df = load_aadf(radius_km=radius_km, refresh=refresh)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)
    print(f"Source: {page_url(1)}")
    print(f"Licence: {LICENCE} (contains public sector information, Department for Transport)")
    if df.empty:
        print(f"No count points within {radius_km} km of Town Quay.")
        return
    print(f"Collected: {df['collected_at'].iloc[0]:%Y-%m-%d %H:%M %Z}")
    print(
        f"{df['count_point_id'].nunique()} count points, {len(df)} rows (each point's latest year) "
        f"within {radius_km} km of Town Quay; "
        f"years {df['year'].min()} to {df['year'].max()}; "
        f"{(df['estimation_method'] == 'Counted').sum()} rows counted, the rest estimated"
    )
    top = df.sort_values("all_motor_vehicles", ascending=False).head(15)
    print(
        top[
            [
                "count_point_id",
                "year",
                "road_name",
                "direction_of_travel",
                "start_junction_road_name",
                "end_junction_road_name",
                "all_motor_vehicles",
                "estimation_method",
                "distance_km",
            ]
        ].to_string(index=False)
    )

    hourly = load_hourly_counts(df["count_point_id"].unique(), refresh=refresh)
    print()
    print(f"Source: {page_url(1, endpoint=RAW_COUNTS_URL)}")
    if hourly.empty:
        print("No hourly manual counts for these count points.")
        return
    print(f"Collected: {hourly['collected_at'].iloc[0]:%Y-%m-%d %H:%M %Z}")
    days = hourly[["count_point_id", "count_date"]].drop_duplicates()
    print(
        f"Hourly manual counts: {len(hourly)} rows, {hourly['count_point_id'].nunique()} count "
        f"points, {len(days)} count-point days, {hourly['count_date'].min():%Y-%m-%d} to "
        f"{hourly['count_date'].max():%Y-%m-%d}, hours {hourly['hour'].min()} to "
        f"{hourly['hour'].max()}"
    )


if __name__ == "__main__":
    main()
