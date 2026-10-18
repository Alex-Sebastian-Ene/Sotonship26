# Pitch playbook, SotonShip 2026 (Southampton City track)

Team-facing. How we demo and pitch the cruise-day traffic forecast, who to whom, and the
video plan. Hard lock **Sun 18 Oct 13:00** (code freeze 11:00, submit by 12:30).

A styled single-page version of this is published as a web page; this markdown copy
is the shareable source of truth (everyone with the repo can read it).

## 1. What we built, in one breath

> We tell Southampton City Council's traffic officers, a week ahead and with honest odds,
> which cruise days and hours need marshals at the dock gates, a sign message, or a hold on
> roadworks, from the port's published ship schedule and public traffic data.

Pitch sentence (track format): *We help council traffic officers decide where to put
marshals, signs and roadworks holds on cruise days around the Southampton docks, using a
probabilistic traffic forecast and a learned mitigation policy built on public data.*

**The three screens**
- **Calendar**, six weeks of ship calls, each day coloured by how much the ships add to
  congestion; roadworks and Saints home games marked.
- **Day view**, headline congested road-hours + likely range + worst moment; P(road >85%
  full) per 15 min; a live map of one simulated day with real bus routes.
- **What to do**, suggested actions (marshals at a named gate, a sign message, move a
  permit), each with a time window and an owner. The learned policy's plan sits beside them.
  **Every action needs an officer's approval.**

**Why it's not just a dashboard:** it leads to a *decision*, it's *probabilistic* (10/50/90%),
it *refuses* dates beyond the schedule and *widens the range* for ships with no passenger
figure, and a *trust panel* shows every number's source, collection time and published-vs-modelled.

## 2. Who it's for & why it matters

