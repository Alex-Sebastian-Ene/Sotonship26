"""Satellite and aerial imagery providers behind one interface.

``search(aoi, start, end)`` lists scenes over an area of interest (lon/lat polygon) and
``fetch(scene, aoi, out)`` writes a GeoTIFF clipped to it. Counting cars needs 50 cm per pixel or
sharper, which free satellites do not reach (Sentinel-2 is 10 m), so the useful providers need an
account and a licence:

* ``StacProvider``: any STAC API (UP42, Sentinel Hub's catalogue, an internal store). Works with
  public STACs such as Earth Search for testing the plumbing.
* ``PlanetProvider``: Planet SkySat (50 cm) archive via the Data API, ordered and clipped via the
  Orders API. Needs ``PL_API_KEY`` (Planet's Education and Research programme gives students
  access).
* ``LocalGeoTiffProvider``: GeoTIFFs dropped in a folder, e.g. scenes bought from a marketplace,
  or the council's APGB aerial photography under the Public Sector Geospatial Agreement.

Tiles from Google, Bing, Esri or Mapbox basemaps are deliberately not supported: their terms
forbid downloading them for automated analysis. Keys come from the environment, never git.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Scene:
    id: str
    provider: str
    when: datetime
    gsd_m: float | None
    cloud: float | None
    footprint: dict | None  # GeoJSON geometry, lon/lat
    assets: dict = field(default_factory=dict)  # name -> href
    licence: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def can_count_cars(self) -> bool:
        return self.gsd_m is not None and self.gsd_m <= 0.5


def clip_to_geotiff(src_path: str, aoi_lonlat, out: Path, target_gsd: float | None = None) -> Path:
    """Read the AOI window of a raster (local path or COG URL) and write it as a GeoTIFF."""
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform

    with rasterio.open(src_path) as src:
        geom = shape(aoi_lonlat) if isinstance(aoi_lonlat, dict) else aoi_lonlat
        to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform
        bounds = shp_transform(to_src, geom).bounds
        win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        scale = 1.0
        if target_gsd:
            scale = max(abs(src.transform.a) / target_gsd, 1e-6)
        h, w = max(1, int(win.height * scale)), max(1, int(win.width * scale))
        data = src.read(window=win, out_shape=(src.count, h, w))
        tr = src.window_transform(win) * src.window_transform(win).scale(win.width / w, win.height / h)
        profile = src.profile | {"driver": "GTiff", "height": h, "width": w, "transform": tr,
                                 "compress": "deflate"}
        profile.pop("blockxsize", None), profile.pop("blockysize", None), profile.pop("tiled", None)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data)
    return out


class StacProvider:
    name = "stac"

    def __init__(self, url: str, collections: list[str], headers: dict | None = None,
                 asset: str = "visual"):
        self.url, self.collections, self.headers, self.asset = url, collections, headers or {}, asset

    def search(self, aoi, start: str, end: str, limit: int = 50) -> list[Scene]:
        from pystac_client import Client

        client = Client.open(self.url, headers=self.headers)
        items = client.search(collections=self.collections, intersects=aoi,
                              datetime=f"{start}/{end}", max_items=limit).items()
        out = []
        for it in items:
            p = it.properties
            gsd = p.get("gsd") or next((b.get("gsd") for b in p.get("eo:bands", []) if b.get("gsd")), None)
            out.append(Scene(it.id, self.name, it.datetime, gsd, p.get("eo:cloud_cover"),
                             it.geometry, {k: a.href for k, a in it.assets.items()},
                             p.get("license", "")))
        return out

    def fetch(self, scene: Scene, aoi, out: Path, target_gsd: float | None = None) -> Path:
        href = scene.assets.get(self.asset) or next(iter(scene.assets.values()))
        return clip_to_geotiff(href, aoi, out, target_gsd)


class PlanetProvider:
    """Planet Data API search + Orders API clip. Untested without a key; follows Planet's v1/v2 APIs."""

    name = "planet"
    DATA = "https://api.planet.com/data/v1/quick-search"
    ORDERS = "https://api.planet.com/compute/ops/orders/v2"

    def __init__(self, api_key: str | None = None, item_types=("SkySatCollect",)):
        self.key = api_key or os.environ.get("PL_API_KEY")
        if not self.key:
            raise RuntimeError("set PL_API_KEY (Planet account; keep it out of git)")
        self.item_types = list(item_types)

    def _req(self, url, body=None, method=None):
        import base64

        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     method=method or ("POST" if body else "GET"))
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{self.key}:".encode()).decode())
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    def search(self, aoi, start: str, end: str, max_cloud: float = 0.2) -> list[Scene]:
        flt = {"type": "AndFilter", "config": [
            {"type": "GeometryFilter", "field_name": "geometry", "config": aoi},
            {"type": "DateRangeFilter", "field_name": "acquired",
             "config": {"gte": f"{start}T00:00:00Z", "lte": f"{end}T23:59:59Z"}},
            {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": max_cloud}}]}
        res = self._req(self.DATA, {"item_types": self.item_types, "filter": flt})
        return [Scene(f["id"], self.name, datetime.fromisoformat(f["properties"]["acquired"].replace("Z", "+00:00")),
                      f["properties"].get("gsd"), f["properties"].get("cloud_cover"), f["geometry"],
                      {}, "Planet licence (see your agreement)", {"item_type": f["properties"].get("item_type")})
                for f in res.get("features", [])]

    def fetch(self, scene: Scene, aoi, out: Path, target_gsd: float | None = None,
              poll_s: int = 30, timeout_s: int = 3600) -> Path:
        order = self._req(self.ORDERS, {
            "name": f"sotonship26-{scene.id}",
            "products": [{"item_ids": [scene.id], "item_type": scene.extra.get("item_type", self.item_types[0]),
                          "product_bundle": "pansharpened"}],
            "tools": [{"clip": {"aoi": aoi}}]})
        url, t0 = order["_links"]["_self"], time.time()
        while time.time() - t0 < timeout_s:
            state = self._req(url)
            if state["state"] == "success":
                tif = next(r for r in state["_links"]["results"] if r["name"].endswith(".tif"))
                tmp = out.with_suffix(".order.tif")
                urllib.request.urlretrieve(tif["location"], tmp)
                return clip_to_geotiff(str(tmp), aoi, out, target_gsd)
            if state["state"] in ("failed", "partial", "cancelled"):
                raise RuntimeError(f"Planet order {state['id']} {state['state']}")
            time.sleep(poll_s)
        raise TimeoutError("Planet order did not finish in time")


class LocalGeoTiffProvider:
    """GeoTIFFs in a folder; the date comes from a YYYY-MM-DD[THHMM] in the file name."""

    name = "local"
    STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T_](\d{2})(\d{2}))?")

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def search(self, aoi=None, start: str = "0000", end: str = "9999") -> list[Scene]:
        import rasterio

        out = []
        for p in sorted(self.folder.glob("*.tif")):
            m = self.STAMP.search(p.name)
            if not m:
                continue
            when = datetime.fromisoformat(m.group(1) + (f"T{m.group(2)}:{m.group(3)}" if m.group(2) else "T11:00"))
            if not (start <= when.date().isoformat() <= end):
                continue
            with rasterio.open(p) as src:
                gsd = abs(src.transform.a) if src.crs and src.crs.is_projected else None
            out.append(Scene(p.stem, self.name, when, gsd, None, None, {"file": str(p)}, "see file"))
        return out

    def fetch(self, scene: Scene, aoi, out: Path, target_gsd: float | None = None) -> Path:
        return clip_to_geotiff(scene.assets["file"], aoi, out, target_gsd)


def provider_from_env():
    """IMAGERY_PROVIDER = local (default) | stac | planet, configured by environment variables."""
    kind = os.environ.get("IMAGERY_PROVIDER", "local")
    if kind == "planet":
        return PlanetProvider()
    if kind == "stac":
        headers = {}
        if os.environ.get("STAC_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['STAC_TOKEN']}"
        return StacProvider(os.environ["STAC_URL"], os.environ["STAC_COLLECTIONS"].split(","), headers,
                            os.environ.get("STAC_ASSET", "visual"))
    return LocalGeoTiffProvider(Path(os.environ.get("IMAGERY_DIR", "data/raw/imagery")))
