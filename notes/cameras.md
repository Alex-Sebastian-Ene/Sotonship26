# National Highways camera counts: source, licence, privacy

Checked Sat 17 Oct 2026 by Keanu's Claude. Code: `src/sotonship26/data/cameras.py` (sampler),
`src/sotonship26/vision/detect.py` (vehicle counter), camera list in
`src/sotonship26/data/cameras.csv`.

## What it is

Vehicle counts (cars and large vehicles) from the public National Highways traffic camera stills
on the M27 (J3 to J5) and the M3 (J13 to J14, including the M3/M27 link), one row per camera per
pass. They are an observed signal for the approaches to the port, not a flow count: one still is a
snapshot of whatever the camera points at.

## Source

- Camera page: `https://public.highwaystrafficcameras.co.uk/cctvpublicaccess/html/{id}.html`
  (official name such as "M27 18/8A J5", and "The carriageway closest to the camera is
  Eastbound").
- Still: `https://public.highwaystrafficcameras.co.uk/cctvpublicaccess/images/{id}.jpg`, a 720x576
  JPEG. The page script says images refresh every 30 seconds. Measured on
  17 Oct, 09:08 to 09:12 UTC (3 cameras polled every 10 s for 4 min, hashes held in memory only),
  the bytes changed every 20 s (median; range 10 to 31 s). Two full passes 2 min apart got a
  fresh still from every working camera. A 300 s interval therefore samples a new frame every
  time.
- No `Last-Modified`, `ETag` or EXIF on the stills, so `image_time` is empty and `fetched_at_utc`
  is the timestamp to use.
- An unknown or switched-off camera returns a 352x288 "unavailable" card. On 17 Oct, 19123 and
  12173 served that card, and 19111, 19131 and 19150 served a flat grey 720x576 frame. The sampler
  skips both rather than recording zero.
- The site root says "Access to the specified resource is forbidden"; that is a static notice, not
  a login or bot challenge. The camera pages and stills load without either. If the server ever
  answers every camera with something other than an image, the sampler stops (exit code 3).
- The separate `highwaystrafficcameras.co.uk/HETCOperational` site is for staff. Not used.
- No National Highways cameras on the M271, A33 or A35 (Southampton City Council roads). Lat/lon
  are not published on the camera pages, so those columns are blank.

## Licence and credit

National Highways standard terms for traffic images
(https://nationalhighways.co.uk/roads-and-travel/live-travel-updates/traffic-cameracctv-services/standard-terms-and-conditions/):

> The traffic images are Crown Copyright protected and may be reproduced free of charge in any
> format or medium as long as it is for non-commercial research or private study, subject to the
> material being reproduced accurately and not used in a misleading context.

Licensees must credit the images as from National Highways traffic management cameras and
acknowledge Crown copyright. Credit line to use wherever counts appear:

> Vehicle counts derived from National Highways traffic management camera images, © Crown
> copyright.

We do not republish the images, only counts derived from them. Under the terms, users are Data
Controllers for their own use. That is why the privacy rule below exists.

The counter is Ultralytics YOLO (AGPL-3.0). `yolo11n.pt` is trained on COCO. The aerial
`yolo11s-obb.pt` is trained on DOTA v1, which is for academic use only. Both are fine for this
non-commercial student project.

## Privacy rule (non-negotiable)

- Images are never written to disk. Each still is fetched into memory, decoded, counted and
  dropped.
- No frames, crops, plates, plate hashes or anything identifying are stored or logged.
- Only the counts in `COLUMNS` are written: `camera_id, fetched_at_utc, image_time, cars,
  large_vehicles, conf_mean, model, width, height`.
- To skip a still that hasn't changed, the sampler keeps one SHA-256 of the whole JPEG per camera,
  in memory only. It is never written and is gone when the process exits.
- The offline test `test_main_once_writes_only_the_counts_csv` checks that a run leaves nothing
  but the counts CSV.

## Cameras

Directions marked "suffix" are inferred: the page left the direction blank, and on this stretch
the marker suffix A is Eastbound and B is Westbound. The other directions come from the camera
pages. Junction labels not in the official name come from trafficcameras.uk.

| id | name | junction | direction |
|---|---|---|---|
| 19111 | M27 11/1B | J3 | Westbound |
| 19123 | M27 12/3A | J3-J4 | Eastbound |
| 19131 | M27 13/1A | J3-J4 | Eastbound |
| 19148 | M27 14/8A | J3-J4 | Eastbound |
| 19150 | M27 15/0A | J3-J4 | Eastbound |
| 19156 | M27 15/6A J4 | J4 | Eastbound |
| 19169 | M27 16/9A J4 | J4 | Eastbound |
| 19171 | M27 17/1A J4 | J4 | Eastbound |
| 19174 | M27 17/4B J4 | J4 | Westbound (suffix) |
| 19178 | M27 17/8B J4 | J4 | Westbound (suffix) |
| 19180 | M27 18/0B J4-5 | J4-J5 | Westbound |
| 19183 | M27 18/3B J4-5 | J4-J5 | Westbound (suffix) |
| 19188 | M27 18/8A J5 | J5 | Eastbound |
| 19190 | M27 19/0A J5 | J5 | Eastbound |
| 19192 | M27 19/2B J5 | J5 | Westbound (suffix) |
| 12156 | M3 115/6B J13 | J13 | Northbound |
| 12173 | M3 117/3L J13-14 | J13-J14 | Northbound |
| 12176 | M3 117/6K J4 | J14 (M3-M27 link) | Southbound |
| 12178 | M3 117/8A J14 | J14 | Southbound |
| 12179 | M3 117/8K J4 | J14 (M3-M27 link) | Southbound |
| 12182 | M3 118/2K J4 | J14 (M3-M27 link) | Southbound |

Two cameras were left out:

- 12126 (M3 J12): outside J13 to J14.
- 40460 (A36 Deptford): in Wiltshire.

## Caveats

- Operators pan and zoom these cameras, so counts from one camera are not comparable across
  different views.
- The street model is `yolo11n` at 640 px. It misses distant, small vehicles, so treat the counts
  as an index of how busy the road is, not a census.
- `motorcycle` is not counted. Vans come out as either car or truck.

## How to run

```sh
uv sync --extra vision          # once; also downloads weights to data/cache/models/ on first use
uv run python -m sotonship26.data.cameras --once
uv run python -m sotonship26.data.cameras --every 300 --until 2026-10-18T13:00
```

- Output is appended to `data/raw/cameras/counts_YYYY-MM-DD.csv`, using the UTC date (the folder
  is gitignored).
- `--ids 19180,19188` restricts the run to those cameras.
- `--pause 1` sets the gap in seconds between cameras.
- Each pass makes one request per camera. Each request has a 20 s timeout and up to 3 tries with
  2 s, then 4 s, backoff. A failed camera is logged and skipped.
