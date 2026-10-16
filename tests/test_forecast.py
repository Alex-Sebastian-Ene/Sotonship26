from functools import partial

import pytest

from sotonship26.forecast import forecast
from sotonship26.synthetic import SCENARIOS


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_forecast_gives_probabilities(name):
    scenario = SCENARIOS[name]
    result = forecast(
        partial(scenario.sample_day, graph=scenario.build_graph()),
        n_scenarios=4,
        seed=0,
        routing={"max_iters": 5},
    )
    assert not result.edges.empty
    assert result.edges.p_overload.between(0, 1).all()
    assert (result.edges.mean_util > 0).all()


def test_craft_are_held_at_the_channel_edge_while_a_ship_passes():
    scenario = SCENARIOS["water"]
    result = forecast(
        partial(scenario.sample_day, graph=scenario.build_graph()), n_scenarios=20, seed=0
    )
    assert not result.held.empty
    # Channel rows are j = 4, 5; craft wait on the rows either side of it.
    assert {node[1] for node in result.held.node} <= {3, 6}


def test_street_turnaround_overloads_narrow_lane_sometimes():
    scenario = SCENARIOS["streets"]
    result = forecast(
        partial(scenario.sample_day, graph=scenario.build_graph()), n_scenarios=8, seed=1
    )
    assert result.edges.p_overload.max() > 0
