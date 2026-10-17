"""How noisy is observed traffic around a good forecast? Targets for demo/traffic_model.py NOISE.

Measures, in log space like the demo's lognormal and AR(1) noise, at WebTRIS sites 20025 (M3 J14)
and 19974 (M271 NB), around out-of-sample ridge forecasts (monthly refit, 105-day publication lag,
same as the backtest):

- day-wide: log(actual daytime total / forecast total), one value per test day;
- within-day: per-bin log ratio minus that day's mean, minus the average profile error for
  weekdays or weekends, then its sd and lag-1 autocorrelation, with Poisson count noise
  (var of log y about 1/y) taken off.

Residuals include ridge's own errors, so these are upper bounds on demand noise. Output is
written up in notes/observed-noise.md.

    PYTHONPATH=src python scripts/observed_noise.py
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from sotonship26 import flow_forecast as ff
from sotonship26.backtest import DAYTIME
from sotonship26.data import observed

CUTOFF = date(2025, 7, 1)
SITES = (20025, 19974)
MIN_VEH = 20.0  # skip near-empty bins, where the log ratio is mostly count noise


def oos_preds(dates: np.ndarray, y: np.ndarray, lag: int = ff.LAG_DAYS) -> dict:
    """Ridge forecast for every test day, fitted only on days published by the 1st of its month."""
    feats = ff.calendar_features(dates)
    test = [d for d in dates if d >= CUTOFF]
    out = {}
    for ym in sorted({(d.year, d.month) for d in test}):
        pub = np.flatnonzero([d <= date(*ym, 1) - timedelta(days=lag) for d in dates])
        if len(pub) < 120:
            continue
        model = ff.Ridge(features=ff.CAL_FEATURES).fit(feats.iloc[pub], y[pub])
        days = [d for d in test if (d.year, d.month) == ym]
        out.update(zip(days, ff.predict_flow(model, ff.calendar_features(days)), strict=True))
    return out


def robust_sd(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def site_noise(dates: np.ndarray, y: np.ndarray) -> dict:
    preds = oos_preds(dates, y)
    by_date = dict(zip(dates, y, strict=True))
    days = sorted(preds)
    yt = np.stack([by_date[d] for d in days])[:, DAYTIME]
    pt = np.stack([preds[d] for d in days])[:, DAYTIME]
    ok = (yt >= MIN_VEH) & (pt >= MIN_VEH)
    r = np.full(yt.shape, np.nan)
    r[ok] = np.log(yt[ok] / pt[ok])
    day_log = np.log(yt.sum(axis=1) / pt.sum(axis=1))
    within = r - np.nanmean(r, axis=1, keepdims=True)
    weekend = np.array([d.weekday() >= 5 for d in days])
    for mask in (weekend, ~weekend):
        within[mask] = within[mask] - np.nanmean(within[mask], axis=0)
    count_var = float(np.mean(1 / yt[ok]))
    w = within[~np.isnan(within)]
    a, b = within[:, :-1], within[:, 1:]
    pair = ~(np.isnan(a) | np.isnan(b))
    cov1 = float(np.mean(a[pair] * b[pair]))
    var = float(np.var(w))
    tail = float(np.mean(np.abs(w) > 3 * robust_sd(w)))
    return {
        "n_days": len(days), "first": days[0], "last": days[-1],
        "mean_veh_per_bin": float(yt.mean()),
        "day_sd": float(day_log.std()), "day_robust_sd": robust_sd(day_log),
        "day_p5": float(np.percentile(day_log, 5)), "day_p95": float(np.percentile(day_log, 95)),
        "bin_sd": float(np.sqrt(max(var - count_var, 0))),
        "bin_robust_sd": float(np.sqrt(max(robust_sd(w) ** 2 - count_var, 0))),
        "bin_rho": cov1 / (var - count_var), "count_sd": float(np.sqrt(count_var)),
        "tail_share": tail,
    }


def main() -> None:
    flows = observed.load_flows(list(SITES), date(2024, 1, 1), date(2026, 6, 30))
    for site in SITES:
        s = site_noise(*ff.site_days(flows, site))
        print(f"site {site}: {s['n_days']} test days {s['first']}..{s['last']}, "
              f"mean {s['mean_veh_per_bin']:.0f} veh/15 min")
        print(f"  day-wide log sd {s['day_sd']:.3f}, robust {s['day_robust_sd']:.3f}, "
              f"5%/95% {s['day_p5']:.3f}/{s['day_p95']:.3f}")
        print(f"  15-min log sd net of count noise {s['bin_sd']:.3f}, robust "
              f"{s['bin_robust_sd']:.3f}, lag-1 rho {s['bin_rho']:.2f} "
              f"(count noise sd {s['count_sd']:.3f}); bins beyond 3 robust sd "
              f"{s['tail_share']:.3f}")


if __name__ == "__main__":
    main()
