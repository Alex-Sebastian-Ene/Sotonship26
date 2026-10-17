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
* ``LocalGeoTiffProvider``: GeoTIFFs dropped in a folder. **The source we use is Getmapping aerial
  photography (25 cm) from EDINA Digimap Aerial**, downloaded by hand with a university login
  (no script logs in to or scrapes Digimap). Its licence allows analysis but not display on the
  internet: the imagery never goes into git, the app or the video. Car counts derived from it may
  be shown, credited "Getmapping via EDINA Digimap". The council's APGB photography (Public Sector
  Geospatial Agreement) or marketplace scenes work the same way.

  Digimap delivers 1 km tiles, and tiles can come from different flights. Tiles are grouped by
  capture date (from the file name or a ``capture_dates.csv`` next to them), and each date is one
  scene, mosaicked on fetch: one occupancy observation per date. ``order_tiles()`` lists the
  tiles that cover the docks.

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


DIGIMAP_CREDIT = "Getmapping via EDINA Digimap"
OS_100KM = {(4, 1): "SU", (4, 0): "SZ"}  # (easting // 100 km, northing // 100 km) -> letters


def order_tiles(bbox=(50.885, -1.475, 50.915, -1.380)) -> list[str]:
    """OS 1 km tile names (e.g. SU3709) covering a south, west, north, east WGS84 box."""
    from pyproj import Transformer

    s, w, n, e = bbox
    tr = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    xs, ys = zip(*(tr.transform(lon, lat) for lon in (w, e) for lat in (s, n)), strict=True)
    out = []
    for ny in range(int(min(ys) // 1000), int(max(ys) // 1000) + 1):
        for ex in range(int(min(xs) // 1000), int(max(xs) // 1000) + 1):
            letters = OS_100KM.get((ex // 100, ny // 100))
            if letters is None:
                raise ValueError(f"tile {ex} km E, {ny} km N is outside SU/SZ")
            out.append(f"{letters}{ex % 100:02d}{ny % 100:02d}")
    return out


def clip_to_geotiff(src_path, aoi_lonlat, out: Path, target_gsd: float | None = None) -> Path:
    """Read the AOI window of a raster (local path, COG URL, or a list of tiles to mosaic) and
    write it as a GeoTIFF."""
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform

    if isinstance(src_path, (list, tuple)):
        if len(src_path) > 1:
            from rasterio.merge import merge

            srcs = [rasterio.open(x) for x in src_path]
            try:
                to_src = Transformer.from_crs("EPSG:4326", srcs[0].crs, always_xy=True).transform
                geom = shape(aoi_lonlat) if isinstance(aoi_lonlat, dict) else aoi_lonlat
                data, tr = merge(srcs, bounds=shp_transform(to_src, geom).bounds)
                profile = srcs[0].profile | {
                    "driver": "GTiff",
                    "height": data.shape[1],
                    "width": data.shape[2],
                    "transform": tr,
                    "compress": "deflate",
                }
            finally:
                for x in srcs:
                    x.close()
            for k in ("blockxsize", "blockysize", "tiled", "photometric"):
                profile.pop(k, None)
            mosaic = out.with_suffix(".mosaic.tif")
            mosaic.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(mosaic, "w", **profile) as dst:
                dst.write(data)
            src_path = str(mosaic)
        else:
            src_path = src_path[0]

    with rasterio.open(src_path) as src:
        geom = shape(aoi_lonlat) if isinstance(aoi_lonlat, dict) else aoi_lonlat
        if src.crs and src.crs.is_geographic and target_gsd:
            return _warp_metric(src, geom, out, target_gsd)
        to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform
        bounds = shp_transform(to_src, geom).bounds
        win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        scale = 1.0
        if target_gsd:
            scale = max(abs(src.transform.a) / target_gsd, 1e-6)
        h, w = max(1, int(win.height * scale)), max(1, int(win.width * scale))
        data = src.read(window=win, out_shape=(src.count, h, w))
        tr = src.window_transform(win) * src.window_transform(win).scale(
            win.width / w, win.height / h
        )
        profile = src.profile | {
            "driver": "GTiff",
            "height": h,
            "width": w,
            "transform": tr,
            "compress": "deflate",
        }
        for k in (
            "blockxsize",
            "blockysize",
            "tiled",
            "photometric",
        ):  # JPEG/YCbCr sources: re-encode as RGB
            profile.pop(k, None)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data)
    return out


def _warp_metric(src, geom, out: Path, gsd: float) -> Path:
    """Lon/lat sources (e.g. drone mosaics): resample the AOI into its UTM zone at ``gsd`` metres,
    so pixels are square and the size of a car in pixels matches a projected scene."""
    import math

    import rasterio
    from pyproj import Transformer
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from shapely.ops import transform as shp_transform

    lon, lat = geom.centroid.x, geom.centroid.y
    epsg = (32600 if lat >= 0 else 32700) + int(math.floor((lon + 180) / 6)) + 1
    minx, miny, maxx, maxy = shp_transform(
        Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform, geom
    ).bounds
    w, h = max(1, int((maxx - minx) / gsd)), max(1, int((maxy - miny) / gsd))
    tr = from_origin(minx, maxy, gsd, gsd)
    with WarpedVRT(
        src, crs=f"EPSG:{epsg}", transform=tr, width=w, height=h, resampling=Resampling.bilinear
    ) as vrt:
        data = vrt.read()
        profile = {
            "driver": "GTiff",
            "height": h,
            "width": w,
            "count": vrt.count,
            "dtype": vrt.dtypes[0],
            "crs": f"EPSG:{epsg}",
            "transform": tr,
            "compress": "deflate",
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data)
    return out


class StacProvider:
    name = "stac"

    def __init__(
        self, url: str, collections: list[str], headers: dict | None = None, asset: str = "visual"
    ):
        self.url, self.collections, self.headers, self.asset = (
            url,
            collections,
            headers or {},
            asset,
        )

    def search(self, aoi, start: str, end: str, limit: int = 50) -> list[Scene]:
        from pystac_client import Client

        client = Client.open(self.url, headers=self.headers)
        items = client.search(
            collections=self.collections, intersects=aoi, datetime=f"{start}/{end}", max_items=limit
        ).items()
        out = []
        for it in items:
            p = it.properties
            gsd = p.get("gsd") or next(
                (b.get("gsd") for b in p.get("eo:bands", []) if b.get("gsd")), None
            )
            if gsd is None and self.asset in it.assets:  # STAC 1.0 puts it on the asset
                ex = it.assets[self.asset].extra_fields
                gsd = ex.get("gsd") or next(
                    (
                        b.get("spatial_resolution")
                        for b in ex.get("raster:bands", [])
                        if b.get("spatial_resolution")
                    ),
                    None,
                )
            out.append(
                Scene(
                    it.id,
                    self.name,
                    it.datetime,
                    gsd,
                    p.get("eo:cloud_cover"),
                    it.geometry,
                    {k: a.href for k, a in it.assets.items()},
                    p.get("license", ""),
                )
            )
        return out

    def fetch(self, scene: Scene, aoi, out: Path, target_gsd: float | None = None) -> Path:
        href = scene.assets.get(self.asset) or next(iter(scene.assets.values()))
        return clip_to_geotiff(href, aoi, out, target_gsd)


class PlanetProvider:
    """Planet Data API search + Orders API clip. Untested without a key (Planet v1/v2 APIs)."""

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

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body else None,
            method=method or ("POST" if body else "GET"),
        )
        req.add_header(
            "Authorization", "Basic " + base64.b64encode(f"{self.key}:".encode()).decode()
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    def search(self, aoi, start: str, end: str, max_cloud: float = 0.2) -> list[Scene]:
        flt = {
            "type": "AndFilter",
            "config": [
                {"type": "GeometryFilter", "field_name": "geometry", "config": aoi},
                {
                    "type": "DateRangeFilter",
                    "field_name": "acquired",
                    "config": {"gte": f"{start}T00:00:00Z", "lte": f"{end}T23:59:59Z"},
                },
                {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": max_cloud}},
            ],
        }
        res = self._req(self.DATA, {"item_types": self.item_types, "filter": flt})
        return [
            Scene(
                f["id"],
                self.name,
                datetime.fromisoformat(f["properties"]["acquired"].replace("Z", "+00:00")),
                f["properties"].get("gsd"),
                f["properties"].get("cloud_cover"),
                f["geometry"],
                {},
                "Planet licence (see your agreement)",
                {"item_type": f["properties"].get("item_type")},
            )
            for f in res.get("features", [])
        ]

    def fetch(
        self,
        scene: Scene,
        aoi,
        out: Path,
        target_gsd: float | None = None,
        poll_s: int = 30,
        timeout_s: int = 3600,
    ) -> Path:
        order = self._req(
            self.ORDERS,
            {
                "name": f"sotonship26-{scene.id}",
                "products": [
                    {
                        "item_ids": [scene.id],
                        "item_type": scene.extra.get("item_type", self.item_types[0]),
                        "product_bundle": "pansharpened",
                    }
                ],
                "tools": [{"clip": {"aoi": aoi}}],
            },
        )
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
    """GeoTIFF tiles in a folder, one scene per capture date.

    The date comes from ``capture_dates.csv`` in the folder (columns ``file,date`` and optional
    ``time`` HH:MM, copied from Digimap's tile metadata), else from a YYYY-MM-DD[THHMM] in the
    file name. Without a time the image is assumed to be taken at 11:00 (survey flights run
    around midday), which matters on embark and return days. Tiles without a date are skipped.
    """

    name = "local"
    STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T_](\d{2})(\d{2}))?")

    def __init__(
        self, folder: Path, licence: str = DIGIMAP_CREDIT + " (analysis only, not for display)"
    ):
        self.folder, self.licence = Path(folder), licence

    def dates(self) -> dict[str, datetime]:
        out = {}
        sidecar = self.folder / "capture_dates.csv"
        if sidecar.exists():
            import csv

            with sidecar.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    t = (r.get("time") or "11:00").strip()
                    out[r["file"]] = datetime.fromisoformat(f"{r['date'].strip()}T{t}")
        for p in self.folder.glob("*.tif"):
            m = self.STAMP.search(p.name)
            if p.name not in out and m:
                out[p.name] = datetime.fromisoformat(
                    m.group(1) + (f"T{m.group(2)}:{m.group(3)}" if m.group(2) else "T11:00")
                )
        return out

    def search(self, aoi=None, start: str = "0000", end: str = "9999") -> list[Scene]:
        import rasterio

        by_date: dict[datetime, list[Path]] = {}
        for name, when in self.dates().items():
            p = self.folder / name
            if p.exists() and start <= when.date().isoformat() <= end:
                by_date.setdefault(when, []).append(p)
        out = []
        for when, files in sorted(by_date.items()):
            with rasterio.open(files[0]) as src:
                gsd = abs(src.transform.a) if src.crs and src.crs.is_projected else None
            out.append(
                Scene(
                    f"{when:%Y-%m-%dT%H%M}",
                    self.name,
                    when,
                    gsd,
                    None,
                    None,
                    {"files": [str(f) for f in sorted(files)]},
                    self.licence,
                    {"tiles": len(files)},
                )
            )
        return out

    def fetch(self, scene: Scene, aoi, out: Path, target_gsd: float | None = None) -> Path:
        return clip_to_geotiff(scene.assets["files"], aoi, out, target_gsd)


def provider_from_env():
    """IMAGERY_PROVIDER = local (default) | stac | planet, configured by environment variables."""
    kind = os.environ.get("IMAGERY_PROVIDER", "local")
    if kind == "planet":
        return PlanetProvider()
    if kind == "stac":
        headers = {}
        if os.environ.get("STAC_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['STAC_TOKEN']}"
        return StacProvider(
            os.environ["STAC_URL"],
            os.environ["STAC_COLLECTIONS"].split(","),
            headers,
            os.environ.get("STAC_ASSET", "visual"),
        )
    return LocalGeoTiffProvider(Path(os.environ.get("IMAGERY_DIR", "data/raw/imagery")))
