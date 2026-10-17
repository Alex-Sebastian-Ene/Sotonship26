# Backtest: learned cruise uplift on the M271

Generated 2026-10-17 08:01 UTC by `demo/webtris_backtest.py` (written with Claude Code; see the README provenance section). Summary numbers for the page are in `demo/out/backtest.json`.

## Summary

- Backtest: 179 held-out days, Jan 2026 to Jun 2026. Beats all three baselines on whole-day uplift: error 877 vehicles a day, against 1,233 for the last comparable cruise day, 1,156 for passengers only and 1,353 for no cruise effect.
- Most of that gain is the calendar (weekday, month, holidays): without ship passengers the same model scores 910. The ship schedule cuts the error by a further 4% a day (not significant) and 2% per 15 minutes (significant), and the Brier score for a day above 2,000 vehicles by 8%.
- 87% of held-out days fell inside the 80% band (74% of 15-minute intervals).
- Observed on the M271 northbound (National Highways WebTRIS 19974), 4 to 7 km from the terminals; counts end 29 Jun 2026. Past calls from archived ABP schedules. Dock-gate traffic itself is not observable from any public source, so this is a test on a proxy.

## What was tested

**Observable.** Vehicles per 15 minutes on the M271 northbound, National Highways WebTRIS sites 7588 (Jan to Aug 2024) and 19974 (from Oct 2024). Northbound is traffic leaving towards the M27; the sensors are 4 to 7 km from the terminals.

**Target.** Cruise uplift: the count minus the median for the same weekday and 15 minutes on non-cruise days (bank holidays use the Sunday median). Medians come only from days before 01 Jan 2026, per sensor.

**Learned model.** Gradient-boosted quantile regression (scikit-learn HistGradientBoosting, quantiles 5% to 95%) of the 15-minute uplift on: turnaround passengers at the Eastern Docks (berths 38/39, 46) and Western Docks (101, 102, 106), time of day, weekday, bank holiday, school holiday, month, and Southampton FC home league matches (with hours since kick-off). The uplift may only rise with passengers.

**Baselines.** (1) Last comparable cruise day: the 15-minute uplift of the latest earlier day of the same weekday with the same calls per dock group (else same number of calls, else within one); it may use any day already observed, including earlier test days. (2) Passenger count only: a straight line per 15-minute slot on the day's total turnaround passengers. (3) No cruise effect: zero uplift. An extra row, the same learned model without the passenger inputs, shows how much of the gain is the cruise information rather than the calendar.

**Uncertainty.** The learned model's 15-minute bands are its own 10% and 90% quantiles. Baselines, and every whole-day band, use each forecaster's own past errors on training days (out-of-fold for fitted models). Brier scores use the same distributions.

**Split.** Training before 01 Jan 2026: 340 days (2024-01-14 to 2025-12-31), 226 with calls, 418 calls. Held out: 179 days (2026-01-01 to 2026-06-29), 99 with calls, 57 weekend or bank-holiday days, 191 calls. Rolling origin: every model is refit on all earlier days at the start of each test month (2026-01: 340 train / 31 test days, 2026-02: 371 train / 28 test days, 2026-03: 399 train / 31 test days, 2026-04: 430 train / 30 test days, 2026-05: 460 train / 30 test days, 2026-06: 490 train / 29 test days). Thresholds (50 vehicles per 15 minutes, 2,000 per day) and model settings were fixed from training data before the test run.

## Results on held-out days

### Whole-day uplift, all 179 test days

| Forecaster | MAE (vehicles per day) | Brier, uplift > 2,000 | 80% band coverage | Band width |
|---|---|---|---|---|
| Learned model (gradient-boosted quantiles) | 876.8 | 0.109 | 87% | 2,996 |
| Last comparable cruise day | 1,233.1 | 0.133 | 79% | 3,622 |
| Passenger count only (linear) | 1,156.5 | 0.113 | 77% | 3,263 |
| No cruise effect | 1,353.4 | 0.134 | 77% | 3,462 |
| Same model without cruise inputs | 909.8 | 0.118 | 86% | 3,124 |

### Whole-day uplift, 99 test days with calls

