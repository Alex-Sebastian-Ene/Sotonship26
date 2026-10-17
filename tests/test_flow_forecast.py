"""Synthetic checks for the lag-aware everyday traffic forecast."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from sotonship26.flow_forecast import (
    backtest_site,
    calendar_features,
    lagged_split,
    last_year,
    recent_median,
    site_days,
    year_median,
)

SHAPE = 150 + 120 * np.sin(np.linspace(0, np.pi, 96))


def synthetic_flows(n_days: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_days):
        d = date(2024, 1, 1) + timedelta(days=i)
        season = 1 + 0.2 * np.sin(2 * np.pi * d.timetuple().tm_yday / 365.25)
        weekday = 1.15 if d.weekday() < 5 else 0.75
        flow = SHAPE * season * weekday + rng.normal(0, 8, 96)
        t = pd.date_range(pd.Timestamp(d, tz="Europe/London"), periods=96, freq="15min")
        rows.append(pd.DataFrame({"site_id": 7, "bin_start": t, "flow_veh": flow,
                                  "good_day": True}))
    return pd.concat(rows, ignore_index=True)


def test_calendar_features_flags():
    f = calendar_features([date(2024, 12, 25), date(2024, 6, 5)])
    assert f["bank_holiday"].tolist() == [1.0, 0.0]
    assert f["christmas"].tolist() == [1.0, 0.0]
    assert f.loc[date(2024, 6, 5), "wd2"] == 1.0  # a Wednesday


def test_school_holiday_flags_weekdays_inside_council_dates_only():
    # Mon 19 Feb 2024 is term (spring half-term was 12-16 Feb); Sat 10 Aug 2024 is a weekend
    days = [date(2024, 2, 12), date(2024, 2, 16), date(2024, 2, 19), date(2024, 8, 7),
            date(2024, 8, 10), date(2026, 7, 22), date(2026, 7, 23)]
    f = calendar_features(days)
    assert f["school_holiday"].tolist() == [1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0]


def test_baselines_respect_publication_lag():
    by_date = {date(2024, 1, 1) + timedelta(days=i): np.full(96, float(i)) for i in range(800)}
    target = date(2025, 6, 4)
    assert last_year(target, by_date, lag=105) is not None
    assert last_year(target, by_date, lag=400) is None  # a year ago is not published yet
    med = recent_median(target, by_date, lag=105)
    newest_allowed = (target - timedelta(days=105) - date(2024, 1, 1)).days
    assert med is not None and med[0] <= newest_allowed


def test_ridge_beats_baselines_on_seasonal_synthetic():
    flows = synthetic_flows()
    dates, y = site_days(flows, 7)
    assert len(dates) >= 890  # clock-change days (92 or 100 bins) are dropped as incomplete
    table = backtest_site(7, dates, y, cutoff=date(2025, 7, 1))
    vs = table[table["versus"] == "recent_median"].set_index("model")
    assert vs.loc["ridge", "mae_veh_per_15min"] < vs.loc["recent_median", "mae_veh_per_15min"]
    assert vs.loc["ridge", "skill_vs_baseline"] > 0
    assert 0.6 < vs.loc["ridge", "coverage80"] < 0.97


def test_year_median_needs_three_published_weeks():
    target = date(2025, 6, 4)
    by_date = {target - timedelta(days=364 + 7 * k): np.full(96, float(k)) for k in range(-2, 3)}
    assert np.allclose(year_median(target, by_date, 105), 0.0)
    two = {d: v for d, v in list(by_date.items())[:2]}
    assert year_median(target, two, 105) is None


def test_lagged_split_leaves_a_publication_gap():
    dates = np.array([date(2024, 1, 1) + timedelta(days=i) for i in range(500)])
    proper, cal = lagged_split(dates, np.arange(500), 105)
    assert len(cal) == 100
    assert (dates[cal[0]] - dates[proper[-1]]).days >= 105
