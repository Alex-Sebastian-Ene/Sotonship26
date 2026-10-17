"""Count cars and large vehicles in an image with a pretrained Ultralytics YOLO model.

Two modes share one output (``COLUMNS``), one row per polygon:

- ``"street"``: a roadside camera still. COCO-pretrained ``yolo11n.pt``. COCO ``car`` counts as a
  car; ``truck`` and ``bus`` count as large vehicles. ``motorcycle`` and ``bicycle`` are ignored
  (too small and too rare on motorway stills to count reliably; vans come out as car or truck).
  Polygons are in pixel coordinates (lane regions drawn on the still).
- ``"aerial"``: an overhead tile, e.g. a Digimap 25 cm GeoTIFF. ``yolo11s-obb.pt``, an
  oriented-box model pretrained on DOTA v1: ``small-vehicle`` counts as a car, ``large-vehicle``
  as a large vehicle. Big rasters are cut into overlapping square crops (``TILE`` px, ``OVERLAP``
  px shared, at least); neighbouring crops split their shared strip down the middle and each
  keeps only the detections whose centre falls on its side, so a vehicle seen by two crops is
  counted once. For a
  GeoTIFF the polygons are in the raster's CRS (British National Grid for Digimap) and the
  detection centres are mapped through the raster transform; for a plain image or array they are
  pixel coordinates.

A vehicle is in a polygon when its box centre is (boundary counts as inside). With no polygons
there is one row, ``polygon_id="all"``. ``conf_mean`` is the mean confidence of the counted
detections (NaN when there are none); ``model`` is the weights file name.

Licences: Ultralytics is AGPL-3.0 (https://github.com/ultralytics/ultralytics). The COCO weights
are Ultralytics releases under the same licence; the DOTA OBB weights are trained on DOTA v1,
which is for academic use only (https://captain-whu.github.io/DOTA/). Both are fine for this
non-commercial student project; check again before any other use.

Weights download once from the Ultralytics GitHub releases into ``data/cache/models/``
(gitignored), and Ultralytics keeps its settings file there too, with its usage analytics
(``sync``) switched off. Each model loads once per process. ``ultralytics``, ``shapely`` and
``rasterio`` come from the ``vision`` extra (``uv sync --extra vision``) and are imported only
when needed, so this module imports without them.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MODELS_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "models"

COLUMNS = ["polygon_id", "cars", "large_vehicles", "conf_mean", "model"]
ALL = "all"

WEIGHTS = {"street": "yolo11n.pt", "aerial": "yolo11s-obb.pt"}
# Model class name -> output column. Classes not listed are ignored. Names are compared with "-"
# read as " ": the DOTA labels say "small-vehicle", the Ultralytics weights say "small vehicle".
CLASS_MAP = {
    "street": {"car": "cars", "truck": "large_vehicles", "bus": "large_vehicles"},
    "aerial": {"small vehicle": "cars", "large vehicle": "large_vehicles"},
}
# Inference size per mode: COCO models are trained at 640 px, the DOTA OBB models at 1024 px.
IMGSZ = {"street": 640, "aerial": 1024}

TILE = 1024
OVERLAP = 128
# Above this bicubic only blurs, and a value like 25 is more likely cm than a factor. A sweep of
# yolo11s-obb on DOTA at simulated 12-50 cm (notes/upsample-sweep.md) found F1 plateaus by k~=2-3
# and k>=6 is harmful (large-vehicle false positives multiply, fine imagery loses recall), so 4 is
# the ceiling, not 8.
MAX_UPSAMPLE = 4.0
GEOTIFF_SUFFIXES = {".tif", ".tiff"}

_MODELS: dict[str, Any] = {}


def load_model(weights: str, models_dir: str | Path = MODELS_DIR) -> Any:
    """The Ultralytics model for ``weights`` (a file name), loaded once and kept for the process."""
    if weights in _MODELS:
        return _MODELS[weights]
    models_dir = Path(models_dir)
    (models_dir / "Ultralytics").mkdir(parents=True, exist_ok=True)
    # Must be set before ultralytics is first imported: it reads its settings at import. It keeps
    # settings.json (and any font it fetches for plotting) in <dir>/Ultralytics.
    os.environ.setdefault("YOLO_CONFIG_DIR", str(models_dir))
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS

    if SETTINGS.get("sync"):
        SETTINGS.update({"sync": False})  # no usage analytics sent to Ultralytics
    model = YOLO(str(models_dir / weights))  # downloads to this path if missing
    _MODELS[weights] = model
    return model


def read_image(image: str | Path | np.ndarray) -> tuple[np.ndarray, Any | None]:
    """HxWx3 uint8 RGB array, plus the raster transform for a GeoTIFF (else None)."""
    if isinstance(image, np.ndarray):
        return _as_rgb(image), None
    path = Path(image)
    if path.suffix.lower() in GEOTIFF_SUFFIXES:
        try:
            import rasterio
        except ImportError:
            rasterio = None
        if rasterio is not None:
            with rasterio.open(path) as src:
                bands = src.read(indexes=list(range(1, min(src.count, 3) + 1)))
                return _as_rgb(np.moveaxis(bands, 0, -1)), src.transform
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB")), None


def _as_rgb(arr: np.ndarray) -> np.ndarray:
    """Grey, RGBA or 16-bit arrays -> HxWx3 uint8."""
    if arr.ndim == 2:
        arr = arr[..., None]
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    arr = arr[..., :3]
    if arr.dtype != np.uint8:
        top = float(arr.max()) or 1.0
        arr = (arr.astype(np.float32) * (255.0 / top)).clip(0, 255).astype(np.uint8)
    return arr


def _axis_starts(n: int, tile: int, overlap: int) -> list[int]:
    """Crop start offsets along one axis: fewest crops sharing >= ``overlap`` px, spread evenly."""
    if not 0 <= overlap < tile:
        raise ValueError(f"overlap {overlap} must be in [0, tile={tile})")
    if n <= tile:
        return [0]
    count = math.ceil((n - overlap) / (tile - overlap))
    return [round(i * (n - tile) / (count - 1)) for i in range(count)]


def _axis_cores(starts: list[int], tile: int) -> list[tuple[float, float]]:
    """Which part of the axis each crop owns: neighbours split their shared strip in half."""
    cuts = [(starts[i] + tile + starts[i + 1]) / 2 for i in range(len(starts) - 1)]
    return list(zip([-np.inf, *cuts], [*cuts, np.inf], strict=True))


def tile_windows(
    height: int, width: int, tile: int = TILE, overlap: int = OVERLAP
) -> list[tuple[int, int, int, int]]:
    """Crops ``(x0, y0, x1, y1)`` covering the image, neighbours sharing >= ``overlap`` px.

    The first and last crop in each direction sit on the image edges and the rest are spread
    evenly between them, so every crop is full size unless the image is smaller than ``tile``.
    """
    return [
        (x0, y0, min(x0 + tile, width), min(y0 + tile, height))
        for y0 in _axis_starts(height, tile, overlap)
        for x0 in _axis_starts(width, tile, overlap)
    ]


def _detections(result: Any) -> pd.DataFrame:
    """One Ultralytics result -> DataFrame (cx, cy, name, conf) in the crop's pixels."""
    boxes = result.obb if getattr(result, "obb", None) is not None else result.boxes
    if boxes is None or len(boxes.cls) == 0:
        return pd.DataFrame({"cx": [], "cy": [], "name": pd.Series([], dtype=object), "conf": []})
    xy = boxes.xywhr if hasattr(boxes, "xywhr") else boxes.xywh
    xy, cls, conf = (np.asarray(_to_numpy(v)) for v in (xy, boxes.cls, boxes.conf))
    return pd.DataFrame(
        {
            "cx": xy[:, 0].astype(float),
            "cy": xy[:, 1].astype(float),
            "name": [result.names[int(c)] for c in cls],
            "conf": conf.astype(float),
        }
    )


