"""Wire the SOT-8 Optuna harness to Seb's SOT-10 demo simulator (the real target).

``calibrate.calibrate`` takes a dependency-injected ``Simulator`` -- a callable ``(knobs, days)
-> uplift rows``. Seb's ``forecast.simulator.simulator`` already has that exact shape, plus the
keyword-only context it needs (``sites``, ``samples``, historic ``calls``, a loaded ``ctx``).
This module binds those keywords once so the result is a plain two-argument ``Simulator``, then
runs ``calibrate`` over the demo's real search space ``simulator.SPACE`` (not the synthetic
``DEFAULT_SPACE``) and labels the artifact ``source="data"``.

Running it needs the demo context ``data/cache/southampton/ctx.pkl`` (built on Seb's laptop or
Iridis; see SOT-10) and the WebTRIS flow cache plus a permitted historic call list, so ``main``
is the Iridis/laptop entry point, not something that runs in CI. The wiring itself -- the knob
names line up, the arguments are forwarded, ``SPACE`` and ``source`` reach ``calibrate`` -- is
what the offline tests cover (``tests/test_calibrate_demo.py``).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from sotonship26.calibrate import BEST_JSON, CalibrationResult, Simulator, calibrate
from sotonship26.data import cruise_history, observed
from sotonship26.forecast.simulator import DEFAULT_SITES, SPACE, load_context, simulator
from sotonship26.uplift import observed_uplift

# Low by default: Seb clocks the demo at ~6 s per day per trial at samples=8, so a 200-trial
# study over a handful of days is cheaper to iterate at samples=2 and still stable enough to
# rank knob sets. Raise it for the final fit.
DEFAULT_SAMPLES = 2


def demo_simulator(
    calls: pd.DataFrame,
    *,
    sites: Sequence[int] = DEFAULT_SITES,
    samples: int = DEFAULT_SAMPLES,
    ctx=None,
) -> Simulator:
    """Bind the demo simulator's non-knob arguments into a two-argument ``Simulator``.

    ``calibrate`` calls the result as ``simulate(knobs, days)``; everything else -- the sites to
    score, the Monte-Carlo ``samples``, the historic ``calls`` (past days have no live VTS
    schedule, so they must be supplied) and the loaded ``ctx`` -- is fixed here.
    """
    return partial(simulator, sites=tuple(sites), samples=samples, calls=calls, ctx=ctx)


def calibrate_demo(
    observed_uplift_rows: pd.DataFrame,
    days: Sequence[date],
    calls: pd.DataFrame,
    *,
    sites: Sequence[int] = DEFAULT_SITES,
    samples: int = DEFAULT_SAMPLES,
    n_trials: int = 200,
    seed: int = 0,
    out_path: Path = BEST_JSON,
    ctx=None,
) -> CalibrationResult:
    """Calibrate the demo simulator's knobs to observed uplift over ``SPACE``.

    ``ctx`` is loaded once (not per trial) and shared across the whole study. The written
    ``best.json`` is labelled ``source="data"`` -- it is fitted to measured WebTRIS uplift, not
    to the synthetic stand-in.
    """
    if ctx is None:
        ctx = load_context()  # read the demo context pickle once; reused by every trial
    simulate = demo_simulator(calls, sites=sites, samples=samples, ctx=ctx)
    return calibrate(
        simulate,
        observed_uplift_rows,
        days,
        param_space=SPACE,
        n_trials=n_trials,
        seed=seed,
        out_path=out_path,
        source="data",
    )


def load_inputs(
    start: date,
    end: date,
    *,
    sites: Sequence[int],
) -> tuple[pd.DataFrame, list[date], pd.DataFrame]:
    """Assemble the real calibration target: observed uplift, training days and historic calls.

    Mirrors ``run_backtest.main`` so the same provenance holds: training days are the *covered*
    cruise days (a schedule source lists every call that day), never uncovered zeros.
    """
    flows = observed.load_flows(sites, start, end)
    calls = cruise_history.load_calls(start, end)
    day_frame = cruise_history.cruise_days(calls, start, end)
    uplift = observed_uplift(flows, day_frame)
    is_cruise = (day_frame["n_calls"] > 0) & day_frame["covered"].astype(bool)
    training = sorted(day_frame.loc[is_cruise, "date"])
    return uplift, training, calls


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    p.add_argument("--sites", type=int, nargs="*", default=list(observed.SITES))
    p.add_argument("--n-trials", type=int, default=200)
    p.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=BEST_JSON)
    args = p.parse_args(argv)

    uplift, training, calls = load_inputs(args.start, args.end, sites=args.sites)
    if not training:
        print(
            "No covered cruise days in range, so there is nothing to calibrate against. Add a "
            "permitted historic call list (data/raw/cruise_history/manual_calls.csv + "
            "manual_coverage.csv, see notes/cruise-history.md and SOT-21)."
        )
        return 1

    ctx = load_context()  # once, shared by the study and the backtest report below
    result = calibrate_demo(
        uplift,
        training,
        calls,
        sites=args.sites,
        samples=args.samples,
        n_trials=args.n_trials,
        seed=args.seed,
        out_path=args.out,
        ctx=ctx,
    )
    print(
        f"calibrated {len(result.space)} knobs on {len(training)} cruise days "
        f"({len(result.sites)} sites), MAE {result.mae:.3f} veh/15min -> {result.path}"
    )
    report_sim = demo_simulator(calls, sites=args.sites, samples=args.samples, ctx=ctx)
    print(result.backtest_table(report_sim, uplift).to_string(index=False))
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
