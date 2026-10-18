# Dock Gate 4-2010 traffic back-up overlay

Animated, transparent motion-graphic overlay illustrating the real
8 November 2010 Dock Gate 4 traffic back-up in Southampton, for the
SotonShip 2026 pitch video (drops over camera footage at the "problem" beat).

Faithful illustration of a historical incident, **not live data**.

## The incident (sourced)

On 8 Nov 2010 four cruise liners (three among the world's biggest) were in
port. Dock traffic backed up onto the public road and could not be cleared
through the port's traffic-control computer. Dock Gate 4 and Dock Gate 10 are
the pinch points.

> Source: Southampton City Council, Full Council minutes, 17 Nov 2010, p.44–45.

The on-screen source line and quote wording are exact and must not be altered.

## Files

- `dockgate.html`, self-contained render source (geometry + fonts embedded).
  Deterministic: `?f=N` seeks frame N (0–239). 240 frames @ 30fps = 8.0s,
  1920×1080, transparent background.
- `dockgate-geo.json`, real map geometry extracted from the live demo page
  (road segments, area layers, Dock Gate 4 at grid (9300, 8825), and the
  queue spine traced westward along Platform Road / Town Quay).
  Map data © OpenStreetMap contributors (ODbL).
- `render_frames.py`, renders the 240 transparent PNG frames via headless
  Chromium per-frame screenshots.
- `assemble.py`, assembles the three deliverables with ffmpeg.

## Render pipeline

Run from this directory (`demo/video/overlays/dockgate/`):

```
python3 render_frames.py     # -> demo/video/out/frames/frame_0000.png ..
python3 assemble.py          # -> demo/video/out/dockgate.{webm,mov,mp4}
```

Needs `chromium-browser` (override with `CHROME_BIN`) and `ffmpeg`.

Outputs (in `demo/video/out/`, git-ignored):

- `dockgate.webm`, VP9 with real alpha (yuva420p). **Primary deliverable.**
- `dockgate.mov`, ProRes 4444 (yuva444p10le), editor-friendly alpha.
- `dockgate.mp4`, H.264 flattened on #F4F6F8 (opaque preview).
