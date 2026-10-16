"""The clear channel kept ahead of large ships in Southampton Water.

A large ship under way carries a moving exclusion box: ``ahead_m`` in front of the bow and
``beside_m`` either side (plus ``astern_m`` behind, usually 0). Small craft and ferries have to keep
out of it, so waterway nodes inside the box are removed from the graph for that time bin. The
default sizes live in ``configs/default.yaml``; check them against current ABP Southampton harbour
notices.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx
import numpy as np


def position_along(track: np.ndarray, frac: float) -> tuple[np.ndarray, float]:
    """Ship position and heading (radians) after ``frac`` (0-1) of a polyline ``track`` (N x 2)."""
    seg = np.diff(track, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    dist = np.clip(frac, 0.0, 1.0) * seg_len.sum()
    i = min(int(np.searchsorted(np.cumsum(seg_len), dist, side="right")), len(seg) - 1)
    into = dist - seg_len[:i].sum()
    direction = seg[i] / seg_len[i]
    return track[i] + direction * into, float(np.arctan2(direction[1], direction[0]))


def zone_mask(
    xy: np.ndarray,
    ship_xy: np.ndarray,
    heading: float,
    *,
    ahead_m: float,
    beside_m: float,
    astern_m: float = 0.0,
) -> np.ndarray:
    """Boolean mask of points ``xy`` (N x 2, metres) inside the ship's exclusion box."""
    rel = xy - ship_xy
    fwd = np.array([np.cos(heading), np.sin(heading)])
    side = np.array([-fwd[1], fwd[0]])
    along = rel @ fwd
    across = rel @ side
    return (along >= -astern_m) & (along <= ahead_m) & (np.abs(across) <= beside_m)


def blocked_nodes(graph: nx.Graph, ships: Iterable[tuple[np.ndarray, float]], **zone) -> set:
    """Nodes (with a ``pos`` attribute) inside any ship's exclusion box."""
    nodes = list(graph.nodes)
    if not nodes:
        return set()
    xy = np.array([graph.nodes[n]["pos"] for n in nodes], dtype=float)
    mask = np.zeros(len(nodes), dtype=bool)
    for ship_xy, heading in ships:
        mask |= zone_mask(xy, np.asarray(ship_xy, dtype=float), heading, **zone)
    return {n for n, m in zip(nodes, mask, strict=True) if m}


def without(graph: nx.Graph, nodes: Iterable) -> nx.Graph:
    """Read-only view of ``graph`` with ``nodes`` removed."""
    return nx.restricted_view(graph, list(nodes), [])
