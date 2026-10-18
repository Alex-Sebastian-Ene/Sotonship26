#!/usr/bin/env python3
"""Render the 240 transparent PNG frames of the Dock Gate 4 overlay.

Headless Chromium per-frame screenshot. dockgate.html is deterministic:
?f=N seeks frame N (0..239). 1920x1080, transparent background.
Frames land in demo/video/out/frames/ (git-ignored).
"""
import subprocess, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = "file://" + os.path.join(HERE, "dockgate.html")
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "out"))
FRAMES = os.path.join(OUT, "frames")
PROFILE = os.path.join(OUT, "shot-profile")
os.makedirs(FRAMES, exist_ok=True)

CHROME = os.environ.get("CHROME_BIN", "chromium-browser")
TOTAL = 240
t0 = time.time()
for n in range(TOTAL):
    dst = os.path.join(FRAMES, "frame_%04d.png" % n)
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", "--force-device-scale-factor=1",
        "--default-background-color=00000000", "--window-size=1920,1080",
        "--virtual-time-budget=2200", "--user-data-dir=" + PROFILE,
        "--screenshot=" + dst, HTML + "?f=%d" % n,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    if not os.path.exists(dst):
        print("FAILED frame", n); sys.exit(1)
    if n % 20 == 0:
        print("frame %d/%d  %.1fs" % (n, TOTAL, time.time() - t0), flush=True)
print("DONE %d frames -> %s  (%.1fs)" % (TOTAL, FRAMES, time.time() - t0))
