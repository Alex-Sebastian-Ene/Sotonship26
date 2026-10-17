"""Port lorry day factors from VTS freight calls (demo/freight_days.py, SOT-24)."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from sotonship26.data.vts_freight import DAY_COLUMNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import freight_days as fd  # noqa: E402


def calls(rows):
    """A daily_freight_calls frame from (date, freight_moves, unconfirmed, complete) rows."""
    df = pd.DataFrame(rows, columns=["date", "freight_moves", "unconfirmed", "complete"])
    for c in DAY_COLUMNS:
        if c not in df:
            df[c] = 0
    return df[DAY_COLUMNS]


def test_factor_follows_calls_with_half_the_swing():
    days = calls([
        (date(2026, 10, 17), 3, 0, False),  # the snapshot day undercounts: left out
        (date(2026, 10, 18), 8, 0, True),
        (date(2026, 10, 19), 12, 2, True),
        (date(2026, 10, 20), 16, 0, True),
    ])
    f = fd.freight_day_factors(days)
    assert sorted(f) == ["2026-10-18", "2026-10-19", "2026-10-20"]
    # mean over complete days is 12, so 8 -> 1 + 0.5 * (8/12 - 1)
    assert f["2026-10-18"]["factor"] == pytest.approx(1 + 0.5 * (8 / 12 - 1), abs=1e-3)
    assert f["2026-10-19"]["factor"] == pytest.approx(1.0)
    assert f["2026-10-20"]["factor"] == pytest.approx(1 + 0.5 * (16 / 12 - 1), abs=1e-3)
    assert f["2026-10-19"]["unconfirmed"] == 2
    assert f["2026-10-20"]["mean_moves"] == 12.0


def test_days_outside_the_feed_stay_at_one():
    f = fd.freight_day_factors(calls([(date(2026, 10, 18), 10, 0, True)]))
    assert fd.factor_on(f, date(2026, 10, 18)) == pytest.approx(1.0)
    assert fd.factor_on(f, date(2026, 10, 17)) == 1.0  # snapshot day / before the feed
    assert fd.factor_on(f, date(2026, 11, 1)) == 1.0  # beyond the feed window


def test_no_usable_days_gives_no_factors():
    assert fd.freight_day_factors(None) == {}
    assert fd.freight_day_factors(calls([])) == {}
    assert fd.freight_day_factors(calls([(date(2026, 10, 18), 9, 0, False)])) == {}
    assert fd.freight_day_factors(calls([(date(2026, 10, 18), 0, 0, True)])) == {}


def test_shrink_zero_keeps_every_day_at_the_average():
    days = calls([(date(2026, 10, 18), 4, 0, True), (date(2026, 10, 19), 20, 0, True)])
    assert {v["factor"] for v in fd.freight_day_factors(days, shrink=0.0).values()} == {1.0}
