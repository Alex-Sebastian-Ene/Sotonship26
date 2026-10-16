"""Forecast everyday traffic on the dock approaches for a planning date, learned from WebTRIS.

The planning question: an officer looks at a date weeks ahead. What 15-minute traffic should the
M271 / M3 approaches carry on that day before any cruise effect? WebTRIS publishes about 3.5
months late, so a forecast for day D may only use counts from before D - ``lag_days``.

Models, all scored on days after ``cutoff`` with the same lag rule:
  last_year     the same weekday 52 weeks earlier (the planner's usual rule of thumb)
  recent_median median of the same weekday over the 4 newest weeks that are published by then
  planner_rule  last_year when published, else recent_median
  ridge         learned: per-bin ridge regression on calendar features (weekday x season,
                bank holidays, Christmas week, trend), refit at each test month on published data
Intervals: split conformal on the newest published 20% of days before each refit.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sotonship26.backtest import DAYTIME, Ridge, conformal_halfwidth
from sotonship26.uplift import BANK_HOLIDAYS, day_matrix

ROOT = Path(__file__).resolve().parents[2]
LAG_DAYS = 105


def calendar_features(dates) -> pd.DataFrame:
    """Calendar features per date. Weekday dummies are interacted with an annual cycle so the
    weekend profile can change with the season."""
    idx = pd.to_datetime(pd.Index(dates))
    doy = idx.dayofyear.to_numpy() / 365.25 * 2 * np.pi
    out = pd.DataFrame(index=pd.Index(dates, name="date"))
    for k in (1, 2):
        out[f"sin{k}"] = np.sin(k * doy)
        out[f"cos{k}"] = np.cos(k * doy)
    for wd in range(7):
        is_wd = (idx.weekday == wd).astype(float)
        out[f"wd{wd}"] = is_wd
        out[f"wd{wd}_sin"] = is_wd * np.sin(doy)
        out[f"wd{wd}_cos"] = is_wd * np.cos(doy)
    out["bank_holiday"] = [float(d in BANK_HOLIDAYS) for d in dates]
    out["christmas"] = [float((d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 2))
                        for d in dates]
    out["trend"] = (idx - pd.Timestamp("2024-01-01")).days.to_numpy() / 365.25
    return out


CAL_FEATURES = tuple(calendar_features([date(2024, 1, 1)]).columns)


def site_days(flows: pd.DataFrame, site: int) -> tuple[np.ndarray, np.ndarray]:
    """Dates and (n_days x 96) flows for complete, good-quality days at one site."""
    index, mats = day_matrix(flows[flows["site_id"] == site])
    if site not in mats:
        return np.array([]), np.empty((0, 96))
    ok = (index["good_day"] & index["complete"]).to_numpy()
    return index["date"].to_numpy()[ok], mats[site][ok]


def last_year(target: date, by_date: dict, lag: int) -> np.ndarray | None:
    ref = target - timedelta(days=364)
    if (target - ref).days < lag:
        return None
    return by_date.get(ref)


def recent_median(target: date, by_date: dict, lag: int) -> np.ndarray | None:
    newest = target - timedelta(days=lag)
    rows = [by_date[d] for d in (newest - timedelta(days=i) for i in range(28))
            if d in by_date and d.weekday() == target.weekday()]
    return np.median(np.stack(rows), axis=0) if len(rows) >= 2 else None


def planner_rule(target: date, by_date: dict, lag: int) -> np.ndarray | None:
    """What a planner would do: same weekday last year if published, else the recent median."""
    p = last_year(target, by_date, lag)
    return p if p is not None else recent_median(target, by_date, lag)


BASELINES = (("last_year", last_year), ("recent_median", recent_median),
             ("planner_rule", planner_rule))


def backtest_site(site: int, dates: np.ndarray, y: np.ndarray, cutoff: date,
                  lag: int = LAG_DAYS) -> pd.DataFrame:
    """Score the three models on every test day at one site, refitting ridge once a month."""
    by_date = dict(zip(dates, y, strict=True))
    feats = calendar_features(dates)
    test_days = [d for d in dates if d >= cutoff]
    preds = {m: {} for m in (*(b for b, _ in BASELINES), "ridge")}
    halves = {m: {} for m in preds}
    months = sorted({(d.year, d.month) for d in test_days})
    for year, month in months:
        first = date(year, month, 1)
        published = np.array([d <= first - timedelta(days=lag) for d in dates])
        if published.sum() < 120:
            continue
        pub_idx = np.flatnonzero(published)
        n_cal = max(20, int(len(pub_idx) * 0.2))
        proper, cal = pub_idx[:-n_cal], pub_idx[-n_cal:]
        model = Ridge(features=CAL_FEATURES).fit(feats.iloc[proper], y[proper])
        half_ridge = conformal_halfwidth(y[cal] - model.predict(feats.iloc[cal]))
        final = Ridge(lam=model.lam, features=CAL_FEATURES).fit(feats.iloc[pub_idx], y[pub_idx])
        # baseline intervals from their errors on the newest published days they can forecast
        base_resid = {b: [] for b, _ in BASELINES}
        for i in pub_idx[::-1]:
            for name, fn in BASELINES:
                p = fn(dates[i], by_date, lag)
                if p is not None and len(base_resid[name]) < n_cal:
                    base_resid[name].append(y[i] - p)
        month_days = [d for d in test_days if (d.year, d.month) == (year, month)]
        month_pred = final.predict(calendar_features(month_days))
        for d, p in zip(month_days, month_pred, strict=True):
            preds["ridge"][d], halves["ridge"][d] = p, half_ridge
            for name, fn in BASELINES:
                bp = fn(d, by_date, lag)
                if bp is not None and len(base_resid[name]) >= 10:
                    preds[name][d] = bp
                    halves[name][d] = conformal_halfwidth(np.stack(base_resid[name]))
    rows = []
    for base, _ in BASELINES:
        common = sorted(set(preds[base]) & set(preds["ridge"]))
        if len(common) < 10:
            continue
        yt = np.stack([by_date[d] for d in common])[:, DAYTIME]
        scores = {}
        for name in (base, "ridge"):
            pt = np.stack([preds[name][d] for d in common])[:, DAYTIME]
            h = np.stack([halves[name][d] for d in common])[:, DAYTIME]
            err = np.abs(yt - pt)
            scores[name] = err.mean()
            rows.append({"site_id": site, "versus": base, "model": name,
                         "n_test_days": len(common), "first_test_day": str(common[0]),
                         "last_test_day": str(common[-1]),
                         "mae_veh_per_15min": float(err.mean()),
                         "wape_pct": float(100 * err.sum() / max(yt.sum(), 1)),
                         "coverage80": float((err <= h).mean()),
                         "width80_veh": float(2 * h.mean())})
        rows[-1]["skill_vs_baseline"] = float(1 - scores["ridge"] / scores[base])
    table = pd.DataFrame(rows)
    return table


def forecast(dates: np.ndarray, y: np.ndarray, targets: list[date]) -> pd.DataFrame:
    """Fit ridge on every published day and forecast ``targets`` with 80% intervals."""
    n_cal = max(20, int(len(dates) * 0.2))
    feats = calendar_features(dates)
    model = Ridge(features=CAL_FEATURES).fit(feats.iloc[:-n_cal], y[:-n_cal])
    half = conformal_halfwidth(y[-n_cal:] - model.predict(feats.iloc[-n_cal:]))
    final = Ridge(lam=model.lam, features=CAL_FEATURES).fit(feats, y)
    pred = final.predict(calendar_features(targets))
    rows = [pd.DataFrame({"date": d, "tod_bin": np.arange(96), "flow_veh": p,
                          "lo80": np.maximum(p - half, 0), "hi80": p + half})
            for d, p in zip(targets, pred, strict=True)]
    return pd.concat(rows, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    from sotonship26.data import observed
    from sotonship26.run_backtest import md_table

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    p.add_argument("--cutoff", type=date.fromisoformat, default=date(2025, 7, 1))
    p.add_argument("--lag", type=int, default=LAG_DAYS)
    p.add_argument("--sites", type=int, nargs="*", default=list(observed.SITES))
    p.add_argument("--forecast", type=date.fromisoformat, nargs=2, metavar=("FROM", "TO"),
                   help="also write runs/flow_forecast/<site>.csv for these dates")
    args = p.parse_args(argv)
    flows = observed.load_flows(args.sites, args.start, args.end)
    if args.forecast:
        out = ROOT / "runs" / "flow_forecast"
        out.mkdir(parents=True, exist_ok=True)
        targets = list(pd.date_range(*args.forecast, freq="D").date)
        for site in args.sites:
            dates, y = site_days(flows, site)
            if len(dates) >= 200:
                forecast(dates, y, targets).to_csv(out / f"{site}.csv", index=False)
                print(f"forecast written: {out / f'{site}.csv'}")
    tables = []
    for site in args.sites:
        dates, y = site_days(flows, site)
        t = backtest_site(site, dates, y, args.cutoff, args.lag)
        print(f"site {site}: {len(dates)} usable days, {len(t)} model rows")
        if len(t):
            tables.append(t)
    if not tables:
        print("No site had enough published days to score.")
        return 1
    table = pd.concat(tables, ignore_index=True)
    out_dir = ROOT / "notes"
    table.to_csv(out_dir / "flow_forecast_table.csv", index=False)
    cols = ["site_id", "versus", "model", "n_test_days", "mae_veh_per_15min",
            "skill_vs_baseline", "wape_pct", "coverage80", "width80_veh"]
    text = "\n".join([
        "# Everyday traffic forecast on the dock approaches: learned model vs baselines",
        "",
        f"Generated {datetime.now():%a %d %b %Y %H:%M} by `python -m sotonship26.flow_forecast "
        f"--cutoff {args.cutoff} --lag {args.lag}`. Data: National Highways WebTRIS 15-minute "
        "counts, " + f"{args.start} to {args.end} (Contains National Highways data, OGL v3.0).",
        "",
        f"Each test day after {args.cutoff} is forecast using only counts published "
        f"{args.lag} days before it, because WebTRIS lags about 3.5 months. Scores cover "
        "05:00-22:00. Ridge is compared with each baseline on the days both can forecast "
        "(sensor gaps differ). `skill` = 1 - MAE(ridge) / MAE(baseline): above 0 means the "
        "learned model wins. `coverage80` should be near 0.80.",
        "",
        md_table(table[cols]),
        "",
        "![One test week at M3 J14](figures/flow_forecast_20025.png)",
        "",
        "Reading it: sites with a long, continuous record (20025 M3 J14, 19974 M271 NB) are the "
        "trustworthy results. 20313/20605 have under 30 comparable test days and patchy sensor "
        "data, so their scores are noise. 7588 and 19796 have no test days after the cutoff.",
        "",
        "Cruise days are not removed (no historic cruise list yet, see SOT-21), so these "
        "forecasts are 'typical traffic including the average cruise effect'. Forward "
        "forecasts for any date range: `--forecast FROM TO` writes runs/flow_forecast/<site>.csv "
        "(date, tod_bin, flow_veh, lo80, hi80).",
    ])
    (out_dir / "flow-forecast.md").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
