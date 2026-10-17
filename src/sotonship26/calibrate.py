"""Calibrate a cruise-day traffic simulator to the observed cruise uplift (SOT-8).

The task: pick the simulator knobs the brief names -- mode shares, approach shares, arrival
offset, background scale -- so the simulated uplift matches the observed uplift on training
cruise days, minimising mean absolute error per 15-minute bin. ``calibrate`` runs an Optuna
study over those knobs, writes the winner to ``runs/calibration/best.json`` and returns a
``CalibrationResult`` exposing ``fitted_params()`` and ``backtest_table()``.

The simulator is dependency-injected as a ``Simulator`` callable, not imported, so this module
runs today against any model that maps knobs to per-site/bin uplift and swaps straight onto
Seb's SOT-10 ``forecast_day(day, params: SimParams)`` the moment it lands. Until then the only
real target -- a parametric ``simulate_uplift`` over the WebTRIS sites -- does not exist in
``src/`` (SOT-10 is Backlog), so the committed ``best.json`` is produced from the synthetic
stand-in in this module and is labelled ``"source": "synthetic"``.

Observed uplift comes from ``sotonship26.data.observed.observed_uplift(flows, days)``:
columns site_id, date, tod_bin, uplift_veh, is_cruise_day, ... (SOT-7).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import optuna
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BEST_JSON = ROOT / "runs" / "calibration" / "best.json"
KEY_COLS = ["site_id", "date", "tod_bin"]
BINS_PER_DAY = 96

# The knobs the SOT-8 brief names, each as an inclusive (low, high) search range. The injected
# simulator decides what each one means; these defaults suit the synthetic stand-in below and are
# a reasonable starting envelope for SOT-10's SimParams.
DEFAULT_SPACE: dict[str, tuple[float, float]] = {
    "mode_share_car": (0.3, 0.9),
    "mode_share_coach": (0.0, 0.4),
    "approach_share_western": (0.2, 0.8),
    "arrival_offset_min": (-120.0, 120.0),
    "background_scale": (0.5, 1.5),
}


class Simulator(Protocol):
    """Maps calibration knobs to simulated uplift, one row per site, date and 15-min bin.

    Returns a frame with at least ``site_id``, ``date``, ``tod_bin`` and ``uplift_veh``. This is
    exactly the shape ``observed.observed_uplift`` returns, and the shape SOT-10's
    ``forecast_day`` output can be reduced to, so a thin adapter is all that is needed later.
    """

    def __call__(self, params: Mapping[str, float], days: Sequence[date]) -> pd.DataFrame: ...


@dataclass(frozen=True)
class CalibrationResult:
    """Immutable outcome of one study: the fitted knobs and everything needed to reproduce them."""

    params: Mapping[str, float]
    mae: float
    n_trials: int
    seed: int
    days: tuple[date, ...]
    sites: tuple[int, ...]
    space: Mapping[str, tuple[float, float]]
    source: str
    path: Path = BEST_JSON
    generated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def fitted_params(self) -> dict[str, float]:
        """The calibrated knob values."""
        return dict(self.params)

    def backtest_table(self, simulate: Simulator, observed: pd.DataFrame) -> pd.DataFrame:
        """Per-site simulated-vs-observed error under the fitted knobs (see module function)."""
        return backtest_table(simulate, observed, self.days, params=self.params)


def _norm(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise key columns so observed and simulated frames merge: python ``date``, int keys."""
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["site_id"] = out["site_id"].astype(int)
    out["tod_bin"] = out["tod_bin"].astype(int)
    return out


def observed_target(observed: pd.DataFrame, days: Sequence[date]) -> pd.DataFrame:
    """Observed uplift on the given cruise days, dropping bins without a baseline (NaN uplift)."""
    wanted = {pd.Timestamp(d).date() for d in days}
    o = _norm(observed)
    keep = o["date"].isin(wanted)
    if "is_cruise_day" in o.columns:
        keep &= o["is_cruise_day"].astype(bool)
    cols = [*KEY_COLS, "uplift_veh"]
    return o.loc[keep, cols].dropna(subset=["uplift_veh"]).reset_index(drop=True)


