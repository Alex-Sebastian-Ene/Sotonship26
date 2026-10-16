"""Named corridors, dock gate approaches and candidate paths on the directed road graph.

Cruise traffic travels between an approach (where it enters or leaves the network: the M271, the
A35 from Totton, Southampton Central ...) and the dock gate its terminal uses. For each
(approach, gate, direction) ``candidate_paths`` precomputes a few distinct, sensible routes, so
assignment chooses among real routes instead of searching the whole graph every time
(design.md 3.4). ``corridor_vc`` reports each named corridor by its worst segment (design.md 3.5).

``load_network`` builds all of it from ``configs/default.yaml`` and caches the result under
``data/cache/roads``.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import warnings
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from sotonship26.config import load_config
from sotonship26.data.roads import load_roads, to_xy, tokens
from sotonship26.graphs import nearest_node

Node = Hashable
Edge = tuple[Node, Node]
DIRECTIONS = ("in", "out")  # in: approach -> gate (embarkation); out: gate -> approach
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "roads"


@dataclass(frozen=True)
class Corridor:
    id: str
    label: str
    edges: tuple[Edge, ...]


@dataclass
class Network:
    graph: nx.DiGraph
    bin_minutes: float
    gates: dict[str, Node]  # gate name -> node
    approaches: dict[tuple[str, str], Node]  # (approach, direction) -> node
    terminal_gates: dict[str, str]  # terminal (as in vts.py) -> gate name
    corridors: dict[str, Corridor]
    paths: dict[tuple[str, str, str], list[list[Node]]]  # (approach, gate, direction) -> paths

    def gate_of(self, terminal: str) -> str | None:
        """Gate a terminal's traffic uses, or None if the terminal is outside coverage."""
        return self.terminal_gates.get(terminal)


def load_network(cfg: Mapping | None = None, *, refresh: bool = False) -> Network:
    """Road graph, gates, approaches, corridors and candidate paths, cached per config."""
    cfg = cfg or load_config()
    roads = cfg["roads"]
    bin_minutes = float(cfg["time"]["bin_minutes"])
    key = hashlib.sha1(
        json.dumps({"roads": roads, "bin_minutes": bin_minutes}, sort_keys=True).encode()
    ).hexdigest()[:12]
    path = CACHE / f"network-{key}.pkl"
    if path.exists() and not refresh:
        with open(path, "rb") as f:
            return pickle.load(f)
    graph = load_roads(
        bbox=roads["bbox"],
        crs=roads["crs"],
        classes=roads["classes"],
        bin_minutes=bin_minutes,
        gates=roads["gates"],
        access_radius_m=roads.get("access_radius_m", 0.0),
    )
    network = build_network(graph, roads, bin_minutes=bin_minutes)
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(network, f)
    return network


def build_network(graph: nx.DiGraph, roads: Mapping, *, bin_minutes: float) -> Network:
    """Snap gates and approaches, match corridors and precompute candidate paths on ``graph``."""
    crs = roads["crs"]
    gates = {}
    for name, (lat, lon) in roads["gates"].items():
        xy = to_xy(lat, lon, crs)
        gates[name] = nearest_node(graph, xy)
        off = math.dist(graph.nodes[gates[name]]["pos"], xy)
        if off > roads.get("access_radius_m", 0.0):
            warnings.warn(f"{name} snapped {off:.0f} m away: no kept road reaches it", stacklevel=2)
    missing = {t: g for t, g in roads["terminal_gates"].items() if g not in gates}
    if missing:
        raise ValueError(f"terminal_gates names gates that are not in roads.gates: {missing}")
    approaches = locate_approaches(
        graph,
        {
            name: (to_xy(*spec["point"], crs), spec.get("refs", ()))
            for name, spec in roads["approaches"].items()
        },
        gates.values(),
    )
    corridors = corridor_edges(graph, roads["corridors"])
    for name, node in gates.items():
        cid = "gate_" + name.split()[-1]
        edges = gate_access_edges(graph, node, roads.get("gate_approach_m", 400))
        corridors[cid] = Corridor(cid, f"{name} approach", tuple(edges))
    paths = cruise_paths(graph, approaches, gates, **roads.get("candidate_paths", {}))
    return Network(
        graph=graph,
        bin_minutes=bin_minutes,
        gates=gates,
        approaches=approaches,
        terminal_gates=dict(roads["terminal_gates"]),
        corridors=corridors,
        paths=paths,
    )


def locate_approaches(
    graph: nx.DiGraph,
    points: Mapping[str, tuple[tuple[float, float], Sequence[str]]],
    gates: Iterable[Node],
    *,
    warn_m: float = 1500.0,
) -> dict[tuple[str, str], Node]:
    """Entry ("in") and exit ("out") node for each approach.

    Each approach is a point plus optional road refs. With refs, "in" starts at the tail of the
    nearest segment on those roads that heads towards the docks (the gates' centre) and "out"
    ends at the head of the nearest one heading away, so a dual carriageway uses the right side.
    Without refs (a city-centre point) both are the nearest node.
    """
    docks = tuple(
        sum(c) / len(c) for c in zip(*(graph.nodes[g]["pos"] for g in gates), strict=True)
    )
    out: dict[tuple[str, str], Node] = {}
    for name, (xy, refs) in points.items():
        wanted = set(refs)
        if not wanted:
            node = nearest_node(graph, xy)
            out[(name, "in")] = out[(name, "out")] = node
            continue
        toward = (docks[0] - xy[0], docks[1] - xy[1])
        segments: dict[str, list[tuple[float, Edge]]] = {"in": [], "out": []}
        for u, v, d in graph.edges(data=True):
            if not wanted & set(tokens(d["ref"])):
                continue
            (ux, uy), (vx, vy) = graph.nodes[u]["pos"], graph.nodes[v]["pos"]
            heading = (vx - ux) * toward[0] + (vy - uy) * toward[1]
            if heading:
                line = d.get("geometry") or [(ux, uy), (vx, vy)]
                segments["in" if heading > 0 else "out"].append((_distance(xy, line), (u, v)))
        for direction, found in segments.items():
            if not found:
                raise ValueError(
                    f"approach {name!r}: no {direction}bound road with ref {sorted(wanted)}"
                )
            dist, (u, v) = min(found, key=lambda s: s[0])
            if dist > warn_m:
                warnings.warn(
                    f"approach {name!r} snapped {dist:.0f} m from its point", stacklevel=2
                )
            out[(name, direction)] = u if direction == "in" else v
    return out


