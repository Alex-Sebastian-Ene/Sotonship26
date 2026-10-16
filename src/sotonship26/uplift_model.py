"""The learned cruise-uplift model as the product uses it: fit once on history, forecast any day.

``fit_production`` fits the ridge model per sensor site on every usable day, holding out the
latest 20% to set the 80% interval and the event probabilities, then refits on all days with the
chosen penalty. ``predict_uplift`` turns one day's cruise calls (e.g. from the VTS schedule) into
a forecast with intervals, without needing any traffic data for that day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from sotonship26.backtest import BINS, FEATURES, Ridge, conformal_halfwidth

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "uplift_ridge.json"
QUANTILES = np.linspace(0.025, 0.975, 39)


@dataclass(frozen=True)
class SiteModel:
    site_id: int
    lam: float
    mu: list[float]
    sd: list[float]
    coef: list[list[float]]  # (1 + len(FEATURES)) x 96
    halfwidth80: list[float]  # 96
    resid_q: list[list[float]]  # 24 hours x len(QUANTILES), calibration residual quantiles
    threshold_veh: float
    n_days: int
    first_day: str
    last_day: str


def fit_site(site_id: int, dates: np.ndarray, y: np.ndarray, feats: pd.DataFrame,
             threshold: float, calib_frac: float = 0.2) -> SiteModel:
    f = feats.reindex(dates)
    n_cal = max(10, int(len(dates) * calib_frac))
    proper = Ridge().fit(f.iloc[:-n_cal], y[:-n_cal])
    resid = y[-n_cal:] - proper.predict(f.iloc[-n_cal:])
    by_hour = resid.reshape(n_cal, 24, 4).transpose(1, 0, 2).reshape(24, -1)
    final = Ridge(lam=proper.lam).fit(f, y)  # same features as the backtest
    return SiteModel(
        site_id=int(site_id), lam=float(proper.lam), mu=final.mu.tolist(), sd=final.sd.tolist(),
        coef=final.b.tolist(), halfwidth80=conformal_halfwidth(resid).tolist(),
        resid_q=np.quantile(by_hour, QUANTILES, axis=1).T.tolist(),
        threshold_veh=float(threshold), n_days=int(len(dates)),
        first_day=str(dates[0]), last_day=str(dates[-1]),
    )


def save(models: list[SiteModel], meta: dict, path: Path = MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "features": FEATURES, "quantiles": QUANTILES.tolist(),
               "sites": [m.__dict__ for m in models]}
    path.write_text(json.dumps(payload, indent=1))


def load(path: Path = MODEL_PATH) -> tuple[list[SiteModel], dict]:
    payload = json.loads(path.read_text())
    return [SiteModel(**s) for s in payload["sites"]], payload["meta"]


def predict_uplift(feats: pd.DataFrame, models: list[SiteModel] | None = None) -> pd.DataFrame:
    """Forecast uplift for each row of ``feats`` (from ``backtest.day_features``) at every site.

    Columns: date, site_id, tod_bin, uplift_veh, lo80, hi80, p_event (probability the uplift beats
    that site's 'unusual traffic' threshold, the 95th percentile of noise on non-cruise days).
    """
    if models is None:
        models, _ = load()
    out = []
    for m in models:
        x = (feats[FEATURES].to_numpy(dtype=float) - np.array(m.mu)) / np.array(m.sd)
        pred = np.column_stack([np.ones(len(x)), x]) @ np.array(m.coef)
        half = np.array(m.halfwidth80)
        rq = np.repeat(np.array(m.resid_q), 4, axis=0)  # 96 x n_quantiles
        # P(pred + resid > threshold): share of residual quantiles above threshold - pred
        p = (pred[:, :, None] + rq[None, :, :] > m.threshold_veh).mean(axis=2)
        for i, d in enumerate(feats.index):
            out.append(pd.DataFrame({
                "date": d, "site_id": m.site_id, "tod_bin": np.arange(BINS),
                "uplift_veh": pred[i], "lo80": pred[i] - half, "hi80": pred[i] + half,
                "p_event": p[i],
            }))
    return pd.concat(out, ignore_index=True)
