"""Backtest: does a learned model predict cruise-day traffic uplift better than simple baselines?

Each model predicts a day's uplift at one sensor as a vector of 96 fifteen-minute values, from
that day's cruise calls only (never from the day's own traffic). Models are trained on days
before ``cutoff`` and scored on days after it.

Models
  zero        no-cruise median: predicts no uplift (the reference profile itself)
  last_day    the brief's baseline: the uplift seen on the most comparable earlier cruise day
  pax_linear  uplift per bin proportional to that day's turnaround passengers
  ridge       learned: per-bin ridge regression on passengers by dock side, weekend and ship
              timing, with the penalty picked on a later validation slice of the training period

Every model gets an 80% interval by split conformal prediction: hold out the last part of the
training period, take the 80th percentile of absolute errors there, per hour of day.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BINS = 96
DAYTIME = slice(5 * 4, 22 * 4)  # 05:00-22:00, where cruise traffic happens
COVERAGE = 0.8
FEATURES = ["pax_western", "pax_eastern", "pax_unknown", "pax_weekend", "pax_dep_shift",
            "pax_arr_shift"]


def day_features(days: pd.DataFrame, calls: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per date: passengers in thousands by dock side, plus timing of the ships.

    ``pax_dep_shift`` / ``pax_arr_shift`` are total passengers times the passenger-weighted mean
    departure (arrival) hour, centred on 17:00 (07:00), so a late sailing moves the evening peak.
    """
    d = days.assign(date=pd.to_datetime(days["date"]).dt.date).set_index("date")
    out = pd.DataFrame(index=d.index)
    for side in ("western", "eastern", "unknown"):
        col = d[f"pax_{side}"] if f"pax_{side}" in d else pd.Series(0.0, index=d.index)
        out[f"pax_{side}"] = col.astype(float) / 1000  # NaN = a call of unknown size
    total = out[["pax_western", "pax_eastern", "pax_unknown"]].sum(axis=1, skipna=False)
    weekend = pd.Series([x.weekday() >= 5 for x in out.index], index=out.index)
    out["pax_weekend"] = total * weekend
    out["pax_dep_shift"] = 0.0
    out["pax_arr_shift"] = 0.0
    if calls is not None and len(calls):
        c = calls.dropna(subset=["passengers"]).copy()
        c["date"] = c["arrival"].dt.date  # same day key as cruise_history.cruise_days
        dep = c["departure"].dt.tz_convert("Europe/London")
        arr = c["arrival"].dt.tz_convert("Europe/London")
        c["dep_h"] = dep.dt.hour + dep.dt.minute / 60 - 17
        c["arr_h"] = arr.dt.hour + arr.dt.minute / 60 - 7
        g = c.groupby("date")
        w = g["passengers"].sum()
        dep_mean = g.apply(lambda x: np.average(x["dep_h"], weights=x["passengers"]))
        arr_mean = g.apply(lambda x: np.average(x["arr_h"], weights=x["passengers"]))
        common = out.index.intersection(w.index)
        out.loc[common, "pax_dep_shift"] = (w / 1000 * dep_mean).reindex(common).to_numpy()
        out.loc[common, "pax_arr_shift"] = (w / 1000 * arr_mean).reindex(common).to_numpy()
    out["pax_total"] = total
    out["n_calls"] = d["n_calls"]
    out["weekend"] = weekend
    out["western_heavy"] = out["pax_western"] >= out["pax_eastern"]
    return out


def site_targets(uplift: pd.DataFrame, site: int) -> tuple[np.ndarray, np.ndarray]:
    """Dates and (n_days x 96) uplift for one site, keeping only complete, covered days."""
    u = uplift[(uplift["site_id"] == site) & uplift["covered"]]
    wide = u.pivot_table(index="date", columns="tod_bin", values="uplift_veh", aggfunc="first")
    wide = wide.reindex(columns=range(BINS)).dropna()
    return wide.index.to_numpy(), wide.to_numpy(dtype=float)


# --- models ---------------------------------------------------------------------------------


class Zero:
    name = "zero"

    def fit(self, feats: pd.DataFrame, y: np.ndarray) -> Zero:
        return self

    def predict(self, feats: pd.DataFrame) -> np.ndarray:
        return np.zeros((len(feats), BINS))


