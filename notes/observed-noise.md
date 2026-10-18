# How noisy is real traffic? Targets for the demo's noise settings

Keanu's Claude Code session, Sat 17 Oct 2026. Source: National Highways WebTRIS 15-minute counts (OGL v3.0,
collected 16–17 Oct 2026). Reproduce with `PYTHONPATH=src python scripts/observed_noise.py`.

`demo/traffic_model.py` (v0.3, main 8daf6c7) samples each day with assumed noise, all in log space:
`NOISE = {"day": 0.04, "purpose": 0.04, "bin": 0.05, "rho": 0.8, ...}`. A day-wide lognormal factor,
one per trip purpose, and an AR(1) wobble per purpose per 15-minute bin. This note measures the same
quantities on real counts, around our out-of-sample ridge forecast. Ridge is refitted monthly on
data published 105 days earlier, as in `notes/flow-forecast.md`. Daytime bins only; bins with
fewer than 20 vehicles are skipped.

| Quantity (log scale) | M3 J14 (20025), 355 days | M271 NB (19974), 178 days | Demo v0.3 setting |
|---|---|---|---|
| Day-wide sd, robust (1.4826 × MAD) | 0.045 | 0.061 | day 0.04 plus purpose 0.04 each |
| Day-wide sd, plain | 0.090 | 0.082 | |
| Day-wide 5% / 95% | −0.14 / +0.08 | −0.13 / +0.06 | |
| 15-min sd net of count noise, robust | 0.065 | 0.079 | bin 0.05 per purpose |
| 15-min sd net of count noise, plain | 0.117 | 0.112 | |
| 15-min lag-1 autocorrelation | 0.75 | 0.76 | rho 0.8 |
| Share of 15-min bins beyond 3 robust sd (normal: 0.003) | 0.041 | 0.031 | incidents, 15% of days |

How to read it:

- **Day-wide:** the typical day matches the demo. The plain sd is about twice the robust one
  because the left tail is heavy (5% of days are 13–14% below forecast). Those are bad days: wet,
  incidents, snow, holidays the calendar misses. The demo's wet-day and incident draws are meant
  to make that tail, so check it against the 5% quantile, not just the sd.
- **15-minute wobble:** rho 0.8 is about right (measured 0.75). The size may be too small.
  Each of the 12 purposes gets its own independent AR(1) at sd 0.05. On a road carrying a mix,
  they partly cancel. Weighting by the weekday trip totals in `PURPOSES` (rough, since each link
  carries its own mix), the effective sd is about 0.05 × 0.46 ≈ 0.023.
  The measured core is 0.065–0.08. Suggest Seb measures the same statistics on his sampled
  flows at a corridor link and tunes `bin` (or adds a shared, not per-purpose, AR(1) term) until
  they match.
- **Fat tails:** 3–4% of bins sit beyond 3 sd, ten times a normal curve. Short incidents and
  queues do this. A 15% daily incident chance should produce something like it.

Caveats, so these are targets, not truths:

- These are motorway sites (M3 J14, M271), not the city streets by the docks. Urban links are
  probably noisier per vehicle (signals, lower volumes), which pushes the other way from the next
  point. Treat the numbers as a rough guide, not exact targets.
- Residuals include ridge's own mistakes (for example, a holiday it doesn't know about). So they
  overstate pure demand noise, mostly in the plain sd and the tails. The robust figures are less
  affected.
- Count noise is taken as Poisson (variance of log count ≈ 1/count, sd about 0.06 here). If
  detector counts are noisier than Poisson, the net figures are slightly too high.
- No weather data, so the wet-day share (50–55%, assumed) and its 7% capacity drop are not
  checked here.
