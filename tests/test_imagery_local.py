"""LocalGeoTiffProvider groups Digimap-style 1 km tiles by capture date and mosaics them."""

from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")

from rasterio.transform import from_origin  # noqa: E402

from sotonship26.imagery.providers import LocalGeoTiffProvider, order_tiles  # noqa: E402


def tile(path, e0, n0, value, size=40, gsd=25.0):
    # synthetic 1 km tile at 25 m per pixel (real tiles are 25 cm; only the georeferencing matters)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=3,
        dtype="uint8",
        crs="EPSG:27700",
        transform=from_origin(e0, n0 + size * gsd, gsd, gsd),
    ) as dst:
        dst.write(np.full((3, size, size), value, dtype="uint8"))


def test_lonlat_jpeg_source_is_clipped_to_metric_pixels(tmp_path):
    # drone mosaics on OpenAerialMap are lon/lat, JPEG-compressed YCbCr; both broke the clip once
    from sotonship26.imagery.providers import clip_to_geotiff

    src = tmp_path / "drone.tif"
    deg = 0.05 / 111_320  # about 5 cm
    with rasterio.open(
        src,
        "w",
        driver="GTiff",
        height=400,
        width=400,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(-1.40, 50.90, deg, deg),
        compress="jpeg",
        photometric="ycbcr",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(np.full((3, 400, 400), 120, dtype="uint8"))
    w, s, e, n = -1.40 + 50 * deg, 50.90 - 350 * deg, -1.40 + 350 * deg, 50.90 - 50 * deg
    aoi = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    out = clip_to_geotiff(str(src), aoi, tmp_path / "clip.tif", target_gsd=0.25)
    with rasterio.open(out) as clip:
        assert clip.crs.to_epsg() == 32630  # UTM zone 30N
        assert abs(clip.transform.a - 0.25) < 1e-9
        # 300 source pixels: 15 m north-south, 15 m x cos(50.9 deg) = 9.5 m east-west
        assert 36 <= clip.width <= 41 and 57 <= clip.height <= 62


def test_order_tiles_cover_the_docks():
    t = order_tiles()
    assert len(t) == 35 and t[0] == "SU3709" and t[-1] == "SU4313"


def test_tiles_grouped_by_capture_date_and_mosaicked(tmp_path):
    tile(tmp_path / "su4011.tif", 440000, 111000, 10)
    tile(tmp_path / "su4111.tif", 441000, 111000, 20)
    tile(tmp_path / "su4211_2023-06-04.tif", 442000, 111000, 30)
    (tmp_path / "capture_dates.csv").write_text(
        "file,date,time\nsu4011.tif,2022-01-14,10:40\nsu4111.tif,2022-01-14,10:40\n",
        encoding="utf-8",
    )
    prov = LocalGeoTiffProvider(tmp_path)
    scenes = prov.search()
    assert [s.extra["tiles"] for s in scenes] == [2, 1]
    assert scenes[0].when.isoformat() == "2022-01-14T10:40:00"
    assert scenes[1].when.hour == 11  # no time given: assumed late morning
    assert "Digimap" in scenes[0].licence

    from pyproj import Transformer

    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    ring = [
        to_ll.transform(e, n)
        for e, n in (
            (440500, 111200),
            (441500, 111200),
            (441500, 111800),
            (440500, 111800),
            (440500, 111200),
        )
    ]
    out = prov.fetch(scenes[0], {"type": "Polygon", "coordinates": [ring]}, tmp_path / "clip.tif")
    with rasterio.open(out) as src:
        data = src.read(1)
    assert set(np.unique(data)) == {10, 20}  # the clip spans both tiles of that date


def test_digimap_jpeg_world_file_tiles(tmp_path):
    # Digimap Aerial downloads are JPEG + .jgw with no CRS; they are read as British National Grid
    from PIL import Image
    from pyproj import Transformer

    for e0, val in ((440000, 60), (441000, 200)):
        name = f"2023-06-04_SU{e0 // 1000 % 100:02d}11"
        Image.fromarray(np.full((40, 40, 3), val, np.uint8)).save(tmp_path / f"{name}.jpg")
        (tmp_path / f"{name}.jgw").write_text(f"25\n0\n0\n-25\n{e0 + 12.5}\n{112000 - 12.5}\n")
    (scene,) = LocalGeoTiffProvider(tmp_path).search()
    assert scene.extra["tiles"] == 2 and scene.gsd_m == 25
    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    ring = [
        to_ll.transform(e, n)
        for e, n in ((440500, 111200), (441500, 111200), (441500, 111800), (440500, 111800))
    ]
    aoi = {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}
    out = LocalGeoTiffProvider(tmp_path).fetch(scene, aoi, tmp_path / "clip.tif")
    with rasterio.open(out) as src:
        assert src.crs.to_epsg() == 27700
        values = set(np.unique(src.read(1)))
    assert any(v < 100 for v in values) and any(v > 150 for v in values)  # both tiles (JPEG-lossy)
