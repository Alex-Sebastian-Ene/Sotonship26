"""Car park outlines around Southampton's cruise terminals, from OpenStreetMap (ODbL).

Each ``amenity=parking`` way within the docks is classified:

* ``cruise``: run by ABP / ABParking, or named for the cruise terminals (long stay, short stay,
  blue badge, "Green Parking"), or within ``NEAR_TERMINAL_M`` of a terminal and not a vehicle
  compound or a public shopping car park;
* ``vehicle_compound``: the port's import/export car storage ("Vehicle Holding Compound/Area", or
  ``access=no``). Counting these would measure car shipping, not cruise passengers, so they are
  left out;
* ``control``: public car parks further from the terminals (Westquay, Town Quay, Ocean Village),
  used to check the detector and everyday parking, not cruise demand.

Capacity is the OSM ``capacity`` tag when present, else surface area / ``M2_PER_SPACE``.
Multi-storey car parks are kept but flagged: imagery only sees their top deck.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

DOCKS_BBOX = (50.885, -1.475, 50.915, -1.380)  # south, west, north, east (WGS84)
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
NEAR_TERMINAL_M = 250.0
M2_PER_SPACE = 25.0  # bay plus its share of aisles, a common planning rule of thumb
CRUISE_NAME = re.compile(r"cruise|terminal|long stay|short stay|blue badge|green parking", re.I)
COMPOUND_NAME = re.compile(r"vehicle holding", re.I)
CRUISE_OPERATOR = {"abp", "abparking", "associated british ports"}
SHOPPING_NAME = re.compile(r"westquay|west quay|ocean village|town quay|west bay|marlands", re.I)


@dataclass
class CarPark:
    osm_id: str
    name: str
    kind: str  # cruise, vehicle_compound, control
    terminal: str  # nearest cruise terminal
    terminal_m: float
    capacity: int
    capacity_source: str  # tag or area
    multi_storey: bool
    area_m2: float
    polygon_bng: list[tuple[float, float]]  # British National Grid metres
    polygon_wgs84: list[tuple[float, float]]  # lon, lat


def overpass_query(bbox=DOCKS_BBOX) -> str:
    s, w, n, e = bbox
    box = f"({s},{w},{n},{e})"
    return (
        f'[out:json][timeout:90];(nwr["amenity"="parking"]{box};'
        f'nwr["name"~"Cruise Terminal"]{box};);out tags geom;'
    )


def fetch_overpass(cache: Path, bbox=DOCKS_BBOX, urls=OVERPASS_URLS) -> dict:
    """Overpass response for the docks, cached as JSON (overpass-api.de blocks some networks)."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = urllib.parse.urlencode({"data": overpass_query(bbox)}).encode()
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "User-Agent": "Sotonship26/0.1 (github.com/Alex-Sebastian-Ene/Sotonship26)"
                },
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read())
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out), encoding="utf-8")
            return out
        except Exception as exc:  # noqa: BLE001  (try the next mirror)
            last = exc
    raise RuntimeError(f"all Overpass servers failed: {last}")


def classify(osm: dict) -> list[CarPark]:
    from pyproj import Transformer
    from shapely.geometry import Polygon

    to_bng = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)

    def polygon(e):
        g = e.get("geometry") or []
        if e["type"] != "way" or len(g) < 4:
            return None, None
        ll = [(p["lon"], p["lat"]) for p in g]
        p = Polygon([to_bng.transform(*xy) for xy in ll])
        return (p, ll) if p.is_valid and p.area > 50 else (None, None)

    terminals = {}
    for e in osm["elements"]:
        name = e.get("tags", {}).get("name", "")
        if name.endswith("Cruise Terminal") and e.get("tags", {}).get("amenity") != "parking":
            p, _ = polygon(e)
            if p is not None:
                terminals[name.replace(" Cruise Terminal", "")] = p
    if not terminals:
        raise ValueError("no cruise terminal outlines in the OSM data")

    out = []
    for e in osm["elements"]:
        tags = e.get("tags", {})
        if tags.get("amenity") != "parking":
            continue
        p, ll = polygon(e)
        if p is None:
            continue
        name = tags.get("name", "")
        operator = tags.get("operator", "").strip().lower()
        term, dist = min(
            ((t, poly.distance(p)) for t, poly in terminals.items()), key=lambda x: x[1]
        )
        if COMPOUND_NAME.search(name) or tags.get("access") == "no":
            kind = "vehicle_compound"
        elif operator in CRUISE_OPERATOR or CRUISE_NAME.search(name):
            kind = "cruise"
        elif dist <= NEAR_TERMINAL_M and not SHOPPING_NAME.search(name):
            kind = "cruise"
        else:
            kind = "control"
        cap_tag = re.match(r"\d+", tags.get("capacity", ""))
        multi = tags.get("parking") == "multi-storey"
        out.append(
            CarPark(
                osm_id=f"{e['type']}/{e['id']}",
                name=name or "(unnamed)",
                kind=kind,
                terminal=term,
                terminal_m=round(dist, 1),
                capacity=int(cap_tag.group()) if cap_tag else int(p.area / M2_PER_SPACE),
                capacity_source="tag" if cap_tag else "area",
                multi_storey=multi,
                area_m2=round(p.area, 1),
                polygon_bng=[tuple(map(float, c)) for c in p.exterior.coords],
                polygon_wgs84=ll,
            )
        )
    return out


def load_carparks(cache_dir: Path) -> list[CarPark]:
    return classify(fetch_overpass(cache_dir / "overpass_docks.json"))


def to_geojson(parks: list[CarPark]) -> dict:
    feats = []
    for p in parks:
        props = {k: v for k, v in asdict(p).items() if not k.startswith("polygon")}
        feats.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Polygon", "coordinates": [p.polygon_wgs84]},
            }
        )
    return {
        "type": "FeatureCollection",
        "features": feats,
        "attribution": "© OpenStreetMap contributors (ODbL)",
    }