class LastComparableDay:
    """Most recent training cruise day with the same weekend flag and dominant dock side,
    preferring one whose passenger total is within 25%; zero on days without ships."""

    name = "last_day"

    def fit(self, feats: pd.DataFrame, y: np.ndarray) -> LastComparableDay:
        cruise = feats["pax_total"].to_numpy() > 0
        self.feats, self.y = feats[cruise], y[cruise]
        return self

    def predict(self, feats: pd.DataFrame) -> np.ndarray:
        out = np.zeros((len(feats), BINS))
        for i, (_, row) in enumerate(feats.iterrows()):
            if row["pax_total"] <= 0 or len(self.feats) == 0:
                continue
            same = ((self.feats["weekend"] == row["weekend"])
                    & (self.feats["western_heavy"] == row["western_heavy"])).to_numpy()
            close = np.abs(self.feats["pax_total"].to_numpy() / row["pax_total"] - 1) <= 0.25
            for mask in (same & close, same, np.ones(len(self.feats), bool)):
                if mask.any():
                    out[i] = self.y[np.flatnonzero(mask)[-1]]
                    break
        return out


class PaxLinear:
    """uplift[bin] = beta[bin] * thousands of turnaround passengers (least squares, no bias)."""

    name = "pax_linear"

    def fit(self, feats: pd.DataFrame, y: np.ndarray) -> PaxLinear:
        p = feats["pax_total"].to_numpy()
        self.beta = (p @ y) / max(p @ p, 1e-9)
        return self

    def predict(self, feats: pd.DataFrame) -> np.ndarray:
        return np.outer(feats["pax_total"].to_numpy(), self.beta)


@dataclass
class Ridge:
    """Multi-output ridge: Y (days x 96) ~ [1, standardised features] @ B, B smoothed over time."""

    lam: float | None = None
    features: tuple[str, ...] = tuple(FEATURES)
    grid: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0)
    smooth: np.ndarray = field(default_factory=lambda: np.array([1, 2, 3, 2, 1]) / 9)
    name: str = "ridge"

    def _design(self, feats: pd.DataFrame) -> np.ndarray:
        x = (feats[list(self.features)].to_numpy(dtype=float) - self.mu) / self.sd
        return np.column_stack([np.ones(len(x)), x])

    def _solve(self, feats: pd.DataFrame, y: np.ndarray, lam: float) -> np.ndarray:
        raw = feats[list(self.features)].to_numpy(dtype=float)
        self.mu = raw.mean(axis=0)
        sd = raw.std(axis=0)
        self.sd = np.where(sd > 1e-9, sd, 1.0)  # constant in training: leave unscaled, not x1e9
        x = self._design(feats)
        penalty = lam * np.eye(x.shape[1])
        penalty[0, 0] = 0  # never shrink the intercept
        b = np.linalg.solve(x.T @ x + penalty, x.T @ y)
        pad = len(self.smooth) // 2
        wrapped = np.concatenate([b[:, -pad:], b, b[:, :pad]], axis=1)
        return np.stack([np.convolve(row, self.smooth, mode="valid") for row in wrapped])

    def fit(self, feats: pd.DataFrame, y: np.ndarray) -> Ridge:
        if self.lam is None:
            cut = int(len(feats) * 0.75)
            scores = {}
            for lam in self.grid:
                self.b = self._solve(feats.iloc[:cut], y[:cut], lam)
                err = np.abs(self.predict(feats.iloc[cut:]) - y[cut:])[:, DAYTIME]
                scores[lam] = err.mean()
            self.lam = min(scores, key=scores.get)
            self.cv_scores = scores
        self.b = self._solve(feats, y, self.lam)
        return self

    def predict(self, feats: pd.DataFrame) -> np.ndarray:
        return self._design(feats) @ self.b


MODELS = (Zero, LastComparableDay, PaxLinear, Ridge)


# --- conformal intervals and scoring ---------------------------------------------------------