def _to_numpy(value: Any) -> Any:
    return value.cpu().numpy() if hasattr(value, "cpu") else value


def detect(
    rgb: np.ndarray,
    model: Any,
    mode: str,
    conf: float = 0.25,
    tile: int = TILE,
    overlap: int = OVERLAP,
    upsample: float = 1.0,
) -> pd.DataFrame:
    """All counted detections in the image: columns cx, cy (image pixels), kind, conf.

    ``kind`` is "cars" or "large_vehicles"; other classes are dropped. Aerial images are tiled
    (see module docstring); street stills go through in one pass.

    ``upsample`` > 1 is for imagery coarser than the model was trained on. DOTA is roughly
    10-30 cm a pixel, so 25 cm imagery is already in range and native scale (upsample 1) is
    usually best; a measured sweep (notes/upsample-sweep.md) found no gain past ~2-3 and real harm
    by 6-8, hence the ``MAX_UPSAMPLE`` ceiling. Reach for > 1 only on genuinely coarser (40 cm+)
    rasters. Each crop is cut from the original at ``tile / upsample`` px and enlarged (bicubic) to
    about ``tile`` px just before detection, so memory stays at one crop whatever the image size;
    run time still grows with ``upsample**2``.
    Centres are mapped back with each crop's exact size ratio, so cx, cy are in the original
    image's pixels (pixel-edge convention, as raster transforms use).
    """
    if not 0 < upsample <= MAX_UPSAMPLE:
        raise ValueError(f"upsample must be in (0, {MAX_UPSAMPLE}], not {upsample}")
    height, width = rgb.shape[:2]
    if mode == "aerial":
        src_tile = max(1, round(tile / upsample))
        src_overlap = min(round(overlap / upsample), src_tile - 1)
        xs, ys = (
            _axis_starts(width, src_tile, src_overlap),
            _axis_starts(height, src_tile, src_overlap),
        )
    else:
        xs, ys, src_tile = [0], [0], max(height, width)
    frames = []
    for y0, (cy0, cy1) in zip(ys, _axis_cores(ys, src_tile), strict=True):
        for x0, (cx0, cx1) in zip(xs, _axis_cores(xs, src_tile), strict=True):
            crop = rgb[y0 : y0 + src_tile, x0 : x0 + src_tile]
            big = crop if upsample == 1 else _resize(crop, upsample)
            bgr = np.ascontiguousarray(big[..., ::-1])  # Ultralytics takes BGR arrays
            (result,) = model.predict(bgr, conf=conf, imgsz=IMGSZ[mode], verbose=False)
            det = _detections(result)
            det["cx"] = det["cx"] * (crop.shape[1] / big.shape[1]) + x0
            det["cy"] = det["cy"] * (crop.shape[0] / big.shape[0]) + y0
            own = (det["cx"] >= cx0) & (det["cx"] < cx1) & (det["cy"] >= cy0) & (det["cy"] < cy1)
            frames.append(det[own])
    det = pd.concat(frames, ignore_index=True)
    det["kind"] = det["name"].astype(str).str.replace("-", " ").map(CLASS_MAP[mode])
    return det.dropna(subset=["kind"])[["cx", "cy", "kind", "conf"]].reset_index(drop=True)


