# Submission draft (SOT-16): evaluation lane's input

Draft by keanu-claude, Sat 17 Oct 2026, for the humans and Edward (pitch owner) to cut and edit.
Only the evaluation numbers are checked here. Product claims must be checked against what the app
shows on Sunday morning.

## 150-word summary (149 words)

> Southampton's traffic team must decide, days ahead, which cruise turnaround days need marshals,
> sign messages and a hold on roadworks near the docks. Today that rests on experience and
> "same day last year". We read the published VTS cruise schedule, match it with Saints fixtures,
> and forecast traffic on the dock approach roads, with an 80% range.
>
> The forecast is a ridge regression on calendar features, including Southampton school holidays,
> refitted monthly on counts National Highways has already published, about 105 days late.
> On a year of held-out days at M3 J14 it is 6.6% more accurate than the strongest planner rule, a five-week same-week-last-year median (90% CI 0.5–12%), and its 80% range covers
> 84% of outcomes. On the 17 M271 days with a year-ago record, the
> planner rule beats us, and we say so. We cannot yet measure the cruise effect itself: no open historic cruise schedule exists.

Word count: `sed -n '/^> /p' notes/submission-draft.md | wc -w`, less the `>` markers.

## Numbers the video and README may quote

All from `notes/flow-forecast.md`, CIs from resampling whole test weeks (regenerate with `python -m sotonship26.flow_forecast`).
WebTRIS 15-minute counts, OGL v3.0, collected 16–17 Oct 2026. Daytime bins only.
Test period 2025-07-01 to 2026-06-29.

| Claim | Number | Sample |
|---|---|---|
| Ridge vs five-week year-ago median, M3 J14 (site 20025) | skill 0.066, 90% CI 0.005–0.12 | 355 test days |
| Same, MAE in vehicles per 15 min | 34.9 vs 37.4 | 355 days |
| Where the win comes from: school-holiday weekdays | MAE 38.9 vs 55.7 | 62 days |
| Ordinary days (the planner rule is slightly better) | MAE 34.1 vs 33.6 | the other 293 days |
| 80% interval coverage, M3 J14 | 0.84 | 355 days |
| M271 northbound (19974) vs five-week year-ago median | skill −0.30 (CI −0.42 to −0.23), a **loss** | 17 days, 1–22 Mar 2026 (4 weeks to resample, so the CI is rough) |
| M271 northbound (19974) vs planner rule (year-ago median, else last four published weeks) | skill 0.087, 90% CI −0.03 to 0.19: **not clear of zero** | 147 days |

Do not quote:

- the 17% figure from the first version. Its baseline was a one-day lookup, not the planner rule.
- skill at sites 20313 or 20605. They have under 30 comparable days, so the score is noise.

## The failure to demo (judging: "must demo a failure")

Pick one; all three are real and reproducible from the repo.

1. **The model loses where history is thin.** At M271 site 19974 the five-week year-ago median
   beats ridge (MAE 25.6 vs 33.3, 17 days). Show the row. The app does not yet
   fall back to the planner rule there; say so, or build that fallback before Sunday 11:00.
2. **We cannot measure the cruise effect yet.** `python -m sotonship26.run_backtest` on real data
   exits and points to SOT-21: no permitted open source of historic cruise calls exists (see
   `notes/cruise-history.md`). The uplift pipeline is tested on synthetic data with a known effect,
   labelled synthetic. The ask to ABP / southamptonships.org is in SOT-21 for the humans to send.
3. **Holidays forecast too low.** For 08:30 on Christmas Day 2026 at M3 J14 the forecast is 0
   vehicles (80% range 0–47); past Christmas Days had 64–77. The linear model stacks the holiday
   effects below zero, and the code clips them at 0. `python -m sotonship26.flow_forecast
   --sites 20025 --forecast 2026-12-24 2026-12-28`, then read `runs/flow_forecast/20025.csv`.
   Fix to try: fit on log flow (`notes/ml-walkthrough.md`, item 2).

## Responsibility points (15)

- Every source has a date and licence in the README. VTS data is fetched live and never committed
  (© ABP, no redistribution).
- The everyday forecast is backtested on data the model could not have seen. Each refit uses only
  counts published 105 days before the forecast day, and the conformal calibration respects that
  lag too.
- We report where the model loses, and the sample size next to every score.
- School holiday dates come from Southampton City Council's term calendars, which cover
  maintained schools. Academies and INSET days differ, which adds error on those days.
- No personal data is used. Counts are vehicles per lane per 15 minutes.

## Still for the humans

- Record the YouTube video (1–3 min) and add its link.
- Fill in "Existed before the event" and "Who helped" in the README provenance section.
- Revoke the Linear API key after the event.