def _aligned_errors(target: pd.DataFrame, simulated: pd.DataFrame) -> np.ndarray:
    """Absolute per-bin errors on the bins present in both frames."""
    sim = _norm(simulated)[[*KEY_COLS, "uplift_veh"]]
    merged = target.merge(sim, on=KEY_COLS, suffixes=("_obs", "_sim"))
    if merged.empty:
        return np.array([])
    return np.abs(merged["uplift_veh_obs"].to_numpy() - merged["uplift_veh_sim"].to_numpy())


def _suggest(trial: optuna.Trial, space: Mapping[str, tuple[float, float]]) -> dict[str, float]:
    return {name: trial.suggest_float(name, low, high) for name, (low, high) in space.items()}


def calibrate(
    simulate: Simulator,
    observed: pd.DataFrame,
    days: Sequence[date],
    *,
    param_space: Mapping[str, tuple[float, float]] = DEFAULT_SPACE,
    n_trials: int = 200,
    seed: int = 0,
    out_path: Path = BEST_JSON,
    source: str = "data",
) -> CalibrationResult:
    """Fit ``simulate``'s knobs to the observed uplift on ``days``, minimising per-bin MAE.

    Writes the winner to ``out_path`` as JSON and returns it. ``source`` labels the artifact
    ("synthetic" for the stand-in simulator, "data" for a real one).
    """
    target = observed_target(observed, days)
    if target.empty:
        raise ValueError("no observed uplift on the given days -- nothing to calibrate against")

    def objective(trial: optuna.Trial) -> float:
        errors = _aligned_errors(target, simulate(_suggest(trial, param_space), days))
        return float(errors.mean()) if errors.size else float("inf")

    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed)
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    result = CalibrationResult(
        params=dict(study.best_params),
        mae=float(study.best_value),
        n_trials=n_trials,
        seed=seed,
        days=tuple(sorted(pd.Timestamp(d).date() for d in days)),
        sites=tuple(sorted(int(s) for s in target["site_id"].unique())),
        space={k: (float(lo), float(hi)) for k, (lo, hi) in param_space.items()},
        source=source,
        path=Path(out_path),
    )
    _write_best(result, n_bins=int(len(target)))
    return result


def _write_best(result: CalibrationResult, *, n_bins: int) -> None:
    payload = {
        "generated": result.generated,
        "source": result.source,
        "n_trials": result.n_trials,
        "seed": result.seed,
        "mae_veh_per_15min": result.mae,
        "n_bins": n_bins,
        "params": dict(result.params),
        "param_space": {k: list(v) for k, v in result.space.items()},
        "days": [d.isoformat() for d in result.days],
        "sites": list(result.sites),
    }
    result.path.parent.mkdir(parents=True, exist_ok=True)
    result.path.write_text(json.dumps(payload, indent=1))


def fitted_params(path: Path = BEST_JSON) -> dict[str, float]:
    """The calibrated knob values from a saved ``best.json``."""
    return dict(json.loads(Path(path).read_text())["params"])


