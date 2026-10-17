"""Tests for the NTIS predicted-vs-actual diagnostics (sotonship26.ntis_score).

The logger stores the feed's Europe/London wall-clock as epoch ms. These fixtures mimic
that: bucket_ms is a London wall time read as UTC epoch, captured_at is a true offset-
aware timestamp. The scorer converts captured_at into the same wall-clock frame, so lead
times come out as the intended minutes regardless of the BST offset.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sotonship26 import ntis_score as ns

LONDON = ns.LONDON
# A London wall time; Oct 17 2026 is BST (+01:00).
T0_LONDON = datetime(2026, 10, 17, 12, 0, tzinfo=LONDON)


def _bucket(dt_london: datetime) -> int:
    """London wall-clock read as a UTC epoch, as the logger stored it."""
    wall = dt_london.replace(tzinfo=None)
    return int(wall.replace(tzinfo=UTC).timestamp() * 1000)


def _pred(link: str, target: datetime, captured: datetime, value: float) -> dict:
    return {"source": "predicted", "road": "M27", "link_id": link,
            "bucket_ms": _bucket(target), "value": value,
            "captured_at": captured.isoformat()}


def _fused(link: str, bucket: datetime, value: float) -> dict:
    return {"source": "fused", "road": "M27", "link_id": link,
            "bucket_ms": _bucket(bucket), "value": value,
            "captured_at": bucket.isoformat()}


def test_fused_actuals_keyed_by_link_and_bucket():
    rows = [_fused("L1", T0_LONDON, 60.0), _fused("L2", T0_LONDON, 70.0)]
    acts = ns.fused_actuals(rows)
    assert acts[("L1", _bucket(T0_LONDON))] == 60.0
    assert acts[("L2", _bucket(T0_LONDON))] == 70.0


def test_lead_is_in_london_wall_clock_domain():
    # Target at 12:00 London, captured 90 min earlier -> lead 90, not shifted by BST.
    rows = [_fused("L1", T0_LONDON, 60.0),
            _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=90), 50.0)]
    pairs = ns.build_pairs(rows)
    assert len(pairs) == 1
    assert pairs[0]["lead_min"] == pytest.approx(90.0, abs=0.5)


def test_build_pairs_scores_each_distinct_value_and_computes_errors():
    rows = [
        _fused("L1", T0_LONDON, 60.0),
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=90), 50.0),  # err -10
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=20), 58.0),  # err -2 (revision)
    ]
    pairs = ns.build_pairs(rows)
    assert len(pairs) == 2
    errs = sorted(p["err"] for p in pairs)
    assert errs == pytest.approx([-10.0, -2.0])


def test_restart_resnapshot_duplicates_are_collapsed():
    # Same value for the same target seen in two polls (restart re-snapshot) -> one pair,
    # keeping the longest lead.
    rows = [
        _fused("L1", T0_LONDON, 60.0),
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=40), 50.0),
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=10), 50.0),
    ]
    pairs = ns.build_pairs(rows)
    assert len(pairs) == 1
    assert pairs[0]["lead_min"] == pytest.approx(40.0, abs=0.5)


def test_build_pairs_excludes_nonforecast_and_unmatched():
    rows = [
        _fused("L1", T0_LONDON, 60.0),
        _pred("L1", T0_LONDON, T0_LONDON + timedelta(minutes=5), 55.0),   # after target
        _pred("L2", T0_LONDON, T0_LONDON - timedelta(minutes=30), 40.0),  # no fused L2
    ]
    assert ns.build_pairs(rows) == []


def test_nearest_actual_respects_tolerance():
    rows_in = [
        _fused("L1", T0_LONDON + timedelta(minutes=5), 60.0),   # within 7.5
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=30), 58.0),
    ]
    assert len(ns.build_pairs(rows_in)) == 1

    rows_out = [
        _fused("L1", T0_LONDON + timedelta(minutes=10), 60.0),  # beyond 7.5
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=30), 58.0),
    ]
    assert ns.build_pairs(rows_out) == []


def test_agg_mae_bias_rmse():
    pairs = [
        {"predicted": 50.0, "actual": 60.0, "abs_err": 10.0, "err": -10.0},
        {"predicted": 58.0, "actual": 60.0, "abs_err": 2.0, "err": -2.0},
    ]
    a = ns._agg(pairs)
    assert a["n"] == 2
    assert a["mae"] == pytest.approx(6.0)
    assert a["bias"] == pytest.approx(-6.0)
    assert a["mean_actual"] == pytest.approx(60.0)


def test_agg_empty_is_null():
    a = ns._agg([])
    assert a["n"] == 0 and a["mae"] is None and a["bias"] is None


def test_score_by_lead_buckets_coverage_and_one_sidedness():
    rows = [
        _fused("L1", T0_LONDON, 60.0),
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=90), 50.0),  # 60-120
        _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=20), 58.0),  # 15-30
    ]
    scored = ns.score_by_lead(ns.build_pairs(rows))
    assert scored["overall"]["n"] == 2
    assert scored["n_links"] == 1
    assert scored["n_targets"] == 1
    assert scored["frac_pred_below_actual"] == pytest.approx(1.0)
    nonempty = {(b["lead_lo"], b["lead_hi"]): b["n"] for b in scored["by_lead"] if b["n"]}
    assert nonempty == {(15, 30): 1, (60, 120): 1}


def test_render_report_states_inferred_units_and_handles_empty():
    empty = ns.render_report([], [], ns.score_by_lead([]))
    assert "No scored pairs yet" in empty

    rows = [_fused("L1", T0_LONDON, 60.0),
            _pred("L1", T0_LONDON, T0_LONDON - timedelta(minutes=30), 58.0)]
    pairs = ns.build_pairs(rows)
    report = ns.render_report(rows, pairs, ns.score_by_lead(pairs))
    assert "x1.609" in report          # mph -> km/h conversion stated
    assert "mph -> km/h" in report     # primary skill line is the converted read
    assert "provisional" in report     # still flagged pending first-overlap confirm
    assert "scored pairs: 1" in report
