"""Sprite sheets for the Story app, drawn from the generated icons in demo/assets/.

Each sheet is one row of equal frames (demo/assets/sprites/<name>.webp) and sprites.json records the
frame count, frame size and loop time that demo/ui_variants.py turns into CSS steps() animations.

    python demo/sprites.py
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ASSETS = Path(__file__).with_name("assets")
OUT = ASSETS / "sprites"
NAVY = (29, 43, 69, 255)
CREAM = (255, 248, 236, 255)


def load(name):
    """Icon with the JPEG halo cleaned off: near-white pixels touching transparency become transparent."""
    a = np.array(Image.open(ASSETS / f"{name}.webp").convert("RGBA"))
    for _ in range(2):
        clear = a[..., 3] < 40
        edge = np.zeros_like(clear)
        edge[1:] |= clear[:-1]; edge[:-1] |= clear[1:]; edge[:, 1:] |= clear[:, :-1]; edge[:, :-1] |= clear[:, 1:]
        a[edge & (a[..., :3].min(axis=2) > 205), 3] = 0
    return Image.fromarray(a)


def pad(im, l=0, t=0, r=0, b=0):
    out = Image.new("RGBA", (im.width + l + r, im.height + t + b))
    out.alpha_composite(im, (l, t))
    return out


def sample(a, sx, sy):
    """Bilinear sample of RGBA array a at float coordinates, transparent outside."""
    h, w = a.shape[:2]
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    out = np.zeros(sx.shape + (4,))
    for dx, dy, wt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xx, yy = x0 + dx, y0 + dy
        ok = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
        px = np.zeros(sx.shape + (4,))
        px[ok] = a[yy[ok], xx[ok]]
        out += px * wt
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def gull(n=8):
    """Wings fold towards the shoulders and open again; head, body and tail stay put."""
    im = pad(load("gull"), t=4, b=4)
    a = np.array(im).astype(float)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    # left wing tip (left of the beak) and right wing fold; the part of the left wing above the head
    # tucks out of sight behind it as the wings close
    wl = np.clip((36 - xx) / 8, 0, 1)
    wr = np.clip((xx - 104) / 18, 0, 1)
    band = np.clip((42 - yy) / 8, 0, 1) * np.clip((86 - xx) / 10, 0, 1) * (xx >= 30)
    pivot = np.where(xx < 100, 84.0, 99.0)
    weight = np.maximum(wl, wr) * (yy < pivot)
    frames = []
    for i in range(n):
        s = 0.6 + 0.4 * math.cos(2 * math.pi * i / n)          # 1 = wings up, 0.2 = folded
        k = 1 - weight * (1 - s)
        fr = np.array(sample(a, xx, pivot + (yy - pivot) / k)).astype(float)
        fr[..., 3] *= 1 - band * (1 - s) / 0.8
        frames.append(Image.fromarray(fr.astype(np.uint8)))
    return frames, 0.7


def rotate_frames(name, angles, centre=None, padding=0):
    im = pad(load(name), padding, padding, padding, padding)
    c = centre(im) if centre else None
    return [im.rotate(-ang, resample=Image.BICUBIC, center=c) for ang in angles]


def lighthouse(n=16):
    """The drawn beam is cut off and replaced by one that sweeps round the lantern."""
    base = load("lighthouse")
    a = np.array(base)
    a[:57, 77:] = 0                                              # the original beam
    base = Image.fromarray(a)
    L = 96
    base = pad(base, L, 0, L, 0)
    cx, cy = L + 62, 33
    frames = []
    for i in range(n):
        th = 2 * math.pi * i / n
        c, sn = math.cos(th), math.sin(th)
        fr = Image.new("RGBA", base.size)
        d = ImageDraw.Draw(fr)
        if abs(c) > 0.12:
            length, half = 92 * abs(c), 7 + 13 * abs(c)
            x2 = cx + length * (1 if c > 0 else -1)
            d.polygon([(cx, cy - 6), (x2, cy - half), (x2, cy + half), (cx, cy + 6)], fill=(255, 214, 102, 215), outline=NAVY, width=2)
        if sn > 0.5:                                             # facing us: the lamp flares
            r = 10 + 12 * (sn - 0.5) * 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 236, 160, int(200 * (sn - 0.5) * 2)))
        fr.alpha_composite(base)
        if sn > 0.5:
            r = 7 * (sn - 0.5) * 2 + 4
            ImageDraw.Draw(fr).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 245, 200, 255))
        frames.append(fr)
    return frames, 3.2


def puff(d, x, y, r, alpha=255):
    d.ellipse([x - r, y - r, x + r, y + r], fill=CREAM[:3] + (alpha,), outline=NAVY[:3] + (alpha,), width=2)


def ship(n=12):
    """Rocks on the swell; fresh puffs rise from both funnels and drift astern."""
    a = np.array(load("ship"))
    a[:27, 60:160] = 0                                           # the drawn smoke above the funnels
    base = pad(Image.fromarray(a), 8, 46, 8, 6)
    funnels = [(8 + 80, 46 + 28), (8 + 123, 46 + 28)]
    frames = []
    for i in range(n):
        t = i / n
        fr = Image.new("RGBA", base.size)
        d = ImageDraw.Draw(fr)
        for fx, fy in funnels:
            for j in range(3):
                u = (t + j / 3 + (0.15 if fx > 100 else 0)) % 1
                puff(d, fx - 30 * u, fy - 6 - 44 * u, 5 + 9 * u, int(255 * min(1, (1 - u) * 2.2)))
        body = base.rotate(1.6 * math.sin(2 * math.pi * t), resample=Image.BICUBIC, center=(base.width / 2, base.height - 10),
                           translate=(0, round(2 * math.sin(2 * math.pi * t + 1))))
        fr.alpha_composite(body)
        frames.append(fr)
    return frames, 2.4


def spray(n=10, w=150, h=96):
    """Salt spray: droplets thrown up in arcs from the bow wave, staggered so the loop never restarts."""
    rnd = random.Random(7)
    drops = [(rnd.random(), rnd.uniform(-0.9, 0.5), rnd.uniform(0.55, 1.0), rnd.uniform(2.2, 4.8), rnd.random() < 0.3) for _ in range(26)]
    frames = []
    for i in range(n):
        t = i / n
        fr = Image.new("RGBA", (w, h))
        d = ImageDraw.Draw(fr)
        for ph, vx, vy, r, teal in drops:
            u = (t + ph) % 1
            x = w * 0.5 + vx * 70 * u
            y = h - 6 - (vy * 4 * 80 * u * (1 - u))
            rr = r * (1 - 0.5 * u)
            al = int(255 * min(1, (1 - u) * 3, u * 8))
            col = (127, 204, 199, al) if teal else (255, 255, 255, al)
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=col, outline=NAVY[:3] + (al,), width=1)
        frames.append(fr)
    return frames, 0.9


def sheet(name, frames, dur):
    w, h = frames[0].size
    s = Image.new("RGBA", (w * len(frames), h))
    for i, f in enumerate(frames):
        s.alpha_composite(f, (i * w, 0))
    s.save(OUT / f"{name}.webp", quality=86, method=6)
    return {"n": len(frames), "w": w, "h": h, "dur": dur}


def main():
    OUT.mkdir(exist_ok=True)
    wob = lambda n, amp: [amp * math.sin(2 * math.pi * i / n) for i in range(n)]
    meta = {
        "gull": sheet("gull", *gull()),
        "lighthouse": sheet("lighthouse", *lighthouse()),
        "ship": sheet("ship", *ship()),
        "spray": sheet("spray", *spray()),
        "anchor": sheet("anchor", rotate_frames("anchor", wob(12, 9), lambda im: (im.width / 2, 22), 24), 2.2),
        "wheel": sheet("wheel", rotate_frames("wheel", [45 * i / 8 for i in range(8)]), 1.2),
        "ring": sheet("ring", rotate_frames("ring", [90 * i / 8 for i in range(8)], padding=4), 1.0),
        "hat": sheet("hat", rotate_frames("hat", wob(10, 7), lambda im: (im.width / 2, im.height - 10), 14), 1.6),
    }
    (OUT / "sprites.json").write_text(json.dumps(meta, indent=1))
    for k, v in meta.items():
        print(k, v, (OUT / f"{k}.webp").stat().st_size)


if __name__ == "__main__":
    main()
