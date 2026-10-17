# Past flows and publication delay: does ridge on past traffic cut the M271 cruise-day forecast error?

Generated 2026-10-17 08:59 UTC by `python demo/ridge_history.py`. Test window 2026-01-01 to 2026-06-30 (179 days, 99 with turnarounds), M271 northbound. Data and target as in [backtest.md](backtest.md). Features and the penalty grid were fixed on a Jul to Dec 2025 development window before this single run.

Horizon h = days between the newest count a forecaster can see and the forecast day. Every model is refit on days at least h before each month's origin. WebTRIS publishes about 105 days late, so **h = 105 is what we can do today**; h = 1 needs the council's own counts.

## Mean absolute error, vehicles per day (all test days)

| model | h = 1 | h = 7 | h = 28 | h = 105 |
|---|---|---|---|---|
| Learned model (gradient-boosted, calendar + passengers) | 876 | 890 | 906 | 914 |
| Ridge, calendar + passengers | 949 | 958 | 923 | 923 |
| Ridge, calendar + passengers + past flows | 769 | 809 | 905 | 952 |
| Gradient-boosted, calendar + passengers + past flows | 751 | 787 | 918 | 994 |
| Mean of gradient-boosted and ridge with past flows | 762 | 811 | 883 | 915 |
| Last comparable cruise day we can see | 1,233 | 1,256 | 1,613 | 1,786 |
| No cruise effect | 1,353 | 1,353 | 1,353 | 1,353 |

## Mean absolute error, vehicles per 15 minutes

| model | h = 1 | h = 7 | h = 28 | h = 105 |
|---|---|---|---|---|
| Learned model (gradient-boosted, calendar + passengers) | 24.1 | 24.2 | 24.5 | 24.8 |
| Ridge, calendar + passengers | 25.8 | 26.0 | 26.0 | 26.1 |
| Ridge, calendar + passengers + past flows | 23.6 | 23.8 | 25.2 | 25.7 |
| Gradient-boosted, calendar + passengers + past flows | 22.8 | 23.0 | 24.4 | 25.3 |
| Mean of gradient-boosted and ridge with past flows | 23.4 | 23.6 | 24.6 | 25.0 |
| Last comparable cruise day we can see | 31.1 | 31.2 | 34.3 | 36.9 |
| No cruise effect | 28.1 | 28.1 | 28.1 | 28.1 |

## Skill (1 - MAE / MAE of the comparison), 90% interval from resampling test weeks

| comparison | level | h = 1 | h = 7 | h = 28 | h = 105 |
|---|---|---|---|---|---|
| ridge_hist vs gbm | per day | +12.3% (+3.4% to +20.3%) | +9.1% (+0.6% to +16.5%) | +0.1% (-8.2% to +8.3%) ns | -4.1% (-12.7% to +3.8%) ns |
| ridge_hist vs gbm | per 15min | +1.9% (+0.6% to +3.3%) | +1.6% (+0.1% to +3.1%) | -3.0% (-4.6% to -1.5%) | -4.0% (-5.4% to -2.6%) |
| gbm_hist vs gbm | per day | +14.3% (+9.0% to +19.7%) | +11.5% (+3.6% to +19.1%) | -1.3% (-9.0% to +6.5%) ns | -8.8% (-13.4% to -4.2%) |
| gbm_hist vs gbm | per 15min | +5.2% (+3.6% to +6.7%) | +5.1% (+3.5% to +6.6%) | +0.5% (-1.2% to +2.1%) ns | -2.3% (-3.0% to -1.5%) |
| blend vs gbm | per day | +13.0% (+6.8% to +19.3%) | +8.8% (+4.0% to +13.2%) | +2.6% (-1.6% to +6.9%) ns | -0.2% (-4.5% to +4.0%) ns |
| blend vs gbm | per 15min | +3.0% (+2.2% to +3.9%) | +2.4% (+1.6% to +3.2%) | -0.3% (-1.1% to +0.4%) ns | -1.0% (-1.7% to -0.3%) |
| ridge_hist vs ridge | per day | +19.0% (+12.7% to +25.5%) | +15.6% (+9.9% to +21.2%) | +1.9% (-5.5% to +9.3%) ns | -3.1% (-6.9% to +0.7%) ns |
| ridge_hist vs ridge | per 15min | +8.4% (+7.1% to +9.7%) | +8.2% (+7.2% to +9.4%) | +3.0% (+1.4% to +4.4%) | +1.5% (+0.7% to +2.3%) |
| ridge vs gbm | per day | -8.3% (-16.2% to -1.0%) | -7.7% (-16.1% to +0.3%) ns | -1.8% (-10.3% to +5.5%) ns | -1.0% (-9.8% to +6.7%) ns |
| ridge vs gbm | per 15min | -7.0% (-8.3% to -5.8%) | -7.3% (-8.5% to -6.0%) | -6.1% (-7.7% to -4.5%) | -5.5% (-7.2% to -3.9%) |
| ridge_hist vs last_comparable | per day | +37.7% (+27.7% to +46.9%) | +35.6% (+26.1% to +43.9%) | +43.9% (+34.0% to +53.6%) | +46.7% (+38.2% to +54.0%) |
| ridge_hist vs last_comparable | per 15min | +24.1% (+20.6% to +27.3%) | +23.7% (+20.4% to +26.8%) | +26.5% (+22.3% to +30.6%) | +30.2% (+26.8% to +33.5%) |
| gbm vs last_comparable | per day | +28.9% (+19.3% to +37.4%) | +29.2% (+20.9% to +36.8%) | +43.8% (+34.2% to +52.7%) | +48.8% (+41.4% to +55.6%) |
| gbm vs last_comparable | per 15min | +22.6% (+18.8% to +26.2%) | +22.5% (+18.8% to +26.0%) | +28.6% (+24.6% to +32.6%) | +32.9% (+29.7% to +35.9%) |

