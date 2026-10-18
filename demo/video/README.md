# Pitch-video overlays (Boby + Remotion)

Source for the motion-graphic overlays that sit over the team/screen footage in the
SotonShip 2026 pitch video. We record the talking (tripod + DJI Mic Mini) and the screen
capture ourselves; these overlays add the title/end cards, the stat lower-thirds, the
council quote, the human-control caption and the scale card.

**Tooling.** [Boby](https://github.com/ReyNeill/boby), a local Bun + Remotion creative
workspace driven by the `creative` CLI. Everything renders on-machine; nothing is uploaded.

## Build

```bash
bash demo/video/setup.sh     # once: clone + install Boby, link the `creative` CLI
bash demo/video/build.sh     # renders each overlay to demo/video/out/<name>.png (transparent)
```

`out/` is git-ignored, regenerate it; don't commit the renders.

> `build.sh` is written against Boby's documented CLI but has not been run end to end here.
> If a flag name has drifted, check `creative --help` and `creative skills get boby`.

## The overlays

| File(s) | What it is | Where in the cut |
|---|---|---|
| `title.*` | Title card: product + pitch line + the three names | 0:00 open |
| `quote.*` | Council's 2011 congestion quote, attributed | ~0:15 problem |
| `stat.html` + `stat-scale.params.json` | **88%** of UK cruise passengers | ~0:15 problem |
| `stat.html` + `stat-saving.params.json` | **3.1 congested road-hours/day avoided** by the learned plan (held-out) | ~1:40 AI-vs-baseline |
| `stat.html` + `stat-skill.params.json` | **+6.6%** forecast vs the planner rule | ~1:40 AI-vs-baseline |
| `stat.html` + `stat-anchor.params.json` | **£29k/yr** price anchor | ~2:20 business |
| `caption.*` | "Suggestions, an officer approves each one" chip | ~1:10 the plan |
| `scale.*` | Southampton → Dover / Portsmouth / EU ports | ~2:20 close |
| `end.*` | End card + repo URL | ~2:40 close |

`stat` is one template reused with several params files, edit a `.params.json` to re-word
or re-number without touching HTML/CSS.

## Rules these overlays keep

- **Every number carries its source and date** in the `source` line (freeze-day guardrail).
- The learned-plan stat is the **authoritative page eval** (`docs/ppo-results-aa8eae9.md` + robust
  `docs/ppo-robust-aa8eae9.md`, job 1899759 re-score; Seb's call, SOT-32). Say what the plan **gains**
  and what it **costs**, never a negative-vs-nothing number: it **avoids 3.1 congested road-hours/day**
  on held-out dates (7.4% of the 41.1/day baseline, all 7 dates, 96% of days; 95% CI 2.2–3.9) for about
  **£2,500/day** of marshal+sign time, ≈£830 per road-hour avoided, now a **cost, not a saving**
  (+£2,545, 95% +£682…+£4,451). The free ship-timing advisor **saves ~£7,100/day** and avoids 1.2
  road-hours; the £5k/road-hour weighted score is an assumption, not cash. All simulated; unit costs
  assumed. Do **not** quote the pre-aa8eae9 5.0/8.3%/£2,100/£410/£220 figures, the old −£10,724
  (`ppo-results-gpu2.md`, superseded) or the embed's −£19.6k/96%. See `SUBMISSION.md`.
- The human-control caption and the "simulated days / observed, not live" captions keep
  provenance and officer-approval on screen.

## Editing / compositing

1. Record team intro + voiceover (DJI Mic Mini, record the receiver backup track too).
2. Screen-capture `demo/page.html` at 1080p, dark theme, with the demo cruise day pre-picked.
3. Lay the PNG overlays on top per the beat sheet in [docs/pitch-playbook.md](../../docs/pitch-playbook.md) §6.
4. Keep the total **1:00–3:00**; target ~2:40.
5. Upload to YouTube, Public/Unlisted, **allow embedding**.

For moving cards (title/scale/end), add keyframes with `creative motion enter|move|exit`
(`creative skills get boby motion`) before exporting as `--format mp4`/webm instead of PNG.
