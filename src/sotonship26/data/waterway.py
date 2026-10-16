"""Southampton Water as a routing lattice.

Square cells of ``cell_m`` metres over the area (British National Grid metres), kept where
``is_water`` says so and joined to their eight neighbours. Nodes carry ``pos`` and, when bathymetry
is supplied, ``depth_cd`` (depth below chart datum); ``navigable`` then drops cells too shallow for
a craft's draught at the predicted tide height, which is how the UKHO tides gate the waterway.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import networkx as nx

XYPredicate = Callable[[float, float], bool]


def lattice(
    bounds: tuple[float, float, float, float],
    cell_m: float,
    *,
    speed_mps: float,
    capacity: float,
    is_water: XYPredicate | None = None,
    depth_cd: Callable[[float, float], float] | None = None,
) -> nx.Graph:
    xmin, ymin, xmax, ymax = bounds
    nx_cells = int((xmax - xmin) // cell_m)
    ny_cells = int((ymax - ymin) // cell_m)
    graph = nx.Graph()
    for i in range(nx_cells):
        for j in range(ny_cells):
            x, y = xmin + (i + 0.5) * cell_m, ymin + (j + 0.5) * cell_m
            if is_water is None or is_water(x, y):
                attrs = {"pos": (x, y)}
                if depth_cd is not None:
                    attrs["depth_cd"] = depth_cd(x, y)
                graph.add_node((i, j), **attrs)
    for i, j in list(graph.nodes):
        for di, dj in ((1, 0), (0, 1), (1, 1), (1, -1)):
            other = (i + di, j + dj)
            if other in graph:
                dist = cell_m * math.hypot(di, dj)
                graph.add_edge((i, j), other, cost=dist / speed_mps, capacity=capacity)
    return graph


def navigable(graph: nx.Graph, tide_m: float, draught_m: float, under_keel_m: float = 0.5):
    """View of ``graph`` without cells shallower than ``draught_m + under_keel_m`` at this tide."""
    need = draught_m + under_keel_m
    shallow = [n for n, d in graph.nodes(data=True) if d.get("depth_cd", math.inf) + tide_m < need]
    return nx.restricted_view(graph, shallow, [])