def _resize(rgb: np.ndarray, factor: float) -> np.ndarray:
    """``rgb`` scaled by ``factor`` with bicubic resampling (at least 1 px each way)."""
    from PIL import Image

    height, width = rgb.shape[:2]
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return np.asarray(
        Image.fromarray(np.ascontiguousarray(rgb)).resize(size, Image.Resampling.BICUBIC)
    )


def _polygon_items(polygons: Any) -> list[tuple[str, Any]]:
    """dict id -> polygon, or a list (ids "0", "1", ...). A polygon is shapely or [(x, y), ...]."""
    from shapely.geometry import Polygon
    from shapely.geometry.base import BaseGeometry

    items = polygons.items() if isinstance(polygons, Mapping) else enumerate(polygons)
    out = []
    for key, poly in items:
        if not isinstance(poly, BaseGeometry):
            if not isinstance(poly, Sequence) or len(poly) < 3:
                raise ValueError(f"polygon {key!r}: need a shapely geometry or >= 3 (x, y) points")
            poly = Polygon(poly)
        out.append((str(key), poly))
    return out


def count_in_polygons(
    det: pd.DataFrame, polygons: Any = None, transform: Any | None = None, model_name: str = ""
) -> pd.DataFrame:
    """Per-polygon counts from ``detect`` output. See ``COLUMNS``.

    With a raster ``transform`` the pixel centres are first mapped to the raster's CRS, which is
    what the polygons are taken to be in.
    """
    xs, ys = det["cx"].to_numpy(), det["cy"].to_numpy()
    if transform is not None:
        a, b, c, d, e, f = tuple(transform)[:6]
        xs, ys = a * xs + b * ys + c, d * xs + e * ys + f
    if polygons is None:
        groups = [(ALL, np.ones(len(det), dtype=bool))]
    else:
        import shapely

        groups = [(pid, shapely.intersects_xy(p, xs, ys)) for pid, p in _polygon_items(polygons)]
    rows = []
    for pid, inside in groups:
        sel = det[inside]
        rows.append(
            {
                "polygon_id": pid,
                "cars": int((sel["kind"] == "cars").sum()),
                "large_vehicles": int((sel["kind"] == "large_vehicles").sum()),
                "conf_mean": float(sel["conf"].mean()) if len(sel) else float("nan"),
                "model": model_name,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def count_vehicles(
    image: str | Path | np.ndarray,
    mode: str = "street",
    polygons: Any = None,
    conf: float = 0.25,
    *,
    model: Any = None,
    weights: str | None = None,
    tile: int = TILE,
    overlap: int = OVERLAP,
    upsample: float = 1.0,
) -> pd.DataFrame:
    """Cars and large vehicles in ``image``, one row per polygon (see module docstring).

    ``image`` is a path (JPEG/PNG, or a GeoTIFF for aerial) or an HxWx3 RGB array. ``polygons``
    is None (one "all" row), a dict id -> polygon, or a list of polygons. ``model`` overrides the
    cached Ultralytics model (tests pass a stub); ``weights`` picks another weights file.
    ``upsample`` enlarges the image before detection (see ``detect``).
    """
    if mode not in WEIGHTS:
        raise ValueError(f"mode must be one of {sorted(WEIGHTS)}, not {mode!r}")
    weights = weights or WEIGHTS[mode]
    model = model if model is not None else load_model(weights)
    rgb, transform = read_image(image)
    det = detect(rgb, model, mode, conf=conf, tile=tile, overlap=overlap, upsample=upsample)
    return count_in_polygons(det, polygons, transform, model_name=weights)
