"""Put the agents, buses and PPO results into the page synthetic_demo.py built.

synthetic_demo.py fills the page's main data block and leaves the second one (__EXTRA_DATA__)
for this script, so the forecast and these layers can be rebuilt separately. If the page would
pass ``--max-mb``, agents are thinned (a random share of each day's everyday and cruise agents is
dropped, and the weights of the rest go up) until it fits.

    uv run --no-project --python 3.12 --with numpy python demo/page_extras.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from agents import dec, enc  # noqa: E402
from ppo_stats import bundle, read_csv  # noqa: E402

TAG = '<script id="extra-data" type="application/json">'


def thin(agents: dict, keep: float, seed: int = 0) -> None:
    """Keep a random share ``keep`` of each day's agents, in place; the rest stand for more
    vehicles, and the agents-added-up check is recounted from the agents kept."""
    rng = np.random.default_rng(seed)
    nb = [len(dec(p["b"])) for p in agents["paths"]]
    P = agents["purposes"]
    used = set()
    for day in agents["days"].values():
        A = day["agents"]
        ints, pos, per = dec(A["t"]), 0, []
        for p in A["p"]:
            per.append(ints[pos:pos + nb[p]])
            pos += nb[p]
        k = rng.random(A["n"]) < keep
        for col in ("k", "o", "d", "p", "q", "c"):
            A[col] = [v for v, s in zip(A[col], k, strict=True) if s]
        per = [t for t, s in zip(per, k, strict=True) if s]
        A["t"] = "".join(enc(t) for t in per)
        A["n"] = int(k.sum())
        used |= set(A["p"])
        day["rates"] = {w: r * keep for w, r in day["rates"].items()}
        day["weights"] = {w: round(1 / r, 1) for w, r in day["rates"].items()}
        counts = {g: [0.0] * len(c["agents"]) for g, c in day["check"].items()}
        for kk, t in zip(A["k"], per, strict=True):
            g, w = P[kk]["group"], 1 / day["rates"]["cruise" if P[kk]["cruise"] else "everyday"]
            if g not in counts:
                continue
            b = min(len(counts[g]) - 1, t[0] // 900)  # seconds after 05:00 -> 15-minute bin
            counts[g][b] += w * (2.0 if P[kk]["key"] == "cruise_coach" else 1.0) * 4
        for g, c in day["check"].items():
            c["agents"] = [round(v) for v in counts[g]]
    # drop paths no agent uses any more, renumbering the rest
    order = sorted(used)
    new = {old: i for i, old in enumerate(order)}
    agents["paths"] = [agents["paths"][i] for i in order]
    for day in agents["days"].values():
        day["agents"]["p"] = [new[p] for p in day["agents"]["p"]]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", type=Path, default=HERE / "out" / "demo.html")
    ap.add_argument("--agents", type=Path, default=HERE / "out" / "agents.json")
    ap.add_argument("--ppo", type=Path, default=HERE / "out" / "ppo.json")
    ap.add_argument("--ablation", type=Path, default=HERE / "out" / "ppo_ablation.json",
                    help="train_ppo.py ablation output for the same policy, shown with it")
    ap.add_argument("--episodes", type=Path,
                    help="train_ppo.py evaluate's per-day rows (default: ppo.episodes.csv next to "
                         "--ppo), for the PPO charts")
    ap.add_argument("--train-days", type=Path,
                    help="train_days.csv of the run (default: beside the model ppo.json names)")
    ap.add_argument("--run", action="append", default=[], metavar="LABEL=PPO_JSON",
                    help="another run's evaluate output, compared with this one in the charts")
    ap.add_argument("--out", type=Path, help="default: overwrite --page")
    ap.add_argument("--max-mb", type=float, default=15.5)
    ap.add_argument("--template", type=Path,
                    help="move the page's forecast data into this template first (a page built "
                         "with an older demo/page.html)")
    args = ap.parse_args(argv)
    page = args.page.read_text(encoding="utf-8")
    if args.template:
        tag = '<script id="demo-data" type="application/json">'
        i = page.index(tag) + len(tag)
        forecast = page[i:page.index("</script>", i)]
        page = args.template.read_text(encoding="utf-8").replace("__DEMO_DATA__", forecast)
    i = page.find(TAG)
    if i < 0:
        sys.exit(f"{args.page} has no extra-data block: rebuild it with demo/synthetic_demo.py "
                 "from this branch (its template has the block)")
    j = page.find("</script>", i)
    head, tail = page[:i + len(TAG)], page[j:]
    extra = {"agents": None, "ppo": None}
    if args.agents.exists():
        extra["agents"] = json.loads(args.agents.read_text(encoding="utf-8"))
    if args.ppo.exists():
        extra["ppo"] = json.loads(args.ppo.read_text(encoding="utf-8"))
        if args.ablation.exists():
            extra["ppo"]["ablation"] = json.loads(args.ablation.read_text(encoding="utf-8"))
        ppo = extra["ppo"]
        train_days = args.train_days or (Path(ppo["model"]).with_name("train_days.csv")
                                         if ppo.get("model") else None)
        runs = {"This run": ppo}
        for r in args.run:
            label, path = r.split("=", 1)
            runs[label] = json.loads(Path(path).read_text(encoding="utf-8"))
        ppo["stats"] = bundle(ppo, read_csv(args.episodes or args.ppo.with_suffix(".episodes.csv")),
                              read_csv(train_days), runs)
    keep = 1.0
    while True:
        payload = json.dumps(extra, separators=(",", ":")).replace("</", "<\\/")
        size = len((head + payload + tail).encode("utf-8")) / 1e6
        if size <= args.max_mb or not extra["agents"]:
            break
        step = max(0.5, min(0.95, (args.max_mb - 0.3) / size))
        thin(extra["agents"], step)
        keep *= step
        print(f"page {size:.1f} MB > {args.max_mb} MB: kept {keep:.0%} of the agents")
    out = args.out or args.page
    out.write_text(head + payload + tail, encoding="utf-8")
    print(f"wrote {out} ({size:.1f} MB; agents {'yes' if extra['agents'] else 'no'}, "
          f"PPO {'yes' if extra['ppo'] else 'no'})")


if __name__ == "__main__":
    main()
