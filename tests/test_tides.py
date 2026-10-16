from datetime import datetime, timedelta

import pytest

from sotonship26.data.tides import TidalEvent, height_at

T0 = datetime(2026, 6, 6)
EVENTS = [
    TidalEvent(T0, 1.0, "LowWater"),
    TidalEvent(T0 + timedelta(hours=6), 4.0, "HighWater"),
]


def test_height_hits_events_and_midpoint():
    assert height_at(EVENTS, T0) == pytest.approx(1.0)
    assert height_at(EVENTS, T0 + timedelta(hours=3)) == pytest.approx(2.5)
    assert height_at(EVENTS, T0 + timedelta(hours=6)) == pytest.approx(4.0)


def test_outside_prediction_range_raises():
    with pytest.raises(ValueError):
        height_at(EVENTS, T0 - timedelta(minutes=1))
