"""Southampton map layers and road network from OpenStreetMap (© OpenStreetMap contributors, ODbL).

Downloads once through osmnx (responses cached under data/cache/osm) and writes:

* ``data/cache/southampton/base.json``: map layers as SVG paths on a local metre grid, north up
  (x = easting - x0, y = y1 - northing, British National Grid).
* ``data/cache/southampton/network.pkl``: the road network the traffic model routes on, plus
  land-use samples, place points and landmarks it builds its zones from.

    uv run --no-project --python 3.12 --with osmnx --with scipy python demo/osm_base.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import re
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

BBOX = (-1.53, 50.855, -1.29, 50.975)  # west, south, east, north (WGS84)
CRS = "EPSG:27700"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUT = CACHE / "southampton"

# Road classes the model routes on; everything else is drawn as minor streets.
MAJOR = {
    "motorway": (1900, 100, 2), "motorway_link": (1500, 60, 1),
    "trunk": (1600, 70, 1), "trunk_link": (1300, 50, 1),
    "primary": (1100, 45, 1), "primary_link": (1000, 40, 1),
    "secondary": (900, 40, 1), "secondary_link": (850, 35, 1),
    "tertiary": (750, 35, 1), "tertiary_link": (700, 30, 1),
    "unclassified": (600, 30, 1),
}  # class: (capacity per lane veh/h, default free-flow km/h, default lanes per direction)
RANK = list(MAJOR)

LANDMARK_QUERIES = {
    "Ocean": "Ocean Cruise Terminal, Southampton",
    "QEII": "QEII Cruise Terminal, Southampton",
    "Mayflower": "Mayflower Cruise Terminal, Southampton",
    "City": "City Cruise Terminal, Southampton",
    "Horizon": "Horizon Cruise Terminal, Southampton",
    "station": "Southampton Central railway station",
    "stadium": "St Mary's Stadium, Southampton",
    "westquay": "Westquay, Southampton",
    "hospital": "Southampton General Hospital",
    "university": "University of Southampton, Highfield",
}
GATE_NAMES = ["Dock Gate 4", "Dock Gate 5", "Dock Gate 8", "Dock Gate 10", "Dock Gate 20"]


def first(v):
    return v[0] if isinstance(v, list) else v


def road_class(hw) -> str | None:
    vals = hw if isinstance(hw, list) else [hw]
    ranked = [RANK.index(h) for h in vals if h in MAJOR]
    return RANK[min(ranked)] if ranked else None


def parse_int(v) -> int | None:
    m = re.search(r"\d+", str(first(v))) if v is not None else None
    return int(m.group()) if m else None


def parse_speed(v) -> float | None:
    s = str(first(v)) if v is not None else ""
    m = re.search(r"\d+", s)
    if not m:
        return None
    n = float(m.group())
    return n * 1.609 if "mph" in s or n <= 70 else n  # UK limits are mph


class Grid:
    """Projected BNG metres -> page grid (origin top-left, y down), rounded to a metre."""

    def __init__(self, frame: Polygon):
        self.x0, self.y0, self.x1, self.y1 = frame.bounds

    def xy(self, x, y):
        return round(x - self.x0), round(self.y1 - y)

    def path(self, geom, close=None) -> str:
        out = []

        def ring(coords, closed):
            pts = []
            for x, y in coords:
                p = self.xy(x, y)
                if not pts or p != pts[-1]:
                    pts.append(p)
            if len(pts) < 2:
                return
            rel = " ".join(f"{b[0] - a[0]} {b[1] - a[1]}" for a, b in zip(pts, pts[1:], strict=False))
            out.append(f"M{pts[0][0]} {pts[0][1]}l{rel}{'z' if closed else ''}")

        for g in getattr(geom, "geoms", [geom]):
            if isinstance(g, Polygon):
                ring(g.exterior.coords, True)
                for hole in g.interiors:
                    ring(hole.coords, True)
            elif isinstance(g, LineString):
                ring(g.coords, False if close is None else close)
            elif hasattr(g, "geoms"):
                out.append(self.path(g, close))
        return "".join(out)


def polys(gdf) -> list:
    return [g for g in gdf.geometry if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty]


def tagged(gdf, col, values):
    if col not in gdf.columns:
        return gdf.iloc[0:0]
    return gdf[gdf[col].isin(values)]


def sea_from_coastline(coast, frame: Polygon) -> list[Polygon]:
    """Polygonize coastline + frame and keep faces on the water side (OSM: land on the left)."""
    lines = []
    for g in coast:
        g = g.exterior if isinstance(g, Polygon) else g
        clipped = g.intersection(frame)
        lines += [c for c in getattr(clipped, "geoms", [clipped]) if isinstance(c, LineString)]
    if not lines:
        return []
    faces = [f for f in polygonize(unary_union([*lines, frame.exterior])) if f.area > 1]
    tree = STRtree(faces)
    votes = np.zeros(len(faces))
    for line in lines:
        c = list(line.coords)
        for (x1, y1), (x2, y2) in list(zip(c, c[1:], strict=False))[::3]:
            dx, dy = x2 - x1, y2 - y1
            seg = math.hypot(dx, dy)
            if seg < 3:
                continue
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            nx_, ny_ = dy / seg * 1.5, -dx / seg * 1.5  # right-hand normal, y north
            for side, (px, py) in ((1, (mx + nx_, my + ny_)), (-1, (mx - nx_, my - ny_))):
                for i in tree.query(Point(px, py), predicate="within"):
                    votes[i] += side
    return [f for f, v in zip(faces, votes, strict=True) if v > 0]


def fetch(tags: dict, label: str):
    print(f"fetching {label} ...", flush=True)
    gdf = ox.features_from_bbox(BBOX, tags)
    return ox.projection.project_gdf(gdf, to_crs=CRS)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    ox.settings.cache_folder = str(CACHE / "osm")
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 180
    if os.environ.get("OVERPASS_URL"):  # e.g. a mirror when overpass-api.de is unreachable
        ox.settings.overpass_url = os.environ["OVERPASS_URL"]
    ox.settings.log_console = False

    import geopandas as gpd

    frame_ll = gpd.GeoSeries([box(*BBOX)], crs="EPSG:4326").to_crs(CRS)
    frame = frame_ll.iloc[0].envelope
    grid = Grid(frame)
    W, H = grid.xy(grid.x1, grid.y0)

    # --- road network ---------------------------------------------------------------------------
    print("fetching drive network ...", flush=True)
    G = ox.project_graph(ox.graph_from_bbox(BBOX, network_type="drive", simplify=True), to_crs=CRS)
    minor_lines, seen = [], set()
    model = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        geom = data.get("geometry") or LineString(
            [(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])]
        )
        cls = road_class(data.get("highway"))
        if cls is None:
            key = (min(u, v), max(u, v))
            if key not in seen:
                seen.add(key)
                minor_lines.append(geom)
            continue
        cap_lane, speed_default, lanes_default = MAJOR[cls]
        oneway = bool(first(data.get("oneway", False)))
        lanes = parse_int(data.get("lanes"))
        lanes = (lanes if oneway else max(1, round(lanes / 2))) if lanes else lanes_default
        lanes = max(1, min(lanes, 4))
        speed = parse_speed(data.get("maxspeed"))
        speed = min(speed * 0.9, speed_default * 1.2) if speed else speed_default
        length = float(data.get("length", geom.length))
        if model.has_edge(u, v) and model[u][v]["length"] <= length:
            continue
        model.add_edge(
            u, v,
            length=length,
            cls=cls,
            name=str(first(data.get("name")) or ""),
            ref=str(first(data.get("ref")) or ""),
            lanes=lanes,
            cap=lanes * cap_lane,
            t0=length / (speed / 3.6),
            coords=[grid.xy(x, y) for x, y in geom.coords],
        )
    for n in model.nodes:
        model.nodes[n]["xy"] = grid.xy(G.nodes[n]["x"], G.nodes[n]["y"])
        model.nodes[n]["bng"] = (G.nodes[n]["x"], G.nodes[n]["y"])
    scc = max(nx.strongly_connected_components(model), key=len)
    model = model.subgraph(scc).copy()
    print(f"model network: {model.number_of_nodes()} nodes, {model.number_of_edges()} edges; "
          f"minor streets: {len(minor_lines)}", flush=True)

    # --- map layers -----------------------------------------------------------------------------
    water = fetch({"natural": ["water", "bay", "strait", "coastline", "wetland", "mud"],
                   "water": True, "waterway": ["riverbank", "dock"],
                   "landuse": ["basin", "reservoir"]}, "water and coast")
    land = fetch({"landuse": ["residential", "commercial", "retail", "industrial", "port", "railway",
                              "grass", "recreation_ground", "cemetery", "allotments", "forest",
                              "meadow", "village_green", "construction", "brownfield"],
                  "leisure": ["park", "golf_course", "nature_reserve", "common"],
                  "natural": ["wood", "scrub", "heath", "grassland"],
                  "aeroway": ["aerodrome"],
                  "amenity": ["university", "hospital"]}, "land use")
    rail = fetch({"railway": ["rail"]}, "railways")
    places = fetch({"place": ["town", "suburb", "neighbourhood", "quarter", "village"]}, "places")
    try:
        schools = fetch({"amenity": ["school"]}, "schools")
    except Exception as exc:  # noqa: BLE001  (Overpass is often overloaded; schools are optional)
        print("schools unavailable, the model will use homes instead:", exc)
        schools = places.iloc[0:0]

    coast = [g for g in tagged(water, "natural", ["coastline"]).geometry
             if isinstance(g, (LineString, MultiLineString, Polygon))]
    coast = [c for g in coast for c in getattr(g, "geoms", [g])]
    sea = sea_from_coastline(coast, frame)
    natural = water["natural"] if "natural" in water.columns else water.geometry.map(lambda _: None)
    inland = polys(water[~natural.isin(["coastline", "wetland", "mud"])])
    mud = polys(tagged(water, "natural", ["wetland", "mud"]))
    water_all = unary_union([*sea, *inland]).intersection(frame)

    def cls_of(row) -> str | None:
        lu, le, na = row.get("landuse"), row.get("leisure"), row.get("natural")
        if row.get("aeroway") == "aerodrome":
            return "airport"
        if row.get("amenity") in ("university", "hospital"):
            return "campus"
        if lu == "port" or row.get("industrial") == "port":
            return "port"
        if lu == "residential":
            return "residential"
        if lu in ("commercial", "retail"):
            return "commercial"
        if lu in ("industrial", "railway", "construction", "brownfield"):
            return "industrial"
        if lu == "forest" or na in ("wood", "scrub"):
            return "wood"
        if lu or le or na:
            return "green"
        return None

    buckets: dict[str, list] = {}
    samples = []  # land-use pieces the traffic model turns into trip ends
    for _, row in land.iterrows():
        g = row.geometry
        if not isinstance(g, (Polygon, MultiPolygon)) or g.area < 400:
            continue
        c = cls_of(row)
        if not c:
            continue
        buckets.setdefault(c, []).append(g)
        p = g.representative_point()
        samples.append((c, *grid.xy(p.x, p.y), float(g.area)))

    school_pts = []
    for _, row in schools.iterrows():
        g = row.geometry
        p = g.representative_point()
        if not frame.contains(p):
            continue
        area = float(g.area) if isinstance(g, (Polygon, MultiPolygon)) else 4000.0
        samples.append(("school", *grid.xy(p.x, p.y), max(area, 2000.0)))
        school_pts.append(grid.xy(p.x, p.y))
    print(f"schools: {len(school_pts)}", flush=True)

    layers = {}
    for name, geoms in [("water", [water_all]), ("mud", mud), *buckets.items()]:
        merged = unary_union(geoms).intersection(frame).simplify(4, preserve_topology=True)
        if name != "water":
            merged = merged.difference(water_all) if name not in ("port",) else merged
        layers[name] = grid.path(merged)
    layers["minor"] = grid.path(
        unary_union(minor_lines).intersection(frame).simplify(3), close=False
    )
    rail_lines = [g for g in rail.geometry if isinstance(g, (LineString, MultiLineString))]
    layers["rail"] = grid.path(unary_union(rail_lines).intersection(frame).simplify(4), close=False)

    try:
        city = ox.projection.project_gdf(ox.geocode_to_gdf("Southampton, England"), to_crs=CRS)
        layers["boundary"] = grid.path(city.geometry.iloc[0].boundary.simplify(10), close=False)
        city_poly = city.geometry.iloc[0]
    except Exception as exc:  # noqa: BLE001
        print("city boundary unavailable:", exc)
        city_poly = None

    place_pts = []
    for _, row in places.iterrows():
        name = row.get("name")
        if not isinstance(name, str):
            continue
        p = row.geometry.representative_point()
        if not frame.contains(p) or water_all.contains(p):
            continue
        inside = bool(city_poly is not None and city_poly.contains(p))
        place_pts.append({"name": name, "kind": row.get("place"), "x": grid.xy(p.x, p.y)[0],
                          "y": grid.xy(p.x, p.y)[1], "city": inside})

    # --- landmarks ------------------------------------------------------------------------------
    from pyproj import Transformer

    to_bng = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    landmarks = {}
    for key, query in LANDMARK_QUERIES.items():
        try:
            lat, lon = ox.geocode(query)
            landmarks[key] = grid.xy(*to_bng.transform(lon, lat))
        except Exception as exc:  # noqa: BLE001
            print(f"  could not geocode {query!r}: {exc}")
    gates = {}
    try:
        g = fetch({"name": GATE_NAMES}, "dock gates")
        for _, row in g.iterrows():
            p = row.geometry.representative_point()
            gates.setdefault(row["name"], grid.xy(p.x, p.y))
    except Exception as exc:  # noqa: BLE001
        print("  dock gates not found:", exc)
    print("landmarks:", landmarks, "\ngates:", gates, flush=True)

    base = {
        "size": [W, H],
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "layers": layers,
        "places": place_pts,
        "landmarks": landmarks,
        "gates": gates,
        "schools": school_pts,
    }
    (args.out / "base.json").write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")
    with open(args.out / "network.pkl", "wb") as f:
        pickle.dump({"graph": model, "size": (W, H), "samples": samples, "places": place_pts,
                     "landmarks": landmarks, "gates": gates,
                     "city": grid.path(city_poly) if city_poly is not None else None}, f)
    sizes = {k: len(v) // 1000 for k, v in layers.items()}
    print(f"wrote {args.out} (layer sizes kB: {sizes})")


if __name__ == "__main__":
    main()
