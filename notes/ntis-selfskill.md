# NTIS predicted vs fused actual - diagnostics (NOT a validated self-skill yet)

NTIS's own live forecast vs its fused actual on the Southampton dock-approach
links (M27 / M271 / M3), from our forward log of the owner-permitted mobilityflow
feed. Source: NTIS via mobilityflow (OGL / National Highways).

> Units/definition UNCONFIRMED - do not quote any error below as NTIS's skill.
> Fused actual is km/h (confirmed). predicted_speed carries no unit; read as **mph
> and converted x1.609 to km/h** it still runs far below the actual (predicted is
> roughly half the fused value, below it on almost every pair). That residual is
> much larger than the known space-mean vs loop-spot-speed gap, so either the unit
> is still wrong, predicted_speed is a different quantity, or the link<->bucket
> match is off. DATEX II mandates km/h; confirm against raw DATEX XML / the feed
> owner first. Treat as provisional - a mechanism, not a validated number yet.

- capture window (Europe/London wall-clock buckets): 2026-10-17T10:09:17+00:00 - 2026-10-17T11:17:40+00:00
- scored pairs: 376  (links 20, distinct targets 376)
- mean predicted 33.7 mph (= 54.2 km/h) vs mean actual 109.8 km/h
- predicted below actual on 96% of pairs after conversion

Skill (predicted mph -> km/h vs fused km/h):
- MAE 56.8 km/h  bias -55.6 km/h  RMSE 59.3 km/h
- diagnostic, no conversion (both raw): MAE 76.3  bias -76.1

By realised lead (predicted mph -> km/h):
| lead ahead (min) | n | MAE | bias | RMSE |
|---|---|---|---|---|
| 0-15 | 286 | 56.7 | -56.6 | 59.0 |
| 15-30 | 90 | 57.2 | -52.1 | 60.1 |
