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
| `stat.html` + `stat-saving.params.json` | **5.0 congested road-hours/day avoided** by the learned plan (held-out) | ~1:40 AI-vs-baseline |
| `stat.html` + `stat-skill.params.json` | **+6.6%** forecast vs the planner rule | ~1:40 AI-vs-baseline |
| `stat.html` + `stat-anchor.params.json` | **£29k/yr** price anchor | ~2:20 business |
| `caption.*` | "Suggestions, an officer approves each one" chip | ~1:10 the plan |
| `scale.*` | Southampton → Dover / Portsmouth / EU ports | ~2:20 close |
| `end.*` | End card + repo URL | ~2:40 close |

`stat` is one template reused with several params files, edit a `.params.json` to re-word
or re-number without touching HTML/CSS.

## Rules these overlays keep

- **Every number carries its source and date** in the `source` line (freeze-day guardrail).
- The learned-plan stat is the **authoritative page eval** (`docs/ppo-results.md`; Seb's call, SOT-32).
  Say what the plan **gains** and what it **costs**, never a negative-vs-nothing number: it **avoids
  5.0 congested road-hours/day** on held-out dates (8.3% fewer, all 7 dates; 95% CI −5.28…−4.73) for
  about **£2,100/day** of marshal+sign time, ≈£410 per road-hour avoided, **not a money saving**
  (date-resampled −£330…+£4,180). The £5k/road-hour weighted score is an assumption, not cash. All
  simulated; marshals' +25% gate capacity assumed. Do **not** quote the old −£10,724
  (`ppo-results-gpu2.md`, superseded) or the embed's −£19.6k/96%. When job 1899759 lands (~08:15),
  swap to `docs/ppo-results-aa8eae9.md`. See `SUBMISSION.md`.
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
