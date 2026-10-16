"""Monte Carlo congestion forecast.

Each scenario is one sampled turnaround day: ship timings, passenger numbers and craft movements
drawn from their uncertainty, giving per-bin flows and a per-bin graph (the waterway loses nodes to
the clear channel while a large ship is moving). Every bin is routed with PathFinder and we count
how often each edge ends up over capacity, which gives the overload probability.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd

from sotonship26.routing import Flow, route


@dataclass
class Day:
    flows: dict[int, list[Flow]]
    graph_for_bin: Callable[[int], nx.Graph]


@dataclass
class Forecast:
    edges: pd.DataFrame  # bin, u, v, p_overload, mean_util
    held: pd.DataFrame = field(default_factory=pd.DataFrame)  # bin, node, p_held, mean_held

    def hotspots(self, n: int = 10) -> pd.DataFrame:
        return self.edges.nlargest(n, ["p_overload", "mean_util"])


def forecast(
    sample_day: Callable[[np.random.Generator], Day],
    *,
    n_scenarios: int,
    seed: int | None = None,
    threshold: float = 1.0,
    routing: Mapping | None = None,
) -> Forecast:
    rng = np.random.default_rng(seed)
    over: dict[tuple, int] = defaultdict(int)
    util: dict[tuple, float] = defaultdict(float)
    held_n: dict[tuple, int] = defaultdict(int)
    held_v: dict[tuple, float] = defaultdict(float)

    for _ in range(n_scenarios):
        day = sample_day(rng)
        for b, flows in day.flows.items():
            if not flows:
                continue
            result = route(day.graph_for_bin(b), flows, **(routing or {}))
            for (u, v), x in result.utilisation().items():
                if x > 0:
                    util[(b, u, v)] += x
                    over[(b, u, v)] += x > threshold
            for node, vol in result.held.items():
                held_n[(b, node)] += 1
                held_v[(b, node)] += vol

    edges = _frame(["bin", "u", "v"], util, over, n_scenarios, "mean_util", "p_overload")
    held = _frame(["bin", "node"], held_v, held_n, n_scenarios, "mean_held", "p_held")
    return Forecast(edges=edges, held=held)


def _frame(
    keys: list[str],
    totals: Mapping[tuple, float],
    counts: Mapping[tuple, int],
    n: int,
    mean_col: str,
    p_col: str,
) -> pd.DataFrame:
    rows: list[dict[str, Hashable]] = [
        {**dict(zip(keys, k, strict=True)), p_col: counts.get(k, 0) / n, mean_col: t / n}
        for k, t in totals.items()
    ]
    df = pd.DataFrame(rows, columns=[*keys, p_col, mean_col])
    return df.sort_values([p_col, mean_col], ascending=False, ignore_index=True)