def conformal_halfwidth(resid: np.ndarray, coverage: float = COVERAGE) -> np.ndarray:
    """Per-bin half-width from |residuals| on calibration days, pooled by hour of day."""
    a = np.abs(resid).reshape(len(resid), 24, 4)
    n = a.shape[0] * 4
    q = min(1.0, np.ceil((n + 1) * coverage) / n)
    by_hour = np.quantile(a.transpose(1, 0, 2).reshape(24, -1), q, axis=1)
    return np.repeat(by_hour, 4)


def event_probability(pred: np.ndarray, resid: np.ndarray, threshold: float) -> np.ndarray:
    """P(uplift > threshold) per bin, using calibration residuals of the same hour as the noise."""
    r = resid.reshape(len(resid), 24, 4).transpose(1, 0, 2).reshape(24, -1)
    r_bins = np.repeat(r, 4, axis=0)  # (96, n_resid)
    return (pred[:, :, None] + r_bins[None, :, :] > threshold).mean(axis=2)


def score(name: str, y: np.ndarray, pred: np.ndarray, half: np.ndarray, prob: np.ndarray,
          threshold: float, cruise: np.ndarray) -> list[dict]:
    rows = []
    for label, mask in (("cruise_days", cruise), ("all_days", np.ones(len(y), bool))):
        if not mask.any():
            continue
        yt, pt, pr = y[mask][:, DAYTIME], pred[mask][:, DAYTIME], prob[mask][:, DAYTIME]
        h = half[DAYTIME]
        rows.append({
            "model": name, "days": label, "n_days": int(mask.sum()),
            "mae_veh_per_15min": float(np.abs(yt - pt).mean()),
            "brier": float((((yt > threshold) - pr) ** 2).mean()),
            "coverage80": float((np.abs(yt - pt) <= h).mean()),
            "width80_veh": float(2 * h.mean()),
        })
    return rows


@dataclass
class SiteResult:
    site_id: int
    table: pd.DataFrame
    threshold: float
    n_train: int
    n_test: int
    ridge: Ridge | None = None


def backtest_site(site_id: int, dates: np.ndarray, y: np.ndarray, feats: pd.DataFrame, cutoff,
                  calib_frac: float = 0.2) -> SiteResult | None:
    """Train before ``cutoff`` (last ``calib_frac`` held out for intervals), test after."""
    f = feats.reindex(dates)
    keep = f["pax_total"].notna().to_numpy()
    dates, y, f = dates[keep], y[keep], f[keep]
    train = np.array([d < cutoff for d in dates])
    if train.sum() < 30 or (~train).sum() < 10:
        return None
    n_cal = max(10, int(train.sum() * calib_frac))
    idx_train = np.flatnonzero(train)
    proper, cal = idx_train[:-n_cal], idx_train[-n_cal:]
    test = np.flatnonzero(~train)
    noise = y[proper][f.iloc[proper]["pax_total"].to_numpy() == 0][:, DAYTIME]
    threshold = float(np.quantile(noise, 0.95)) if noise.size else 50.0
    cruise_test = f.iloc[test]["pax_total"].to_numpy() > 0
    rows, ridge = [], None
    for cls in MODELS:
        model = cls().fit(f.iloc[proper], y[proper])
        resid = y[cal] - model.predict(f.iloc[cal])
        half = conformal_halfwidth(resid)
        # refit on the whole training period so e.g. last_day can use the newest cruise days
        model = (Ridge(lam=model.lam) if isinstance(model, Ridge) else cls()).fit(
            f.iloc[idx_train], y[idx_train])
        pred = model.predict(f.iloc[test])
        prob = event_probability(pred, resid, threshold)
        rows += score(model.name, y[test], pred, half, prob, threshold, cruise_test)
        if isinstance(model, Ridge):
            ridge = model
    table = pd.DataFrame(rows).assign(site_id=site_id, threshold_veh=threshold)
    return SiteResult(site_id, table, threshold, len(idx_train), len(test), ridge)


def skill(table: pd.DataFrame) -> pd.DataFrame:
    """Add MAE skill of every model against the best baseline for the same day set."""
    out = []
    for _, g in table.groupby("days"):
        best = g[g["model"] != "ridge"]["mae_veh_per_15min"].min()
        out.append(g.assign(skill_vs_best_baseline=1 - g["mae_veh_per_15min"] / best))
    return pd.concat(out)
