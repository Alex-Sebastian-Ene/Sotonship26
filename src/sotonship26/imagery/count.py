"""Cars in each cruise car park on each imagery date, for the park-and-cruise share fit.

Detection is the team's aerial counter (``sotonship26.vision.detect``, YOLO OBB trained on DOTA).
Each car park is clipped on its own (its outline's bounding box plus ``MARGIN_M``), the counter
enlarges it before detecting (``upsample_for``: x4 at 25 cm, x2 at 12.5 cm) and maps detection
centres back to the clip's pixels, and they are counted inside the car park outline. Why enlarge:
at 25 cm (Digimap) a car is about 18 x 7 px, smaller than most DOTA training cars; see
``scripts/detector_sample_check.py`` for the trial on a CC-BY image.

Only counts leave this module. Images stay in gitignored ``data/raw/`` (Digimap's licence bars
showing them); counts are credited to the imagery source. Multi-storey car parks are counted
from their top deck only, so keep the same car parks in every date's count.

    uv run --extra vision python -m sotonship26.imagery.count  # IMAGERY_* as in providers.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from sotonship26.imagery.carparks import CarPark, load_carparks
from sotonship26.imagery.occupancy import dock_of
from sotonship26.imagery.providers import Scene, provider_from_env

ROOT = Path(__file__).resolve().parents[3]
MARGIN_M = 15.0
COLUMNS = [
    "when",
    "scene",
    "osm_id",
    "name",
    "kind",
    "terminal",
    "dock",
    "capacity",
    "multi_storey",
    "cars",
    "large_vehicles",
    "conf_mean",
    "model",
    "upsample",
    "licence",
]


def park_aoi(park: CarPark, margin_m: float = MARGIN_M) -> dict:
    """Lon/lat rectangle round the car park outline, ``margin_m`` metres wider on each side."""
    from pyproj import Transformer

    xs, ys = zip(*park.polygon_bng, strict=True)
    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    x0, y0, x1, y1 = min(xs) - margin_m, min(ys) - margin_m, max(xs) + margin_m, max(ys) + margin_m
    ring = [to_ll.transform(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return {"type": "Polygon", "coordinates": [ring]}


def outline_in(park: CarPark, crs) -> object:
    """The car park outline as a shapely polygon in the raster's CRS."""
    from pyproj import CRS, Transformer
    from shapely.geometry import Polygon

    if CRS.from_user_input(crs).to_epsg() == 27700:
        return Polygon(park.polygon_bng)
    tr = Transformer.from_crs("EPSG:27700", crs, always_xy=True)
    return Polygon([tr.transform(x, y) for x, y in park.polygon_bng])


def upsample_for(gsd_m: float | None) -> float:
    """Enlargement before detection for a pixel size: x4 at 25 cm, x2 at 12.5 cm, else none."""
    if gsd_m is None or gsd_m < 0.1:
        return 1.0
    return 4.0 if gsd_m >= 0.2 else 2.0


def count_park(
    tif: Path,
    park: CarPark,
    model,
    upsample: float | None = None,
    conf: float = 0.25,
    model_name: str = "",
) -> dict:
    """Detect on one car park clip and count inside its outline (upsample None: by pixel size)."""
    import rasterio

    from sotonship26.vision import detect

    rgb, transform = detect.read_image(tif)
    with rasterio.open(tif) as src:
        crs, gsd = src.crs, abs(src.transform.a)
    up = upsample if upsample is not None else upsample_for(gsd)
    det = detect.detect(rgb, model, "aerial", conf=conf, upsample=up)
    row = detect.count_in_polygons(
        det, {park.osm_id: outline_in(park, crs)}, transform, model_name=model_name
    )
    return row.iloc[0].to_dict() | {"upsample": up}


def count_scene(
    provider,
    scene: Scene,
    parks: list[CarPark],
    work_dir: Path,
    *,
    model=None,
    weights: str | None = None,
    upsample: float | None = None,
    conf: float = 0.25,
    target_gsd: float | None = None,
) -> pd.DataFrame:
    """One row per car park for one imagery date (see ``COLUMNS``)."""
    from sotonship26.vision import detect

    weights = weights or detect.WEIGHTS["aerial"]
    model = model if model is not None else detect.load_model(weights)
    rows = []
    for park in parks:
        tif = provider.fetch(
            scene,
            park_aoi(park),
            work_dir / scene.id / f"{park.osm_id.replace('/', '_')}.tif",
            target_gsd,
        )
        c = count_park(tif, park, model, upsample, conf, weights)
        rows.append(
            {
                "when": scene.when,
                "scene": scene.id,
                "osm_id": park.osm_id,
                "name": park.name,
                "kind": park.kind,
                "terminal": park.terminal,
                "dock": _dock(park.terminal),
                "capacity": park.capacity,
                "multi_storey": park.multi_storey,
                "cars": c["cars"],
                "large_vehicles": c["large_vehicles"],
                "conf_mean": c["conf_mean"],
                "model": weights,
                "upsample": c["upsample"],
                "licence": scene.licence,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def _dock(terminal: str) -> str:
    try:
        return dock_of(terminal)
    except KeyError:
        return "unknown"


def dock_counts(rows: pd.DataFrame) -> pd.DataFrame:
    """Cars in the cruise car parks per dock and date: the input to ``occupancy.fit_share``."""
    cruise = rows[rows["kind"] == "cruise"]
    out = cruise.groupby(["when", "dock"], as_index=False).agg(
        cars=("cars", "sum"), capacity=("capacity", "sum"), parks=("osm_id", "nunique")
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="0000")
    ap.add_argument("--end", default="9999")
    ap.add_argument("--kinds", default="cruise,control", help="car park kinds to count")
    ap.add_argument("--upsample", type=float, default=None, help="default: by pixel size")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "cache" / "carparks" / "counts.csv")
    a = ap.parse_args()
    provider = provider_from_env()
    parks = [
        p
        for p in load_carparks(ROOT / "data" / "cache" / "carparks")
        if p.kind in a.kinds.split(",")
    ]
    scenes = provider.search(None, a.start, a.end)
    if not scenes:
        raise SystemExit("no imagery found; see providers.py for where to put Digimap tiles")
    frames = []
    for sc in scenes:
        print(f"{sc.when:%Y-%m-%d %H:%M}: {sc.extra.get('tiles', 1)} tiles, {len(parks)} car parks")
        frames.append(
            count_scene(
                provider, sc, parks, ROOT / "data" / "raw" / "imagery_clips", upsample=a.upsample
            )
        )
    rows = pd.concat(frames, ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(a.out, index=False)
    print(dock_counts(rows).to_string(index=False))
    print(f"wrote {a.out} (counts only; credit: {scenes[0].licence})")


if __name__ == "__main__":
    main()