| Judges ask | Our answer (local evidence) |
|---|---|
| Problem real in Southampton? | 2.69M cruise passengers in 2024, **88% of the UK total** (DfT). Council's transport manager (2011): cruise growth "causes significant congestion, especially at weekends, by Dock Gate 4", worse when ships clash with a football match. |
| Why now / not just react? | The story we open on: the **2010 Dock Gate 4 backup** (cited by the council's transport manager in 2011), on 8 Nov 2010 four liners "backed traffic onto the public road… we were unable to clear through our traffic control computer". A dock road at its limit **snaps into lockup**; once the queue forms it's too late to clear. The levers (hold roadworks, book marshals, set signs) are pulled **days ahead**, exactly where a week-ahead forecast + the learned plan (PPO) kick in. |
| Who owns & pays? | The council, under its network-management duty (Traffic Management Act 2004 s.16). Second buyer: bus operators whose routes cross the dock roads. |
| Second city? | Engine generalises to any scheduled road load, ferry/freight peaks at **Dover, Portsmouth**, EU turnaround ports, stadium days. Feeds (BODS, WebTRIS, DfT counts) are England-national. |

## 3. Judging split, and where our points come from

VC-for-a-Day on Sunday: audience + judges invest virtual money; top 3 per track → final panel.
Pitch the **problem + business** first, prove the AI second.

| Criterion | Weight | What wins it for us |
|---|---|---|
| **Working product** | **25%** | End-to-end on a real day: pick a cruise day → forecast → suggested plan; live map + trust panel. **Demo a failure** (§5). |
| Problem & user | 20% | Council's own words + 88%-of-UK scale; one named user (traffic officers). §2 |
| AI at the core | 20% | Forecast beats a sensible baseline (6.6% at M3 J14); learned policy avoids ~3 congested road-hours/day, more than the advisor (1.2) or the rule (none). Product can't do its job without it. |
| Business & scale | 20% | Buyer + price anchor (Devon CC £29k/yr; the £40M road fix "prohibitive"); ~18 core-hours/rebuild, static page, no data fees; Dover/Portsmouth path. |
| Responsibility & trust | 15% | Human-in-the-loop (suggestions only), full provenance, honest losses, no personal data, ABP data never redistributed. |

## 4. Three ways to demo it

- **To the council (buyer):** lead with the decision and the money. "Two ships in, Saints at
  home. Here's the day, and three actions your officer can approve: marshals at Dock Gate 4
  12:00–15:00, a sign on Platform Road, move the Portswood permit. Every one is a suggestion
  with an owner, nothing happens automatically. Public data, no new sensors, runs for pennies,
  sits under your s.16 duty."
- **To SotonHack judges:** hit the five criteria in weight order, 30s problem (council quote +
  88%), 30s product live, 30s AI-vs-baseline (one honest number), 30s business (who pays +
  second city), 20s responsibility + the failure.
- **To technical people:** Monte-Carlo traffic model on the real OSM network, 15-min bins with
  queue carry-over; cruise effect learned from 2.5 years of WebTRIS M271 counts matched to
  archived schedules; everyday ridge refit on counts published by forecast time (105-day lag)
  with conformal intervals; PPO decision policy trained on the simulator (Stable-Baselines3);
  SUMO micro-sim cross-check; and we report where the model *loses*.

## 5. The failure to demo (required)

The track demands at least one failure on screen. Pick one, all real, all reproducible.

- **Strongest and honest:** "the ships barely beat the calendar." The cruise model with ship
  data scores MAE 877 veh/day vs 910 without, a real but small ~4% gain whose daily interval
  includes zero (per-15-min it's 2% and clears zero). Message: the turnaround day is mostly
  predictable from the calendar; the ship list is a small, real refinement, and we say so.
- **Thin history:** at M271 site 19974 the five-week year-ago median *beats* our model (MAE 25.6
  vs 33.3, 17 days); the app doesn't yet fall back to the rule there, we flag it.
- **Out of coverage:** dates beyond the published schedule get a refusal, not a guess.

## 6. Video plan (1:00–3:00, YouTube, embedding on)

Kit: tripod + DJI Mic Mini. Structure: team intro to camera, then app functionality overlaid as
we talk. Target ~2:40. Must show the **real product working**.

| Time | What | Overlay |
|---|---|---|
| 0:00 | Team intro to camera (all three) | Title card + pitch line |
| 0:15 | The problem, the 2010 Dock Gate 4 backup | Dock Gate 4 pin + **88%** + the backup quote lower-third ("backed traffic onto the public road", cited 2011); caption "a road at its limit snaps into lockup, and then it's too late to clear" |
| 0:40 | Product live, pick a real two-ship Saturday → day view | Screen capture of `demo/page.html`; zoom headline + P(>85%) heatmap |
| 1:10 | The map + the plan | Highlight the three action cards; caption "suggestions, officer approves" |
| 1:40 | AI vs baseline, honest | **+6.6%** forecast skill, then the plan **avoids 3.1 congested road-hours/day** for about **£2,500/day** of marshal+sign time (≈£830 per road-hour avoided; a cost, not a saving), while the free ship-timing advisor **saves ~£7,100/day**, all labelled "simulated" |
| 2:05 | Trust + failure | Trust-panel close-up; the refusal state |
| 2:20 | Business + close, back on camera | **£29k/yr** anchor, Dover/Portsmouth scale card, end card + repo |

**The honest payoff line (say it as written, at 1:40).** In pure money the learned plan is a
**cost**, +£2,545/day (95% +£682…+£4,451), and we say so on screen. What the ~£2,500/day of
marshals and signs buys is insurance against a **2010-style Dock Gate 4 lockup**: price a congested
road-hour at **£5,000** (an assumption the council sets, a gridlock-risk weight, not cash), and the
plan's **3.1 avoided congested road-hours/day** are worth about **£12,800/day** net of the spend, a
weighted score of **−£12,777/day**, roughly **5×** the money cost. That "pays off" claim is
weighted-only; in cash the plan does not save money. The one true cash saver stays the free
**ship-timing advisor, ~£7,100/day** (95% £3,400…£11,100), which edges PPO on the weighted score too
(−£13,058). All **simulated**, unit costs assumed.

**Remotion / Boby fit.** We record the talking + screen capture; Boby (Bun + Remotion, driven by
its `creative` CLI) generates the overlays, title/end cards, lower-thirds (88%, council quote),
the caption, the scale card, as transparent PNGs/clips to drop over the footage in CapCut /
Premiere / DaVinci. The six live embeds animate themselves, so screen-capture them directly.
Overlay source + build scripts: [`demo/video/`](../demo/video/README.md).

**Gear notes.** One DJI TX per speaker (or pass one), record the receiver backup track; peaks
around −12 dB. Lock the tripod, landscape 1080p/4K at 25 or 30 fps (match the screen capture).
Screen-capture `demo/page.html` dark theme, notifications off, the demo day pre-picked.

## 7. Numbers cheat-sheet (cite the source on screen)

| Claim | Number | Source / sample |
|---|---|---|
| Everyday forecast vs planner rule (M3 J14) | **+6.6%** | 90% CI 0.5–12%, 355 held-out days; 84% in 80% band (`notes/flow-forecast.md`) |
| Cruise effect on M271 (backtest) | **877** | MAE veh/day vs 1,233 (last-day baseline), 1,353 (no effect); 179 days; 87% in band (`docs/backtest.md`) |
| Ship list's own contribution | **~2%** | per 15 min, clears zero; per-day 4% does not, say "per 15 min" |
| **PPO, gain** | **avoids 3.1 road-hours/day** | 7.4% of the 41.1/day baseline, all 7 held-out dates, 96% of days, simulated, 95% CI 2.2–3.9 (`docs/ppo-results-aa8eae9.md`). Total delay unchanged (−6, −136…+124). |
| **PPO, cost** | **~£2,500/day** (marshal+sign) | ≈£830 per road-hour avoided; money alone a **cost** now (+£2,545, 95% +£682…+£4,451). Weighted −£12,777/day; £5k/road-hour = assumption, not cash. |
| **Baselines** | advisor saves **~£7,100/day**, 1.2 hrs; rule +0.4 hrs @ ~£25k | same eval; advisor the no-cost money lever (edges PPO on weighted score, −£13,058 vs −£12,777), PPO buys most congestion cut. |
| Scale | **88%** | of UK cruise passengers through Southampton (2024, DfT) |
| Price anchor | **£29k/yr** | Devon CC traffic-data service (Find a Tender, Nov 2025); £40M road fix "prohibitive" |
| Run cost | **~18** | core-hours/rebuild; static page; no data fees |

> **PPO number, settled (Seb's call, SOT-32, 2026-10-18).** Pin to **`docs/ppo-results-aa8eae9.md`** +
> robust `docs/ppo-robust-aa8eae9.md` (job 1899759, re-scored on the corrected demand). **Don't present
> results as negative numbers "versus doing nothing"**, say what each policy gains and costs: on held-out
> dates the plan **avoids 3.1 congested road-hours/day** (7.4% of the 41.1/day baseline, all 7 dates, 96%
> of days; 95% CI 2.2–3.9; total delay unchanged), for about **£2,500/day** of marshal and sign time,
> about **£830 per congested road-hour avoided**. In money alone that is now a **cost** (+£2,545, 95%
> +£682…+£4,451), not a saving. The free **ship-timing advisor saves ~£7,100/day** (95% £3,400…£11,100)
> and avoids **1.2 road-hours**; the 85%-rule doesn't help (congestion +0.4, ~£25,000/day). On the
> weighted score the advisor (−£13,058) edges PPO (−£12,777); say so if asked. All **simulated**; unit
> costs assumed. **Do not quote** the pre-aa8eae9 5.0/8.3%/£2,100/£410/£220 figures, the old −£10,724
> (`ppo-results-gpu2.md`, superseded) or the embed's −£19.6k/96%.

## 8. Pre-record / pre-lock checklist

- [ ] Pick the demo cruise day (two ships + ideally a Saints clash); rehearse the click path.
- [ ] Record team intro + VO; screen-capture `demo/page.html` (dark theme).
- [ ] Build overlays (`demo/video/`); keep total 1:00–3:00.
- [ ] Upload to YouTube, Public/Unlisted + **allow embedding**; copy link + exact m:ss.
- [ ] Paste the 150-word summary (README → "In a paragraph") into the form.
- [ ] Fill README provenance "Existed before the event" + "Who helped".
- [ ] Pick pitch format (full video vs video + live). Save submission before 13:00.
- [ ] After the event: revoke the Linear API key.
