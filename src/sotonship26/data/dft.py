"""DfT road traffic counts (AADF by direction) for Southampton, from the DfT road traffic API.

The Department for Transport publishes Annual Average Daily Flow (AADF) per count point, per
direction of travel and per year at https://roadtraffic.dft.gov.uk, under the Open Government
Licence v3.0. We pull every row for Southampton (``local_authority_id`` 137) from ``API_URL``,
page by page, and cache the combined JSON under ``data/raw/dft/`` (gitignored, never committed)
as ``aadf_by_direction_la137_<UTC time>.json``. ``collected_at`` is when we fetched it, taken from
that file name.

AADF is a yearly average for an average day, so it gives the background traffic on counted roads,
not the extra load on a cruise turnaround day. Rows are either counted on the day ("Counted") or
estimated by DfT from earlier years or nearby links ("Estimated"); ``estimation_method`` says
which. ``load_aadf`` keeps count points within ``radius_km`` of the docks and, by default, only
the most recent year per count point and direction.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

API_URL = "https://roadtraffic.dft.gov.uk/api/average-annual-daily-flow-by-direction"
SOURCE_PAGE = "https://roadtraffic.dft.gov.uk/local-authorities/137"
LICENCE = "Open Government Licence v3.0"
USER_AGENT = "sotonship26/0.1 (SotonShip 2026 hackathon)"
LOCAL_AUTHORITY_ID = 137  # Southampton
PAGE_SIZE = 5000  # the API accepts this; Southampton had 3,334 rows on 16 Oct 2026

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "dft"

# Centre of the docks, Town Quay area. Distances are measured from here.
DOCKS = (50.8985, -1.4040)
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

_CACHE_NAME = re.compile(r"aadf_by_direction_la\d+_(\d{8}T\d{6}Z)\.json$")


def page_url(page: int, local_authority_id: int = LOCAL_AUTHORITY_ID) -> str:
    """API URL for one page of AADF-by-direction rows for a local authority."""
    query = urllib.parse.urlencode(
        {
            "filter[local_authority_id]": local_authority_id,
            "page[size]": PAGE_SIZE,
            "page[number]": page,
        }
    )
    return f"{API_URL}?{query}"


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_aadf(
    raw_dir: str | Path = RAW_DIR,
    local_authority_id: int = LOCAL_AUTHORITY_ID,
    timeout: float = 60,
) -> Path:
    """Download every page (sequentially) and cache the rows as one JSON file; return its path."""
    rows: list[dict] = []
    page, last_page = 1, 1
    while page <= last_page:
        body = _get_json(page_url(page, local_authority_id), timeout)
        if not isinstance(body.get("data"), list):
            raise ValueError(f"unexpected DfT API response on page {page}: {list(body)[:5]}")
        rows.extend(body["data"])
        last_page = int(body.get("last_page") or page)
        page += 1
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"aadf_by_direction_la{local_authority_id}_{stamp}.json"
    payload = {"source": page_url(1, local_authority_id), "licence": LICENCE, "data": rows}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def collected_at(path: str | Path) -> pd.Timestamp:
    """When a cached file was fetched: from its file name, else its modification time."""
    path = Path(path)
    m = _CACHE_NAME.search(path.name)
    if m:
        return pd.Timestamp(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)


def latest_cached(raw_dir: str | Path = RAW_DIR) -> Path | None:
    files = sorted(Path(raw_dir).glob("aadf_by_direction_la*.json"))
    return files[-1] if files else None


def haversine_km(lat: pd.Series, lon: pd.Series, origin: tuple[float, float] = DOCKS) -> pd.Series:
    """Great-circle distance in km from ``origin`` to each (lat, lon)."""
    lat0, lon0 = np.radians(origin[0]), np.radians(origin[1])
    lat_r, lon_r = np.radians(lat.astype(float)), np.radians(lon.astype(float))
    a = (
        np.sin((lat_r - lat0) / 2) ** 2
        + np.cos(lat0) * np.cos(lat_r) * np.sin((lon_r - lon0) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def parse_aadf(raw: dict | list, collected: pd.Timestamp | datetime) -> pd.DataFrame:
    """Turn cached API rows into a typed DataFrame with every column in ``COLUMNS``."""
    rows = raw["data"] if isinstance(raw, dict) else raw
    df = pd.DataFrame(rows)
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


def load_aadf(
    radius_km: float = 4.0,
    refresh: bool = False,
    raw_dir: str | Path = RAW_DIR,
    latest_only: bool = True,
) -> pd.DataFrame:
    """AADF by direction for count points within ``radius_km`` of ``DOCKS`` (columns: ``COLUMNS``).

    Uses the newest cache in ``raw_dir``, fetching from the API if there is none or ``refresh`` is
    set. If the fetch fails and a cache exists, falls back to it with a warning; ``collected_at``
    then shows its age. With ``latest_only``, keeps only the most recent year per
    (count_point_id, direction_of_travel). Sorted by distance from the docks.
    """
    path = latest_cached(raw_dir)
    if refresh or path is None:
        try:
            path = fetch_aadf(raw_dir)
        except (OSError, ValueError) as e:
            if path is None:
                raise
            warnings.warn(f"DfT fetch failed ({e}); using cache {path.name}", stacklevel=2)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    df = parse_aadf(raw, collected_at(path))
    df = df[df["distance_km"] <= radius_km]
    if latest_only:
        latest = df.groupby(["count_point_id", "direction_of_travel"])["year"].transform("max")
        df = df[df["year"] == latest]
    return df.sort_values(
        ["distance_km", "count_point_id", "direction_of_travel", "year"]
    ).reset_index(drop=True)


def main() -> None:
    radius_km = 4.0
    df = load_aadf(radius_km=radius_km, refresh="--refresh" in sys.argv)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)
    print(f"Source: {page_url(1)}")
    print(f"Licence: {LICENCE} (contains public sector information, Department for Transport)")
    if df.empty:
        print(f"No count points within {radius_km} km of the docks.")
        return
    print(f"Collected: {df['collected_at'].iloc[0]:%Y-%m-%d %H:%M %Z}")
    print(
        f"{df['count_point_id'].nunique()} count points, {len(df)} rows (latest year per point "
        f"and direction) within {radius_km} km of the docks; "
        f"years {df['year'].min()} to {df['year'].max()}"
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


if __name__ == "__main__":
    main()
