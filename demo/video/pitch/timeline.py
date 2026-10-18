"""Lay out the video: scene start/end times from the narration lengths, and the demo segment's
time map (narrated parts at 1x, gaps sped up). Writes timeline.json for pitch.html and the audio mix."""

import json

D = json.load(open("vot/durations.json"))
VO = dict(json.load(open("vo.json", encoding="utf-8")))
cap = json.load(open("capture.json"))
P = cap["phases"]
PAD, TITLE, TAIL, FAST = 0.35, 1.6, 2.2, 2.5

scenes, audio, t = [], [], 0.0
scenes.append({"id": "title", "t0": 0.0, "t1": TITLE})
t = TITLE
for k in ["hook", "problem", "money", "user", "idea"]:
    audio.append({"k": k, "at": t})
    scenes.append({"id": k, "t0": t, "t1": t + D[k] + PAD, "text": VO[k]})
    t += D[k] + PAD

# demo: capture time c -> video time; piecewise segments [c0, c1, rate]
segs, c = [], 1.4
order = ["demo1", "demo2", "demo3", "demo4", "demo5", "fail"]
segs.append([c, P["demo1"], 1.0])
c = P["demo1"]
for i, k in enumerate(order):
    nxt = P[order[i + 1]] if i + 1 < len(order) else P["end"] - 0.2
    s_end = min(c + D[k] + 0.3, nxt)
    segs.append([c, s_end, 1.0])
    if nxt > s_end:
        segs.append([s_end, nxt, FAST])
    c = nxt
demo_t0, vt, dmap = t, t, []
for c0, c1, r in segs:
    dmap.append({"v0": vt, "c0": c0, "c1": c1, "r": r})
    vt += (c1 - c0) / r


def vtime(cc):
    for m in dmap:
        if m["c0"] <= cc <= m["c1"]:
            return m["v0"] + (cc - m["c0"]) / m["r"]
    return dmap[-1]["v0"]


demo_sub = []
for k in order:
    audio.append({"k": k, "at": vtime(P[k])})
    demo_sub.append({"k": k, "t0": vtime(P[k]), "text": VO[k]})
scenes.append({"id": "demo", "t0": demo_t0, "t1": vt, "sub": demo_sub})
t = vt + 0.2
for k in ["ai", "business", "data", "scale", "close"]:
    audio.append({"k": k, "at": t})
    scenes.append({"id": k, "t0": t, "t1": t + D[k] + PAD, "text": VO[k]})
    t += D[k] + PAD
scenes[-1]["t1"] = t + TAIL
total = t + TAIL
json.dump(
    {
        "scenes": scenes,
        "audio": audio,
        "dmap": dmap,
        "frames": cap["frames"],
        "total": total,
        "D": D,
    },
    open("timeline.json", "w"),
)
for s in scenes:
    print(f"{s['id']:9s} {s['t0']:6.1f} {s['t1']:6.1f}")
print("total", round(total, 1))
