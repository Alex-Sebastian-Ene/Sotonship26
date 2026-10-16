"""Directed major-road network around the docks, from OpenStreetMap via osmnx (ODbL).

Cars care about direction, so unlike ``streets.py`` the graph stays directed: one-way streets and
separate carriageways keep their own edges and capacities. Only the road classes in
``roads.classes`` are kept (trunk to tertiary by default), plus any drivable road within
``access_radius_m`` of a dock gate, so the dock access roads stay connected. The result is the
largest strongly connected component, so every node can reach every other.

Each edge carries ``cost`` (free-flow seconds) and ``capacity`` (vehicles per time bin = lanes x
capacity per lane x bin length), which is what ``routing.pathfinder.route`` reads, plus ``name``,
``ref``, ``road_class``, ``lanes``, ``length_m``, ``speed_kph``, ``capacity_vph`` and
``geometry`` (British National Grid points) for corridors and maps. Nodes carry ``pos``.

The download uses the same box and settings as ``demo/osm_base.py``, so both read one cached copy
under ``data/cache/osm``.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import networkx as nx

OSM_CACHE = Path(__file__).resolve().parents[3] / "data" / "cache" / "osm"
UK_SPEED_UNITS_MPH = 70  # untagged UK maxspeed values are mph; anything above is km/h


def load_roads(
    *,
    bbox: Sequence[float],
    crs: str,
    classes: Mapping[str, Sequence[float]],
    bin_minutes: float,
    gates: Mapping[str, Sequence[float]] = (),
    access_radius_m: float = 0.0,
) -> nx.DiGraph:
    """Download (or read from cache) the OSM drive network in ``bbox`` and build the road graph.

    ``bbox`` is (west, south, east, north) in WGS84; ``gates`` maps a dock gate name to (lat, lon).
    """
    import osmnx as ox

    ox.settings.cache_folder = str(OSM_CACHE)
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 180  # part of the Overpass query, so it must match the demo's
    ox.settings.log_console = False
    # A mirror when overpass-api.de is unreachable, e.g. https://maps.mail.ru/osm/tools/overpass/api
    # (the venue network was blocked on 16 Oct). Mirrors' /status can hang, so skip the check.
    if os.environ.get("OVERPASS_URL"):
        ox.settings.overpass_url = os.environ["OVERPASS_URL"]
        ox.settings.overpass_rate_limit = False

    multi = ox.project_graph(
        ox.graph_from_bbox(tuple(bbox), network_type="drive", simplify=True), to_crs=crs
    )
    keep_near = [to_xy(lat, lon, crs) for lat, lon in dict(gates).values()]
    return build_roads(
        multi,
        classes=classes,
        bin_minutes=bin_minutes,
        keep_near=keep_near,
        keep_near_m=access_radius_m,
        crs=crs,
    )


def build_roads(
    multi: nx.MultiDiGraph,
    *,
    classes: Mapping[str, Sequence[float]],
    bin_minutes: float,
    keep_near: Iterable[tuple[float, float]] = (),
    keep_near_m: float = 0.0,
    crs: str | None = None,
) -> nx.DiGraph:
    """Turn a projected osmnx multigraph into the directed road graph described in the module doc.

    ``classes`` maps an OSM ``highway`` value to (capacity per lane in vehicles/hour, default
    free-flow km/h, default lanes per direction). Roads of other classes are kept only when both
    ends lie within ``keep_near_m`` of a point in ``keep_near``; they get ``road_class="access"``
    and the figures of the class with the lowest capacity per lane.
    """
    rank = list(classes)
    access = min(classes.values(), key=lambda c: c[0])
    near = list(keep_near)

    def close(node) -> bool:
        x, y = multi.nodes[node]["x"], multi.nodes[node]["y"]
        return any(math.dist((x, y), p) <= keep_near_m for p in near)

    graph = nx.DiGraph(crs=crs or multi.graph.get("crs"))
    for u, v, data in multi.edges(data=True):
        cls = road_class(data.get("highway"), rank)
        if cls is None:
            if not (near and close(u) and close(v)):
                continue
            cap_lane, speed_default, lanes_default = access
            cls = "access"
        else:
            cap_lane, speed_default, lanes_default = classes[cls]
        lanes = _lanes(data, lanes_default)
        speed = _speed(data.get("maxspeed"), speed_default)
        length = float(data["length"])
        cost = length / (speed / 3.6)
        if graph.has_edge(u, v) and graph[u][v]["cost"] <= cost:
            continue
        geom = data.get("geometry")
        coords = (
            [(float(x), float(y)) for x, y in geom.coords]
            if geom is not None
            else [_xy(multi, u), _xy(multi, v)]
        )
        graph.add_edge(
            u,
            v,
            name=_joined(data.get("name")),
            ref=_joined(data.get("ref")),
            road_class=cls,
            lanes=lanes,
            length_m=length,
            speed_kph=speed,
            cost=cost,
            capacity_vph=lanes * cap_lane,
            capacity=lanes * cap_lane * bin_minutes / 60.0,
            geometry=coords,
        )
    for node in graph.nodes:
        graph.nodes[node]["pos"] = _xy(multi, node)
    if graph.number_of_nodes():
        graph = graph.subgraph(max(nx.strongly_connected_components(graph), key=len)).copy()
    return graph


def road_class(highway, rank: Sequence[str]) -> str | None:
    """Highest-ranked kept class among an edge's ``highway`` values (osmnx may give a list)."""
    values = highway if isinstance(highway, list) else [highway]
    found = [rank.index(h) for h in values if h in rank]
    return rank[min(found)] if found else None


def tokens(value: str) -> list[str]:
    """Split a ``name`` or ``ref`` attribute joined with ';' (merged OSM ways) into its parts."""
    return [t.strip() for t in value.split(";") if t.strip()]


def to_xy(lat: float, lon: float, crs: str) -> tuple[float, float]:
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    return float(x), float(y)


def _xy(multi: nx.MultiDiGraph, node) -> tuple[float, float]:
    return float(multi.nodes[node]["x"]), float(multi.nodes[node]["y"])


def _first(value):
    return value[0] if isinstance(value, list) else value


def _joined(value) -> str:
    values = value if isinstance(value, list) else [value]
    seen: list[str] = []
    for v in values:
        if v is None or v != v:  # missing, or NaN from pandas
            continue
        for t in tokens(str(v)):
            if t not in seen:
                seen.append(t)
    return ";".join(seen)


def _lanes(data: Mapping, default: float) -> int:
    """Lanes per direction. OSM ``lanes`` counts both directions on a two-way road."""
    match = re.search(r"\d+", str(_first(data.get("lanes")) or ""))
    if not match:
        return int(default)
    lanes = int(match.group())
    if not data.get("oneway", False):
        lanes = max(1, round(lanes / 2))
    return max(1, min(lanes, 4))


def _speed(maxspeed, default_kph: float) -> float:
    """Free-flow km/h: 90% of the posted limit, never above 1.2x the class default."""
    text = str(_first(maxspeed) or "")
    match = re.search(r"\d+", text)
    if not match:
        return float(default_kph)
    n = float(match.group())
    kph = n * 1.609 if "mph" in text or n <= UK_SPEED_UNITS_MPH else n
    return min(kph * 0.9, default_kph * 1.2)
