# Submission, SotonShip 2026 (Southampton City track)

Single source of truth for the submission: form fields, what's left, the numbers we may quote
(with provenance), the failure we must demo, and the responsibility points. The demo/pitch/video
plan lives in [docs/pitch-playbook.md](docs/pitch-playbook.md).

**Hard lock: Sun 18 Oct 2026, 13:00.** Code freeze 11:00, submit by 12:30. Incomplete
submissions at the lock are not shown in Stage 1. Save early, update until lock.

## Form fields

| # | Field | Required | Status | Owner | Note |
|---|-------|----------|--------|-------|------|
| 1 | GitHub repository (public) | yes | ✅ done | - | `https://github.com/Alex-Sebastian-Ene/Sotonship26` |
| 2 | Project summary (≤150 words) | yes | ✅ drafted | Keanu | `README.md` → "In a paragraph" (148 words). Paste into form, edit to taste. |
| 3 | Pitch video, YouTube link | yes | ❌ **BLOCKER** | team | Public/Unlisted, embedding allowed, must show the real product working. |
| 4 | Video length (m:ss) | yes | ❌ depends on 3 | team | Must be **1:00–3:00** (target ~2:40). |
| 5 | Pitch format | yes | ❌ decide | team | Full 3-min video, or shorter video + live pitch for the rest of the slot. |
| 6 | Live link / run instructions | optional | ⚠️ partial | - | README has run steps; no hosted live link. See below. |

## What's left to lock in (ordered)

1. **Record the pitch video (BLOCKER).** 1:00–3:00. Must show the real product
   (`demo/page.html`: calendar → day view → what-if) working. Beat sheet + overlay plan:
   [docs/pitch-playbook.md](docs/pitch-playbook.md) §6; overlay build in [demo/video/](demo/video/README.md).
2. **Upload to YouTube**, set Public/Unlisted + allow embedding, grab link + exact length.
3. **Pick pitch format** (full video vs video + live) and fill the field.
4. **Paste the 150-word summary** from README into the form.
5. **Save the submission** (can keep updating until 13:00).

## Optional live link

The overview page is a single self-contained file (`demo/ui_embeds/` merged). Judge-openable
without a server:
- GitHub Pages on the repo (static; `demo/page.html` + embeds), **or**
- leave it out (optional field) and rely on README run instructions.

Decide only if time permits after the blockers.

## Numbers we may quote (every one carries its source + date)

From the evaluation lane. CIs resample whole test weeks / bootstrap days. WebTRIS 15-min counts,
OGL v3.0, collected 16–17 Oct 2026, daytime bins; test period 2025-07-01 to 2026-06-29.

| Claim | Number | Sample / source |
|---|---|---|
| Ridge vs five-week year-ago median, M3 J14 (site 20025) | skill **0.066**, 90% CI 0.005–0.12 | 355 test days (`notes/flow-forecast.md`) |
| Same, MAE veh/15 min | 34.9 vs 37.4 | 355 days |
| Where the win comes from: school-holiday weekdays | MAE 38.9 vs 55.7 | 62 days |
| Ordinary days (planner rule slightly better) | MAE 34.1 vs 33.6 | the other 293 days |
| 80% interval coverage, M3 J14 | 0.84 | 355 days |
| M271 NB (19974) vs five-week year-ago median | skill **−0.30** (CI −0.42…−0.23), a **loss** | 17 days, 1–22 Mar 2026 (rough CI) |
| M271 NB (19974) vs planner rule | skill 0.087, 90% CI −0.03…0.19, **not clear of zero** | 147 days |
| Cruise effect, M271 backtest | MAE **877** veh/day vs 1,233 (last-day) / 1,353 (no effect); 87% in 80% band | 179 held-out days (`docs/backtest.md`) |
| Ship list's own contribution | **~2%** per 15 min (clears zero); per-day 4% does **not** | say "per 15 minutes" |
| **Learned plan (PPO), what it gains** | **avoids 3.1 congested road-hours/day** (7.4% of the 41.1/day baseline), all 7 held-out dates, 96% of days (95% CI 2.2–3.9) | held-out cruise dates, **simulated** (`docs/ppo-results-aa8eae9.md`). Total delay unchanged (−6 veh-hrs, −136…+124). |
| **PPO, what it costs** | ~**£2,500/day** (+£2,545; 95% +£682…+£4,451), ≈ **£830 per congested road-hour avoided** | money alone is now a clear **cost**, the interval no longer crosses zero. Weighted score −£12,777/day; the £5,000/road-hour weight is an **assumption, not money**. |
| **Ship-timing advisor, the money saver** | **saves ~£7,100/day** (95% £3,400…£11,100) and avoids **1.2 road-hours** | all 7 dates, 94% of days; cuts delay 471 veh-hrs/day, no marshals or signs. The free lever. |
| **85% rule, for scale** | congestion unchanged (**+0.4**), +1,600 veh-hrs delay, ~**£25,000/day** | the naive baseline; worse than doing nothing on cost and on >85% road-hours. |

