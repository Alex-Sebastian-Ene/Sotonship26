"""Vehicle counts from National Highways traffic camera stills on the M27 and M3 near Southampton.

Source: the public National Highways camera pages. Each camera has a page (``PAGE_URL``: official
name and carriageway direction) and a 720x576 JPEG still (``STILL_URL``). The page script says it
refreshes every 30 s; on 17 Oct the bytes changed about every 20 s. The stills carry no
``Last-Modified`` header and no EXIF, so ``image_time`` is usually empty and ``fetched_at_utc`` is
the time to use. A camera that is off, or an unknown id, returns a 352x288 "unavailable" card, and
some serve a flat grey 720x576 frame; both are skipped, not counted as zero. The cameras sampled
are in ``cameras.csv`` (``CAMERAS``), with where each fact came from and when it was checked.

Licence: National Highways standard terms for traffic images: "The traffic images are Crown
Copyright protected and may be reproduced free of charge in any format or medium as long as it is
for non-commercial research or private study, subject to the material being reproduced accurately
and not used in a misleading context." Show ``CREDIT`` wherever the counts appear. Operators pan
and zoom these cameras, so a count is for whatever view was up at the time, not a fixed
screenline.

PRIVACY (non-negotiable): images are never written to disk. Each still is fetched into memory,
decoded, passed to the vehicle counter, and dropped. No frames, crops, plates, plate hashes or
anything else identifying are stored or logged; only the counts in ``COLUMNS`` leave this module.
To skip a still that has not changed since the last pass we keep, in memory only, one SHA-256 of
the whole JPEG per camera (or its Last-Modified time); it is never written out and dies with the
process. The counts go to ``data/raw/cameras/counts_YYYY-MM-DD.csv`` (UTC date, gitignored).

Run: ``python -m sotonship26.data.cameras --every 300 --until 2026-10-18T13:00`` (``--until`` is
Europe/London time if no offset is given), or ``--once`` for a single pass. Needs the ``vision``
extra. One request per camera per pass, cameras spaced ``--pause`` seconds apart.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sotonship26.vision.detect import count_vehicles

PAGE_URL = "https://public.highwaystrafficcameras.co.uk/cctvpublicaccess/html/{id}.html"
STILL_URL = "https://public.highwaystrafficcameras.co.uk/cctvpublicaccess/images/{id}.jpg"
USER_AGENT = (
    "sotonship26/0.1 (SotonShip 2026 hackathon; cruise-day traffic forecast; "
    "non-commercial research; vehicle counts only, no images kept)"
)
TZ = "Europe/London"
CREDIT = (
    "Vehicle counts derived from National Highways traffic management camera images, "
    "\u00a9 Crown copyright"
)

CAMERAS_CSV = Path(__file__).resolve().parent / "cameras.csv"
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "cameras"

TIMEOUT = 20.0  # seconds per request
RETRIES = 3  # attempts per still, per pass
BACKOFF = 2.0  # seconds before the first retry, doubling after
MAX_BYTES = 5_000_000  # a still is ~50 kB; anything far bigger is not a still
PLACEHOLDER_SIZE = (352, 288)  # the "camera unavailable" card (real stills are 720x576)
# Some cameras serve a flat grey 720x576 frame instead (seen 17 Oct on 19111, 19131, 19150, ~9 kB):
# a still is "blank" when this share of its pixels sits within BLANK_TOLERANCE grey levels of the
# median. Real road views scored 0.16-0.76 on 17 Oct, the grey frames 0.99.
BLANK_SHARE = 0.95
BLANK_TOLERANCE = 12

COLUMNS = [
    "camera_id",
    "fetched_at_utc",
    "image_time",
    "cars",
    "large_vehicles",
    "conf_mean",
    "model",
    "width",
    "height",
]

log = logging.getLogger(__name__)


class NotAnImageError(RuntimeError):
    """The server answered with something other than an image (an error or challenge page)."""


@dataclass(frozen=True)
class Still:
    """One fetched still, in memory only. ``data`` is never written anywhere."""

    data: bytes
    fetched_at: pd.Timestamp
    last_modified: pd.Timestamp | None = None


def load_cameras(path: Path = CAMERAS_CSV) -> pd.DataFrame:
    """The camera table: id, official name, road, junction, direction, URLs, source, checked."""
    return pd.read_csv(path, dtype={"camera_id": str})


CAMERAS = load_cameras()


def fetch_still(
    url: str,
    timeout: float = TIMEOUT,
    retries: int = RETRIES,
    backoff: float = BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
) -> Still:
    """GET one still into memory, retrying timeouts, 429 and 5xx with exponential backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                kind = resp.headers.get("Content-Type", "")
                if not kind.startswith("image/"):
                    raise NotAnImageError(f"{url}: got {kind or 'no content type'}, not an image")
                data = resp.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise NotAnImageError(f"{url}: more than {MAX_BYTES} bytes, not a still")
                return Still(data, pd.Timestamp.now(tz="UTC"), _http_time(resp.headers))
        except urllib.error.HTTPError as err:
            retryable = err.code == 429 or err.code >= 500
            if not retryable or attempt == retries - 1:
                raise
            log.info("%s: HTTP %s, retrying", url, err.code)
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == retries - 1:
                raise
            log.info("%s: %s, retrying", url, err)
        sleep(backoff * 2**attempt)
    raise RuntimeError("unreachable")


