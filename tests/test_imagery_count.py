"""Per-car-park counting: enlargement and the clip transform map detections back to BNG."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")
pytest.importorskip("PIL")

from rasterio.transform import from_origin  # noqa: E402

from sotonship26.imagery.carparks import CarPark  # noqa: E402
from sotonship26.imagery.count import count_scene, dock_counts  # noqa: E402
from sotonship26.imagery.providers import LocalGeoTiffProvider  # noqa: E402


class FixedSpot:
    """Stub detector: one small vehicle at a fixed fraction of every crop it is given."""

    names = {10: "small vehicle", 9: "large vehicle"}

    def __init__(self, fx: float, fy: float):
        self.fx, self.fy, self.shapes = fx, fy, []

    def predict(self, crop, conf=0.25, imgsz=1024, verbose=False):
        h, w = crop.shape[:2]
        self.shapes.append((h, w))
        boxes = SimpleNamespace(
            xywhr=np.array([[w * self.fx, h * self.fy, 18.0, 7.0, 0.0]]),
            cls=np.array([10.0]),
            conf=np.array([0.8]),
        )
        return [SimpleNamespace(names=self.names, obb=boxes, boxes=None)]


def park(osm_id, x0, y0, x1, y1, terminal="Mayflower", kind="cruise"):
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return CarPark(osm_id, "test", kind, terminal, 0.0, 8, "area", False, 200.0, ring, [])


@pytest.fixture
def scene(tmp_path):
    # 200 m x 200 m BNG tile at 25 cm, named by capture date as Digimap tiles are
    path = tmp_path / "2023-06-04_SU4011.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=800,
        width=800,
        count=3,
        dtype="uint8",
        crs="EPSG:27700",
        transform=from_origin(440000, 111200, 0.25, 0.25),
    ) as dst:
        dst.write(np.full((3, 800, 800), 90, dtype="uint8"))
    prov = LocalGeoTiffProvider(tmp_path)
    (sc,) = prov.search()
    return prov, sc, tmp_path


def test_centre_detection_lands_in_the_car_park(scene):
    prov, sc, tmp = scene
    p = park("way/1", 440090, 111090, 440110, 111100)  # 20 m x 10 m, clip is 50 m x 40 m
    model = FixedSpot(0.5, 0.5)
    rows = count_scene(prov, sc, [p], tmp / "clips", model=model, weights="stub.pt", upsample=4)
    assert model.shapes == [(640, 800)]  # 200 x 160 px enlarged x4, one crop
    assert rows.loc[0, "cars"] == 1 and rows.loc[0, "dock"] == "west"
    assert rows.loc[0, "when"].isoformat() == "2023-06-04T11:00:00"


def test_detection_in_the_margin_is_not_counted(scene):
    prov, sc, tmp = scene
    p = park("way/2", 440090, 111090, 440110, 111100, terminal="Ocean")
    rows = count_scene(prov, sc, [p], tmp / "clips", model=FixedSpot(0.05, 0.05), weights="stub.pt")
    assert rows.loc[0, "cars"] == 0


def test_dock_counts_sum_cruise_parks_only(scene):
    prov, sc, tmp = scene
    parks = [
        park("way/1", 440090, 111090, 440110, 111100),
        park("way/3", 440030, 111030, 440050, 111040),
        park("way/4", 440150, 111150, 440170, 111160, kind="control"),
    ]
    rows = count_scene(prov, sc, parks, tmp / "clips", model=FixedSpot(0.5, 0.5), weights="stub.pt")
    d = dock_counts(rows)
    assert d[["dock", "cars", "parks"]].to_dict("records") == [
        {"dock": "west", "cars": 2, "parks": 2}
    ]
