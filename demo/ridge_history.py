"""Does past traffic cut the M271 cruise-day forecast error? Ridge on past flows, validated at
the delay with which counts are actually published.

Same table, held-out days and monthly rolling origin as demo/webtris_backtest.py (imported, not
changed). For each forecast horizon h (days between the last count we can see and the forecast
day) every model is refit on days up to h before each month's origin, and its past-flow features
use only counts up to h days before the forecast day:

  h = 1    the council has yesterday's counts (its own counters or a live feed);
  h = 7    a weekly data drop;
  h = 28   a monthly drop;
  h = 105  WebTRIS as it is (about 3.5 months behind), the only source we have today.

Models (all forecast the 15-minute uplift over the non-cruise median, as in the backtest):

  gbm             the backtest's gradient-boosted quantile model (calendar + passengers)
  ridge           ridge regression on the same inputs, one-hot time-of-day by day type
  ridge_hist      ridge plus past flows: same day type at the latest date we can see, the
                  last four such days by hour, the 14-day background level, and a year ago
  gbm_hist        the gradient-boosted model plus the same past flows
  blend           mean of gbm and ridge_hist
  last_comparable last comparable cruise day among the days we can see (lag-aware)
  no_cruise       zero uplift

Ridge's penalty is chosen inside each training set by blocked cross-validation (contiguous
blocks of days). Features and the penalty grid were fixed on a development window
(--dev: Jul to Dec 2025, models trained on earlier days) before the single run on the test
window. Skill intervals resample whole test weeks (days in a week share weather and roadworks).

    uv run --no-project --python 3.12 --with numpy --with pandas --with scikit-learn \\
        python demo/ridge_history.py [--dev]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webtris_backtest as wb  # noqa: E402

ROOT = wb.ROOT
HORIZONS = (1, 7, 28, 105)
TEST = (wb.TEST_START, wb.END)
DEV = (date(2025, 7, 1), date(2025, 12, 31))
HIST = ["same_lag", "hour_recent", "level_recent", "year_ago"]
ALPHAS = np.logspace(0, 6, 13)
MODELS = {
    "gbm": "Learned model (gradient-boosted, calendar + passengers)",
    "ridge": "Ridge, calendar + passengers",
    "ridge_hist": "Ridge, calendar + passengers + past flows",
    "gbm_hist": "Gradient-boosted, calendar + passengers + past flows",
    "blend": "Mean of gradient-boosted and ridge with past flows",
    "last_comparable": "Last comparable cruise day we can see",
    "no_cruise": "No cruise effect",
}
LOOKBACK = 35  # days to search back for the latest same-type day


def log(msg: str) -> None:
    print(f"[ridge {datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------------------------
# Past flows, available h days before the forecast day
# --------------------------------------------------------------------------------------------


def uplift_grid(obs: pd.DataFrame, table: pd.DataFrame, bank: set[date]) -> tuple[np.ndarray, np.ndarray]:
    """Uplift over the non-cruise median for every valid sensor day (with or without a known
    call list), as a [calendar day, bin] grid from wb.START, and each calendar day's type."""
    med = table.groupby(["site", "day_type", "bin"])["median"].first()
    o = obs.copy()
    d = pd.to_datetime(o["date"])
    o["day_type"] = np.where(o["date"].isin(bank), 6, d.dt.dayofweek)
    o = o.join(med, on=["site", "day_type", "bin"])
    n_days = (wb.END - wb.START).days + 1
    grid = np.full((n_days, wb.BINS), np.nan)
    i = np.array([(x - wb.START).days for x in o["date"]])
    ok = o["median"].notna().to_numpy()
    grid[i[ok], o["bin"].to_numpy()[ok]] = (o["flow"] - o["median"]).to_numpy()[ok]
    cal = [wb.START + timedelta(k) for k in range(n_days)]
    dtype = np.array([6 if c in bank else c.weekday() for c in cal])
    return grid, dtype


def nanmean(a: np.ndarray, axis) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices give NaN, which we want
        return np.nanmean(a, axis=axis)


