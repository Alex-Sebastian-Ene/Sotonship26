"""Robust summaries of a PPO evaluation: each policy's change against doing nothing on the same
sampled day, as the mean, the median and the 10% trimmed mean, with 95% intervals from a two-stage
bootstrap that resamples dates and then sampled days within each date.

train_ppo.py evaluate's own intervals resample the sampled days as if they were independent, but
each date contributes 20 of them, so those intervals show simulation noise rather than how the
result carries to other dates. Resampling dates first fixes that. The median and trimmed mean show
whether a few extreme days drive the mean. Money only is the cost less the congested road-hours at
their assumed weight (ppo_env.COSTS), so it counts marshals, signs, delay and held passengers.

    python demo/ppo_robust.py demo/out/ppo_eval.episodes.csv [--md out.md] [--json out.json]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

CORRIDOR_HOUR = 5000.0  # ppo_env.COSTS["corridor_hour"], the assumed weight
LABELS = {"corridor_hours": "Congested road-hours (over 85%)",
          "excess_load_hours": "Excess load over 85% (continuous)",
          "corridor_hours_75": "Road-hours over 75%", "corridor_hours_95": "Road-hours over 95%",
          "corridor_hours_100": "Road-hours over 100%", "vehicle_hours": "Delay (vehicle-hours)",
          "cost": "Weighted cost score (£, assumed weights)",
          "money": "Money only (£, no congestion weight)"}
BOOT = 2000
TRIM = 0.1


def trimmed(a: np.ndarray, cut: float = TRIM) -> float:
    a = np.sort(a)
    k = int(len(a) * cut)
    return float(a[k:len(a) - k].mean()) if len(a) > 2 * k else float(a.mean())


def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in list(r.items()):
            if k not in ("policy", "date", "held_out") and v not in ("", None):
                r[k] = float(v)
        r["held_out"] = r["held_out"] in ("True", "true", "1")
        if "cost" in r and "corridor_hours" in r:
            r["money"] = r["cost"] - CORRIDOR_HOUR * r["corridor_hours"]
    return rows


def paired(rows: list[dict], policy: str, metric: str, split: str) -> tuple[np.ndarray, np.ndarray]:
    base = {(r["date"], r["seed"]): r for r in rows if r["policy"] == "nothing"}
    d, dates = [], []
    for r in rows:
        if r["policy"] != policy or metric not in r or isinstance(r[metric], str):
            continue
        if split != "all" and r["held_out"] != (split == "held_out"):
            continue
        b = base.get((r["date"], r["seed"]))
        if b is not None:
            d.append(r[metric] - b[metric])
            dates.append(r["date"])
    return np.asarray(d), np.asarray(dates)


def summarise(d: np.ndarray, dates: np.ndarray, rng: np.random.Generator) -> dict:
    by_date = defaultdict(list)
    for v, dt in zip(d, dates, strict=True):
        by_date[dt].append(v)
    groups = [np.asarray(v) for v in by_date.values()]
    stats = {"mean": np.mean, "median": np.median, "trimmed": trimmed}
    boot = {k: np.empty(BOOT) for k in stats}
    for i in range(BOOT):
        pick = rng.integers(0, len(groups), len(groups))
        sample = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in (groups[j] for j in pick)])
        for k, fn in stats.items():
            boot[k][i] = fn(sample)
    out = {k: {"value": float(fn(d)), "lo": float(np.percentile(boot[k], 2.5)),
               "hi": float(np.percentile(boot[k], 97.5))} for k, fn in stats.items()}
    date_means = np.array([g.mean() for g in groups])
    out["median_of_date_means"] = float(np.median(date_means))
    out["dates_better"] = int((date_means < 0).sum())
    out["days_better"] = float((d < 0).mean())
    out["n_days"], out["n_dates"] = int(len(d)), int(len(groups))
    return out


def run(path: Path, seed: int = 7) -> dict:
    rows = load(path)
    policies = sorted({r["policy"] for r in rows} - {"nothing"})
    metrics = [k for k in LABELS if k in rows[0]]
    rng = np.random.default_rng(seed)
    res = {}
    for split in ("held_out", "all"):
        res[split] = {}
        for p in policies:
            res[split][p] = {}
            for k in metrics:
                d, dates = paired(rows, p, k, split)
                if len(d):
                    res[split][p][k] = summarise(d, dates, rng)
    return {"source": str(path), "boot": BOOT, "trim": TRIM, "results": res}


def fmt(v: float, k: str) -> str:
    s = "−" if v < 0 else "+"
    return f"{s}£{abs(v):,.0f}" if k in ("cost", "money") else f"{s}{abs(v):,.2f}"


def cell(st: dict, k: str) -> str:
    return f"{fmt(st['value'], k)} [{fmt(st['lo'], k)}, {fmt(st['hi'], k)}]"


def markdown(res: dict) -> str:
    out = []
    for split, title in (("held_out", "Held-out dates"), ("all", "All test dates")):
        out.append(f"### {title}\n")
        out.append("| Policy | Measure | Mean [95%] | Median [95%] | 10% trimmed mean [95%] | "
                   "Median of date means | Dates better | Days better |")
        out.append("|---|---|---|---|---|---|---|---|")
        for p, ms in res["results"][split].items():
            for k, s in ms.items():
                mean, med, trim = (cell(s[x], k) for x in ("mean", "median", "trimmed"))
                out.append(f"| {p} | {LABELS[k]} | {mean} | {med} | {trim} | "
                           f"{fmt(s['median_of_date_means'], k)} | {s['dates_better']} of {s['n_dates']} | "
                           f"{s['days_better']:.0%} of {s['n_days']} |")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("episodes", type=Path)
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    res = run(args.episodes)
    md = markdown(res)
    print(md.encode("ascii", "replace").decode())
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(res), encoding="utf-8")


if __name__ == "__main__":
    main()