| Forecaster | MAE (vehicles per day) | Brier, uplift > 2,000 | 80% band coverage | Band width |
|---|---|---|---|---|
| Learned model (gradient-boosted quantiles) | 933.9 | 0.156 | 85% | 2,962 |
| Last comparable cruise day | 1,465.4 | 0.197 | 72% | 3,609 |
| Passenger count only (linear) | 1,189.6 | 0.166 | 73% | 3,237 |
| No cruise effect | 1,596.2 | 0.198 | 75% | 3,444 |
| Same model without cruise inputs | 973.7 | 0.176 | 85% | 3,103 |

### 15-minute uplift, all 179 test days

| Forecaster | MAE (vehicles per 15 minutes) | Brier, uplift > 50 | 80% band coverage | Band width |
|---|---|---|---|---|
| Learned model (gradient-boosted quantiles) | 24.1 | 0.080 | 74% | 65 |
| Last comparable cruise day | 31.1 | 0.094 | 82% | 98 |
| Passenger count only (linear) | 26.1 | 0.083 | 78% | 76 |
| No cruise effect | 28.1 | 0.094 | 78% | 79 |
| Same model without cruise inputs | 24.5 | 0.082 | 72% | 65 |

### 15-minute uplift, 57 weekend and bank-holiday test days

| Forecaster | MAE (vehicles per 15 minutes) | Brier, uplift > 50 | 80% band coverage | Band width |
|---|---|---|---|---|
| Learned model (gradient-boosted quantiles) | 25.8 | 0.080 | 73% | 69 |
| Last comparable cruise day | 32.9 | 0.102 | 81% | 98 |
| Passenger count only (linear) | 28.0 | 0.086 | 76% | 76 |
| No cruise effect | 32.2 | 0.109 | 75% | 79 |
| Same model without cruise inputs | 26.6 | 0.083 | 71% | 70 |

MAE: mean absolute error. Brier: mean squared error of the forecast probability that the uplift is above the threshold (lower is better; base rates 16% of days and 12% of 15-minute intervals). Coverage: share of observations inside the 80% band (should be near 80%).

## Verdict

- Whole-day uplift, MAE 877 vs 1,233: the model beats last comparable cruise day by 29% (90% interval of the gap -514 to -205, excludes zero).
- Whole-day uplift, MAE 877 vs 1,156: the model beats passenger count only (linear) by 24% (90% interval of the gap -340 to -219, excludes zero).
- Whole-day uplift, MAE 877 vs 1,353: the model beats no cruise effect by 35% (90% interval of the gap -571 to -382, excludes zero).
- Whole-day uplift, MAE 877 vs 910: the model is not clearly different from same model without cruise inputs (+4%, 90% interval of the gap -86 to +20 includes zero).
- 15-minute uplift, MAE 24 vs 31: the model beats last comparable cruise day by 23% (90% interval of the gap -8 to -6, excludes zero).
- 15-minute uplift, MAE 24 vs 26: the model beats passenger count only (linear) by 8% (90% interval of the gap -2 to -2, excludes zero).
- 15-minute uplift, MAE 24 vs 28: the model beats no cruise effect by 14% (90% interval of the gap -5 to -4, excludes zero).
- 15-minute uplift, MAE 24 vs 24: the model beats same model without cruise inputs by 2% (90% interval of the gap -1 to -0, excludes zero).

Intervals are from 2,000 bootstrap resamples of test days (paired, so both forecasters are scored on the same days).

## What the model learned

Refit on all 519 days, for an October Saturday or Sunday in school term, with no bank holiday or home match; passengers are split evenly between the docks. The steps are those of a tree model: it is flat where the training data had few days.