def history(table: pd.DataFrame, grid: np.ndarray, dtype: np.ndarray, h: int) -> pd.DataFrame:
    """Past-flow features for each table row, from counts up to h days before its date."""
    valid = np.isfinite(grid).sum(axis=1) >= 48
    by_type = {t: np.flatnonzero(valid & (dtype == t)) for t in range(7)}
    smooth = pd.DataFrame(grid.T).rolling(5, center=True, min_periods=1).mean().to_numpy().T
    dates = np.sort(table["date"].unique())
    feats = {c: np.full((len(dates), wb.BINS), np.nan) for c in HIST}
    for j, d in enumerate(dates):
        k = (d - wb.START).days
        lim = k - h
        cand = by_type[dtype[k]]
        cand = cand[(cand <= lim) & (cand > lim - LOOKBACK)]
        if len(cand):
            feats["same_lag"][j] = grid[cand[-1]]
            last4 = grid[cand[-4:]]
            hourly = nanmean(last4.reshape(len(last4), 24, 4), axis=(0, 2))
            feats["hour_recent"][j] = np.repeat(hourly, 4)
        if lim >= 0:
            win = grid[max(lim - 13, 0):lim + 1, 24:80]
            if np.isfinite(win).any():
                feats["level_recent"][j] = nanmean(win, axis=None)
        if k - 364 >= 0 and h <= 364 and valid[k - 364]:
            feats["year_ago"][j] = smooth[k - 364]
    row = pd.Series(np.arange(len(dates)), index=dates)[table["date"]].to_numpy()
    b = table["bin"].to_numpy()
    return pd.DataFrame({c: feats[c][row, b] for c in HIST}, index=table.index)


# --------------------------------------------------------------------------------------------
# Ridge
# --------------------------------------------------------------------------------------------


