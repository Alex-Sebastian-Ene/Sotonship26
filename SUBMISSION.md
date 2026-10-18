# Submission checklist, SotonShip 2026 (Southampton City track)

**Hard lock: Sun 18 Oct 2026, 13:00.** Code freeze 11:00, submit by 12:30.
Incomplete submissions at the lock are **not shown in Stage 1**. Save early, update until lock.

## Form fields

| # | Field | Required | Status | Owner | Note |
|---|-------|----------|--------|-------|------|
| 1 | GitHub repository (public) | yes | ✅ done | - | `https://github.com/Alex-Sebastian-Ene/Sotonship26` (public) |
| 2 | Project summary (≤150 words) | yes | ✅ drafted | Keanu | In `README.md` → "In a paragraph" (148 words). Paste into form, edit to taste. |
| 3 | Pitch video, YouTube link | yes | ❌ **BLOCKER** | team | Public or Unlisted, embedding allowed, must show the real product working. |
| 4 | Video length (m:ss) | yes | ❌ depends on 3 | team | Must be **1:00–3:00**. |
| 5 | Pitch format | yes | ❌ decide | team | Full 3-min video, **or** shorter video + live pitch for the rest of the slot. |
| 6 | Live link / run instructions | optional | ⚠️ partial | - | README has run steps; no hosted live link. See below. |

## What's left to lock in (ordered)

1. **Record the pitch video (BLOCKER).** 1:00–3:00. Must show the real product (`demo/page.html`:
   calendar → day view → what-if) actually working. Suggested beat sheet:
   - 0:00 the problem (council decides marshals/signs/roadworks per cruise day, on gut feel).
   - 0:20 the forecast page: pick a cruise day, show P(congestion) heatmap + 10/50/90 range.
   - 0:50 the learned plan pays its way, the overview views (verdict dials, where-it-saves).
   - 1:30 buses observed on the day (bustimes.org), honest "observed, not live" labelling.
   - 2:10 scale + close (any UK port city with open feeds).
2. **Upload to YouTube**, set Public/Unlisted + allow embedding, grab link + exact length.
3. **Pick pitch format** (full video vs video+live) and fill the field.
4. **Paste the 150-word summary** from README into the form.
5. **Save the submission** (can keep updating until 13:00).

## Optional, live link

The overview page is a single self-contained file (`demo/ui_embeds/` merged). Options for a judge-openable
live link without a server:
- GitHub Pages on the repo (static; `demo/page.html` + embeds), **or**
- leave it out (field is optional) and rely on README run instructions.

Decide only if time permits after the blockers.

## README coverage (judging asks the README cover these)

- [x] Setup, `## Setup` (uv, Python 3.12, per-machine torch extras, Iridis, ROCm)
- [x] Data sources, `## Data sources` (every source dated + licensed; TODOs flagged)
- [x] What the AI does, `## Provenance` (per-module AI-generated log)
- [x] Tests, `uv run --extra <extra> pytest` under `## Running`
- [x] Limits, "Limits of the cruise backtest" + per-view synthetic/observed labels

## Freeze-day guardrails

- Every number shown says where it came from and when; synthetic labelled synthetic; cached never shown as live.
- No API keys or raw VTS/WebTRIS pages/CSVs in git.
- Shared files change through a PR; no direct pushes to `main`.
