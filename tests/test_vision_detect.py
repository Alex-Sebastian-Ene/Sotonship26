"""Offline tests for sotonship26.vision.detect, with a stub in place of the YOLO model.

The stub "detects" a fixed list of vehicles given in full-image pixels. To know where each crop
sits in the full image it reads the crop's top-left pixel, which the test image encodes as its
own (x, y). Set SOTONSHIP_VISION_SMOKE=1 to also run the real street model once (downloads
yolo11n.pt into data/cache/models/ on first use).
"""

from __future__ import annotations

import math
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from sotonship26.vision import detect

shapely = pytest.importorskip("shapely")
from shapely.geometry import box  # noqa: E402

COCO = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
DOTA = {9: "large vehicle", 10: "small vehicle", 1: "ship"}


def coord_image(height: int, width: int) -> np.ndarray:
    """RGB image whose pixel (x, y) encodes x and y, so a crop can tell where it came from."""
    ys, xs = np.mgrid[0:height, 0:width]
    rgb = np.stack([xs % 256, ys % 256, (xs // 256) * 16 + ys // 256], axis=-1)
    return rgb.astype(np.uint8)


def crop_origin(bgr: np.ndarray) -> tuple[int, int]:
    b, g, r = (int(v) for v in bgr[0, 0])
    return (b // 16) * 256 + r, (b % 16) * 256 + g


class StubModel:
    """Returns every vehicle whose centre lies inside the crop, in crop pixels."""

    def __init__(self, vehicles, names, obb: bool):
        self.vehicles = vehicles  # [(cx, cy, class_id, conf)] in full-image pixels
        self.names = names
        self.obb = obb
        self.calls: list[dict] = []

    def predict(self, crop, conf=0.25, imgsz=640, verbose=False):
        h, w = crop.shape[:2]
        x0, y0 = crop_origin(crop)
        self.calls.append({"origin": (x0, y0), "shape": (h, w), "conf": conf, "imgsz": imgsz})
        rows = [
            (cx - x0, cy - y0, c, p)
            for cx, cy, c, p in self.vehicles
            if x0 <= cx < x0 + w and y0 <= cy < y0 + h and p >= conf
        ]
        arr = np.array([[x, y, 20.0, 10.0, 0.3] for x, y, _, _ in rows]).reshape(-1, 5)
        cls = np.array([c for *_, c, _ in rows], dtype=float)
        confs = np.array([p for *_, p in rows], dtype=float)
        if self.obb:
            boxes = SimpleNamespace(xywhr=arr, cls=cls, conf=confs)
            return [SimpleNamespace(names=self.names, obb=boxes, boxes=None)]
        boxes = SimpleNamespace(xywh=arr[:, :4], cls=cls, conf=confs)
        return [SimpleNamespace(names=self.names, obb=None, boxes=boxes)]


def test_coord_image_round_trip():
    rgb = coord_image(1500, 1300)
    for x, y in [(0, 0), (255, 256), (1299, 1499), (896, 768)]:
        assert crop_origin(rgb[y:, x:, ::-1]) == (x, y)


def test_street_class_mapping_and_schema():
    vehicles = [
        (10, 10, 2, 0.9),  # car
        (50, 10, 2, 0.7),  # car
        (90, 10, 7, 0.8),  # truck
        (130, 10, 5, 0.6),  # bus
        (170, 10, 3, 0.9),  # motorcycle: ignored
        (210, 10, 0, 0.9),  # person: ignored
    ]
    model = StubModel(vehicles, COCO, obb=False)
    out = detect.count_vehicles(coord_image(120, 240), model=model)
    assert list(out.columns) == detect.COLUMNS
    assert out.to_dict("records")[0] | {"conf_mean": None} == {
        "polygon_id": "all",
        "cars": 2,
        "large_vehicles": 2,
        "conf_mean": None,
        "model": "yolo11n.pt",
    }
    assert out["conf_mean"].iloc[0] == pytest.approx((0.9 + 0.7 + 0.8 + 0.6) / 4)
    assert len(model.calls) == 1 and model.calls[0]["imgsz"] == detect.IMGSZ["street"]


def test_conf_threshold_passed_to_model():
    model = StubModel([(10, 10, 2, 0.3), (40, 10, 2, 0.6)], COCO, obb=False)
    out = detect.count_vehicles(coord_image(64, 64), conf=0.5, model=model)
    assert out["cars"].iloc[0] == 1
    assert model.calls[0]["conf"] == 0.5


def test_no_detections_gives_zero_and_nan():
    out = detect.count_vehicles(coord_image(64, 64), model=StubModel([], COCO, obb=False))
    row = out.iloc[0]
    assert (row["cars"], row["large_vehicles"]) == (0, 0)
    assert math.isnan(row["conf_mean"])


def test_street_polygons_by_centre_dict_list_and_points():
    vehicles = [(20, 20, 2, 0.9), (80, 20, 7, 0.9), (80, 80, 2, 0.9), (50, 50, 2, 0.9)]
    model = StubModel(vehicles, COCO, obb=False)
    rgb = coord_image(100, 100)
    polys = {"left": box(0, 0, 50, 100), "top_right": [(50, 0), (100, 0), (100, 40), (50, 40)]}
    out = detect.count_vehicles(rgb, polygons=polys, model=model).set_index("polygon_id")
    # (50, 50) sits on the edge of "left": boundary counts as inside.
    assert out.loc["left", ["cars", "large_vehicles"]].tolist() == [2, 0]
    assert out.loc["top_right", ["cars", "large_vehicles"]].tolist() == [0, 1]

    out = detect.count_vehicles(rgb, polygons=[box(60, 60, 100, 100)], model=model)
    assert out["polygon_id"].tolist() == ["0"]
    assert out["cars"].tolist() == [1]
    assert math.isnan(
        detect.count_vehicles(rgb, polygons=[box(0, 90, 5, 95)], model=model)["conf_mean"][0]
    )


def test_bad_polygon_and_mode_raise():
    model = StubModel([], COCO, obb=False)
    with pytest.raises(ValueError):
        detect.count_vehicles(coord_image(10, 10), polygons=[[(0, 0), (1, 1)]], model=model)
    with pytest.raises(ValueError):
        detect.count_vehicles(coord_image(10, 10), mode="satellite", model=model)


def test_tile_windows_cover_and_overlap():
    wins = detect.tile_windows(2500, 1000, tile=1024, overlap=128)
    assert wins == [(0, 0, 1000, 1024), (0, 738, 1000, 1762), (0, 1476, 1000, 2500)]
    for n in [1025, 1300, 1920, 4000, 10_000]:
        starts = sorted({x0 for x0, *_ in detect.tile_windows(10, n, tile=1024, overlap=128)})
        assert starts[0] == 0 and starts[-1] == n - 1024
        assert all(b - a <= 1024 - 128 for a, b in zip(starts, starts[1:], strict=False))
    assert detect.tile_windows(500, 600) == [(0, 0, 600, 500)]
    with pytest.raises(ValueError):
        detect.tile_windows(100, 100, tile=64, overlap=64)


def test_aerial_tiling_counts_each_vehicle_once():
    h, w, tile, overlap = 1500, 1300, 512, 128
    rng = np.random.default_rng(0)
    vehicles = [(float(x), float(y), 10, 0.8) for x, y in rng.uniform(0, [w, h], (300, 2))]
    # Put some right inside the shared strips and on a four-way corner, the cases dedupe is for.
    vehicles += [(400.0, 100.0, 9, 0.9), (420.0, 450.0, 10, 0.9), (447.5, 447.5, 9, 0.9)]
    model = StubModel(vehicles, DOTA, obb=True)
    out = detect.count_vehicles(
        coord_image(h, w), mode="aerial", model=model, tile=tile, overlap=overlap
    )
    assert len(model.calls) > 4
    assert all(c["shape"] == (tile, tile) for c in model.calls)
    seen = sum(
        x0 <= cx < x0 + tile and y0 <= cy < y0 + tile
        for c in model.calls
        for (x0, y0) in [c["origin"]]
        for cx, cy, *_ in vehicles
    )
    assert seen > len(vehicles)  # without dedupe this image would be over-counted
    assert out["cars"].iloc[0] == 301
    assert out["large_vehicles"].iloc[0] == 2
    assert out["model"].iloc[0] == "yolo11s-obb.pt"


class FixedModel:
    """Returns the same detections (crop pixels) for every crop and records each crop's shape."""

    def __init__(self, rows, names):
        self.rows, self.names, self.shapes = rows, names, []

    def predict(self, crop, conf=0.25, imgsz=640, verbose=False):
        self.shapes.append(crop.shape[:2])
        arr = np.array([[x, y, 20.0, 10.0, 0.3] for x, y, _ in self.rows]).reshape(-1, 5)
        cls = np.array([c for *_, c in self.rows], dtype=float)
        boxes = SimpleNamespace(xywhr=arr, cls=cls, conf=np.full(len(self.rows), 0.9))
        return [SimpleNamespace(names=self.names, obb=boxes, boxes=None)]


def test_upsample_enlarges_input_and_maps_centres_back():
    model = FixedModel([(80.0, 40.0, 10), (10.0, 10.0, 9)], DOTA)
    rgb = np.zeros((60, 100, 3), dtype=np.uint8)
    det = detect.detect(rgb, model, "aerial", upsample=2.0)
    assert model.shapes == [(120, 200)]
    assert sorted(zip(det["cx"], det["cy"], strict=True)) == [(5.0, 5.0), (40.0, 20.0)]
    # Polygons stay in the original image's pixels.
    out = detect.count_vehicles(
        rgb, mode="aerial", polygons={"lot": box(30, 10, 50, 30)}, model=model, upsample=2.0
    )
    assert out.set_index("polygon_id").loc["lot", ["cars", "large_vehicles"]].tolist() == [1, 0]


def test_upsample_default_is_native_and_bad_values_raise():
    model = FixedModel([], DOTA)
    rgb = np.zeros((60, 100, 3), dtype=np.uint8)
    detect.detect(rgb, model, "aerial")
    assert model.shapes == [(60, 100)]
    for bad in (0, -1.0):
        with pytest.raises(ValueError, match="upsample"):
            detect.detect(rgb, model, "aerial", upsample=bad)


def test_aerial_dota_hyphenated_names_also_map():
    model = StubModel([(5, 5, 1, 0.9), (9, 9, 2, 0.9)], {1: "small-vehicle", 2: "ship"}, True)
    out = detect.count_vehicles(coord_image(32, 32), mode="aerial", model=model)
    assert (out["cars"].iloc[0], out["large_vehicles"].iloc[0]) == (1, 0)


def test_geotiff_polygons_in_british_national_grid(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    # 0.25 m pixels, top-left corner at (441000, 112000) BNG: Southampton docks area.
    transform = from_origin(441000.0, 112000.0, 0.25, 0.25)
    rgb = coord_image(400, 400)
    path = tmp_path / "tile.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=400, height=400, count=3, dtype="uint8",
        crs="EPSG:27700", transform=transform,
    ) as dst:
        dst.write(np.moveaxis(rgb, -1, 0))
    vehicles = [(40, 40, 10, 0.9), (360, 40, 10, 0.9), (360, 360, 9, 0.9)]
    model = StubModel(vehicles, DOTA, obb=True)
    # West half of the tile in metres: x 441000..441050, y 111900..112000.
    west = box(441000.0, 111900.0, 441050.0, 112000.0)
    south_east = box(441050.0, 111900.0, 441100.0, 111950.0)
    out = detect.count_vehicles(
        path, mode="aerial", polygons={"west": west, "se": south_east}, model=model
    ).set_index("polygon_id")
    assert out.loc["west", "cars"] == 1 and out.loc["west", "large_vehicles"] == 0
    assert out.loc["se", "cars"] == 0 and out.loc["se", "large_vehicles"] == 1


def test_image_path_and_greyscale_array(tmp_path):
    from PIL import Image

    path = tmp_path / "still.png"
    Image.fromarray(coord_image(64, 80)).save(path)
    model = StubModel([(30, 30, 2, 0.9)], COCO, obb=False)
    assert detect.count_vehicles(path, model=model)["cars"].iloc[0] == 1
    rgb, transform = detect.read_image(np.zeros((8, 8), dtype=np.uint16) + 1000)
    assert rgb.shape == (8, 8, 3) and rgb.dtype == np.uint8 and transform is None


def test_model_cache_loads_once_and_turns_off_sync(monkeypatch, tmp_path):
    loads = []
    settings = {"sync": True}
    fake = SimpleNamespace(YOLO=lambda p: loads.append(p) or SimpleNamespace(path=p))
    fake_utils = SimpleNamespace(SETTINGS=settings)
    monkeypatch.setitem(sys.modules, "ultralytics", fake)
    monkeypatch.setitem(sys.modules, "ultralytics.utils", fake_utils)
    monkeypatch.setattr(detect, "_MODELS", {})
    monkeypatch.delenv("YOLO_CONFIG_DIR", raising=False)
    a = detect.load_model("x.pt", models_dir=tmp_path)
    b = detect.load_model("x.pt", models_dir=tmp_path)
    assert a is b and loads == [str(tmp_path / "x.pt")]
    assert settings["sync"] is False
    assert os.environ["YOLO_CONFIG_DIR"] == str(tmp_path)


@pytest.mark.skipif(
    os.environ.get("SOTONSHIP_VISION_SMOKE") != "1", reason="set SOTONSHIP_VISION_SMOKE=1"
)
def test_smoke_real_street_model():
    pytest.importorskip("ultralytics")
    from ultralytics.utils import ASSETS

    out = detect.count_vehicles(ASSETS / "bus.jpg")
    assert isinstance(out, pd.DataFrame) and list(out.columns) == detect.COLUMNS
    assert out["large_vehicles"].iloc[0] >= 1  # the bus