def design(df: pd.DataFrame, hist: bool) -> np.ndarray:
    n, r = len(df), np.arange(len(df))
    b = df["bin"].to_numpy()
    hr = b // 4
    dt = df["day_type"].to_numpy()
    dc = np.select([dt <= 4, dt == 5], [0, 1], 2)  # weekday, Saturday, Sunday or bank holiday
    we = (dc > 0).astype(int)
    tod = np.zeros((n, 3 * wb.BINS))
    tod[r, dc * wb.BINS + b] = 1
    school = np.zeros((n, 24))
    school[r, hr] = df["school_hol"].to_numpy()
    month = np.zeros((n, 12))
    month[r, df["month"].to_numpy() - 1] = 1
    ko = df["since_ko"].to_numpy()
    near = np.isfinite(ko) & (ko >= -3) & (ko < 5)
    match = np.zeros((n, 8))
    match[np.flatnonzero(near), (np.floor(ko[near]) + 3).astype(int)] = 1
    pax = np.zeros((n, 96))
    pax[r, we * 24 + hr] = df["pax_east_k"].to_numpy()
    pax[r, 48 + we * 24 + hr] = df["pax_west_k"].to_numpy()
    parts = [tod, school, month, match, pax]
    if hist:
        past = np.zeros((n, 6 * len(HIST)))
        miss = np.zeros((n, len(HIST)))
        for j, c in enumerate(HIST):
            v = df[c].to_numpy()
            m = np.isnan(v)
            past[r, j * 6 + hr // 4] = np.where(m, 0.0, v)
            miss[:, j] = m
        parts += [past, miss]
    return np.hstack(parts)


def blocks(dates: pd.Series, k: int = wb.FOLDS) -> list[np.ndarray]:
    return [dates.isin(blk).to_numpy() for blk in np.array_split(np.sort(dates.unique()), k)]


class Ridge:
    """Ridge on standardised features; the penalty is chosen by blocked CV on mean absolute error."""

    def __init__(self, hist: bool, alpha: float | None = None):
        self.hist, self.alpha = hist, alpha

    def fit(self, train: pd.DataFrame) -> Ridge:
        x, y = design(train, self.hist), train["uplift"].to_numpy()
        self.mu, self.sd = x.mean(axis=0), x.std(axis=0)
        self.sd[self.sd == 0] = 1.0
        z = (x - self.mu) / self.sd
        if self.alpha is None:
            err = np.zeros(len(ALPHAS))
            for test in blocks(train["date"]):
                zt, yt = z[~test], y[~test]
                w, v = np.linalg.eigh(zt.T @ zt)
                proj = v.T @ (zt.T @ (yt - yt.mean()))
                for a, alpha in enumerate(ALPHAS):
                    beta = v @ (proj / (w + alpha))
                    err[a] += np.abs(y[test] - yt.mean() - z[test] @ beta).sum()
            self.alpha = float(ALPHAS[int(np.argmin(err))])
            self.edge = self.alpha in (ALPHAS[0], ALPHAS[-1])
        self.y0 = y.mean()
        self.beta = np.linalg.solve(z.T @ z + self.alpha * np.eye(z.shape[1]), z.T @ (y - self.y0))
        return self

    def point(self, df: pd.DataFrame) -> np.ndarray:
        return (design(df, self.hist) - self.mu) / self.sd @ self.beta + self.y0


class GBMPoint:
    """Median gradient-boosted model; drops features with no values in the training days (the
    year-ago flow before a year of counts exists)."""

    def __init__(self, features: list[str]):
        self.features = features

    def fit(self, train: pd.DataFrame) -> GBMPoint:
        use = [f for f in self.features if train[f].notna().any()]
        self.m = wb.GBMQuantile(use, [0.5]).fit(train)
        return self

    def point(self, df: pd.DataFrame) -> np.ndarray:
        return self.m.point(df)


class LastComparableLag(wb.LastComparable):
    """The backtest's baseline, but only among days at least h days before the forecast day."""

    def __init__(self, h: int):
        self.h = h

    def point(self, df: pd.DataFrame) -> np.ndarray:
        out = np.full(len(df), np.nan)
        for d, idx in df.groupby("date").indices.items():
            row = self.days[self.days["date"] == d].iloc[0].to_dict()
            row["date"] = d - timedelta(self.h - 1)  # comparable_day looks at days before this
            ref = wb.comparable_day(row, self.days)
            if ref is not None:
                out[idx] = self.profile.loc[ref].reindex(df["bin"].iloc[idx]).fillna(0.0).to_numpy()
        return out


# --------------------------------------------------------------------------------------------
# Backtest at one horizon
# --------------------------------------------------------------------------------------------


def frames(name: str, train: pd.DataFrame, test: pd.DataFrame, point: np.ndarray,
           oof: np.ndarray, q: np.ndarray | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """15-minute and daily forecasts with 80% bands from past (out-of-fold) errors, as in the
    backtest; the gradient-boosted model's 15-minute band comes from its own quantiles."""
    by_hour, r_day = wb.residuals(train, oof)
    rows = test[["date", "bin", "uplift", "cruise", "day_type"]].assign(point=point)
    if q is not None:
        rows["lo"], rows["hi"] = q[:, 1], q[:, 5]
    else:
        hour = rows["bin"].to_numpy() // 4
        lo, hi = np.empty(len(rows)), np.empty(len(rows))
        for hh in range(24):
            k = hour == hh
            lo[k] = point[k] + np.quantile(by_hour[hh], 0.1)
            hi[k] = point[k] + np.quantile(by_hour[hh], 0.9)
        rows["lo"], rows["hi"] = lo, hi
    g = rows.groupby("date")
    days = pd.DataFrame({"uplift": wb.daily(rows, "uplift"), "point": wb.daily(rows, "point"),
                         "cruise": g["cruise"].first(), "day_type": g["day_type"].first()})
    days["lo"] = days["point"] + np.quantile(r_day, 0.1)
    days["hi"] = days["point"] + np.quantile(r_day, 0.9)
    return rows.assign(model=name), days.reset_index().assign(model=name)


def run_horizon(args) -> dict:
    table, grid, dtype, h, window = args
    t0 = time.time()
    hist = history(table, grid, dtype, h)
    tab = pd.concat([table, hist], axis=1)
    feats = wb.CONTEXT + wb.CRUISE
    test_days = sorted(d for d in tab["date"].unique() if window[0] <= d <= window[1])
    origins = sorted({date(d.year, d.month, 1) for d in test_days})
    rows, days, alphas = [], [], []
    for i, origin in enumerate(origins):
        nxt = origins[i + 1] if i + 1 < len(origins) else window[1] + timedelta(days=1)
        train = tab[tab["date"] < origin - timedelta(h - 1)]
        test = tab[(tab["date"] >= origin) & (tab["date"] < nxt)]
        out = {}
        gq = wb.GBMQuantile(feats).fit(train)
        oof_g = wb.oof_points(lambda: wb.GBMQuantile(feats, [0.5]), train)
        out["gbm"] = (gq.point(test), oof_g, gq.quantiles(test))
        for name, use_hist in (("ridge", False), ("ridge_hist", True)):
            r = Ridge(use_hist).fit(train)
            alphas.append({"origin": origin.isoformat(), "model": name, "alpha": r.alpha,
                           "at_grid_edge": r.edge})
            out[name] = (r.point(test), wb.oof_points(lambda r=r, u=use_hist: Ridge(u, r.alpha), train), None)
        gh = GBMPoint(feats + HIST).fit(train)
        out["gbm_hist"] = (gh.point(test), wb.oof_points(lambda: GBMPoint(feats + HIST), train), None)
        out["blend"] = (0.5 * (out["gbm"][0] + out["ridge_hist"][0]),
                        0.5 * (out["gbm"][1] + out["ridge_hist"][1]), None)
        lc = LastComparableLag(h).fit(tab)
        out["last_comparable"] = (np.nan_to_num(lc.point(test)), lc.point(train), None)
        out["no_cruise"] = (np.zeros(len(test)), np.zeros(len(train)), None)
        for name, (p, oof, q) in out.items():
            r_, d_ = frames(name, train, test, p, oof, q)
            rows.append(r_)
            days.append(d_)
        log(f"h={h:3d} origin {origin}: train {train['date'].nunique()} days, "
            f"test {test['date'].nunique()} days")
    rows, days = pd.concat(rows, ignore_index=True), pd.concat(days, ignore_index=True)
    avail = {c: round(float(hist.loc[tab["date"].isin(test_days), c].notna().mean()), 3) for c in HIST}
    return {"h": h, "rows": rows, "days": days, "alphas": alphas, "available": avail,
            "seconds": round(time.time() - t0)}


# --------------------------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------------------------


def score(f: pd.DataFrame) -> dict:
    inside = (f["uplift"] >= f["lo"]) & (f["uplift"] <= f["hi"])
    return {"mae": round(float((f["uplift"] - f["point"]).abs().mean()), 1),
            "coverage80": round(float(inside.mean()), 3),
            "band_width": round(float((f["hi"] - f["lo"]).mean()), 1)}


def week_bootstrap(err: pd.DataFrame, a: str, b: str, n: int = 4000, seed: int = 26) -> dict:
    """Skill of a over b (1 - MAE_a / MAE_b) with a 90% interval resampling whole ISO weeks."""
    wk = pd.Series(["{}-{:02d}".format(*d.isocalendar()[:2]) for d in err.index], index=err.index)
    weeks = sorted(set(wk))
    sa = np.array([err.loc[wk == w, a].sum() for w in weeks])
    sb = np.array([err.loc[wk == w, b].sum() for w in weeks])
    idx = np.random.default_rng(seed).integers(0, len(weeks), size=(n, len(weeks)))
    skill = 1 - sa[idx].sum(axis=1) / sb[idx].sum(axis=1)
    lo, hi = np.quantile(skill, [0.05, 0.95])
    return {"skill": round(float(1 - sa.sum() / sb.sum()), 3), "ci90": [round(float(lo), 3), round(float(hi), 3)],
            "weeks": len(weeks), "clear_of_zero": bool(lo > 0 or hi < 0)}


def summarise(res: dict) -> dict:
    rows, days = res["rows"], res["days"]
    out = {"h": res["h"], "available": res["available"], "seconds": res["seconds"],
           "alphas": res["alphas"], "per_day": {}, "per_15min": {}, "skill": {}}
    for level, f in (("per_day", days), ("per_15min", rows)):
        for sub, pick in (("all", f), ("cruise_days", f[f["cruise"] == 1])):
            out[level][sub] = {"days": int(pick["date"].nunique()),
                               **{m: score(pick[pick["model"] == m]) for m in MODELS}}
    err_d = days.assign(e=(days["uplift"] - days["point"]).abs()).pivot(index="date", columns="model", values="e")
    err_q = rows.assign(e=(rows["uplift"] - rows["point"]).abs()).pivot_table(
        index="date", columns="model", values="e", aggfunc="mean")
    for level, err in (("per_day", err_d), ("per_15min", err_q)):
        out["skill"][level] = {f"{a}_vs_{b}": week_bootstrap(err, a, b) for a, b in (
            ("ridge_hist", "gbm"), ("gbm_hist", "gbm"), ("blend", "gbm"), ("ridge_hist", "ridge"),
            ("ridge", "gbm"), ("ridge_hist", "last_comparable"), ("gbm", "last_comparable"))}
    return out


# --------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------


def write_doc(r: dict, path: Path) -> None:
    hs = r["horizons"]
    L = [f"# {r['title']}", "",
         f"Generated {r['generated']} by `python demo/ridge_history.py`. "
         f"Test window {r['window'][0]} to {r['window'][1]} ({hs[0]['per_day']['all']['days']} days, "
         f"{hs[0]['per_day']['cruise_days']['days']} with turnarounds), M271 northbound. Data and target as in "
         "[backtest.md](backtest.md). Features and the penalty grid were fixed on a Jul to Dec 2025 "
         "development window before this single run.", "",
         "Horizon h = days between the newest count a forecaster can see and the forecast day. Every "
         "model is refit on days at least h before each month's origin. WebTRIS publishes about 105 "
         "days late, so **h = 105 is what we can do today**; h = 1 needs the council's own counts.", "",
         "## Mean absolute error, vehicles per day (all test days)", "",
         "| model | " + " | ".join(f"h = {x['h']}" for x in hs) + " |",
         "|---|" + "---|" * len(hs)]
    for m, label in MODELS.items():
        L.append(f"| {label} | " + " | ".join(f"{x['per_day']['all'][m]['mae']:,.0f}" for x in hs) + " |")
    L += ["", "## Mean absolute error, vehicles per 15 minutes", "",
          "| model | " + " | ".join(f"h = {x['h']}" for x in hs) + " |", "|---|" + "---|" * len(hs)]
    for m, label in MODELS.items():
        L.append(f"| {label} | " + " | ".join(f"{x['per_15min']['all'][m]['mae']:.1f}" for x in hs) + " |")
    L += ["", "## Skill (1 - MAE / MAE of the comparison), 90% interval from resampling test weeks", "",
          "| comparison | level | " + " | ".join(f"h = {x['h']}" for x in hs) + " |",
          "|---|---|" + "---|" * len(hs)]
    for key in hs[0]["skill"]["per_day"]:
        for level in ("per_day", "per_15min"):
            cells = []
            for x in hs:
                s = x["skill"][level][key]
                cells.append(f"{s['skill']:+.1%} ({s['ci90'][0]:+.1%} to {s['ci90'][1]:+.1%})"
                             + ("" if s["clear_of_zero"] else " ns"))
            L.append(f"| {key.replace('_vs_', ' vs ')} | {level.replace('_', ' ')} | " + " | ".join(cells) + " |")
    L += ["", "`ns`: the interval includes zero.", "",
          "## 80% band coverage, per day / per 15 minutes", "",
          "| model | " + " | ".join(f"h = {x['h']}" for x in hs) + " |", "|---|" + "---|" * len(hs)]
    for m, label in MODELS.items():
        L.append(f"| {label} | " + " | ".join(
            f"{x['per_day']['all'][m]['coverage80']:.0%} / {x['per_15min']['all'][m]['coverage80']:.0%}"
            for x in hs) + " |")
    L += ["", "## Past-flow features available on test days", "",
          "| feature | " + " | ".join(f"h = {x['h']}" for x in hs) + " |", "|---|" + "---|" * len(hs)]
    for c in HIST:
        L.append(f"| {c} | " + " | ".join(f"{x['available'][c]:.0%}" for x in hs) + " |")
    edges = sum(a["at_grid_edge"] for x in hs for a in x["alphas"])
    L += ["", f"Ridge penalties chosen: {sorted({a['alpha'] for x in hs for a in x['alphas']})}; "
          f"{edges} of {sum(len(x['alphas']) for x in hs)} fits at the edge of the grid.", "",
          "## Reading it", ""] + [f"- {v}" for v in r["verdict"]] + ["", "## Limits", ""] + [
          f"- {x}" for x in r["limits"]]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def verdict(hs: list[dict]) -> list[str]:
    out = []
    for x in hs:
        s = x["skill"]["per_day"]
        best = min(MODELS, key=lambda m: x["per_day"]["all"][m]["mae"])
        rh, gh, bl = s["ridge_hist_vs_gbm"], s["gbm_hist_vs_gbm"], s["blend_vs_gbm"]
        out.append(
            f"h = {x['h']}: best per day is {MODELS[best].lower()} ({x['per_day']['all'][best]['mae']:,.0f}). "
            f"Against the gradient-boosted model, ridge with past flows {rh['skill']:+.1%} "
            f"({rh['ci90'][0]:+.1%} to {rh['ci90'][1]:+.1%}), gradient-boosted with past flows "
            f"{gh['skill']:+.1%} ({gh['ci90'][0]:+.1%} to {gh['ci90'][1]:+.1%}), blend {bl['skill']:+.1%} "
            f"({bl['ci90'][0]:+.1%} to {bl['ci90'][1]:+.1%}).")
    return out


LIMITS = [
    "One road (M271 northbound) and one half-year of test days; the result may not carry to the "
    "dock roads, which have no public counts.",
    "The non-cruise median the uplift is measured from uses days up to the test window for every "
    "horizon, so h = 105 is slightly optimistic for January.",
    "Days without an archived cruise list are missing from training and testing, but their counts "
    "still feed the past-flow features.",
    "Development-window choices: the four past-flow features, a 35-day look-back for the latest "
    "same-type day, the 14-day background window and a 1 to 1,000,000 penalty grid.",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dev", action="store_true", help="development window Jul-Dec 2025 (no doc)")
    ap.add_argument("--horizons", default=",".join(map(str, HORIZONS)))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    window = DEV if a.dev else TEST
    horizons = [int(x) for x in a.horizons.split(",")]
    started = time.time()
    log("loading the backtest table")
    obs, _ = wb.load_webtris()
    days, _, _ = wb.load_calls()
    bank = wb.bank_holidays()
    football, _ = wb.sfc_home_matches()
    table, _ = wb.build_table(obs, days, bank, football)
    grid, dtype = uplift_grid(obs, table, bank)
    n_test = sum(window[0] <= d <= window[1] for d in table["date"].unique())
    log(f"{table['date'].nunique()} days in the table, {n_test} in the window {window[0]} to {window[1]}")
    os.environ["OMP_NUM_THREADS"] = str(max(1, (os.cpu_count() or 4) // min(a.workers, len(horizons))))
    jobs = [(table, grid, dtype, h, window) for h in horizons]
    with ProcessPoolExecutor(max_workers=min(a.workers, len(horizons))) as pool:
        results = list(pool.map(run_horizon, jobs))
    hs = [summarise(x) for x in sorted(results, key=lambda x: x["h"])]
    report = {"title": "Past flows and publication delay: does ridge on past traffic cut the M271 "
                       "cruise-day forecast error?",
              "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
              "script": "demo/ridge_history.py", "dev": a.dev,
              "window": [window[0].isoformat(), window[1].isoformat()], "models": MODELS,
              "horizons": hs, "verdict": verdict(hs), "limits": LIMITS,
              "runtime_s": round(time.time() - started)}
    out = ROOT / "demo" / "out" / ("ridge_history_dev.json" if a.dev else "ridge_history.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, separators=(",", ":"), default=float), encoding="utf-8")
    if not a.dev:
        write_doc(report, ROOT / "docs" / "ridge-history.md")
    log(f"wrote {out.relative_to(ROOT)} in {report['runtime_s']} s")
    for v in report["verdict"]:
        log("  " + v)


if __name__ == "__main__":
    sys.exit(main())
