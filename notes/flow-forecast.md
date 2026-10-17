# Everyday traffic forecast on the dock approaches: learned model vs baselines

Generated Sat 17 Oct 2026 01:15 by `python -m sotonship26.flow_forecast --cutoff 2025-07-01 --lag 105`. Data: National Highways WebTRIS 15-minute counts, 2024-01-01 to 2026-06-30 (Contains National Highways data, OGL v3.0).

Each test day after 2025-07-01 is forecast using only counts published 105 days before it, because WebTRIS lags about 3.5 months. Scores cover 05:00-22:00. Ridge is compared with each baseline on the days both can forecast (sensor gaps differ). `skill` = 1 - MAE(ridge) / MAE(baseline): above 0 means the learned model wins. `skill_ci5`-`skill_ci95` is its 90% interval from resampling whole test weeks. `coverage80` should be near 0.80.

## Headline: ridge against the strongest baseline at each site

| site_id | strongest_baseline | n_test_days | ridge_skill_vs_strongest | skill_ci5 | skill_ci95 |
|---|---|---|---|---|---|
| 19974 | year_median | 17 | -0.30 | -0.42 | -0.23 |
| 20313 | planner_rule | 29 | -0.08 | -0.24 | 0.07 |
| 20025 | year_median | 355 | 0.07 | 0.01 | 0.12 |

## All comparisons

| site_id | versus | model | n_test_days | mae_veh_per_15min | skill_vs_baseline | skill_ci5 | skill_ci95 | wape_pct | coverage80 | width80_veh |
|---|---|---|---|---|---|---|---|---|---|---|
| 19974 | last_year | last_year | 17 | 31.56 | nan | nan | nan | 9.20 | 0.83 | 115.84 |
| 19974 | last_year | ridge | 17 | 32.64 | -0.03 | -0.07 | -0.02 | 9.51 | 0.86 | 120.89 |
| 19974 | year_median | year_median | 17 | 25.60 | nan | nan | nan | 7.50 | 0.87 | 107.04 |
| 19974 | year_median | ridge | 17 | 33.28 | -0.30 | -0.42 | -0.23 | 9.75 | 0.86 | 120.89 |
| 19974 | recent_median | recent_median | 147 | 44.84 | nan | nan | nan | 12.38 | 0.76 | 126.58 |
| 19974 | recent_median | ridge | 147 | 39.70 | 0.11 | 0.01 | 0.21 | 10.96 | 0.80 | 124.99 |
| 19974 | planner_rule | planner_rule | 147 | 43.51 | nan | nan | nan | 12.01 | 0.76 | 122.56 |
| 19974 | planner_rule | ridge | 147 | 39.70 | 0.09 | -0.03 | 0.19 | 10.96 | 0.80 | 124.99 |
| 20313 | planner_rule | planner_rule | 29 | 19.53 | nan | nan | nan | 20.45 | 0.86 | 69.80 |
| 20313 | planner_rule | ridge | 29 | 21.11 | -0.08 | -0.24 | 0.07 | 22.10 | 0.86 | 74.66 |
| 20025 | last_year | last_year | 350 | 43.43 | nan | nan | nan | 11.70 | 0.80 | 130.26 |
| 20025 | last_year | ridge | 350 | 35.05 | 0.19 | 0.15 | 0.23 | 9.44 | 0.84 | 124.39 |
| 20025 | year_median | year_median | 355 | 37.41 | nan | nan | nan | 10.10 | 0.80 | 105.52 |
| 20025 | year_median | ridge | 355 | 34.96 | 0.07 | 0.01 | 0.12 | 9.43 | 0.84 | 124.24 |
| 20025 | recent_median | recent_median | 355 | 48.46 | nan | nan | nan | 13.08 | 0.77 | 132.70 |
| 20025 | recent_median | ridge | 355 | 34.96 | 0.28 | 0.20 | 0.35 | 9.43 | 0.84 | 124.24 |
| 20025 | planner_rule | planner_rule | 355 | 37.41 | nan | nan | nan | 10.10 | 0.80 | 106.68 |
| 20025 | planner_rule | ridge | 355 | 34.96 | 0.07 | 0.01 | 0.12 | 9.43 | 0.84 | 124.24 |

![One test week at M3 J14](figures/flow_forecast_20025.png)

Reading it: only 20025 (M3 J14) has a long enough record to compare with every baseline over a full test year. There the learned model is a small but real improvement on a careful planner (median of five same weekdays a year earlier). It is a large improvement on the one-day year-ago lookup and the recent median. At 19974 (M271 NB) the year-ago baselines only exist for a handful of test days, so its reliable comparison is against the recent median. 20313/20605 have under 30 comparable test days and patchy sensor data, so their scores are noise. 7588 and 19796 have no test days after the cutoff.

Cruise days are not removed (no historic cruise list yet, see SOT-21), so these forecasts are 'typical traffic including the average cruise effect'. Forward forecasts for any date range: `--forecast FROM TO` writes runs/flow_forecast/<site>.csv (date, tod_bin, flow_veh, lo80, hi80).
