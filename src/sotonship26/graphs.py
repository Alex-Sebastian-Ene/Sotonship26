"""Small graph helpers shared by the street and waterway models."""

from __future__ import annotations

from collections.abc import Hashable

import networkx as nx
import numpy as np


def nearest_node(graph: nx.Graph, xy: tuple[float, float]) -> Hashable:
    """Node whose ``pos`` is closest to ``xy``."""
    nodes = list(graph.nodes)
    pos = np.array([graph.nodes[n]["pos"] for n in nodes], dtype=float)
    return nodes[int(np.argmin(np.hypot(*(pos - np.asarray(xy, dtype=float)).T)))]
