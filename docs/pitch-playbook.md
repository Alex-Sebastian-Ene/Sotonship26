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
| Why now / not just react? | 8 Nov 2010: four liners backed traffic onto the public road "we were unable to clear through our traffic control computer". Once the queue forms it's too late, the levers (hold roadworks, book marshals, set signs) are pulled days ahead. |
| Who owns & pays? | The council, under its network-management duty (Traffic Management Act 2004 s.16). Second buyer: bus operators whose routes cross the dock roads. |
| Second city? | Engine generalises to any scheduled road load, ferry/freight peaks at **Dover, Portsmouth**, EU turnaround ports, stadium days. Feeds (BODS, WebTRIS, DfT counts) are England-national. |

## 3. Judging split, and where our points come from

VC-for-a-Day on Sunday: audience + judges invest virtual money; top 3 per track → final panel.
Pitch the **problem + business** first, prove the AI second.

| Criterion | Weight | What wins it for us |
|---|---|---|
| **Working product** | **25%** | End-to-end on a real day: pick a cruise day → forecast → suggested plan; live map + trust panel. **Demo a failure** (§5). |
| Problem & user | 20% | Council's own words + 88%-of-UK scale; one named user (traffic officers). §2 |
| AI at the core | 20% | Forecast beats a sensible baseline (6.6% at M3 J14); learned policy beats doing-nothing / rule / advisor. Product can't do its job without it. |
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
| 0:15 | The problem | Dock Gate 4 pin + **88%** + the 2011 quote lower-third |
| 0:40 | Product live, pick a real two-ship Saturday → day view | Screen capture of `demo/page.html`; zoom headline + P(>85%) heatmap |
| 1:10 | The map + the plan | Highlight the three action cards; caption "suggestions, officer approves" |
| 1:40 | AI vs baseline, honest | **+6.6%** forecast skill, then **−5.0 congested road-hours/day** from the plan, and say it **costs** ~£2,069/day (≈£413 per road-hour avoided), labelled "simulated" |
| 2:05 | Trust + failure | Trust-panel close-up; the refusal state |
| 2:20 | Business + close, back on camera | **£29k/yr** anchor, Dover/Portsmouth scale card, end card + repo |

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
| **Learned plan (PPO), congestion** | **−5.0 road-hours/day** | held-out, simulated, −8.3%, 95% CI −5.28…−4.73 (`docs/ppo-results.md`, run C re-scored 32fe052). Delay change not significant. |
| **Learned plan (PPO), cost** | **+£2,069/day (a cost)** | money-only: marshals ~£1,708 + signs ~£804 vs £495 less delay ≈ £413 per road-hour avoided. Weighted score −£22,976 (£5k/road-hour = risk weight, not cash). |
| Scale | **88%** | of UK cruise passengers through Southampton (2024, DfT) |
| Price anchor | **£29k/yr** | Devon CC traffic-data service (Find a Tender, Nov 2025); £40M road fix "prohibitive" |
| Run cost | **~18** | core-hours/rebuild; static page; no data fees |

> **PPO number, settled (Seb's call, SOT-28, 2026-10-18).** Pin to **`docs/ppo-results.md`** (run C
> re-scored at 32fe052, what the page shows). Lead with the **robust** one: PPO cuts **5.0 congested
> road-hours/day** on held-out dates (−8.3%, 95% CI −5.28…−4.73; delay change not significant). State
> the **cost** honestly: money-only PPO *costs* **+£2,069/day** (marshals + signs), about **£413 per
> congested road-hour avoided**, worth it if the council values a road-hour above ~£410. The £5k/road-hour
> weighted score (−£22,976/day) is a risk valuation, **not cash**; never call the £ a "saving". The
> ship-timing advisor is the no-cost lever (−£223/day, −0.34 road-hours). All **simulated**; marshals'
> +25% gate capacity assumed. Switch to `docs/ppo-results-aa8eae9.md` **only if**
> `seb/demand-census-motorways` merges before the freeze (re-score = Iridis job 1899339).
> **Do not quote** the old −£10,724 (`ppo-results-gpu2.md`, superseded) or the embed's −£19.6k/96%.

## 8. Pre-record / pre-lock checklist

- [ ] Pick the demo cruise day (two ships + ideally a Saints clash); rehearse the click path.
- [ ] Record team intro + VO; screen-capture `demo/page.html` (dark theme).
- [ ] Build overlays (`demo/video/`); keep total 1:00–3:00.
- [ ] Upload to YouTube, Public/Unlisted + **allow embedding**; copy link + exact m:ss.
- [ ] Paste the 150-word summary (README → "In a paragraph") into the form.
- [ ] Fill README provenance "Existed before the event" + "Who helped".
- [ ] Pick pitch format (full video vs video + live). Save submission before 13:00.
- [ ] After the event: revoke the Linear API key.
