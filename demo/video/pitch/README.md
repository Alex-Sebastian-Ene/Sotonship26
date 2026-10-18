# Pitch video

The 2:57 pitch video (1920×1080, 25 fps). It runs from the problem to the idea to the product,
with a real-time demo of the live page in the middle, then the AI against its baselines, the business
case, the data and a second city. **Download:** the `pitch-video` release on GitHub. The MP4 is kept
out of git.

> **The submitted video is narrated by Keanu.** The synthetic narration below belongs to this draft only.
> The team may reuse some of its animated scenes.

## Structure

| Scene | Content | Sources shown on screen |
| --- | --- | --- |
| Hook | 8 Nov 2010: four liners, traffic backed onto the public highway | SCC Full Council minutes, 17 Nov 2010 |
| Problem | 88% of UK cruise passengers; Dock Gate 4 congestion quote; Queen Anne 4½ h late, 11 May 2026 | DfT sea passenger statistics; SCC Scrutiny Panel C 2011; Cruise Hive |
| Cost | £15.56 per car-hour and £102.91 per lorry-hour; an illustrative 1,000 cars × 15 min ≈ £3,890; £1.9–2.5 m per call | DfT TAG data book; ABP, Dec 2025 |
| User | "Imagine you're a traffic officer at Southampton City Council…" | |
| Idea | The track-format sentence, with who, what, where and how highlighted | |
| Demo | Calendar → Sat 24 Oct → the map → approve/reject actions → Does the AI help → the outside-coverage refusal | The live page |
| AI | Forecast MAE 877 against 1,233 (last comparable day); the learned plan avoids 3.1 road-hours a day for about £2,500 | docs/backtest.md; docs/ppo-results-aa8eae9.md |
| Business | The council pays (TMA 2004 s.16); data free; price under £30k a year (Devon £29k); the advisor's ~£7,100 a day (simulated); the £40 m road | notes/local-evidence.md; docs/ppo-results-aa8eae9.md |
| Data | Eight sources with their licences; no personal data; no non-public council data | README "Data sources" |
| Next city | Dover, Portsmouth, stadiums, EU ports; the limits | |
| Close | The QR code and sotonyard.keanuc.net | |

The narration is in `vo.json`. Every figure comes from the repository's docs and notes.

## Rebuild

Needs Node, Chrome, ffmpeg and uv. Run from this folder:

```bash
npm install                                                  # puppeteer-core only; it drives the installed Chrome
curl -s -o live.html https://sotonyard.keanuc.net/           # the built page; it embeds ABP data, so it is never committed
uv run --no-project --with edge-tts python tts.py +16%       # narration per scene -> vo/
uv run --no-project python trim.py                           # trim silence, measure lengths -> vot/
node capture.js                                              # real-time capture of the live page -> frames/, capture.json
uv run --no-project python timeline.py                       # scene times from the narration -> timeline.json
node render.js                                               # every frame -> out/ (about 5 minutes)
uv run --no-project python mix.py                            # narration mix + H.264 encode -> sotonship26-pitch.mp4
```

Set `CHROME` to the Chrome executable if it is not at the default Windows path. `node render.js 10,60`
renders stills at those seconds to `stills/`, and `node render.js "" 168` re-renders from 168 s onwards.

## Provenance

- **Narration:** a synthetic voice (Microsoft Edge neural voice `en-GB-RyanNeural`, via the `edge-tts`
  package). The team can record over it from `vo.json`.
- **Code:** written with an AI coding assistant in Edward's session, 18 Oct 2026, as were the scene designs and the script.
- **Demo footage:** captured from the team's own page.
- **QR code:** generated locally with the `qrcode` package.
