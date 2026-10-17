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
    with rasterio.open(path, "w", driver="GTiff", height=size, width=size, count=3, dtype="uint8",
                       crs="EPSG:27700", transform=from_origin(e0, n0 + size * gsd, gsd, gsd)) as dst:
        dst.write(np.full((3, size, size), value, dtype="uint8"))


def test_order_tiles_cover_the_docks():
    t = order_tiles()
    assert len(t) == 35 and t[0] == "SU3709" and t[-1] == "SU4313"


def test_tiles_grouped_by_capture_date_and_mosaicked(tmp_path):
    tile(tmp_path / "su4011.tif", 440000, 111000, 10)
    tile(tmp_path / "su4111.tif", 441000, 111000, 20)
    tile(tmp_path / "su4211_2023-06-04.tif", 442000, 111000, 30)
    (tmp_path / "capture_dates.csv").write_text(
        "file,date,time\nsu4011.tif,2022-01-14,10:40\nsu4111.tif,2022-01-14,10:40\n", encoding="utf-8")
    prov = LocalGeoTiffProvider(tmp_path)
    scenes = prov.search()
    assert [s.extra["tiles"] for s in scenes] == [2, 1]
    assert scenes[0].when.isoformat() == "2022-01-14T10:40:00"
    assert scenes[1].when.hour == 11  # no time given: assumed late morning
    assert "Digimap" in scenes[0].licence

    from pyproj import Transformer

    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    ring = [to_ll.transform(e, n) for e, n in
            ((440500, 111200), (441500, 111200), (441500, 111800), (440500, 111800), (440500, 111200))]
    out = prov.fetch(scenes[0], {"type": "Polygon", "coordinates": [ring]}, tmp_path / "clip.tif")
    with rasterio.open(out) as src:
        data = src.read(1)
    assert set(np.unique(data)) == {10, 20}  # the clip spans both tiles of that date
