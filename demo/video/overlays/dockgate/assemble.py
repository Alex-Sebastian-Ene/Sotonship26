#!/usr/bin/env python3
"""Assemble the three Dock Gate 4 overlay deliverables from rendered frames.

Reads demo/video/out/frames/frame_%04d.png (see render_frames.py) and writes:
  dockgate.webm  VP9 with real alpha (yuva420p)        -- primary
  dockgate.mov   ProRes 4444 (yuva444p10le) with alpha  -- editor-friendly
  dockgate.mp4   H.264 flattened on #F4F6F8             -- opaque preview
All into demo/video/out/ (git-ignored).
"""

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "out"))
FRAMES = os.path.join(OUT, "frames")
pat = os.path.join(FRAMES, "frame_%04d.png")

n = len(glob.glob(os.path.join(FRAMES, "frame_*.png")))
print("frames found:", n)
if n < 240:
    print("ERROR: expected 240 frames; run render_frames.py first")
    sys.exit(1)


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout.decode()[-800:])
    if r.returncode != 0:
        print("FAILED rc", r.returncode)
        sys.exit(1)


webm = os.path.join(OUT, "dockgate.webm")
mov = os.path.join(OUT, "dockgate.mov")
mp4 = os.path.join(OUT, "dockgate.mp4")

# 1) VP9 WebM with real alpha
run(
    [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-i",
        pat,
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-b:v",
        "0",
        "-crf",
        "20",
        "-auto-alt-ref",
        "0",
        "-metadata:s:v:0",
        "alpha_mode=1",
        webm,
    ]
)

# 2) ProRes 4444 with alpha
run(
    [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-i",
        pat,
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "-alpha_bits",
        "16",
        mov,
    ]
)

# 3) H.264 flattened on #F4F6F8 (opaque preview)
run(
    [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-i",
        pat,
        "-filter_complex",
        "color=c=0xF4F6F8:s=1920x1080[bg];[bg][0:v]overlay=shortest=1,format=yuv420p[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-r",
        "30",
        "-movflags",
        "+faststart",
        mp4,
    ]
)

for f in (webm, mov, mp4):
    print(f, os.path.getsize(f) if os.path.exists(f) else "MISSING", "bytes")