def backtest_table(
    simulate: Simulator,
    observed: pd.DataFrame,
    days: Sequence[date],
    *,
    params: Mapping[str, float] | None = None,
    path: Path = BEST_JSON,
) -> pd.DataFrame:
    """Per-site error of the fitted simulator against observed uplift, with a zero-uplift baseline.

    Columns: site_id, n_bins, mae_fitted, mae_zero, skill_vs_zero (1 - mae_fitted / mae_zero).
    A final ``site_id = -1`` row pools every site. ``params`` defaults to the saved ``best.json``.
    """
    knobs = dict(params) if params is not None else fitted_params(path)
    target = observed_target(observed, days)
    sim = _norm(simulate(knobs, days))[[*KEY_COLS, "uplift_veh"]]
    merged = target.merge(sim, on=KEY_COLS, suffixes=("_obs", "_sim"))

    def row(site_id: int, g: pd.DataFrame) -> dict[str, float]:
        err = np.abs(g["uplift_veh_obs"] - g["uplift_veh_sim"])
        mae_zero = float(np.abs(g["uplift_veh_obs"]).mean())
        mae_fitted = float(err.mean())
        skill = float(1 - mae_fitted / mae_zero) if mae_zero > 0 else float("nan")
        return {"site_id": site_id, "n_bins": int(len(g)), "mae_fitted": mae_fitted,
                "mae_zero": mae_zero, "skill_vs_zero": skill}

    cols = ["site_id", "n_bins", "mae_fitted", "mae_zero", "skill_vs_zero"]
    if merged.empty:
        return pd.DataFrame(columns=cols)
    rows = [row(int(site), g) for site, g in merged.groupby("site_id")]
    rows.append(row(-1, merged))  # -1 = all sites pooled
    return pd.DataFrame(rows).reset_index(drop=True)


# --- synthetic stand-in for SOT-10's simulate_uplift (pending) -------------------------------
# A deterministic, identifiable toy so the pipeline and tests run with no feed data. Each knob
# drives a distinct basis, so the MAE is minimised at one set of values and Optuna can recover
# them. This is NOT a traffic model; it only stands in until forecast_day/simulate_uplift exist.

SYNTHETIC_SITES = (19974, 20025)  # a western and the eastern WebTRIS approach, for realism
_BINS = np.arange(BINS_PER_DAY)


def _bump(centre: float, width: float) -> np.ndarray:
    return np.exp(-(((_BINS - centre) / width) ** 2))


def synthetic_simulate(params: Mapping[str, float], days: Sequence[date]) -> pd.DataFrame:
    """Toy simulator: uplift per site/bin as a linear blend of knob-driven profiles."""
    morning = _bump(28 + params["arrival_offset_min"] / 15.0, 6.0)  # arrival peak, offset shifts it
    evening = _bump(68.0, 7.0)  # departure peak
    base = _bump(52.0, 24.0)  # daytime background
    car, coach = params["mode_share_car"], params["mode_share_coach"]
    scale, west = params["background_scale"], params["approach_share_western"]
    frames = []
    for site in SYNTHETIC_SITES:
        share = west if site == SYNTHETIC_SITES[0] else 1.0 - west
        profile = 120.0 * share * (car * morning + coach * evening) + 40.0 * scale * base
        for d in days:
            frames.append(pd.DataFrame({"site_id": site, "date": pd.Timestamp(d).date(),
                                        "tod_bin": _BINS, "uplift_veh": profile}))
    return pd.concat(frames, ignore_index=True)


def synthetic_observed(days: Sequence[date], truth: Mapping[str, float]) -> pd.DataFrame:
    """Observed-uplift frame (SOT-7 shape) generated from the toy at the ground-truth knobs."""
    return synthetic_simulate(truth, days).assign(is_cruise_day=True)


def main() -> int:
    """Prove the pipeline end to end on the synthetic stand-in and write a labelled best.json."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    days = tuple(date(2025, 6, 1) + pd.Timedelta(days=7 * k) for k in range(6))
    days = tuple(d.date() for d in pd.to_datetime(list(days)))
    truth = {"mode_share_car": 0.70, "mode_share_coach": 0.15, "approach_share_western": 0.60,
             "arrival_offset_min": 30.0, "background_scale": 1.10}
    observed = synthetic_observed(days, truth)
    result = calibrate(synthetic_simulate, observed, days, n_trials=200, seed=0, source="synthetic")
    print(f"synthetic calibration: MAE {result.mae:.3f} veh/15min over {len(days)} days")
    print(f"truth : {truth}")
    print(f"fitted: {result.fitted_params()}")
    print(f"best.json -> {result.path}")
    print(result.backtest_table(synthetic_simulate, observed).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
