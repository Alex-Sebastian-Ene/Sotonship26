"""Walking network around the cruise terminals, from OpenStreetMap via osmnx.

The OSM multigraph is projected to British National Grid and collapsed to a simple undirected graph
(crowds use both directions of a footway, so both count against one capacity). Each edge gets
``cost`` (walking seconds) and ``capacity`` (people per time bin = width x level-of-service flow
rate x bin length); widths fall back to per-highway-type defaults because OSM rarely tags them.
"""

from __future__ import annotations

from collections.abc import Mapping

import networkx as nx


def load_streets(
    centre: str,
    *,
    radius_m: float,
    crs: str,
    walk_speed_mps: float,
    ped_per_m_per_min: float,
    bin_minutes: float,
    default_width_m: Mapping[str, float],
) -> nx.Graph:
    import osmnx as ox

    multi = ox.project_graph(
        ox.graph_from_address(centre, dist=radius_m, network_type="walk"), to_crs=crs
    )
    graph = nx.Graph(crs=crs)
    for node, data in multi.nodes(data=True):
        graph.add_node(node, pos=(float(data["x"]), float(data["y"])))
    for u, v, data in multi.edges(data=True):
        length = float(data["length"])
        width = _width(data, default_width_m)
        cost = length / walk_speed_mps
        if graph.has_edge(u, v) and graph[u][v]["cost"] <= cost:
            continue
        graph.add_edge(
            u,
            v,
            cost=cost,
            capacity=width * ped_per_m_per_min * bin_minutes,
            length=length,
            width=width,
        )
    return graph


def geocode_xy(query: str, crs: str) -> tuple[float, float]:
    """Geocode a place name with OSM Nominatim and project it to ``crs``."""
    import osmnx as ox
    from pyproj import Transformer

    lat, lon = ox.geocode(query)
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)


def _width(data: Mapping, defaults: Mapping[str, float]) -> float:
    raw = data.get("width")
    if isinstance(raw, list):
        raw = raw[0]
    try:
        return float(str(raw).replace("m", "").strip())
    except ValueError:
        pass
    highway = data.get("highway", "default")
    if isinstance(highway, list):
        highway = highway[0]
    return float(defaults.get(highway, defaults["default"]))
