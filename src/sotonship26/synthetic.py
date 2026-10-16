"""Small synthetic scenarios so the whole pipeline runs before real data is wired in.

``street_day``: an 8 x 8 grid of 100 m blocks with one cruise terminal in a corner, three walking
destinations across town and a narrow lane, fed by one turnaround call.

``water_day``: an 800 m x 1 km reach with the deep-water channel along the middle. A large ship
transits mid-morning; its 1 km clear-channel box is longer than the reach, so while it passes,
leisure craft trying to cross are held at the channel edge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import networkx as nx
import numpy as np

from sotonship26.data.cruise import CruiseCall
from sotonship26.data.waterway import lattice
from sotonship26.demand.passengers import turnaround_flows
from sotonship26.demand.vessels import leisure_flows
from sotonship26.forecast import Day
from sotonship26.routing import clear_channel

DAY_START = datetime(2026, 6, 6, 5, 0)
BIN_MINUTES = 15
N_BINS = 60  # 05:00-20:00

TERMINAL = (0, 0)
DESTINATIONS = {(7, 7): 0.5, (7, 0): 0.3, (0, 7): 0.2}
NARROW_LANE = ((3, 3), (4, 3))


def streets(n: int = 8, block_m: float = 100.0, capacity: float = 60.0) -> nx.Graph:
    graph = nx.grid_2d_graph(n, n)
    for i, j in graph.nodes:
        graph.nodes[(i, j)]["pos"] = (i * block_m, j * block_m)
    nx.set_edge_attributes(graph, block_m / 1.2, "cost")
    nx.set_edge_attributes(graph, capacity, "capacity")
    graph.edges[NARROW_LANE]["capacity"] = capacity / 4
    return graph


def street_day(rng: np.random.Generator, graph: nx.Graph | None = None) -> Day:
    graph = graph if graph is not None else streets()
    call = CruiseCall(
        ship="Synthetic Seas",
        terminal="Terminal",
        arrival=DAY_START + timedelta(hours=1),
        departure=DAY_START + timedelta(hours=12),
        passengers=3500,
    )
    flows = turnaround_flows(
        call,
        TERMINAL,
        DESTINATIONS,
        rng=rng,
        day_start=DAY_START,
        bin_minutes=BIN_MINUTES,
        n_bins=N_BINS,
    )
    return Day(flows=flows, graph_for_bin=lambda _b: graph)


WATER_BOUNDS = (0.0, 0.0, 800.0, 1000.0)
SHIP_TRACK = np.array([[-1000.0, 500.0], [800.0, 500.0]])
CLEAR_CHANNEL = {"ahead_m": 1000.0, "beside_m": 100.0, "astern_m": 0.0}
CROSSINGS = {((4, 1), (4, 8)): 6.0, ((6, 8), (1, 1)): 4.0, ((1, 1), (6, 8)): 3.0}


def waterway(capacity: float = 3.0) -> nx.Graph:
    return lattice(WATER_BOUNDS, 100.0, speed_mps=3.0, capacity=capacity)


def water_day(rng: np.random.Generator, graph: nx.Graph | None = None) -> Day:
    graph = graph if graph is not None else waterway()
    flows = leisure_flows(CROSSINGS, rng=rng, bin_minutes=BIN_MINUTES, n_bins=N_BINS)
    transit_start = 16 + rng.normal(0.0, 1.5)  # bin the ship enters, ~09:00 give or take
    transit_bins = 4.0

    def graph_for_bin(b: int) -> nx.Graph:
        frac = (b - transit_start) / transit_bins
        if not 0.0 <= frac <= 1.0:
            return graph
        ship = clear_channel.position_along(SHIP_TRACK, frac)
        return clear_channel.without(
            graph, clear_channel.blocked_nodes(graph, [ship], **CLEAR_CHANNEL)
        )

    return Day(flows=flows, graph_for_bin=graph_for_bin)


@dataclass(frozen=True)
class Scenario:
    build_graph: Callable[[], nx.Graph]
    sample_day: Callable[..., Day]
    controllable: list  # edges an RL agent may steer
    day_start: datetime = DAY_START
    bin_minutes: int = BIN_MINUTES
    n_bins: int = N_BINS


SCENARIOS = {
    "streets": Scenario(
        streets,
        street_day,
        [((0, 0), (1, 0)), ((0, 0), (0, 1)), NARROW_LANE, ((3, 3), (3, 4)), ((4, 3), (4, 4))],
    ),
    "water": Scenario(waterway, water_day, [((i, 3), (i, 4)) for i in (1, 3, 5, 7)]),
}
