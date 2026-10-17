"""Train and test the PPO decision layer (demo/ppo_env.py) against simpler policies.

    UV="uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas
        --with shapely --with pyproj --with gymnasium --with stable-baselines3 --with torch"
    $UV python demo/train_ppo.py prepare                    # warm-start route shares, once
    $UV python demo/train_ppo.py train --n-envs 32 --timesteps 400000 --out runs/ppo/local
    $UV python demo/train_ppo.py evaluate --model runs/ppo/local/model.zip --workers 32

``train`` runs the simulator in ``--n-envs`` processes (CPU) and the policy updates on the GPU
when there is one. ``evaluate`` plays four policies on the same held-out sampled days (new random
draws, on the held-out dates and on some training dates): do nothing, a rule (signs where a
corridor passed 85% of capacity in the last 15 minutes, marshals where a gate did), the existing
ship-timing advisor (synthetic_demo.advise, which plans each date from its own samples), and PPO.
It writes demo/out/ppo.json for the page and docs/ppo-results.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time as clock
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daysim  # noqa: E402
import ppo_env as pe  # noqa: E402
import synthetic_demo as sd  # noqa: E402

PAGE = HERE / "out" / "demo.html"
AGENTS = HERE / "out" / "agents.json"
OUT_JSON = HERE / "out" / "ppo.json"
DOC = HERE.parent / "docs" / "ppo-results.md"
POLICIES = ["nothing", "rule", "advisor", "ppo"]
LABELS = {"nothing": "Do nothing", "rule": "Rule (signs and marshals at 85%)",
          "advisor": "Ship-timing advisor", "ppo": "PPO"}
METRICS = ["corridor_hours", "vehicle_hours", "queue_hours", "held_pax_hours", "marshal_hours",
           "sign_hours", "cost"]
METRIC_LABELS = {"corridor_hours": "Corridor-hours above 85%", "vehicle_hours": "Delay (vehicle-hours)",
                 "queue_hours": "of which queuing (vehicle-hours)",
                 "held_pax_hours": "Passenger-hours held", "marshal_hours": "Marshal gate-hours",
                 "sign_hours": "Sign location-hours", "cost": "Cost (pounds)"}
OWNERS = {"meter": "The port (ABP) and the cruise line", "checkin": "The cruise line and the port",
          "signs": "Council traffic team", "marshals": "The port (ABP), with the council"}


def log(msg):
    print(f"[{clock.strftime('%H:%M:%S')}] {msg}", flush=True)


def cruise_assumptions():
    return daysim.fitted_cruise(daysim.page_data(PAGE))


# --- prepare ------------------------------------------------------------------------------------

def _shares(task):
    ctx = pe.get_ctx()
    return daysim.shares_key(task), daysim.base_shares(ctx, task)


def prepare(args) -> None:
    import pickle

    tasks = daysim.day_tasks(cruise_assumptions())
    keys = {}
    for t in tasks.values():
        keys.setdefault(daysim.shares_key(t), t)
    log(f"warm-start shares for {len(keys)} day types on {args.workers} workers")
    with ProcessPoolExecutor(args.workers, initializer=_init_worker) as pool:
        shares = dict(pool.map(_shares, keys.values()))
    pe.SHARES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(pe.SHARES_PATH, "wb") as f:
        pickle.dump(shares, f)
    log(f"wrote {pe.SHARES_PATH}")


# --- train --------------------------------------------------------------------------------------

def _make_env(dates, cruise, seed):
    def f():
        env = pe.CruiseDayEnv(dates=dates, split="train", baseline=True, cruise=cruise)
        env.reset(seed=seed)
        return env
    return f


def train(args) -> None:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cruise = cruise_assumptions()
    tasks = daysim.day_tasks(cruise)
    split = pe.split_dates(tasks)
    log(f"training dates {len(split['train'])}, held out {split['test']}")
    pe.get_ctx(log)  # loaded once here; forked simulator processes share it
    if args.gpu_envs:  # the simulator itself on the GPU, many days per sparse product
        from ppo_gpu import BatchedCruiseDayEnv
        from stable_baselines3.common.vec_env import VecMonitor

        venv = VecMonitor(BatchedCruiseDayEnv(args.gpu_envs, split["train"], cruise,
                                              device="cpu" if args.cpu else "cuda",
                                              workers=args.n_envs, seed=args.seed))
        log(f"simulator on {'the CPU' if args.cpu else 'the GPU'}: {args.gpu_envs} days per "
            f"batch, {args.n_envs} processes drawing days")
        args.n_envs = args.gpu_envs
    else:
        fns = [_make_env(split["train"], cruise, args.seed + i) for i in range(args.n_envs)]
        if args.n_envs > 1:  # the vec env forks before CUDA starts in this process
            venv = SubprocVecEnv(fns, start_method="fork" if os.name != "nt" else "spawn")
        else:
            venv = DummyVecEnv(fns)
    device = "cuda" if torch.cuda.is_available() and not args.cpu else "cpu"
    if device == "cuda":
        log(f"policy on {torch.cuda.get_device_name(0)}")
    rollout = args.n_envs * args.n_steps
    batch = args.batch_size or next(b for b in range(max(64, rollout // 6), rollout + 1)
                                    if rollout % b == 0)
    log(f"rollout {rollout} steps per update, minibatch {batch}")
    model = PPO("MlpPolicy", venv, n_steps=args.n_steps, batch_size=batch,
                n_epochs=10, learning_rate=args.lr, gamma=0.99, gae_lambda=0.95,
                ent_coef=args.ent_coef, clip_range=0.2, seed=args.seed, device=device,
                policy_kwargs={"net_arch": [256, 256]}, verbose=1)

    rows = []
    started = clock.perf_counter()

    class DayLog(BaseCallback):
        def _on_step(self) -> bool:
            for info in self.locals["infos"]:
                c = info.get("day_costs")
                if c:
                    rows.append({**c, "steps": self.num_timesteps,
                                 "seconds": round(clock.perf_counter() - started)})
                    if len(rows) % 100 == 0:
                        last = rows[-100:]
                        gain = np.mean([r["nothing_cost"] - r["cost"] for r in last])
                        log(f"{self.num_timesteps} steps, {len(rows)} days: last 100 days save "
                            f"{gain:,.0f} pounds a day against doing nothing")
            return True

    model.learn(total_timesteps=args.timesteps, callback=DayLog())
    model.save(out / "model.zip")
    with open(out / "train_days.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    meta = {"timesteps": args.timesteps, "n_envs": args.n_envs, "n_steps": args.n_steps,
            "batch_size": batch, "lr": args.lr, "ent_coef": args.ent_coef,
            "seed": args.seed, "device": device, "gpu_envs": args.gpu_envs,
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "days": len(rows), "seconds": round(clock.perf_counter() - started),
            "train_dates": split["train"], "test_dates": split["test"], "cruise": cruise,
            "made": datetime.now().isoformat(timespec="minutes")}
    (out / "train.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    venv.close()
    log(f"saved {out / 'model.zip'} after {len(rows)} sampled days")


# --- evaluate -----------------------------------------------------------------------------------

_ENV = None
_MODEL = None


def _init_worker(model_path: str | None = None, cruise=None):
    global _ENV, _MODEL
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    ctx = pe.get_ctx(log=lambda *_: None)
    sd.CTX = ctx  # synthetic_demo.forecast / advise read the model from here
    if model_path:
        import torch
        from stable_baselines3 import PPO

        torch.set_num_threads(1)
        _MODEL = PPO.load(model_path, device="cpu")
    _ENV = (ctx, cruise)


def _env():
    global _ENV
    if not isinstance(_ENV, pe.CruiseDayEnv):
        ctx, cruise = _ENV if _ENV else (pe.get_ctx(), None)
        _ENV = pe.CruiseDayEnv(baseline=False, cruise=cruise, ctx=ctx)
    return _ENV


def run_episode(job: dict) -> dict:
    env = _env()
    obs, _ = env.reset(options={"date": job["date"], "day_seed": job["seed"],
                                "split": job["split"], "plan": job.get("plan")})
    done = False
    while not done:
        p = job["policy"]
        nT, nS = env.nT, env.nS
        if p == "rule":
            a = env.rule()
        elif p == "marshal_rule":  # the rule's marshals without its signs
            a = env.rule()
            a[2 * nT:2 * nT + nS] = 0
        elif p.startswith("ppo"):  # PPO, or PPO with one lever switched off (ablation)
            a, _ = _MODEL.predict(obs, deterministic=True)
            a = np.array(a)
            if p == "ppo_no_meter":
                a[:nT] = 0
            elif p == "ppo_no_checkin":
                a[nT:2 * nT] = pe.NOTHING_OPEN
            elif p == "ppo_no_signs":
                a[2 * nT:2 * nT + nS] = 0
            elif p == "ppo_no_marshals":
                a[2 * nT + nS:] = 0
        else:  # nothing, and the advisor (its plan is fixed in reset)
            a = env.nothing()
        obs, _, done, _, _ = env.step(a)
    out = {**job, **env.totals}
    out.pop("plan", None)
    if job.get("want_log"):
        out["log"] = env.log
        out["open"] = env.open.tolist()
    return out


def _advise(task: dict) -> tuple[str, list]:
    r = sd.advise(task)
    return task["date"], r["shifts"]


def ablation(args) -> None:
    """PPO with one lever switched off at a time, and the rule's marshals alone, on the test days."""
    cruise = cruise_assumptions()
    split = pe.split_dates(daysim.day_tasks(cruise))
    seen = split["train"][:: max(1, len(split["train"]) // args.n_seen_dates)][: args.n_seen_dates]
    pols = ["nothing", "ppo", "ppo_no_meter", "ppo_no_checkin", "ppo_no_signs", "ppo_no_marshals",
            "marshal_rule"]
    jobs = [{"policy": p, "date": d, "seed": s, "split": "test", "held_out": d in split["test"]}
            for d in split["test"] + seen for s in range(args.n_days) for p in pols]
    with ProcessPoolExecutor(args.workers, initializer=_init_worker,
                             initargs=(str(args.model), cruise)) as pool:
        rows = list(pool.map(run_episode, jobs, chunksize=4))
    base = {(r["date"], r["seed"]): r for r in rows if r["policy"] == "nothing"}
    sign_cost = pe.COSTS.get("sign_hour", 0.0)
    out = {}
    for p in pols:
        rs = [r for r in rows if r["policy"] == p]
        d = {k: np.array([r[k] - base[(r["date"], r["seed"])][k] for r in rs])
             for k in ("corridor_hours", "vehicle_hours", "held_pax_hours", "marshal_hours",
                       "sign_hours", "cost")}
        d["cost_signs_free"] = d["cost"] - sign_cost * d["sign_hours"]
        out[p] = {k: {"mean": float(v.mean()), "se": float(v.std(ddof=1) / np.sqrt(len(v)))}
                  for k, v in d.items()}
        out[p]["n"] = len(rs)
        log(f"{p:16s} n {len(rs)}  " + "  ".join(
            f"{k} {v['mean']:+,.2f} (se {v['se']:.2f})" for k, v in out[p].items() if k != "n"))
    Path(args.json).write_text(json.dumps({"model": str(args.model), "rows": out,
                                           "made": datetime.now().isoformat(timespec="minutes")}),
                               encoding="utf-8")
    log(f"wrote {args.json}")


def summary(rows: list[dict], boot: int = 2000) -> dict:
    """Mean, spread and percentiles per policy, and paired differences against doing nothing."""
    rng = np.random.default_rng(0)
    base = {(r["date"], r["seed"]): r for r in rows if r["policy"] == "nothing"}
    out = {}
    for p in POLICIES:
        rs = [r for r in rows if r["policy"] == p]
        if not rs:
            continue
        s = {"n": len(rs), "dates": len({r["date"] for r in rs})}
        for k in METRICS:
            v = np.array([r[k] for r in rs])
            d = np.array([r[k] - base[(r["date"], r["seed"])][k] for r in rs])
            bs = [rng.choice(d, len(d)).mean() for _ in range(boot)] if p != "nothing" else [0.0]
            s[k] = {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                    "p10": float(np.percentile(v, 10)), "p50": float(np.percentile(v, 50)),
                    "p90": float(np.percentile(v, 90)), "diff": float(d.mean()),
                    "diff_lo": float(np.percentile(bs, 2.5)), "diff_hi": float(np.percentile(bs, 97.5))}
        s["better_days"] = float(np.mean([r["cost"] < base[(r["date"], r["seed"])]["cost"] - 1e-6
                                          for r in rs])) if p != "nothing" else None
        out[p] = s
    return out


def windows(active: np.ndarray, min_len: int = 1, gap: int = 0) -> list[tuple[int, int]]:
    """Runs of active bins, after joining runs at most ``gap`` bins apart, at least ``min_len``."""
    active = np.asarray(active, bool).copy()
    on = np.flatnonzero(active)
    for a, b in zip(on[:-1], on[1:], strict=True):
        if 1 < b - a <= gap + 1:
            active[a:b] = True
    out, s = [], None
    for b, on in enumerate(list(active) + [False]):
        if on and s is None:
            s = b
        elif not on and s is not None:
            if b - s >= min_len:
                out.append((s, b - 1))
            s = None
    return out


def bin_time(b: int) -> str:
    m = daysim.DAY_START_MIN + b * daysim.BIN_MIN
    return f"{m // 60:02d}:{m % 60:02d}"


MIN_BINS, GAP_BINS = 2, 1  # recommended windows: at least 30 minutes, 15-minute gaps joined


def rewindow(args) -> None:
    """Redo the page's sign and marshal windows of an evaluate output from its per-bin shares."""
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    groups, gates = data["levers"]["sign_groups"], data["levers"]["gates"]
    for r in data["days"].values():
        keep = [a for a in r["actions"] if a["kind"] not in ("signs", "marshals")]
        for kind, names, key, owner in (("signs", groups, "group", OWNERS["signs"]),
                                        ("marshals", gates, "gate", OWNERS["marshals"])):
            share = np.asarray(r["per_bin"][kind])  # bins x levers
            for k, name in enumerate(names):
                for b0, b1 in windows(share[:, k] >= 0.5, MIN_BINS, GAP_BINS):
                    keep.append({"kind": kind, key: name, "from": bin_time(b0),
                                 "to": bin_time(b1 + 1),
                                 "share": round(float(share[b0:b1 + 1, k].mean()), 2),
                                 "owner": owner})
        r["actions"] = sorted(keep, key=lambda a: a.get("from", "00:00"))
    Path(args.json).write_text(json.dumps(data, default=float), encoding="utf-8")
    log(f"rewrote the page windows in {args.json}")


def recommendations(env: pe.CruiseDayEnv, task: dict, runs: list[dict], base: list[dict]) -> dict:
    """Turn PPO's actions on K sampled days into actions with times: a lever is recommended in
    the 15 minutes where PPO used it on at least half of the days, shown as windows of 30
    minutes or more (gaps of 15 minutes joined) so the plan does not flicker."""
    K = len(runs)
    meter = np.array([[s["meter"] for s in r["log"]] for r in runs])  # K x bins x terminals
    held = np.array([[s["held_t"] for s in r["log"]] for r in runs])
    meter = np.where(held > 0.5, meter, 0)  # metering only counts while passengers wait
    signs = np.array([[s["signs"] for s in r["log"]] for r in runs])
    marsh = np.array([[s["marshals"] for s in r["log"]] for r in runs])
    opens = np.array([r["open"] for r in runs])
    recs = []
    for ti, term in enumerate(env.terminals):
        calls = [c for c in task["calls"] if c.terminal == term]
        if not calls:
            continue
        ships = ", ".join(c.ship for c in calls)
        on = (meter[:, :, ti] > 0).mean(axis=0) >= 0.5
        for b0, b1 in windows(on, MIN_BINS, GAP_BINS):
            lv = meter[:, b0:b1 + 1, ti]
            lv = int(np.bincount(lv[lv > 0]).argmax())
            recs.append({"kind": "meter", "terminal": term, "ships": ships, "from": bin_time(b0),
                         "to": bin_time(b1 + 1), "release": pe.METER[lv],
                         "share": round(float((meter[:, b0:b1 + 1, ti] > 0).mean()), 2),
                         "owner": OWNERS["meter"]})
        vals, counts = np.unique(opens[:, ti], return_counts=True)
        top = int(vals[np.argmax(counts)])
        if pe.OPEN_SHIFT[top] != 0 and counts.max() / K >= 0.5:
            planned = sd.minutes(calls[0].departure) - daysim.turnaround_params(
                date.fromisoformat(task["date"])).embark_open_before_dep_min
            new = planned + pe.OPEN_SHIFT[top]
            recs.append({"kind": "checkin", "terminal": term, "ships": ships,
                         "shift": pe.OPEN_SHIFT[top], "planned": f"{int(planned) // 60:02d}:{int(planned) % 60:02d}",
                         "new": f"{int(new) // 60:02d}:{int(new) % 60:02d}",
                         "share": round(float(counts.max() / K), 2), "owner": OWNERS["checkin"]})
    for k, g in enumerate(env.sign_groups):
        for b0, b1 in windows(signs[:, :, k].mean(axis=0) >= 0.5, MIN_BINS, GAP_BINS):
            recs.append({"kind": "signs", "group": g, "from": bin_time(b0), "to": bin_time(b1 + 1),
                         "share": round(float(signs[:, b0:b1 + 1, k].mean()), 2),
                         "owner": OWNERS["signs"]})
    for k, g in enumerate(env.gates):
        for b0, b1 in windows(marsh[:, :, k].mean(axis=0) >= 0.5, MIN_BINS, GAP_BINS):
            recs.append({"kind": "marshals", "gate": env.m.centroids[g].name, "from": bin_time(b0),
                         "to": bin_time(b1 + 1), "share": round(float(marsh[:, b0:b1 + 1, k].mean()), 2),
                         "owner": OWNERS["marshals"]})
    recs.sort(key=lambda r: r.get("from", "00:00"))
    eff = {k: {"ppo": float(np.mean([r[k] for r in runs])),
               "nothing": float(np.mean([r[k] for r in base]))} for k in METRICS}
    return {"k": K, "actions": recs, "effect": eff,
            "per_bin": {"meter": meter.mean(axis=0).round(2).tolist(),
                        "signs": signs.mean(axis=0).round(2).tolist(),
                        "marshals": marsh.mean(axis=0).round(2).tolist()}}


def evaluate(args) -> None:
    cruise = cruise_assumptions()
    tasks = daysim.day_tasks(cruise)
    split = pe.split_dates(tasks)
    seen = split["train"][:: max(1, len(split["train"]) // args.n_seen_dates)][: args.n_seen_dates]
    if args.n_test_dates:
        split["test"] = split["test"][: args.n_test_dates]
    eval_dates = split["test"] + seen
    log(f"evaluating on {len(split['test'])} held-out and {len(seen)} training dates, "
        f"{args.n_days} sampled days each")
    with ProcessPoolExecutor(args.workers, initializer=_init_worker,
                             initargs=(str(args.model), cruise)) as pool:
        atasks = [{**daysim.task_json(tasks[d]), "n": args.n_advise} for d in eval_dates]
        plans = dict(pool.map(_advise, atasks))
        for d, p in plans.items():
            log(f"  advisor {d}: {p}")
        jobs = [{"policy": p, "date": d, "seed": s, "split": "test",
                 "plan": plans[d] if p == "advisor" else None,
                 "held_out": d in split["test"]}
                for d in eval_dates for s in range(args.n_days) for p in POLICIES]
        rows = list(pool.map(run_episode, jobs, chunksize=1))
        log(f"{len(rows)} test episodes")
        # the page: PPO's actions with times on the days the page shows agents for
        page_days = []
        if AGENTS.exists():
            page_days = json.loads(AGENTS.read_text(encoding="utf-8"))["meta"]["days"]
        page_days = page_days or split["test"][:2]
        pjobs = [{"policy": p, "date": d, "seed": s, "split": "page", "want_log": p == "ppo"}
                 for d in page_days for s in range(args.n_page) for p in ("ppo", "nothing")]
        prows = list(pool.map(run_episode, pjobs, chunksize=1))
    env = pe.CruiseDayEnv(baseline=False, cruise=cruise, ctx=pe.get_ctx())
    rec = {}
    for d in page_days:
        runs = [r for r in prows if r["date"] == d and r["policy"] == "ppo"]
        base = [r for r in prows if r["date"] == d and r["policy"] == "nothing"]
        rec[d] = recommendations(env, tasks[d], runs, base)
    res = {"all": summary(rows), "held_out": summary([r for r in rows if r["held_out"]]),
           "seen": summary([r for r in rows if not r["held_out"]])}
    train_meta = {}
    tj = Path(args.model).with_name("train.json")
    if tj.exists():
        train_meta = json.loads(tj.read_text(encoding="utf-8"))
    curve = []
    tc = Path(args.model).with_name("train_days.csv")
    if tc.exists():
        with open(tc, encoding="utf-8") as f:
            tr = list(csv.DictReader(f))
        step = max(1, len(tr) // 40)
        for i in range(0, len(tr), step):
            chunk = tr[i:i + step]
            curve.append({"days": i + len(chunk), "steps": int(chunk[-1]["steps"]),
                          "saving": float(np.mean([float(r["nothing_cost"]) - float(r["cost"])
                                                   for r in chunk]))})
    data = {"made": datetime.now().isoformat(timespec="minutes"), "costs": pe.COSTS,
            "levers": {"meter": pe.METER, "open_shift": pe.OPEN_SHIFT,
                       "sign_factor": pe.SIGN_FACTOR, "marshal_cap": pe.MARSHAL_CAP,
                       "max_hold_min": pe.MAX_HOLD_BINS * daysim.BIN_MIN,
                       "sign_groups": env.sign_groups,
                       "gates": [env.m.centroids[g].name for g in env.gates],
                       "terminals": env.terminals},
            "dates": {"test": split["test"], "seen": seen, "train": split["train"]},
            "n_days": args.n_days, "n_advise": args.n_advise, "summary": res,
            "labels": LABELS, "metric_labels": METRIC_LABELS, "train": train_meta,
            "curve": curve, "days": rec, "cruise": cruise}
    out_json, doc = Path(args.json), Path(args.doc)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, default=float), encoding="utf-8")
    with open(out_json.with_suffix(".episodes.csv"), "w", newline="", encoding="utf-8") as f:
        keys = ["policy", "date", "seed", "held_out", *METRICS]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    doc.write_text(results_md(data), encoding="utf-8")
    log(f"wrote {out_json} and {doc}")


# --- the write-up -------------------------------------------------------------------------------

def _fmt(v: float, k: str) -> str:
    return f"{v:,.0f}" if k in ("cost", "vehicle_hours", "queue_hours", "held_pax_hours") else f"{v:.2f}"


def results_md(data: dict) -> str:
    s, n = data["summary"], data["n_days"]
    test, seen = data["dates"]["test"], data["dates"]["seen"]
    L = ["# PPO decision layer: results", "",
         f"Generated by `demo/train_ppo.py evaluate` on {data['made']}. Do not edit by hand; the "
         "method and the reading of these numbers are in [agents-and-ppo.md](agents-and-ppo.md).",
         "",
         f"Test set: {len(test)} held-out dates ({', '.join(test)}) and {len(seen)} training dates "
         f"({', '.join(seen)}), {n} new sampled days each (random draws never used in training), "
         f"so each policy is scored on {s['all']['nothing']['n']} sampled days. Every policy sees "
         "the same sampled days, so differences are paired. The advisor plans each date from "
         f"{data['n_advise']} of the forecast's own samples, as on the page.", ""]
    tr = data.get("train") or {}
    if tr:
        sim = (f"simulator on the GPU, {tr['gpu_envs']} days per batch" if tr.get("gpu_envs")
               else f"simulator in {tr.get('n_envs')} CPU processes")
        L += [f"Training: {tr.get('timesteps', 0):,} steps ({tr.get('days', 0):,} sampled days, "
              f"{sim}, policy on {tr.get('gpu') or tr.get('device')}, "
              f"{tr.get('seconds', 0) / 60:.0f} minutes).", ""]
    for part, title in (("all", "All test days"), ("held_out", "Held-out dates only"),
                        ("seen", "Training dates, new draws")):
        ss = s[part]
        if not ss:
            continue
        L += [f"## {title}", "",
              "Mean per sampled day, with the 10th to 90th percentile, and the paired difference "
              "from doing nothing with a 95% bootstrap interval.", "",
              "| Policy | n | " + " | ".join(METRIC_LABELS[k] for k in METRICS) + " | Better than nothing |",
              "|---|---|" + "---|" * len(METRICS) + "---|"]
        for p in POLICIES:
            if p not in ss:
                continue
            row = [LABELS[p], str(ss[p]["n"])]
            for k in METRICS:
                v = ss[p][k]
                cell = f"{_fmt(v['mean'], k)} ({_fmt(v['p10'], k)}–{_fmt(v['p90'], k)})"
                if p != "nothing":
                    cell += f"<br>Δ {_fmt(v['diff'], k)} [{_fmt(v['diff_lo'], k)}, {_fmt(v['diff_hi'], k)}]"
                row.append(cell)
            row.append("" if ss[p]["better_days"] is None else f"{100 * ss[p]['better_days']:.0f}% of days")
            L.append("| " + " | ".join(row) + " |")
        L.append("")
    L += ["## What the numbers say", ""]
    a = s["all"]

    def beats(p, q, k="cost"):
        """p - q on metric k, paired via the differences from doing nothing."""
        return a[p][k]["diff"] - a[q][k]["diff"]

    for k, name in (("cost", "total cost"), ("corridor_hours", "corridor-hours above 85%"),
                    ("vehicle_hours", "delay")):
        for q in ("nothing", "rule", "advisor"):
            if q not in a or "ppo" not in a:
                continue
            d = a["ppo"][k]["diff"] if q == "nothing" else beats("ppo", q, k)
            word = "lower" if d < 0 else "higher"
            L.append(f"- PPO's {name} is {_fmt(abs(d), k)} {word} than "
                     f"{LABELS[q].lower()} on average"
                     + (f" (95% interval of the paired difference {_fmt(a['ppo'][k]['diff_lo'], k)} "
                        f"to {_fmt(a['ppo'][k]['diff_hi'], k)})" if q == "nothing" else "") + ".")
    for q in ("rule", "advisor"):
        if q in a and "ppo" in a and beats("ppo", q) >= 0:
            L.append(f"- **PPO does not beat {LABELS[q].lower()} on total cost** on these test days.")
    L += ["", "Costs used: " + ", ".join(f"{k.replace('_', ' ')} £{v:,.0f}"
                                       for k, v in data["costs"].items()) + ".", ""]
    return "\n".join(L) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cpus = max(1, (os.cpu_count() or 2) - 1)
    p = sub.add_parser("prepare")
    p.add_argument("--workers", type=int, default=cpus)
    t = sub.add_parser("train")
    t.add_argument("--n-envs", type=int, default=cpus)
    t.add_argument("--timesteps", type=int, default=400_000)
    t.add_argument("--n-steps", type=int, default=120, help="steps per env per update (2 days)")
    t.add_argument("--batch-size", type=int, default=0, help="0: about a sixth of a rollout")
    t.add_argument("--lr", type=float, default=3e-4)
    t.add_argument("--ent-coef", type=float, default=0.01)
    t.add_argument("--seed", type=int, default=26)
    t.add_argument("--cpu", action="store_true", help="keep the policy on the CPU")
    t.add_argument("--gpu-envs", type=int, default=0,
                   help="run this many days at once on the GPU (demo/ppo_gpu.py); --n-envs "
                        "then sets the processes drawing days")
    t.add_argument("--out", default="runs/ppo/local")
    e = sub.add_parser("evaluate")
    e.add_argument("--model", type=Path, default=Path("runs/ppo/local/model.zip"))
    e.add_argument("--workers", type=int, default=cpus)
    e.add_argument("--n-days", type=int, default=20, help="sampled test days per date")
    e.add_argument("--n-seen-dates", type=int, default=6)
    e.add_argument("--n-test-dates", type=int, default=0, help="limit held-out dates (smoke tests)")
    e.add_argument("--n-advise", type=int, default=8, help="samples the advisor plans from")
    e.add_argument("--n-page", type=int, default=8, help="sampled days per page day")
    e.add_argument("--json", default=str(OUT_JSON), help="results for the page")
    e.add_argument("--doc", default=str(DOC), help="the generated write-up")
    a = sub.add_parser("ablation")
    a.add_argument("--model", type=Path, required=True)
    a.add_argument("--workers", type=int, default=cpus)
    a.add_argument("--n-days", type=int, default=20)
    a.add_argument("--n-seen-dates", type=int, default=6)
    a.add_argument("--json", default=str(HERE / "out" / "ppo_ablation.json"))
    w = sub.add_parser("rewindow")
    w.add_argument("--json", required=True)
    args = ap.parse_args(argv)
    {"prepare": prepare, "train": train, "evaluate": evaluate, "ablation": ablation,
     "rewindow": rewindow}[args.cmd](args)


if __name__ == "__main__":
    main()
