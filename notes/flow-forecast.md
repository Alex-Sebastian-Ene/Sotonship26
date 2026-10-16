# Everyday traffic forecast on the dock approaches: learned model vs baselines

Generated Sat 17 Oct 2026 00:03 by `python -m sotonship26.flow_forecast --cutoff 2025-07-01 --lag 105`. Data: National Highways WebTRIS 15-minute counts, 2024-01-01 to 2026-06-30 (Contains National Highways data, OGL v3.0).

Each test day after 2025-07-01 is forecast using only counts published 105 days before it, because WebTRIS lags about 3.5 months. Scores cover 05:00-22:00. Ridge is compared with each baseline on the days both can forecast (sensor gaps differ). `skill` = 1 - MAE(ridge) / MAE(baseline): above 0 means the learned model wins. `coverage80` should be near 0.80.

| site_id | versus | model | n_test_days | mae_veh_per_15min | skill_vs_baseline | mape_pct | coverage80 | width80_veh |
|---|---|---|---|---|---|---|---|---|
| 19974 | last_year | last_year | 16 | 31.33 | nan | 10.24 | 0.84 | 115.84 |
| 19974 | last_year | ridge | 16 | 31.79 | -0.01 | 12.56 | 0.78 | 96.28 |
| 19974 | recent_median | recent_median | 176 | 46.66 | nan | 19.16 | 0.72 | 118.28 |
| 19974 | recent_median | ridge | 176 | 39.10 | 0.16 | 16.15 | 0.74 | 107.77 |

Cruise days are not removed (no historic cruise list yet, see SOT-21), so these forecasts are 'typical traffic including the average cruise effect'.
