"""Synthetic checks: a known cruise effect must be recovered and beaten baselines must lose."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from sotonship26.backtest import (
    BINS,
    PaxLinear,
    Ridge,
    Zero,
    backtest_site,
    conformal_halfwidth,
    day_features,
    site_targets,
)
from sotonship26.uplift import observed_uplift, reference_mask

START = date(2024, 1, 1)
N_DAYS = 400
PROFILE = 200 + 150 * np.sin(np.linspace(0, np.pi, BINS))  # background veh per 15 min
BUMP = np.exp(-0.5 * ((np.arange(BINS) - 60) / 4) ** 2)  # cruise pulse around 15:00


def synthetic(seed: int = 0):
    rng = np.random.default_rng(seed)
    dates = [START + timedelta(days=i) for i in range(N_DAYS)]
    pax_w = np.where(rng.random(N_DAYS) < 0.3, rng.uniform(2000, 6000, N_DAYS), 0.0)
    rows = []
    for d, pw in zip(dates, pax_w, strict=True):
        flow = PROFILE * (1.1 if d.weekday() < 5 else 0.8) + rng.normal(0, 10, BINS)
        flow = flow + 0.05 * pw * BUMP
        t = pd.date_range(pd.Timestamp(d, tz="Europe/London"), periods=BINS, freq="15min")
        rows.append(pd.DataFrame({"site_id": 1, "bin_start": t, "flow_veh": flow,
                                  "good_day": True}))
    flows = pd.concat(rows, ignore_index=True)
    days = pd.DataFrame({"date": dates, "n_calls": (pax_w > 0).astype(int), "covered": True,
                         "pax_western": pax_w, "pax_eastern": 0.0, "pax_unknown": 0.0,
                         "pax_total": pax_w})
    return flows, days


def test_reference_mask_excludes_cruise_and_bank_holidays():
    days = pd.DataFrame({"date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
                         "n_calls": [0, 1, 0], "covered": [True, True, False]})
    assert reference_mask(days).tolist() == [False, False, False]


def test_observed_uplift_recovers_cruise_pulse():
    flows, days = synthetic()
    up = observed_uplift(flows, days)
    cruise = up[up["is_cruise_day"]].dropna(subset=["uplift_veh"])
    peak = cruise[cruise["tod_bin"] == 60]
    expected = 0.05 * days.set_index("date").loc[peak["date"], "pax_western"].to_numpy()
    assert np.median(np.abs(peak["uplift_veh"].to_numpy() - expected)) < 20
    quiet = up[~up["is_cruise_day"]].dropna(subset=["uplift_veh"])
    assert abs(quiet["uplift_veh"].median()) < 5


def test_models_learn_the_effect_and_beat_zero():
    flows, days = synthetic()
    up = observed_uplift(flows, days)
    dates, y = site_targets(up, 1)
    feats = day_features(days).reindex(dates)
    zero = np.abs(Zero().fit(feats, y).predict(feats) - y).mean()
    for model in (PaxLinear(), Ridge()):
        err = np.abs(model.fit(feats, y).predict(feats) - y).mean()
        assert err < zero


def test_conformal_halfwidth_shape_and_order():
    rng = np.random.default_rng(1)
    resid = rng.normal(0, 10, (50, BINS))
    half = conformal_halfwidth(resid)
    assert half.shape == (BINS,)
    assert 10 < half.mean() < 20  # 80% of |N(0,10)| sits below ~12.8


def test_backtest_site_reports_coverage_near_target():
    flows, days = synthetic(seed=2)
    up = observed_uplift(flows, days)
    dates, y = site_targets(up, 1)
    result = backtest_site(1, dates, y, day_features(days), cutoff=date(2024, 10, 1))
    assert result is not None
    table = result.table
    ridge = table[(table["model"] == "ridge") & (table["days"] == "cruise_days")].iloc[0]
    zero = table[(table["model"] == "zero") & (table["days"] == "cruise_days")].iloc[0]
    assert ridge["mae_veh_per_15min"] < zero["mae_veh_per_15min"]
    assert 0.6 < ridge["coverage80"] < 0.97


def test_production_model_round_trip(tmp_path):
    from sotonship26 import uplift_model

    flows, days = synthetic(seed=3)
    up = observed_uplift(flows, days)
    dates, y = site_targets(up, 1)
    feats = day_features(days)
    model = uplift_model.fit_site(1, dates, y, feats, threshold=40.0)
    path = tmp_path / "m.json"
    uplift_model.save([model], {"note": "synthetic"}, path)
    models, meta = uplift_model.load(path)
    future = day_features(pd.DataFrame({"date": [date(2025, 6, 1), date(2025, 6, 2)],
                                        "n_calls": [1, 0], "pax_western": [5000.0, 0.0],
                                        "pax_eastern": 0.0, "pax_unknown": 0.0}))
    fc = uplift_model.predict_uplift(future, models)
    busy = fc[(fc["date"] == date(2025, 6, 1)) & (fc["tod_bin"] == 60)].iloc[0]
    quiet = fc[(fc["date"] == date(2025, 6, 2)) & (fc["tod_bin"] == 60)].iloc[0]
    assert 150 < busy["uplift_veh"] < 350  # true effect 0.05 * 5000 = 250
    assert busy["lo80"] < busy["uplift_veh"] < busy["hi80"]
    assert busy["p_event"] > 0.9 and quiet["p_event"] < 0.2
    assert meta == {"note": "synthetic"}


def test_clock_change_days_are_not_complete():
    from sotonship26.uplift import day_matrix

    def day(d: str) -> pd.DataFrame:
        t = pd.date_range(pd.Timestamp(d, tz="Europe/London"),
                          pd.Timestamp(d, tz="Europe/London") + pd.Timedelta(days=1),
                          freq="15min", inclusive="left")
        return pd.DataFrame({"site_id": 1, "bin_start": t, "flow_veh": 10.0, "good_day": True})

    # 26 Oct has 96 bins; 27 Oct (clocks go back) has 100 and must not count as complete
    index, _ = day_matrix(pd.concat([day("2024-10-26"), day("2024-10-27")]))
    complete = dict(zip(index["date"], index["complete"], strict=True))
    assert complete[date(2024, 10, 26)] and not complete[date(2024, 10, 27)]
