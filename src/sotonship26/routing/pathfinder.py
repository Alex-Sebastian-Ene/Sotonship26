"""Negotiated-congestion routing (PathFinder, McMurchie & Ebeling 1995).

Every flow takes its cheapest path; edges that end up over capacity get more expensive (a present
congestion term that grows each iteration plus a history term that accumulates), and every flow is
ripped up and rerouted until nothing is overused or the iteration budget runs out. It is the same
negotiation an FPGA/PCB autorouter runs over wiring channels, applied to footways and water lanes.

Graphs are plain networkx graphs whose edges carry a base ``cost`` (seconds) and a ``capacity``
(people or vessels per time bin). Undirected graphs pool both directions on one edge.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field

import networkx as nx

Node = Hashable
Edge = tuple[Node, Node]


@dataclass(frozen=True)
class Flow:
    source: Node
    target: Node
    volume: float  # people or vessels moving in this time bin


@dataclass
class RoutingResult:
    paths: list[list[Node]]
    load: dict[Edge, float]
    capacity: dict[Edge, float]
    iterations: int
    # Volume that could not reach its target, keyed by the node where it is left waiting.
    held: dict[Node, float] = field(default_factory=dict)

    def utilisation(self) -> dict[Edge, float]:
        return {e: self.load[e] / c for e, c in self.capacity.items()}

    def overloaded(self, threshold: float = 1.0) -> dict[Edge, float]:
        return {e: u for e, u in self.utilisation().items() if u > threshold}


def route(
    graph: nx.Graph,
    flows: Sequence[Flow],
    *,
    cost_scale: Mapping[Edge, float] | None = None,
    max_iters: int = 30,
    pres_fac: float = 0.5,
    pres_growth: float = 1.5,
    hist_fac: float = 0.2,
) -> RoutingResult:
    """Route ``flows`` over ``graph`` until no edge is over capacity (or ``max_iters``).

    ``cost_scale`` multiplies an edge's base cost, which is how outside interventions such as
    stewarding, signage or a closure-in-all-but-name enter the model.
    """
    canon: dict[Edge, Edge] = {}
    base: dict[Edge, float] = {}
    cap: dict[Edge, float] = {}
    for u, v, data in graph.edges(data=True):
        key = (u, v)
        canon[key] = key
        if not graph.is_directed():
            canon[(v, u)] = key
        base[key] = float(data["cost"])
        cap[key] = float(data["capacity"])
    if cost_scale:
        for e, scale in cost_scale.items():
            if e in canon:
                base[canon[e]] *= scale

    load = dict.fromkeys(base, 0.0)
    hist = dict.fromkeys(base, 0.0)
    paths: list[list[Node]] = [[] for _ in flows]
    held: dict[Node, float] = {}

    def edges_of(path: list[Node]) -> list[Edge]:
        return [canon[(a, b)] for a, b in zip(path, path[1:], strict=False)]

    iterations = 0
    while iterations < max_iters:
        iterations += 1
        held = {}
        for i, flow in enumerate(flows):
            for e in edges_of(paths[i]):
                load[e] -= flow.volume

            def weight(
                u: Node, v: Node, _data: dict, vol: float = flow.volume, pf: float = pres_fac
            ) -> float:
                e = canon[(u, v)]
                over = max(0.0, load[e] + vol - cap[e]) / cap[e]
                return (base[e] + hist[e]) * (1.0 + pf * over)

            paths[i], stuck_at = _shortest_or_nearest(graph, flow, weight)
            if stuck_at is not None:
                held[stuck_at] = held.get(stuck_at, 0.0) + flow.volume
            for e in edges_of(paths[i]):
                load[e] += flow.volume

        overused = [e for e in load if load[e] > cap[e] + 1e-9]
        if not overused:
            break
        for e in overused:
            hist[e] += hist_fac * base[e] * (load[e] - cap[e]) / cap[e]
        pres_fac *= pres_growth

    return RoutingResult(paths=paths, load=load, capacity=cap, iterations=iterations, held=held)


def _shortest_or_nearest(graph: nx.Graph, flow: Flow, weight) -> tuple[list[Node], Node | None]:
    """Cheapest path to the target, or, if it is cut off, to the reachable node nearest it.

    The second case is how bunching shows up: craft that cannot cross a closed channel end up
    queued on the reachable node closest to where they were going (needs a ``pos`` node attribute;
    without one they wait where they started).
    """
    try:
        return nx.shortest_path(graph, flow.source, flow.target, weight=weight), None
    except nx.NetworkXNoPath:
        pass
    reach = (
        nx.descendants(graph, flow.source)
        if graph.is_directed()
        else nx.node_connected_component(graph, flow.source)
    ) | {flow.source}
    goal = graph.nodes[flow.target].get("pos")
    if goal is None:
        return [flow.source], flow.source
    nearest = min(reach, key=lambda n: math.dist(graph.nodes[n].get("pos", goal), goal))
    return nx.shortest_path(graph, flow.source, nearest, weight=weight), nearest
