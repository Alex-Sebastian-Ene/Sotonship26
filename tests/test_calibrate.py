"""SOT-8: the Optuna calibrator converges on an injected synthetic simulator and writes best.json.

No feed data: the target is built from ``calibrate.synthetic_simulate`` at known ground-truth
knobs, so a correct study drives the per-bin MAE to near zero and recovers the knobs. This is the
scaffold's proof; the real target (a parametric ``simulate_uplift`` over the WebTRIS sites) is
pending Seb's SOT-10 and is injected the same way once it exists.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from sotonship26 import calibrate

TRUTH = {
    "mode_share_car": 0.70,
    "mode_share_coach": 0.15,
    "approach_share_western": 0.60,
    "arrival_offset_min": 30.0,
    "background_scale": 1.10,
}
DAYS = (date(2025, 6, 1), date(2025, 6, 8), date(2025, 6, 15), date(2025, 6, 22))


@pytest.fixture
def observed():
    return calibrate.synthetic_observed(DAYS, TRUTH)


@pytest.fixture
def result(tmp_path, observed):
    out = tmp_path / "best.json"
    return calibrate.calibrate(calibrate.synthetic_simulate, observed, DAYS,
                               n_trials=160, seed=0, out_path=out, source="synthetic")


def test_study_converges_on_synthetic_simulate(result):
    # A no-noise target means the minimum achievable MAE is zero; a working study gets close.
    assert result.mae < 1.0
    fitted = result.fitted_params()
    # The strongly identifiable knobs are recovered; collinear shares need only be roughly right.
    assert abs(fitted["arrival_offset_min"] - TRUTH["arrival_offset_min"]) < 15.0
    assert abs(fitted["background_scale"] - TRUTH["background_scale"]) < 0.2


def test_calibration_beats_a_midpoint_guess(result, observed):
    mid = {k: (lo + hi) / 2 for k, (lo, hi) in calibrate.DEFAULT_SPACE.items()}
    mid_errors = calibrate._aligned_errors(
        calibrate.observed_target(observed, DAYS),
        calibrate.synthetic_simulate(mid, DAYS),
    )
    assert result.mae < float(mid_errors.mean())


def test_best_json_written_with_expected_shape(result):
    payload = json.loads(result.path.read_text())
    assert payload["source"] == "synthetic"
    assert payload["n_trials"] == 160
    assert set(payload["params"]) == set(calibrate.DEFAULT_SPACE)
    assert payload["mae_veh_per_15min"] == pytest.approx(result.mae)
    assert payload["days"] == [d.isoformat() for d in DAYS]
    assert payload["sites"] == list(calibrate.SYNTHETIC_SITES)


def test_backtest_table_shape(result, observed):
    table = result.backtest_table(calibrate.synthetic_simulate, observed)
    assert list(table.columns) == ["site_id", "n_bins", "mae_fitted", "mae_zero", "skill_vs_zero"]
    # one row per site plus the pooled site_id = -1 row
    assert len(table) == len(calibrate.SYNTHETIC_SITES) + 1
    assert set(calibrate.SYNTHETIC_SITES).issubset(set(table["site_id"]))
    assert -1 in set(table["site_id"])
    # the fitted simulator explains the observed uplift far better than predicting zero
    pooled = table[table["site_id"] == -1].iloc[0]
    assert pooled["skill_vs_zero"] > 0.5


def test_fitted_params_roundtrip_from_disk(result):
    assert calibrate.fitted_params(result.path) == result.fitted_params()


def test_empty_target_raises(observed):
    with pytest.raises(ValueError, match="nothing to calibrate"):
        calibrate.calibrate(calibrate.synthetic_simulate, observed, [date(2099, 1, 1)], n_trials=1)
