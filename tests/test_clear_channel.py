import numpy as np
import pytest

from sotonship26.routing.clear_channel import position_along, zone_mask
from sotonship26.synthetic import water_day


def test_zone_covers_ahead_and_beside_but_not_astern():
    xy = np.array([[500, 0], [1500, 0], [-50, 0], [500, 150], [500, -90]], dtype=float)
    mask = zone_mask(xy, np.zeros(2), 0.0, ahead_m=1000, beside_m=100)
    assert mask.tolist() == [True, False, False, False, True]


def test_position_along_track():
    track = np.array([[0, 0], [100, 0], [100, 100]], dtype=float)
    xy, heading = position_along(track, 0.75)
    np.testing.assert_allclose(xy, [100, 50])
    assert heading == pytest.approx(np.pi / 2)


def test_transiting_ship_removes_waterway_nodes():
    day = water_day(np.random.default_rng(0))
    sizes = [day.graph_for_bin(b).number_of_nodes() for b in range(60)]
    assert min(sizes) < max(sizes)
