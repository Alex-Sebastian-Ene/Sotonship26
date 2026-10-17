# UI overhaul: the three Story designs we're keeping

For Keanu and Keanu's coding session. Written in Edward's session, 18 Oct 2026.

We're keeping three versions of the Story app. In all three, the "Does the AI help?" step opens on a
simple **Overview** of two visual designs: one for the learned plan (PPO) and one for the buses observed
on the day. An **Advanced view** switch brings back every statistic. This PR adds the six embedded
designs (`demo/ui_embeds/`), so the three pages can be rebuilt from the repo.

| Keep | Artifact | "Does the AI help?" design | "Buses observed" design |
|---|---|---|---|
| **Saves** | https://claude.ai/artifact/Ga6RwnzjLUSNsRmW6h9gsz | `where-ppo-saves`: the daily saving split by lever (marshals, signs, check-in, meter) | `board`: a departure board of lateness by line |
| **Verdict** | https://claude.ai/artifact/Qz4Tzdu5b8PAE2LvoUWvDN | `verdict`: a stamped answer and three dials showing the share of test days the plan came out cheaper | `clock`: an afternoon clock of lateness by hour |
| **Fleet** | https://claude.ai/artifact/FtyBUC3WJNdPcV9CCz72kD | `pictogram`: one ship per test day, marked cheaper or dearer | `stops`: flags on the busiest stops |

The artifacts are private to Ed. Ask Ed to share them from each artifact's Share menu before opening the links.

## What the Story app is

`demo/ui_variants.py` builds UI variants from the default page (`demo/page.html`) and its built data. The
`story` variant includes:
- a cute steamship landing page with sprite animations and synthesised sound;
- a step-by-step walk through the day, with a steamship marking the current step;
- the Harbour Night theme (the default) and a Steamship theme.

When given a fourth argument, `ui_variants.py` also builds a `story-<key>` page for each pairing in
`AI_PAIRS` whose two embeds exist. The embeds are shown in `srcdoc` iframes on the "Does the AI help?" step, and they follow the page theme.

The Story app is a variant, not the default page we submit. That is Seb's quiet-page call on SOT-28:
one theme, no switcher.

## Rebuild

```bash
# 1. Build the page data first (demo/out/demo_final.html). The steps, in order:
#    demo/collect_schedule.py -> demo/synthetic_demo.py -> demo/buses.py fetch -> demo/agents.py
#    -> scripts/bustimes.py export -> demo/train_ppo.py prepare/evaluate/ablation -> demo/page_extras.py
# 2. Build the variants:
uv run --no-project python demo/ui_variants.py demo/page.html demo/out/demo_final.html <out-dir> demo/ui_embeds
```

This writes `ui-story-saves.html`, `ui-story-verdict.html` and `ui-story-fleet.html`, plus the
plain `ui-focus`, `ui-story`, `ui-officer` and `ui-wall` pages. Each Story page is about 15 MB, close
to the 16 MB artifact limit.

## Where the embedded numbers come from

The six embeds are self-contained pages, with the data baked in when they were built on 17 Oct.
**They do not refresh when the page data is rebuilt.**
- **Does the AI help?** These use the PPO evaluation of run `1889084` (`demo/out/ppo.json` and the
  ablation, made 2026-10-17 20:45). The test days are the model's own simulated cruise days, not observed traffic.
  The pounds come from cost weights we set, and each design says so.
- **Buses observed** These use the `scripts/bustimes.py export` of Edward's collector: bustimes.org vehicle positions, which republish the Bus
  Open Data Service under OGL v3.0. The export holds aggregates only; no raw sightings are in git.

## To do

1. **Improve the look of the Advanced view.** At the moment it is the default page's statistics
   dropped in under the switch: the method fold, PPO in numbers and the observed-buses fold. It doesn't
   match the Overview:
   - dense tables;
   - card styles that differ from the Overview's;
   - charts that don't fully pick up the Steamship theme;
   - a long scroll on a phone.

   Restyle it to sit with the Overview:
   - the same card frame;
   - a few headline numbers first, with the detailed tables collapsed;
   - themed charts;
   - check it at phone width.
2. **Use the held-out split.** The AI designs read `summary.all` (all test days). Seb's branch
   `seb/ppo-numerics` moves the page to `summary.held_out` and adds a money-only figure beside the
   weighted cost score. On held-out days, PPO costs about £2.1k a day *more* in money, though it is cheaper on
   the weighted score. Once that branch is in, rebuild the embeds from `summary.held_out` and show both figures.
3. **Align the bus averages.** The Overview shows +9.4 min and 54% of journeys 5+ min late; the
   Advanced view shows +8.1 min and 52%. They weight journeys differently. Pick one, and switch to Seb's
   robust median once `seb/bus-lateness-robust` is merged and the export is re-run on Edward's laptop,
   where the raw sightings are.
4. **Regenerate the embeds when the data changes.** Right now that's a manual step. Ideally,
   `ui_variants.py` would fill the embeds from `demo/out/ppo.json` and `bus_lateness.json` at build time.