def _distance(p: tuple[float, float], line: Sequence[tuple[float, float]]) -> float:
    """Shortest distance from point ``p`` to a polyline."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(line, line[1:], strict=False):
        dx, dy = bx - ax, by - ay
        t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy) if dx or dy else 0.0
        t = min(1.0, max(0.0, t))
        best = min(best, math.dist(p, (ax + t * dx, ay + t * dy)))
    return best


def corridor_edges(graph: nx.DiGraph, specs: Iterable[Mapping]) -> dict[str, Corridor]:
    """Edges whose OSM ``name`` or ``ref`` matches each corridor spec (id, label, names, refs)."""
    corridors = {}
    for spec in specs:
        names, refs = set(spec.get("names", ())), set(spec.get("refs", ()))
        edges = tuple(
            (u, v)
            for u, v, d in graph.edges(data=True)
            if names & set(tokens(d["name"])) or refs & set(tokens(d["ref"]))
        )
        if not edges:
            warnings.warn(f"corridor {spec['id']!r} matched no roads", stacklevel=2)
        corridors[spec["id"]] = Corridor(spec["id"], spec.get("label", spec["id"]), edges)
    return corridors


def gate_access_edges(graph: nx.DiGraph, gate: Node, length_m: float) -> list[Edge]:
    """Edges within ``length_m`` of driving to or from ``gate``: its approach roads."""
    from_gate = nx.single_source_dijkstra_path_length(
        graph, gate, cutoff=length_m, weight="length_m"
    )
    to_gate = nx.single_source_dijkstra_path_length(
        graph.reverse(copy=False), gate, cutoff=length_m, weight="length_m"
    )
    return [
        (u, v)
        for u, v in graph.edges
        if (u in from_gate and v in from_gate) or (u in to_gate and v in to_gate)
    ]


def corridor_vc(
    load: Mapping[Edge, float], capacity: Mapping[Edge, float], corridors: Mapping[str, Corridor]
) -> dict[str, float]:
    """V/C of each corridor = its worst segment; NaN for a corridor with no edges."""
    return {
        cid: max((load.get(e, 0.0) / capacity[e] for e in c.edges), default=math.nan)
        for cid, c in corridors.items()
    }


def cruise_paths(
    graph: nx.DiGraph,
    approaches: Mapping[tuple[str, str], Node],
    gates: Mapping[str, Node],
    **kwargs,
) -> dict[tuple[str, str, str], list[list[Node]]]:
    """``candidate_paths`` for every (approach, gate, direction)."""
    paths = {}
    for (name, direction), node in approaches.items():
        for gate, gate_node in gates.items():
            source, target = (node, gate_node) if direction == "in" else (gate_node, node)
            paths[(name, gate, direction)] = candidate_paths(graph, source, target, **kwargs)
    return paths


def candidate_paths(
    graph: nx.DiGraph,
    source: Node,
    target: Node,
    *,
    k: int = 5,
    max_overlap: float = 0.8,
    max_detour: float = 1.5,
    penalty: float = 1.6,
    max_tries: int | None = None,
) -> list[list[Node]]:
    """Up to ``k`` distinct sensible routes, quickest first (penalty method).

    Take the quickest path, make its edges ``penalty`` times dearer, and search again. A path is
    kept if it shares at most ``max_overlap`` of its length with every kept path; the search stops
    once a path is more than ``max_detour`` times slower than the quickest at free flow.
    """
    if source == target:
        return [[source]]
    scale: dict[Edge, float] = {}

    def weight(u: Node, v: Node, d: Mapping) -> float:
        return d["cost"] * scale.get((u, v), 1.0)

    kept: list[list[Node]] = []
    kept_edges: list[set[Edge]] = []
    best = None
    for _ in range(max_tries or 4 * k):
        try:
            path = nx.dijkstra_path(graph, source, target, weight=weight)
        except nx.NetworkXNoPath:
            break
        edges = list(zip(path, path[1:], strict=False))
        cost = sum(graph[u][v]["cost"] for u, v in edges)
        best = cost if best is None else best
        if cost > max_detour * best:
            break
        length = sum(graph[u][v]["length_m"] for u, v in edges)
        shared = (
            sum(graph[u][v]["length_m"] for u, v in edges if (u, v) in ke) for ke in kept_edges
        )
        if all(s <= max_overlap * length for s in shared):
            kept.append(path)
            kept_edges.append(set(edges))
            if len(kept) == k:
                break
        for e in edges:
            scale[e] = scale.get(e, 1.0) * penalty
    return kept
