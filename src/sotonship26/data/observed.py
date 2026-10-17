"""Observed 15-minute traffic counts on the dock approaches from National Highways WebTRIS.

WebTRIS (https://webtris.nationalhighways.co.uk/api/v1.0) needs no key. ``fetch_month`` downloads
one site-month of the daily report (one page holds a month: 2,880 rows) and caches it as gzipped
JSON under ``data/raw/webtris/``; ``load_flows`` turns the cache into one row per site per 15-min
bin. Times in the report are UK clock time: a spring-forward day has 92 rows and a fall-back day
repeats the 01:xx bins (BST first, then GMT). Dead sites still return rows, with blank volumes.

Contains National Highways data © Crown copyright and database right 2026, licensed under the
Open Government Licence v3.0.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Observed cruise uplift (flow minus the same-weekday+time median on non-cruise days) is computed
# in sotonship26.uplift from the flows this module loads. SOT-7 documents the public entry point
# as observed.py::observed_uplift, so re-export the one implementation here rather than duplicate
# it. The redundant alias marks this as an intentional re-export.
from sotonship26.uplift import observed_uplift as observed_uplift

API_ROOT = "https://webtris.nationalhighways.co.uk/api/v1.0"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "webtris"
TZ = "Europe/London"
GOOD_QUALITY = 90  # percent of the day's bins present, WebTRIS's own daily quality score
ATTRIBUTION = (
    "Contains National Highways data © Crown copyright and database right 2026, "
    "licensed under the Open Government Licence v3.0"
)

# Western Docks traffic uses the M271; Eastern Docks traffic from the M3 joins the A33 at J14.
SITES: dict[int, dict] = {
    19974: {"name": "TMU 5120/1", "road": "M271", "direction": "northbound",
            "where": "A35 Redbridge to J1", "approach": "western",
            "lat": 50.92695, "lon": -1.47221},
    19796: {"name": "TMU 9997/1", "road": "M271", "direction": "southbound",
            "where": "J1 to A35 Redbridge", "approach": "western",
            "lat": 50.92686, "lon": -1.47135},
    20313: {"name": "TMU 5493/1", "road": "M271", "direction": "southbound",
            "where": "M27 J3 to A3057", "approach": "western",
            "lat": 50.95205, "lon": -1.47471},
    20605: {"name": "TMU 5493/2", "road": "M271", "direction": "northbound",
            "where": "A3057 to M27 J3", "approach": "western",
            "lat": 50.95205, "lon": -1.47471},
    7588: {"name": "TMU 5550/1", "road": "M271", "direction": "northbound",
           "where": "J1 to M27", "approach": "western",
           "lat": 50.93924, "lon": -1.47329},
    20025: {"name": "MIDAS M3/2161A", "road": "M3", "direction": "westbound",
            "where": "J14 (start of the A33)", "approach": "eastern",
            "lat": 50.96785, "lon": -1.38021},
}

LONG_BINS = ("661 - 1160 cm", "1160+ cm")  # vehicles over 6.6 m: coaches, HGVs


def _get_json(url: str, timeout: float = 120.0, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                body = response.read()
            return json.loads(body) if body else {}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            if attempt == retries - 1:
                raise RuntimeError(f"WebTRIS request failed after {retries} tries: {url}") from err
            time.sleep(2.0 * 2**attempt)
    return {}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).date()
    return start, end


def _ddmmyyyy(day: date) -> str:
    return day.strftime("%d%m%Y")


def _month_is_complete(year: int, month: int) -> bool:
    return _month_bounds(year, month)[1] < date.today()


def _cached(path: Path, url: str, refresh: bool, complete: bool) -> dict:
    if path.exists() and not (refresh and not complete):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    payload = _get_json(url)
    time.sleep(0.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return payload


def fetch_month(
    site_id: int, year: int, month: int, cache_dir: Path | None = None, refresh: bool = False
) -> list[dict]:
    """Raw 15-min report rows for one site-month, from the cache when present."""
    start, end = _month_bounds(year, month)
    url = (
        f"{API_ROOT}/reports/daily?sites={site_id}&start_date={_ddmmyyyy(start)}"
        f"&end_date={_ddmmyyyy(end)}&page=1&page_size=40000"
    )
    path = (cache_dir or CACHE_DIR) / str(site_id) / f"{year}-{month:02d}.json.gz"
    payload = _cached(path, url, refresh, _month_is_complete(year, month))
    rows = payload.get("Rows") or []
    if (payload.get("Header") or {}).get("links"):
        raise RuntimeError(f"WebTRIS paged {site_id} {year}-{month:02d}; raise page_size")
    return rows


def fetch_quality_month(
    site_id: int, year: int, month: int, cache_dir: Path | None = None, refresh: bool = False
) -> list[dict]:
    """Daily quality scores (percent of bins present) for one site-month."""
    start, end = _month_bounds(year, month)
    url = (
        f"{API_ROOT}/quality/daily?siteId={site_id}&start_date={_ddmmyyyy(start)}"
        f"&end_date={_ddmmyyyy(end)}"
    )
    path = (cache_dir or CACHE_DIR) / str(site_id) / f"{year}-{month:02d}.quality.json.gz"
    payload = _cached(path, url, refresh, _month_is_complete(year, month))
    return payload.get("Qualities") or []


def _months(start: date, end: date) -> list[tuple[int, int]]:
    return [(p.year, p.month) for p in pd.period_range(start, end, freq="M")]


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace("", None), errors="coerce")


def rows_to_frame(rows: Sequence[dict], site_id: int) -> pd.DataFrame:
    """Parse report rows into site_id, bin_start (tz-aware), flow_veh, long_veh, avg_mph."""
    columns = ["site_id", "bin_start", "flow_veh", "long_veh", "avg_mph"]
    if not rows:
        return pd.DataFrame(columns=columns)
    raw = pd.DataFrame(rows)
    raw["day"] = pd.to_datetime(raw["Report Date"].str[:10])
    bin_start = pd.Series(pd.NaT, index=raw.index, dtype=f"datetime64[ns, {TZ}]")
    for day, idx in raw.groupby("day").groups.items():
        bin_start.loc[idx] = _day_bins(day, raw.loc[idx, "Time Period Ending"])
    long_veh = sum(_to_number(raw[c]) for c in LONG_BINS if c in raw)
    out = pd.DataFrame({
        "site_id": site_id,
        "bin_start": bin_start,
        "flow_veh": _to_number(raw["Total Volume"]).astype("Int64"),
        "long_veh": pd.Series(long_veh).astype("Int64"),
        "avg_mph": _to_number(raw["Avg mph"]),
    })[columns]
    return out.drop_duplicates(["site_id", "bin_start"]).reset_index(drop=True)


def _day_bins(day: pd.Timestamp, ends: pd.Series) -> pd.Series:
    """Start time of each 15-min bin in one report day, in row order.

    A day normally has one row per bin (96; 92 when the clocks go forward, 100 when they go back)
    in time order, but some "Time Period Ending" values are irregular (12:55, 17:01, 00:02). When
    the row count matches the day's length, bins are placed by position, counted in UTC from local
    midnight. Otherwise each end time is snapped to its bin, and repeats are dropped later.
    """
    midnight = pd.Timestamp(day).tz_localize(TZ)
    next_midnight = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(TZ)
    expected = int((next_midnight - midnight) / pd.Timedelta(minutes=15))
    if len(ends) == expected:
        offsets = pd.to_timedelta(range(expected), unit="m") * 15
        return pd.Series((midnight.tz_convert("UTC") + offsets).tz_convert(TZ), index=ends.index)
    end = pd.Timestamp(day) + pd.to_timedelta(ends)
    # Bins end at hh:14, :29, :44, :59 (sometimes :59:59): add a minute, floor, step back 15 min.
    local = (end + pd.Timedelta(minutes=1)).dt.floor("15min") - pd.Timedelta(minutes=15)
    # On the fall-back day the 01:xx bins appear twice, BST first.
    first_seen = local.groupby(local).cumcount() == 0
    return local.dt.tz_localize(TZ, ambiguous=first_seen.to_numpy(), nonexistent="shift_forward")


def load_quality(
    site_ids: Iterable[int], start: date, end: date, refresh: bool = False
) -> pd.DataFrame:
    """One row per site per day: site_id, date, quality (0-100)."""
    frames = []
    for site_id in site_ids:
        for year, month in _months(start, end):
            q = fetch_quality_month(site_id, year, month, refresh=refresh)
            if q:
                frames.append(pd.DataFrame({
                    "site_id": site_id,
                    "date": pd.to_datetime([r["Date"][:10] for r in q]).date,
                    "quality": [r["Quality"] for r in q],
                }))
    if not frames:
        return pd.DataFrame(columns=["site_id", "date", "quality"])
    out = pd.concat(frames, ignore_index=True)
    return out[(out["date"] >= start) & (out["date"] <= end)].reset_index(drop=True)


def load_flows(
    site_ids: Iterable[int], start: date, end: date, refresh: bool = False
) -> pd.DataFrame:
    """15-min flows for each site between two dates inclusive, with a ``good_day`` flag."""
    site_ids = list(site_ids)
    frames = [
        rows_to_frame(fetch_month(site_id, year, month, refresh=refresh), site_id)
        for site_id in site_ids
        for year, month in _months(start, end)
    ]
    flows = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    flows["date"] = flows["bin_start"].dt.date
    flows = flows[(flows["date"] >= start) & (flows["date"] <= end)]
    quality = load_quality(site_ids, start, end, refresh=refresh)
    flows = flows.merge(quality, on=["site_id", "date"], how="left")
    flows["good_day"] = flows["quality"].fillna(0) >= GOOD_QUALITY
    return flows.drop(columns="quality").reset_index(drop=True)


def coverage(site_ids: Iterable[int], start: date, end: date) -> pd.DataFrame:
    """Good days (quality >= 90) per site per month."""
    q = load_quality(site_ids, start, end)
    q["month"] = pd.to_datetime(q["date"]).dt.to_period("M")
    q["good"] = q["quality"] >= GOOD_QUALITY
    return q.pivot_table(index="month", columns="site_id", values="good", aggfunc="sum").fillna(0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download WebTRIS 15-min counts for the dock sites")
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    p.add_argument("--sites", type=int, nargs="*", default=list(SITES))
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args(argv)
    started = datetime.now()
    for site_id in args.sites:
        for year, month in _months(args.start, args.end):
            fetch_month(site_id, year, month, refresh=args.refresh)
            fetch_quality_month(site_id, year, month, refresh=args.refresh)
        print(f"site {site_id}: cached {args.start} to {args.end}", flush=True)
    table = coverage(args.sites, args.start, args.end).astype(int)
    print(f"Good days (quality >= {GOOD_QUALITY}%) per month:")
    print(table.to_string())
    print(f"Totals: {table.sum().to_dict()}  ({datetime.now() - started} elapsed)")
    print(ATTRIBUTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