`ns`: the interval includes zero.

## 80% band coverage, per day / per 15 minutes

| model | h = 1 | h = 7 | h = 28 | h = 105 |
|---|---|---|---|---|
| Learned model (gradient-boosted, calendar + passengers) | 87% / 74% | 85% / 73% | 86% / 73% | 87% / 71% |
| Ridge, calendar + passengers | 85% / 77% | 84% / 76% | 86% / 76% | 87% / 77% |
| Ridge, calendar + passengers + past flows | 86% / 80% | 86% / 80% | 84% / 78% | 84% / 78% |
| Gradient-boosted, calendar + passengers + past flows | 86% / 81% | 87% / 81% | 82% / 80% | 83% / 79% |
| Mean of gradient-boosted and ridge with past flows | 86% / 79% | 86% / 79% | 85% / 78% | 83% / 78% |
| Last comparable cruise day we can see | 79% / 82% | 76% / 82% | 72% / 81% | 84% / 83% |
| No cruise effect | 77% / 78% | 75% / 77% | 75% / 77% | 76% / 76% |

## Past-flow features available on test days

| feature | h = 1 | h = 7 | h = 28 | h = 105 |
|---|---|---|---|---|
| same_lag | 100% | 100% | 100% | 100% |
| hour_recent | 100% | 100% | 100% | 100% |
| level_recent | 100% | 100% | 100% | 100% |
| year_ago | 28% | 28% | 28% | 28% |

Ridge penalties chosen: [10000.0, 31622.776601683792]; 0 of 48 fits at the edge of the grid.

## Reading it

- h = 1: best per day is gradient-boosted, calendar + passengers + past flows (751). Against the gradient-boosted model, ridge with past flows +12.3% (+3.4% to +20.3%), gradient-boosted with past flows +14.3% (+9.0% to +19.7%), blend +13.0% (+6.8% to +19.3%).
- h = 7: best per day is gradient-boosted, calendar + passengers + past flows (787). Against the gradient-boosted model, ridge with past flows +9.1% (+0.6% to +16.5%), gradient-boosted with past flows +11.5% (+3.6% to +19.1%), blend +8.8% (+4.0% to +13.2%).
- h = 28: best per day is mean of gradient-boosted and ridge with past flows (883). Against the gradient-boosted model, ridge with past flows +0.1% (-8.2% to +8.3%), gradient-boosted with past flows -1.3% (-9.0% to +6.5%), blend +2.6% (-1.6% to +6.9%).
- h = 105: best per day is learned model (gradient-boosted, calendar + passengers) (914). Against the gradient-boosted model, ridge with past flows -4.1% (-12.7% to +3.8%), gradient-boosted with past flows -8.8% (-13.4% to -4.2%), blend -0.2% (-4.5% to +4.0%).

## Limits

- One road (M271 northbound) and one half-year of test days; the result may not carry to the dock roads, which have no public counts.
- The non-cruise median the uplift is measured from uses days up to the test window for every horizon, so h = 105 is slightly optimistic for January.
- Days without an archived cruise list are missing from training and testing, but their counts still feed the past-flow features.
- Development-window choices: the four past-flow features, a 35-day look-back for the latest same-type day, the 14-day background window and a 1 to 1,000,000 penalty grid.
