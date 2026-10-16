"""Observed cruise uplift: how much extra traffic a cruise day puts on a road, per 15 minutes.

uplift = observed flow - the median flow at the same site, weekday and time of day on nearby
non-cruise days. "Nearby" is a +/- ``window_days`` band, so the reference follows the season.
Only days we know had no ship (covered by the schedule source, zero calls), with good sensor data
and that are not bank holidays, can be reference days.

Inputs are plain DataFrames so this runs on any source:
  flows: site_id, bin_start (tz-aware), flow_veh, good_day        (data/observed.py)
  days:  date, n_calls, covered, pax_total, ...                    (data/cruise_history.py)
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

BINS_PER_DAY = 96

# England and Wales bank holidays, from https://www.gov.uk/bank-holidays (checked 2026-10-16).
BANK_HOLIDAYS = {
    date(2024, 1, 1), date(2024, 3, 29), date(2024, 4, 1), date(2024, 5, 6), date(2024, 5, 27),
    date(2024, 8, 26), date(2024, 12, 25), date(2024, 12, 26),
    date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21), date(2025, 5, 5), date(2025, 5, 26),
    date(2025, 8, 25), date(2025, 12, 25), date(2025, 12, 26),
    date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25),
    date(2026, 8, 31), date(2026, 12, 25), date(2026, 12, 28),
}


def day_matrix(flows: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, np.ndarray]]:
    """Reshape 15-min flows into one (n_days x 96) matrix per site.

    Returns the day index (site_id, date, good_day, complete) and {site_id: matrix}. Days missing
    bins (DST changes, outages) keep NaN in those bins.
    """
    f = flows.copy()
    local = f["bin_start"].dt.tz_convert("Europe/London")
    f["date"] = local.dt.date
    f["tod_bin"] = local.dt.hour * 4 + local.dt.minute // 15
    if "good_day" not in f:
        f["good_day"] = True
    mats: dict[int, np.ndarray] = {}
    index_rows = []
    for site, g in f.groupby("site_id"):
        wide = g.pivot_table(index="date", columns="tod_bin", values="flow_veh", aggfunc="sum")
        wide = wide.reindex(columns=range(BINS_PER_DAY))
        good = g.groupby("date")["good_day"].all().reindex(wide.index)
        mats[site] = wide.to_numpy(dtype=float)
        for d, ok, n in zip(wide.index, good, wide.notna().sum(axis=1), strict=True):
            index_rows.append({"site_id": site, "date": d, "good_day": bool(ok),
                               "complete": n == BINS_PER_DAY})
    return pd.DataFrame(index_rows), mats


def reference_mask(days: pd.DataFrame) -> pd.Series:
    """Days that can serve as 'no cruise' references: covered, zero calls, not a bank holiday."""
    is_holiday = days["date"].map(lambda d: d in BANK_HOLIDAYS)
    return days["covered"].astype(bool) & (days["n_calls"] == 0) & ~is_holiday


def observed_uplift(flows: pd.DataFrame, days: pd.DataFrame, window_days: int = 28,
                    min_refs: int = 3) -> pd.DataFrame:
    """Observed uplift per site, date and 15-min bin.

    Columns: site_id, date, tod_bin, flow_veh, baseline_veh, uplift_veh, n_refs, is_cruise_day,
    covered. Rows whose baseline has fewer than ``min_refs`` reference days get NaN uplift.
    """
    index, mats = day_matrix(flows)
    days = days.assign(date=pd.to_datetime(days["date"]).dt.date)
    info = days.set_index("date")
    ref_dates = set(days.loc[reference_mask(days), "date"])
    out = []
    for site, mat in mats.items():
        idx = index[index["site_id"] == site].reset_index(drop=True)
        dates = pd.to_datetime(idx["date"])
        usable = (idx["good_day"] & idx["complete"]).to_numpy()
        is_ref = idx["date"].isin(ref_dates).to_numpy() & usable
        weekday = dates.dt.weekday.to_numpy()
        ordinal = dates.map(pd.Timestamp.toordinal).to_numpy()
        for i in range(len(idx)):
            near = (np.abs(ordinal - ordinal[i]) <= window_days) & (weekday == weekday[i])
            near &= is_ref
            near[i] = False
            n_refs = int(near.sum())
            base = np.nanmedian(mat[near], axis=0) if n_refs >= min_refs else np.full(96, np.nan)
            flow = mat[i] if usable[i] else np.full(96, np.nan)
            d = idx.at[i, "date"]
            row_info = info.loc[d] if d in info.index else None
            out.append(pd.DataFrame({
                "site_id": site, "date": d, "tod_bin": np.arange(BINS_PER_DAY),
                "flow_veh": flow, "baseline_veh": base, "uplift_veh": flow - base,
                "n_refs": n_refs,
                "is_cruise_day": bool(row_info is not None and row_info["n_calls"] > 0),
                "covered": bool(row_info is not None and row_info["covered"]),
            }))
    return pd.concat(out, ignore_index=True)


def detectability(uplift: pd.DataFrame, n_boot: int = 500, seed: int = 0) -> pd.DataFrame:
    """Mean uplift by site and hour on cruise vs reference days, with a day-level bootstrap 90% CI.

    This answers "is the cruise effect visible at this sensor at all?" before any modelling.
    """
    rng = np.random.default_rng(seed)
    u = uplift.dropna(subset=["uplift_veh"]).assign(hour=lambda x: x["tod_bin"] // 4)
    rows = []
    for (site, cruise), g in u[u["covered"]].groupby(["site_id", "is_cruise_day"]):
        per_day = g.pivot_table(index="date", columns="hour", values="uplift_veh", aggfunc="sum")
        per_day = per_day.dropna()
        if per_day.empty:
            continue
        values = per_day.to_numpy()
        boot = np.stack([values[rng.integers(0, len(values), len(values))].mean(axis=0)
                         for _ in range(n_boot)])
        lo, hi = np.percentile(boot, [5, 95], axis=0)
        for h, mean, a, b in zip(per_day.columns, values.mean(axis=0), lo, hi, strict=True):
            rows.append({"site_id": site, "cruise_day": cruise, "hour": h, "n_days": len(values),
                         "mean_uplift_veh_per_hour": mean, "ci5": a, "ci95": b})
    return pd.DataFrame(rows)
