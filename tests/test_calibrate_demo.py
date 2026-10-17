"""SOT-8 wiring: the Optuna harness drives Seb's SOT-10 demo simulator (calibrate_demo).

The real fit needs the demo context pickle and the WebTRIS cache, so it runs on Seb's laptop or
Iridis, not here. What these tests pin is the wiring that would silently misbehave otherwise:
the non-knob arguments are forwarded, the study runs over ``simulator.SPACE`` (not the synthetic
``DEFAULT_SPACE``) and labels the artifact ``source="data"``, and every ``SPACE`` knob name is
one ``SimParams.from_knobs`` accepts -- including the ``approach_share_western`` -> ``county_share``
rename that is the one interface break Seb called out.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sotonship26 import calibrate_demo as cd
from sotonship26.calibrate import KEY_COLS
from sotonship26.forecast.simulator import SPACE, SimParams

DAYS = (date(2025, 6, 1), date(2025, 6, 8))
SITES = (19974, 20025)
SENTINEL_CTX = object()  # stands in for a loaded ctx.pkl; a fake simulator never dereferences it


def test_demo_simulator_forwards_every_bound_argument(monkeypatch):
    seen = {}

    def recorder(params, days, *, sites, samples, calls, ctx):
        seen.update(params=params, days=days, sites=sites, samples=samples, calls=calls, ctx=ctx)
        return pd.DataFrame()

    monkeypatch.setattr(cd, "simulator", recorder)
    calls = pd.DataFrame({"ship": ["Aurora"]})
    simulate = cd.demo_simulator(calls, sites=[19974, 20025], samples=3, ctx=SENTINEL_CTX)

    knobs = {"background_scale": 1.0}
    simulate(knobs, DAYS)
    assert seen["params"] is knobs            # knobs passed straight through, positionally
    assert seen["days"] is DAYS
    assert seen["sites"] == (19974, 20025)    # list coerced to a tuple
    assert seen["samples"] == 3
    assert seen["calls"] is calls
    assert seen["ctx"] is SENTINEL_CTX


def test_calibrate_demo_uses_space_and_labels_source_data(monkeypatch):
    captured = {}

    def fake_calibrate(simulate, observed, days, **kwargs):
        captured.update(simulate=simulate, observed=observed, days=days, **kwargs)
        return "result-sentinel"

    monkeypatch.setattr(cd, "calibrate", fake_calibrate)
    out = cd.calibrate_demo(
        pd.DataFrame(), DAYS, pd.DataFrame(),
        sites=SITES, samples=4, n_trials=5, seed=7, out_path="/tmp/x.json", ctx=SENTINEL_CTX,
    )
    assert out == "result-sentinel"
    assert captured["param_space"] is SPACE   # the demo's real space, not DEFAULT_SPACE
    assert captured["source"] == "data"
    assert captured["n_trials"] == 5 and captured["seed"] == 7
    assert captured["out_path"] == "/tmp/x.json"
    assert callable(captured["simulate"])


def test_calibrate_demo_loads_context_once_when_not_supplied(monkeypatch):
    calls_to_load = {"n": 0}

    def fake_load_context(*a, **k):
        calls_to_load["n"] += 1
        return SENTINEL_CTX

    monkeypatch.setattr(cd, "load_context", fake_load_context)
    monkeypatch.setattr(cd, "calibrate", lambda *a, **k: None)
    cd.calibrate_demo(pd.DataFrame(), DAYS, pd.DataFrame(), ctx=None)
    assert calls_to_load["n"] == 1             # loaded once for the whole study, not per trial


def test_every_space_knob_name_is_accepted_by_from_knobs():
    midpoints = {name: (lo + hi) / 2 for name, (lo, hi) in SPACE.items()}
    params = SimParams.from_knobs(midpoints)   # must not raise on any SPACE key
    assert params.county_share == pytest.approx(midpoints["county_share"])
    assert params.disembark_shift_min == pytest.approx(midpoints["disembark_shift_min"])
    assert params.background_scale == pytest.approx(midpoints["background_scale"])


def test_renamed_knob_is_refused_so_a_stale_space_fails_loudly():
    with pytest.raises(ValueError, match="county_share"):
        SimParams.from_knobs({"approach_share_western": 0.6})


def _fake_sim_frame(knobs, days, sites):
    """A deterministic stand-in simulator: per-bin uplift is a fixed function of the knobs, so a
    unique best MAE exists and the study has something real to minimise -- all offline."""
    p = SimParams.from_knobs(knobs)
    rows = []
    for site in sites:
        for day in days:
            bins = np.arange(8)
            uplift = (10.0 * p.background_scale + 5.0 * p.county_share
                      + 0.1 * p.disembark_shift_min + 3.0 * p.mode_shares[0] + bins * 0.0)
            rows.append(pd.DataFrame({"site_id": site, "date": day, "tod_bin": bins,
                                      "uplift_veh": uplift}))
    return pd.concat(rows, ignore_index=True)


def test_calibrate_demo_runs_end_to_end_offline(monkeypatch, tmp_path):
    truth = {"background_scale": 1.1, "county_share": 0.7, "disembark_shift_min": 30.0,
             "mode_share_car": 0.3, "mode_share_coach": 0.2}

    def fake_sim(params, days, *, sites, samples, calls, ctx):
        return _fake_sim_frame(params, days, sites)

    monkeypatch.setattr(cd, "simulator", fake_sim)
    observed = _fake_sim_frame(truth, DAYS, SITES).assign(is_cruise_day=True)
    out = tmp_path / "best.json"
    result = cd.calibrate_demo(observed, DAYS, pd.DataFrame(), sites=SITES, samples=2,
                               n_trials=60, seed=0, out_path=out, ctx=SENTINEL_CTX)

    payload = json.loads(result.path.read_text())
    assert payload["source"] == "data"                 # fitted to data, never mislabelled
    assert set(payload["params"]) == set(SPACE)
    assert set(result.sites) == set(SITES)
    assert result.mae < 1.0                             # a working study drives MAE toward zero
    assert list(KEY_COLS) == ["site_id", "date", "tod_bin"]