| Turnaround passengers | Saturday uplift (80% band) | of which cruise | Sunday uplift (80% band) | of which cruise |
|---|---|---|---|---|
| 0 | -113 (-1,420 to 1,273) | +0 | 566 (-741 to 1,951) | +0 |
| 2,500 | 286 (-1,020 to 1,672) | +400 | 1,163 (-143 to 2,549) | +598 |
| 5,000 | 888 (-418 to 2,274) | +1,001 | 2,100 (794 to 3,486) | +1,534 |
| 7,500 | 1,021 (-286 to 2,407) | +1,134 | 2,298 (992 to 3,684) | +1,733 |
| 10,000 | 1,044 (-263 to 2,429) | +1,157 | 2,298 (992 to 3,684) | +1,733 |
| 12,500 | 1,419 (112 to 2,805) | +1,532 | 2,633 (1,326 to 4,019) | +2,067 |
| 15,000 | 1,930 (624 to 3,316) | +2,044 | 3,159 (1,853 to 4,545) | +2,594 |

"Of which cruise" is the model's forecast minus its forecast for the same day with no ships. It is a forecast for October 2026, which cannot be checked against counts until WebTRIS publishes data after 29 Jun 2026.

## Data, with collection dates

- **National Highways WebTRIS**: 15-minute counts 2024-01-01 to 2026-06-30; valid days: site 7588 203, site 19974 410 (valid = >= 90 of 96 intervals, > 1000 vehicles, no zero interval 07:00-20:00). Retrieved 2026-10-17. Listed by DfT as free and open; Open Government Licence assumed, not confirmed on the WebTRIS site.
- **Southampton VTS cruise ship schedule (ABP), Internet Archive captures**: 792 calls on 625 of 912 days from captures dated 2024-01-13, 2024-09-25, 2025-07-04, 2025-12-08. Retrieved 2026-10-17. ABP terms: personal reference, ABP acknowledged. Raw pages and the call list stay private; only aggregates are published.
- **Wikidata ship capacity (P1083)**: 68 of 82 ships matched by name; 64 of 792 calls use the median (2,483). Retrieved 2026-10-17. CC0.
- **Bank holidays, gov.uk**: England and Wales. Retrieved 2026-10-17. Open Government Licence v3.0.
- **School holidays, Southampton City Council**: Term dates 2023-24 to 2025-26 typed in from https://www.southampton.gov.uk/schools-learning/school-information/school-term-dates/school-year-calendar-<year>/ (Internet Archive captures of Feb to Mar 2024). Retrieved 2026-10-16. Council web pages.
- **Southampton FC home league matches, football-data.co.uk**: 52 home league matches in the period; cup matches are missing. Retrieved 2026-10-17. Free download; source credited.

Non-cruise days behind the medians (before 01 Jan 2026): WebTRIS 7588: Mon 12, Tue 15, Wed 16, Thu 6, Fri 2, Sat 5, Sun 7; WebTRIS 19974: Mon 7, Tue 11, Wed 11, Thu 7, Fri 1, Sat 4, Sun 7.

## Limits

- The M271 sensors are 4 to 7 km from the terminals and northbound only (traffic leaving the docks). No public count exists at the dock gates, Platform Road or West Quay Road.
- WebTRIS currently stops at 29 Jun 2026, so nothing after that date can be checked.
- Past calls come from archived provisional plans (ABP), not actual berthings. 2026 calls are from the 8 Dec 2025 plan. Days no archived plan covers (Jul 2024, Jan to Aug 2025) are left out, not treated as zero. CruiseMapper, which could fill some gaps, forbids automated collection and is not used.
- Every call is treated as a full turnaround at the ship's maximum capacity (Wikidata P1083; definitions vary between lower berths and maximum). Transit calls, real load factors and the share of passengers who drive are unknown. Ships without a Wikidata capacity (Arvia, Disney Fantasy and a few small ships) get the median.
- Few non-cruise Fridays and Saturdays exist in the training period (1 to 5 per sensor), so the non-cruise median for those days is noisy. All models share this target.
- Not controlled: weather, incidents and closures, roadworks, port freight (container and car lorries use the M271), cup matches and other events. Season enters only through the month.
- The test period is six months of one sensor (19974) in one year; the cruise season in it is April to June only.

## Reproduce

```bash
uv run --no-project --python 3.12 --with numpy --with pandas --with scikit-learn python demo/webtris_backtest.py
```

Downloads are cached under `data/cache/` and `data/raw/` (gitignored); a second run makes no requests. Raw VTS captures and the rebuilt call list stay private (ABP terms).
