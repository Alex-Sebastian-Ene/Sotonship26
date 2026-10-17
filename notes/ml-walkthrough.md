# ML walkthrough: what Keanu's lane built overnight, and the ideas behind it

Read this with `src/sotonship26/flow_forecast.py`, `backtest.py` and `uplift.py` open. Each heading
is one ML idea, where it appears in the code, and why it is there.

## 1. Define the target before the model

`uplift.py` defines what we want to predict: **cruise uplift**, meaning observed traffic minus
what that road normally carries at the same weekday and time on nearby days without ships. If
we predicted raw traffic instead, any model would mostly learn "Mondays are busy". Subtracting the
reference isolates the part the cruise schedule can explain. Reference days must be *known*
no-cruise days. A day missing from our schedule source is "unknown", not "zero" (the `covered`
flag), or we would teach the model that cruise days have no effect.

## 2. Baselines first

A model only counts as AI at the core if it beats something simple a person could do by hand
(the brief says so, and so do the judges). Each forecaster ships with its baselines:

- `flow_forecast.py`: **last_year** (same weekday 52 weeks ago, one day so noisy),
  **year_median** (median of the five same weekdays around 52 weeks ago), **recent_median** (the
  same weekday over the newest 4 weeks we can see) and **planner_rule** (year_median if we have
  it, else recent). Always quote skill against the *strongest* baseline: beating a weak one is
  easy. Our first draft compared against last_year only and claimed 17%; against year_median the
  same model won by 4% (7% once school holidays were added, see section 7).
- `backtest.py`: **zero** (no cruise effect), **last_day** (the most comparable earlier cruise
  day, which is the brief's own suggestion) and **pax_linear** (uplift proportional to
  passengers).

`skill = 1 - MAE(model) / MAE(baseline)`. Above 0 means the model wins, and 0.17 means 17% less
error.

## 3. No peeking: time splits and the publication lag

Shuffled cross-validation would leak the future into training. Every split here is by **time**:
train before a cutoff, test after it. There is a second, subtler leak. WebTRIS publishes about
105 days late, so on the day a council officer plans, the newest counts are 3.5 months old.
`flow_forecast.backtest_site` refits the model once a test month using only days published by
then (`dates <= first - lag`). The baselines follow the same rule (`last_year` returns None if
a year ago isn't published yet). Ignoring this would make every model look better than it
could be in real use.

## 4. Ridge regression, and choosing its penalty honestly

The learned model is **multi-output ridge regression** (`backtest.Ridge`). Each day is one
row of features. The output is 96 numbers, one per 15-minute bin. Ridge is least squares plus
`lambda * ||coefficients||^2`, which shrinks coefficients toward 0 so a few hundred days don't
overfit about 30 features. `lambda` is picked by fitting on the first 75% of the training
period and scoring on the last 25%, again split by time. Coefficients are then smoothed across
neighbouring bins, because traffic at 08:00 and 08:15 should not need unrelated parameters.

Features for everyday traffic (`calendar_features`): a weekday one-hot, an annual cycle
(sin/cos of day of year), **weekday x season interactions** (Saturdays in August differ from
Saturdays in January), bank holidays, Christmas week, **Southampton school-holiday weekdays**
(council term dates, which move from year to year, so a year-ago lookup gets them wrong) and a
linear trend.

## 5. Intervals you can trust: split conformal prediction

A single number isn't enough for a council officer, who needs to know how sure we are.
`conformal_halfwidth` holds out the newest 20% of training days, measures the absolute errors
there, and takes the 80th percentile per hour of day. Adding ± that to a forecast gives an
interval that covers the truth about 80% of the time, without assuming the errors are normal.
The `coverage80` column checks this on the test period. 0.79 at M3 J14 means it held.

## 6. Probabilities and the Brier score

For "will this hour be unusually busy?", `event_probability` adds the calibration errors to
the forecast and counts how often the result crosses a threshold. The threshold is the 95th
percentile of uplift on no-cruise days. The **Brier score** is the mean squared difference
between that probability and what happened (0 or 1). Lower is better, and it rewards being
honest about uncertainty.

## 7. What the numbers say tonight

- **Everyday traffic** (`notes/flow-forecast.md`): at M3 J14 (355 test days) the learned model
  beats a careful planner (year_median) by **7%** MAE (35.0 vs 37.4 vehicles per 15 min, WAPE
  9.4% vs 10.1%; week-block bootstrap 90% CI for the skill 0.5% to 12%). It beats the one-day
  year-ago lookup by 19% and the recent median by 28%. Its 80% intervals cover 84%, a little
  wide; year_median's own intervals are narrower (106 vs 124 vehicles) at 80%.
  Where the win comes from: on the 62 school-holiday weekdays year_median is badly off (MAE 55.7
  against 39.1 for ridge), because holiday dates shift and a year-ago lookup lands on term time
  or the other way round. On ordinary days year_median is slightly better (33.6 vs 34.1).
  Adding the school-holiday flag cut ridge's error by 2.7% (90% CI 1.8% to 3.7%). Before the
  flag the skill was 4% and its interval included zero.
  At M271 NB it beats the recent median by 11% over 147 days, but the year-ago baselines exist
  for only 17 test days there, so we cannot say it beats a planner. Sites with under 30
  comparable days are noise (20313 went from +10% to -8% on 29 days when the flag was added).
  Honest headline: the model is a small, real improvement on the best hand rule, not a big one,
  and it wins exactly where calendars shift.
- **Cruise uplift** (`notes/backtest.md` once labels exist): blocked. No permitted source has
  past cruise calls (`notes/cruise-history.md`, SOT-21). The code is tested on synthetic data
  with a known effect (`tests/test_uplift_backtest.py`) and runs as soon as a call list lands.

## Things to try next (good practice reps)

1. Add a **lagged-year feature** to ridge (last year's value in the same bin), so the model
   can beat `last_year` where a year of history exists.
2. Replace ridge with **gradient-boosted trees with quantile loss** (scikit-learn
   `HistGradientBoostingRegressor(loss="quantile")`) and compare skill and coverage.
3. Plot a **reliability diagram** for `p_event`: bin the predicted probabilities, then compare
   each bin with the observed frequency.