def _http_time(headers: Any) -> pd.Timestamp | None:
    value = headers.get("Last-Modified")
    if not value:
        return None
    try:
        return pd.Timestamp(parsedate_to_datetime(value)).tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def _exif_time(img: Any) -> pd.Timestamp | None:
    """EXIF DateTime (tag 306), read as Europe/London. National Highways stills have none."""
    value = img.getexif().get(306)
    if not value:
        return None
    try:
        stamp = pd.Timestamp(pd.to_datetime(value, format="%Y:%m:%d %H:%M:%S"))
        return stamp.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def _decode(data: bytes) -> tuple[np.ndarray, pd.Timestamp | None]:
    """JPEG bytes -> HxWx3 RGB array (in memory) and the EXIF time if there is one."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        when = _exif_time(img)
        return np.asarray(img.convert("RGB")), when


def is_blank(rgb: np.ndarray) -> bool:
    """A flat frame (grey card, lens covered, thick fog): nothing to count."""
    grey = rgb.mean(axis=2)
    return float((np.abs(grey - np.median(grey)) < BLANK_TOLERANCE).mean()) >= BLANK_SHARE


def sample_once(
    cameras: pd.DataFrame = CAMERAS,
    detector: Callable[..., pd.DataFrame] = count_vehicles,
    fetch: Callable[[str], Still] = fetch_still,
    seen: dict[str, str] | None = None,
    pause: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Fetch every camera's still once, count vehicles, return one row per new still.

    Skips cameras whose still has not changed since the last pass (``seen``, kept by the caller
    in memory: camera_id -> Last-Modified or SHA-256 of the JPEG), "unavailable" cards, blank
    frames, and any
    camera whose fetch or count fails (logged; the rest carry on). If every camera answers with
    something that is not an image (an error or bot-challenge page), raises NotAnImageError so
    the caller stops instead of retrying into it.
    """
    seen = {} if seen is None else seen
    rows = []
    blocked = 0
    for i, cam in enumerate(cameras.itertuples(index=False)):
        if i and pause:
            sleep(pause)
        cam_id = str(cam.camera_id)
        try:
            row = _sample_camera(cam_id, cam.still_url, detector, fetch, seen)
        except Exception as err:  # one camera failing must not stop the pass
            log.warning("camera %s: %s: %s", cam_id, type(err).__name__, err)
            blocked += isinstance(err, NotAnImageError)
            continue
        if row is not None:
            rows.append(row)
    if len(cameras) and blocked == len(cameras):
        raise NotAnImageError("every camera answered with a non-image (challenge page?); stopping")
    return pd.DataFrame(rows, columns=COLUMNS)


