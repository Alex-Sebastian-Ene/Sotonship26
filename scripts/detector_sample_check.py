"""Check the pre-trained car detector on an openly licensed aerial image (not Southampton).

Clips the AOI from a cloud-optimised GeoTIFF (reads only that window), resamples it to each pixel
size in GSDS (default 25 cm, the Digimap resolution, and 12.5 cm), runs YOLO11n-OBB (trained on
DOTA) on 640 px tiles enlarged UP times, and writes an overlay PNG per size to
data/raw/oam_sample/ (gitignored).

    GSDS=0.25 UP=4 uv run --no-project --python 3.12 --with ultralytics --with torch \\
        --with rasterio --with pyproj --with shapely --with pillow \\
        python scripts/detector_sample_check.py URL W,S,E,N NAME

Trial on 17 Oct 2026 with OpenAerialMap "Estadio Santa Marta" (HOT, CC-BY 4.0, flown 28 Aug 2026),
one patch of about 17 cars counted by eye: at 12.5 cm it found about 15; at 25 cm it found 4
(tiles enlarged x2) or 10 (x4), with no false alarms in the patch.
"""

import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

SAT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SAT / "src"))
from sotonship26.imagery.providers import clip_to_geotiff  # noqa: E402

URL = sys.argv[1]
w, s, e, n = (float(x) for x in sys.argv[2].split(","))
NAME = sys.argv[3]
GSDS = [float(x) for x in os.environ.get("GSDS", "0.25,0.125").split(",")]
UP = int(os.environ.get("UP", "2"))
CONF = float(os.environ.get("CONF", "0.25"))
MODEL = os.environ.get("MODEL", "yolo11n-obb.pt")
WEIGHTS = SAT / "data" / "cache" / "models" / MODEL
# optional box (x0,y0,x1,y1 in 25 cm pixels) whose cars were counted by eye, scored separately
_P = os.environ.get("PATCH25")
PATCH25 = [float(x) for x in _P.split(",")] if _P else None
OUT = SAT / "data" / "raw" / "oam_sample"
OUT.mkdir(parents=True, exist_ok=True)
aoi = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

import rasterio  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from ultralytics import YOLO  # noqa: E402

model = YOLO(str(WEIGHTS) if WEIGHTS.exists() else MODEL)
T, OV = 640, 64  # tile and overlap, pixels; a car is about 18 x 7 px at 25 cm

for gsd in GSDS:
    tif = clip_to_geotiff(URL, aoi, OUT / f"{NAME}_{int(gsd * 1000)}mm.tif", target_gsd=gsd)
    with rasterio.open(tif) as src:
        rgb = np.moveaxis(src.read([1, 2, 3]), 0, -1)
        print(f"{gsd} m: {src.width} x {src.height} px, {src.crs}")
    polys, confs, cls = [], [], []
    for y0 in range(0, max(rgb.shape[0] - OV, 1), T - OV):
        for x0 in range(0, max(rgb.shape[1] - OV, 1), T - OV):
            tile = rgb[y0 : y0 + T, x0 : x0 + T]
            if tile.size == 0:
                continue
            big = np.array(
                Image.fromarray(tile).resize(
                    (tile.shape[1] * UP, tile.shape[0] * UP), Image.BICUBIC
                )
            )
            r = model.predict(big, imgsz=T * UP, conf=CONF, verbose=False)[0]
            if r.obb is None or len(r.obb) == 0:
                continue
            for p, c, k in zip(
                r.obb.xyxyxyxy.cpu().numpy(),
                r.obb.conf.cpu().numpy(),
                r.obb.cls.cpu().numpy(),
                strict=True,
            ):
                cx, cy = p[:, 0].mean() / UP + x0, p[:, 1].mean() / UP + y0
                # count a detection once: each tile owns its overlap only up to the midline
                if (x0 + T < rgb.shape[1] and cx >= x0 + T - OV / 2) or (
                    y0 + T < rgb.shape[0] and cy >= y0 + T - OV / 2
                ):
                    continue
                if (x0 > 0 and cx < x0 + OV / 2) or (y0 > 0 and cy < y0 + OV / 2):
                    continue
                polys.append(p / UP + [x0, y0])
                confs.append(float(c))
                cls.append(model.names[int(k)])
    cars = [c for c, k in zip(confs, cls, strict=True) if k == "small vehicle"]
    if PATCH25:
        x0p, y0p, x1p, y1p = (v * 0.25 / gsd for v in PATCH25)
        in_patch = sum(
            k == "small vehicle" and x0p <= p[:, 0].mean() < x1p and y0p <= p[:, 1].mean() < y1p
            for p, k in zip(polys, cls, strict=True)
        )
        print(f"  small vehicles in the hand-counted patch: {in_patch}")
    print(
        f"  detections: {dict(Counter(cls))}; small vehicles {len(cars)}, mean confidence "
        f"{np.mean(cars) if cars else 0:.2f}"
    )
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    for p, k in zip(polys, cls, strict=True):
        draw.polygon(
            [tuple(q) for q in p],
            outline=(255, 0, 0) if k == "small vehicle" else (0, 160, 255),
            width=2,
        )
    prev = OUT / f"{NAME}_{int(gsd * 1000)}mm_up{UP}_{Path(MODEL).stem}_detections.png"
    img.save(prev)
    print("  overlay:", prev)
