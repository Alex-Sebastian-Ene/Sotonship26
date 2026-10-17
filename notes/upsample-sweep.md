# Upsample factor sweep (SOT-23 follow-up)

Measured Sat 17 Oct 2026 in Keanu's session, to set `MAX_UPSAMPLE` in
`src/sotonship26/vision/detect.py` from evidence instead of a guess.

## Question

`detect(upsample=k)` cuts each aerial crop at `tile/k` source px and enlarges it bicubic to ~`tile`
px before YOLO. The cap was `MAX_UPSAMPLE = 8.0`, chosen by eye. Does a large `k` actually recover
small vehicles on coarse imagery, or just invent detections?

## Method

- Model: `yolo11s-obb` (DOTA), the aerial detector, CPU.
- Data: 4 DOTA_devkit `example/` images with `labelTxt` ground truth (P1088, P1888, P2598, P2709),
  all GoogleEarth, native GSD 0.11-0.28 m read from each file's `gsd:` meta line.
- Degraded with PIL BOX to target GSDs (~12, 25, 37, 50 cm), then ran `detect(mode="aerial",
  upsample=k)` for k in {1, 1.5, 2, 3, 4, 6, 8}.
- Scored with class-aware greedy centre-matching (tolerance 1.5x GT half-size, mapped to native px)
  giving TP/FP/FN, then F1.
- Artifacts: `scratchpad/upsample_exp/` (`run_exp.py`, `summarise.py`, `results.csv`, `run.log`).

## Result (F1, summed over images in each GSD band)

| GSD | k=1 | 1.5 | 2 | 3 | 4 | 6 | 8 |
|-----|-----|-----|---|---|---|---|---|
| ~12 cm, cars | 0.63 | 0.59 | 0.60 | 0.61 | **0.66** | 0.53 | 0.00 |
| ~25 cm, cars | **0.71** | 0.66 | 0.68 | 0.68 | 0.66 | 0.68 | 0.70 |
| ~25 cm, all vehicles | **0.85** | 0.81 | 0.84 | 0.83 | 0.81 | 0.80 | 0.70 |
| ~37 cm, cars | **0.78** | 0.78 | 0.76 | 0.65 | 0.63 | 0.73 | 0.73 |
| ~50 cm, cars | **0.69** | 0.61 | 0.51 | 0.69 | 0.47 | 0.42 | 0.48 |

- At 25 cm (our Digimap target), native scale is already best; recall is ~1.0 at k=1, so
  upsampling adds false positives, not vehicles. The old docstring claim "25 cm gains from 2-4x" is
  **not** supported.
- F1 plateaus by k~=2-3 in every band. Nothing beats its own k=1-2 score at k=6 or 8.
- k=8 is clearly harmful: large-vehicle FPs multiply (one image 50 -> 82), and on already-fine
  12 cm imagery recall collapses (0.40 at k=6, 0.00 at k=8, vehicles blown past the training scale).
- Run time grows ~k^2 (0.4 s/MP at k=1 to ~22 s/MP at k=8).

## Decision

`MAX_UPSAMPLE = 8.0 -> 4.0`. 4 keeps the team's "upsample x4 at 25 cm" (SOT-23) usable as a safety
margin for genuinely blurry real imagery, while cutting off the harmful 6-8 range. Default stays 1
(native). The edge-of-crop concern (bicubic distortion eating a car near a crop seam) dissolves at
k<=4: `src_overlap = round(128/4) = 32` src px, a 16 px core margin, far larger than a ~9 px car
plus ~2 px bicubic spread, so no separate edge fix is needed, the cap resolves it.

## Caveats

- Only 3 of the 4 images contain cars; n is tiny, so treat the table as directional.
- PIL BOX downsampling is cleaner than real coarse optics (no sensor/atmospheric blur), so real
  25 cm imagery may gain slightly more from a small upsample than this shows. This is the main
  threat to "native is enough"; 4 (not 2) is the cap for that reason.
- Matching is centre-distance, not IoU; only the car-level TP/FP/FN are strictly class-correct.