def _sample_camera(
    cam_id: str,
    url: str,
    detector: Callable[..., pd.DataFrame],
    fetch: Callable[[str], Still],
    seen: dict[str, str],
) -> dict[str, Any] | None:
    still = fetch(url)
    fetched_at, last_modified = still.fetched_at, still.last_modified
    if last_modified is not None:
        fingerprint = f"last-modified {last_modified.isoformat()}"
    else:
        fingerprint = f"sha256 {hashlib.sha256(still.data).hexdigest()}"
    if seen.get(cam_id) == fingerprint:
        log.info("camera %s: unchanged since last pass", cam_id)
        return None
    rgb, exif_time = _decode(still.data)
    del still  # drop the JPEG bytes; only counts go further
    seen[cam_id] = fingerprint
    height, width = rgb.shape[:2]
    if (width, height) == PLACEHOLDER_SIZE:
        log.info("camera %s: unavailable card, skipped", cam_id)
        return None
    if is_blank(rgb):
        log.info("camera %s: blank frame, skipped", cam_id)
        return None
    counts = detector(rgb, mode="street").iloc[0]
    del rgb
    image_time = last_modified if last_modified is not None else exif_time
    return {
        "camera_id": cam_id,
        "fetched_at_utc": fetched_at,
        "image_time": image_time if image_time is not None else pd.NaT,
        "cars": int(counts["cars"]),
        "large_vehicles": int(counts["large_vehicles"]),
        "conf_mean": float(counts["conf_mean"]),
        "model": str(counts["model"]),
        "width": width,
        "height": height,
    }


def append_counts(counts: pd.DataFrame, out_dir: Path = RAW_DIR) -> list[Path]:
    """Append rows to ``out_dir/counts_YYYY-MM-DD.csv`` (UTC date of the fetch); header once."""
    if counts.empty:
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = pd.to_datetime(counts["fetched_at_utc"], utc=True).dt.strftime("%Y-%m-%d")
    paths = []
    for day, rows in counts.groupby(days, sort=True):
        path = out_dir / f"counts_{day}.csv"
        rows[COLUMNS].to_csv(path, mode="a", header=not path.exists(), index=False)
        paths.append(path)
    return paths


def parse_until(value: str) -> pd.Timestamp:
    """ISO time; Europe/London if it has no offset. Returned in UTC."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(TZ)
    return stamp.tz_convert("UTC")


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m sotonship26.data.cameras",
        description="Count vehicles on National Highways camera stills (counts only, no images).",
    )
    parser.add_argument("--every", type=float, default=300.0, help="seconds between passes")
    parser.add_argument("--until", type=parse_until, help="stop after this time (ISO)")
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--ids", help="comma-separated camera ids (default: all in cameras.csv)")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between cameras")
    parser.add_argument("--out-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(None if argv is None else list(argv))
    if args.every <= 0 or args.pause < 0:
        parser.error("--every must be > 0 and --pause >= 0")
    return args


def main(
    argv: Iterable[str] | None = None,
    detector: Callable[..., pd.DataFrame] = count_vehicles,
    fetch: Callable[[str], Still] = fetch_still,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
) -> int:
    """CLI loop: sample every ``--every`` seconds until ``--until`` (or once). Returns exit code."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cameras = CAMERAS
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        cameras = cameras[cameras["camera_id"].isin(wanted)]
        if cameras.empty:
            log.error("none of --ids %s are in %s", args.ids, CAMERAS_CSV)
            return 2
    seen: dict[str, str] = {}
    while True:
        started = clock()
        try:
            counts = sample_once(cameras, detector, fetch, seen, pause=args.pause, sleep=sleep)
        except NotAnImageError as err:
            log.error("%s", err)
            return 3
        paths = append_counts(counts, args.out_dir)
        log.info(
            "pass at %s: %d/%d cameras counted, %d cars, %d large vehicles -> %s",
            started.isoformat(timespec="seconds"),
            len(counts),
            len(cameras),
            counts["cars"].sum(),
            counts["large_vehicles"].sum(),
            ", ".join(str(p) for p in paths) or "nothing new",
        )
        next_pass = started + pd.Timedelta(seconds=args.every)
        if args.once or (args.until is not None and next_pass > args.until):
            return 0
        sleep(max(0.0, (next_pass - clock()).total_seconds()))


if __name__ == "__main__":
    sys.exit(main())
