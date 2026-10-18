"""Statistics from a PPO run for the page's "PPO in numbers" charts.

train_ppo.py evaluate writes demo/out/ppo.json (summaries) and, next to it, ppo.episodes.csv
(one row per policy per sampled test day). train writes train_days.csv beside the model (one row
per sampled training day). This module turns those into the compact block page_extras.py puts
under ``ppo.stats``; the page draws it in a fold that is closed by default. Every number here
comes from simulated days of the demo's traffic model, not observed traffic.

    uv run --no-project --python 3.12 --with numpy python demo/ppo_stats.py \
        --ppo demo/out/ppo.json --train-days runs/ppo/<job>/train_days.csv   # prints a summary
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

POLICIES = ["rule", "advisor", "ppo"]  # each compared with "nothing" on the same sampled day
METRICS = ["cost", "corridor_hours", "vehicle_hours", "marshal_hours", "sign_hours"]
CURVE_POINTS = 80


def read_csv(path: Path | None) -> list[dict] | None:
    if not path or not Path(path).exists():
        return None
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ci(d: np.ndarray, rng: np.random.Generator, boot: int = 2000) -> tuple[float, float]:
    if len(d) < 2:
        return float(d.mean()), float(d.mean())
    bs = rng.choice(d, (boot, len(d))).mean(axis=1)
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def curve(rows: list[dict], points: int = CURVE_POINTS) -> list[dict]:
    """Training days in ``points`` chunks: saving against doing nothing (mean, 10th and 90th
    percentile) and the levers used per day, so the page shows what PPO learned to do.

    The chunks differ in size by at most one day. Cutting fixed-size chunks would leave the
    remainder as a last point of a few days, and its mean would jump about."""
    bounds = np.linspace(0, len(rows), min(points, len(rows)) + 1).round().astype(int)
    out = []
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        ch = rows[a:b]
        save = np.array([float(r["nothing_cost"]) - float(r["cost"]) for r in ch])
        c = {"days": int(b), "steps": int(float(ch[-1]["steps"])),
             "minutes": round(float(ch[-1].get("seconds") or 0) / 60, 1),
             "mean": float(save.mean()), "p10": float(np.percentile(save, 10)),
             "p90": float(np.percentile(save, 90))}
        for k in ("corridor_hours", "marshal_hours", "sign_hours", "held_pax_hours"):
            if k in ch[0]:
                c[k] = float(np.mean([float(r[k]) for r in ch]))
        out.append(c)
    return out


def paired(episodes: list[dict], seed: int = 0) -> dict:
    """Per sampled test day, each policy minus doing nothing on the same day."""
    rng = np.random.default_rng(seed)
    base = {(r["date"], r["seed"]): r for r in episodes if r["policy"] == "nothing"}
    keys = sorted(base)
    held = [str(base[k]["held_out"]).lower() in ("true", "1") for k in keys]
    by = {(r["policy"], r["date"], r["seed"]): r for r in episodes}
    out = {"days": [{"date": d, "seed": int(s), "held_out": h} for (d, s), h in zip(keys, held,
                                                                                  strict=True)],
           "diff": {}, "by_date": [], "head_to_head": {}}
    D = {}
    for p in POLICIES:
        if not all((p, d, s) in by for d, s in keys):
            continue
        D[p] = {m: np.array([float(by[(p, d, s)][m]) - float(base[(d, s)][m]) for d, s in keys])
                for m in METRICS if m in base[keys[0]]}
        out["diff"][p] = {m: [round(float(v), 2) for v in a] for m, a in D[p].items()}
    dates = sorted({d for d, _ in keys})
    for d in dates:
        idx = np.array([k[0] == d for k in keys])
        row = {"date": d, "held_out": held[int(np.argmax(idx))], "n": int(idx.sum())}
        for p, a in D.items():
            row[p] = {m: float(a[m][idx].mean()) for m in ("cost", "corridor_hours")}
        out["by_date"].append(row)
    if "ppo" in D:
        for other in ("rule", "advisor"):
            if other not in D:
                continue
            d = D["ppo"]["cost"] - D[other]["cost"]  # paired: PPO cost minus the other's
            lo, hi = _ci(d, rng)
            out["head_to_head"][other] = {"mean": float(d.mean()), "lo": lo, "hi": hi,
                                          "ppo_cheaper": float(np.mean(d < -1e-6)),
                                          "n": int(len(d))}
    return out


def run_row(label: str, ppo: dict) -> dict | None:
    """One run's headline for the runs comparison: PPO's paired cost and congestion change."""
    s = (ppo.get("summary") or {}).get("all", {}).get("ppo")
    if not s:
        return None
    tr = ppo.get("train") or {}
    return {"label": label, "made": ppo.get("made"), "steps": tr.get("timesteps"),
            "days": tr.get("days"), "minutes": round(tr["seconds"] / 60) if tr.get("seconds")
            else None, "device": tr.get("gpu") or tr.get("device"), "n": s["n"],
            **{f"{m}_{k}": s[m][k] for m in ("cost", "corridor_hours")
               for k in ("diff", "diff_lo", "diff_hi")},
            "better_days": s.get("better_days")}


def bundle(ppo: dict, episodes: list[dict] | None = None, train_days: list[dict] | None = None,
           runs: dict[str, dict] | None = None) -> dict:
    """The ``ppo.stats`` block. Parts whose inputs are missing are left out, and the page skips
    the charts that need them."""
    out: dict = {"source": "Simulated days of the demo's traffic model (synthetic, not observed)"}
    if train_days:
        out["curve"] = curve(train_days)
    if episodes:
        out.update(paired(episodes))
    rows = [r for r in (run_row(k, v) for k, v in (runs or {}).items()) if r]
    if rows:
        out["runs"] = rows
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ppo", type=Path,
                    default=Path(__file__).resolve().parent / "out" / "ppo.json")
    ap.add_argument("--episodes", type=Path, help="default: ppo.episodes.csv next to --ppo")
    ap.add_argument("--train-days", type=Path, help="train_days.csv of the run (beside model.zip)")
    args = ap.parse_args(argv)
    ppo = json.loads(args.ppo.read_text(encoding="utf-8"))
    eps = read_csv(args.episodes or args.ppo.with_suffix(".episodes.csv"))
    st = bundle(ppo, eps, read_csv(args.train_days), {"this run": ppo})
    print(f"curve points {len(st.get('curve', []))}, test days {len(st.get('days', []))}, "
          f"dates {len(st.get('by_date', []))}, runs {len(st.get('runs', []))}")
    for k, v in st.get("head_to_head", {}).items():
        print(f"PPO minus {k}: {v['mean']:+,.0f} pounds a day [{v['lo']:+,.0f}, {v['hi']:+,.0f}], "
              f"PPO cheaper on {v['ppo_cheaper']:.0%} of {v['n']} days")


if __name__ == "__main__":
    main()