**Authoritative source = `docs/ppo-results-aa8eae9.md`** + the robust summary `docs/ppo-robust-aa8eae9.md`
(PPO re-scored on the corrected demand, Iridis **job 1899759** / aa8eae9, generated 2026-10-18T07:58),
Seb's call (SOT-32, 2026-10-18). Quote the robust file (its intervals resample dates, then days). Lands on
main via `seb/ppo-aa8eae9` (PR to follow). All PPO figures are **simulated**; unit costs (£5,000/road-hour,
£15/veh-hr, £120/marshal-hr, £25/sign-hr, £15/pax-hr) are **assumed**. On the weighted score the advisor
(−£13,058/day) now edges PPO (−£12,777/day), PPO no longer wins that score; say so if asked.

**Do not quote:**
- **−£10,724/day, 93%** from `docs/ppo-results-gpu2.md`, superseded old-model run C, not what the
  page uses. (Earlier draft of this doc quoted it in error.)
- **−£19.6k/day, 96%** from the old overview/verdict embed, a separate 52-run quick eval that
  overstated; `seb/ppo-numerics` already removes that embed and moves the page to held-out figures.
- The **pre-aa8eae9** figures (5.0 road-hours / 8.3% / ~£2,100/day / £410 per road-hour / advisor
  ~£220/day / 0.3 road-hours). Old-demand run; superseded by job 1899759 on the corrected demand.
- Results as **negative numbers "versus doing nothing"**. Seb's framing: say what PPO **gains**
  (road-hours avoided) and what it **costs** (£/day, £/road-hour); for PPO money-only is a cost, never
  a saving. The £5k/road-hour weighted score is an assumption, not cash.
- The 17% figure from the first flow-forecast version (its baseline was a one-day lookup).
- Skill at sites 20313 / 20605 (under 30 comparable days, noise).

## The failure to demo (track requires at least one)

Pick one; all three are real and reproducible.

1. **The ships barely beat the calendar.** Cruise model with ship data MAE 873–877 veh/day vs
   ~910 without: ~4%, daily interval includes zero (per-15-min 2% clears zero). Honest message:
   the turnaround day is mostly predictable from the calendar; the ship list adds a small, real
   refinement. Regenerate with `python demo/webtris_backtest.py` (~7 min; needs the archived
   pages, which stay out of git).
2. **The model loses where history is thin.** At M271 site 19974 the five-week year-ago median
   beats ridge (MAE 25.6 vs 33.3, 17 days). The app doesn't yet fall back to the rule there; say
   so, or build that fallback before 11:00.
3. **Holidays forecast too low.** 08:30 Christmas Day 2026 at M3 J14 forecasts 0 vehicles (range
   0–47); past Christmas Days had 64–77. Linear model stacks holiday effects below zero and the
   code clips at 0. `python -m sotonship26.flow_forecast --sites 20025 --forecast 2026-12-24
   2026-12-28`, then read `runs/flow_forecast/20025.csv`. Fix to try: fit on log flow.

## Responsibility points (judging: 15%)

- Every source has a date and licence in the README. VTS data is fetched live, never committed
  (© ABP, no redistribution). Only aggregates are published.
- The everyday forecast is backtested on data the model could not have seen: each refit uses only
  counts published ~105 days before the forecast day; conformal calibration respects that lag.
- We report where the model loses, with the sample size next to every score.
- School-holiday dates come from Southampton City Council term calendars (maintained schools);
  academies and INSET days differ, which adds error on those days.
- No personal data. Bus readings are vehicle positions from a public feed, kept as aggregates.
- Human control: every action is a suggestion with an owner; nothing is applied automatically.

## README coverage (judging asks the README cover these)

- [x] Setup (`## Build the forecast page`): uv, Python 3.12, torch extras, Iridis, ROCm
- [x] Data sources (`## Data sources`): every source dated + licensed
- [x] What the AI does (`## Provenance`): per-module AI-generated log
- [x] Tests: `uv run --extra <extra> pytest` under `## Build the forecast page`
- [x] Limits: per-view synthetic/observed labels + `docs/backtest.md`
- [x] Provenance "Before the event" + "Who did it" (README `## Provenance`)
- [x] One-sentence pitch at the top of the README; limits and failure behaviour under `## Limits, and what happens when it fails`

## Freeze-day guardrails

- Every number shown says where it came from and when; synthetic labelled synthetic; cached never
  shown as live.
- No API keys or raw VTS/WebTRIS pages/CSVs in git.
- Shared files change through a PR; no direct pushes to `main`.
- After the event: revoke the Linear API key.
