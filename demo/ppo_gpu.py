"""The PPO environment batched on a GPU: many sampled days stepped together with PyTorch.

ppo_env.CruiseDayEnv steps one sampled day on one CPU core, about 45 ms per 15-minute bin and
twice that with the do-nothing baseline, and that simulator is where training spends its time.
Here ``n_envs`` sampled days and their do-nothing twins share every sparse matrix product of the
allocation, so one step routes all of them at once on the GPU. CPU worker processes draw the next
batch of sampled days (daysim.sample_day, the forecast's own draws) while the GPU runs the
current one.

Same observations, actions, costs and reward as CruiseDayEnv; run_day's per-bin logic in float32
instead of float64. tests/test_demo_agents_ppo.py checks it against CruiseDayEnv on a small
network. Every day of a batch starts and ends together (60 bins), so the batch resets as one.

    $UV python demo/train_ppo.py train --gpu-envs 128 --n-envs 23 --timesteps 5000000
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import torch
from stable_baselines3.common.vec_env.base_vec_env import VecEnv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daysim  # noqa: E402
import ppo_env as pe  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

N_BINS = tm.N_BINS
R = tm.ROUTES
_W: dict = {}  # state of a sampling process
_PLACEHOLDER = np.zeros(0)


def _init_sampler(cruise, keys, ctx=None):
    ctx = ctx or pe.get_ctx(log=lambda *_: None)
    m = ctx.m
    cod = np.asarray(ctx.cruise_ods)
    cod_pos = np.full(m.n_od, -1)
    cod_pos[cod] = np.arange(len(cod))
    _W.update(ctx=ctx, tasks=daysim.day_tasks(cruise), keys=list(keys), cod_pos=cod_pos,
              terminals=[t for t in sd.TERMINALS if t in ctx.terminal_gate])


def sample_arrays(job) -> dict:
    """One sampled day as the arrays the GPU needs (runs in a sampling process)."""
    date_, day_seed, split = job
    ctx, task = _W["ctx"], _W["tasks"][date_]
    m, terms, cod_pos = ctx.m, _W["terminals"], _W["cod_pos"]
    day = daysim.sample_day(ctx, task, np.random.default_rng([pe.DAY_KEY, split, day_seed]),
                            _PLACEHOLDER)
    veh = day.veh
    t = daysim.cruise_times(veh, day.params)
    b = daysim.bin_index(t)
    ok = (b >= 0) & (b < N_BINS) & (veh["j"] >= 0)
    emb = veh["leg"] == 1
    D_un = daysim.vehicles_matrix(m.n_od, veh, t, mask=~veh["metered"] & ~emb)
    call_term = np.array([terms.index(c.terminal) for c in task["calls"]], int)
    vt = call_term[veh["call"]] if len(call_term) else np.zeros(0, int)
    k = ok & veh["metered"]
    e = emb & (veh["j"] >= 0)
    c = veh["call"][e]
    has_call = np.zeros(len(terms))
    has_call[np.unique(call_term)] = 1.0
    inc = day.events[0] if day.events else (np.zeros(0, int), 0, 0, 1.0)
    return {"Dfix": (day.Dbg + day.Dm + D_un).astype(np.float32),
            "met": {"term": vt[k], "bin": b[k], "cod": cod_pos[veh["j"][k]],
                    "pcu": veh["pcu"][k], "pax": veh["pax"][k]},
            "emb": {"term": vt[e], "lo": veh["lo"][c], "hi": veh["hi"][c], "u": veh["u"][e],
                    "post": veh["post"][e], "cod": cod_pos[veh["j"][e]], "pcu": veh["pcu"][e]},
            "cap": day.cap.astype(np.float32), "noise": day.noise.astype(np.float32),
            "inc_edges": np.asarray(inc[0]), "inc": (int(inc[1]), int(inc[2]), float(inc[3])),
            "dtype": day.dtype, "skey": _W["keys"].index(daysim.shares_key(task)),
            "flags": [float(task["term"]), float(bool(task["match"])), float(day.wet),
                      float(bool(task["closed"]))],
            "has_call": has_call, "date": date_, "day_seed": int(day_seed)}


class BatchedCruiseDayEnv(VecEnv):
    """``n_envs`` CruiseDayEnv days on one device, as a Stable-Baselines3 VecEnv."""

    def __init__(self, n_envs: int, dates: list[str], cruise: dict | None = None,
                 device: str = "cuda", workers: int = 8, seed: int = 0, iters: int = 3,
                 split: str = "train", ctx=None, shares: dict | None = None):
        self.ctx = ctx or pe.get_ctx()
        m = self.ctx.m
        proto = pe.CruiseDayEnv(dates=dates, split=split, baseline=False, cruise=cruise,
                                ctx=self.ctx, shares={})
        self.proto, self.dates, self.split, self.iters = proto, list(dates), pe.SPLITS[split], iters
        shares = dict(shares if shares is not None else pe.load_shares())
        for d in self.dates:  # warm-start shares for any day type the cache lacks
            key = daysim.shares_key(proto.tasks[d])
            if key not in shares:
                shares[key] = daysim.base_shares(self.ctx, proto.tasks[d])
        keys = list(shares)
        # sampling processes start before CUDA does
        self.workers = workers
        if workers > 0:
            self.pool = ProcessPoolExecutor(workers, initializer=_init_sampler,
                                            initargs=(cruise, keys))
        else:
            self.pool = None
            _init_sampler(cruise, keys, self.ctx)
        super().__init__(n_envs, proto.observation_space, proto.action_space)
        dev = self.dev = torch.device(device)
        f32 = torch.float32

        def t(a, dtype=f32):
            return torch.as_tensor(np.asarray(a), dtype=dtype, device=dev)

        def csr(M):
            M = M.tocsr()
            return torch.sparse_csr_tensor(t(M.indptr, torch.int64), t(M.indices, torch.int64),
                                           t(M.data), size=M.shape)

        self.A, self.AT = csr(m.A), csr(m.AT)
        self.n_od, self.P, self.E = m.n_od, len(m.paths), len(m.t0)
        self.t0 = t(m.t0)[:, None]
        self.uniq = t(m.uniq)[:, :, None]
        self.col_idx = t(m.col_idx, torch.int64)
        self.path_len = t([len(p) for p in m.paths], torch.int64)
        self.corr_idx = t(self.ctx.corr_idx, torch.int64)
        self.corr_len = t([len(c[3]) for c in self.ctx.corr], torch.int64)
        self.pre = torch.stack([t(m.pre[k]) if m.pre.get(k) is not None
                                else torch.zeros(N_BINS, self.E, device=dev) for k in (0, 1, 2)])
        self.shares = torch.stack([t(shares[k]) for k in keys])  # (K, bins, od, R)
        self.sign_mask = t(np.array(proto.sign_mask, float) if proto.nS else np.zeros((0, self.E)))
        gm = np.zeros((proto.nG, self.E))
        for k, ed in enumerate(proto.gate_edges):
            gm[k, ed] = 1.0
        self.gate_mask = t(gm)
        self.cod = t(proto.cod, torch.int64)
        self.n_cod = len(proto.cod)
        self.nT, self.nS, self.nG, self.n_corr = proto.nT, proto.nS, proto.nG, proto.n_corr
        self.meter_r = t(pe.METER)
        self.open_shift = t(pe.OPEN_SHIFT, torch.float64)
        self.rng = np.random.default_rng(seed)
        self._actions = None
        self._next = self._submit()

    # --- batches of sampled days -------------------------------------------------------------

    def _submit(self):
        jobs = [(str(self.rng.choice(self.dates)), int(self.rng.integers(2**31 - 1)), self.split)
                for _ in range(self.num_envs)]
        if self.pool is None:
            return [sample_arrays(j) for j in jobs]
        return [self.pool.submit(sample_arrays, j) for j in jobs]

    def _start(self, days: list[dict]) -> None:
        dev, B, nT, nc = self.dev, self.num_envs, self.nT, self.n_cod
        f32, f64, i64 = torch.float32, torch.float64, torch.int64

        def t(a, dtype=f32):
            return torch.as_tensor(np.asarray(a), dtype=dtype, device=dev)

        self.meta = [(d["date"], d["day_seed"]) for d in days]
        self.Dfix = t(np.stack([d["Dfix"] for d in days]))  # (B, bins, od)
        self.cap = t(np.stack([d["cap"] for d in days])).T  # (E, B)
        self.noise = t(np.stack([d["noise"] for d in days])).T
        inc = np.zeros((B, self.E), bool)
        for i, d in enumerate(days):
            inc[i, d["inc_edges"]] = True
        self.inc_mask = t(inc, torch.bool).T
        self.inc_b0 = t([d["inc"][0] for d in days], i64)
        self.inc_b1 = t([d["inc"][1] for d in days], i64)
        self.inc_f = t([d["inc"][2] for d in days])
        self.dtype = t([d["dtype"] for d in days], i64)
        self.skey = t([d["skey"] for d in days], i64)
        self.flags = t([d["flags"] for d in days])
        self.has_call = t(np.stack([d["has_call"] for d in days]))

        def cat(part, key, dtype):
            return t(np.concatenate([d[part][key] for d in days]), dtype)

        env_m = t(np.concatenate([np.full(len(d["met"]["pcu"]), i) for i, d in enumerate(days)]), i64)
        idx = ((env_m * nT + cat("met", "term", i64)) * N_BINS + cat("met", "bin", i64))
        self.A_arr = torch.zeros(B * nT * N_BINS * nc, device=dev).index_add_(
            0, idx * nc + cat("met", "cod", i64), cat("met", "pcu", f32)).view(B, nT, N_BINS, nc)
        self.P_arr = torch.zeros(B * nT * N_BINS, device=dev).index_add_(
            0, idx, cat("met", "pax", f32)).view(B, nT, N_BINS)
        self.A_pcu = self.A_arr.sum(-1)
        self.emb = {"env": t(np.concatenate([np.full(len(d["emb"]["pcu"]), i)
                                             for i, d in enumerate(days)]), i64),
                    "term": cat("emb", "term", i64), "lo": cat("emb", "lo", f64),
                    "hi": cat("emb", "hi", f64), "u": cat("emb", "u", f64),
                    "post": cat("emb", "post", f64), "cod": cat("emb", "cod", i64),
                    "pcu": cat("emb", "pcu", f32)}
        nothing = torch.full((B, nT), pe.NOTHING_OPEN, dtype=i64, device=dev)
        self.Emb_n, self.Epcu = self._emb(nothing)
        self.Emb = self.Emb_n
        self.queue = torch.zeros(self.n_od, 2 * B, device=dev)
        self.pool_v = torch.zeros(B, nT, pe.MAX_HOLD_BINS, nc, device=dev)
        self.pool_p = torch.zeros(B, nT, pe.MAX_HOLD_BINS, device=dev)
        self.last_cx = torch.zeros(B, self.n_corr, device=dev)
        self.signs = torch.zeros(B, self.nS, device=dev)
        self.marshals = torch.zeros(B, self.nG, device=dev)
        self.tot = {k: torch.zeros(B, device=dev, dtype=f64) for k in
                    ("corridor_hours", "vehicle_hours", "queue_hours", "held_pax_hours",
                     "marshal_hours", "sign_hours", "cost", "nothing_cost")}
        self.b = 0

    def _emb(self, choice):
        """Check-in traffic per bin and cruise pair (and PCU per terminal) for opening shifts."""
        e, B, nT, nc = self.emb, self.num_envs, self.nT, self.n_cod
        shift = self.open_shift[choice[e["env"], e["term"]]]
        lo = e["lo"] + shift
        tt = (lo + (e["hi"] - lo) * e["u"]) + e["post"]
        b = torch.floor((tt - daysim.DAY_START_MIN) / daysim.BIN_MIN).long()
        ok = (b >= 0) & (b < N_BINS)
        Emb = torch.zeros(B * N_BINS * nc, device=self.dev).index_add_(
            0, ((e["env"] * N_BINS + b) * nc + e["cod"])[ok], e["pcu"][ok]).view(B, N_BINS, nc)
        Epcu = torch.zeros(B * nT * N_BINS, device=self.dev).index_add_(
            0, ((e["env"] * nT + e["term"]) * N_BINS + b)[ok], e["pcu"][ok]).view(B, nT, N_BINS)
        return Emb, Epcu

    def start_jobs(self, jobs) -> np.ndarray:
        """Start a batch on chosen (date, day seed, split number) days; returns observations."""
        self._start([sample_arrays(j) for j in jobs] if self.pool is None
                    else list(self.pool.map(sample_arrays, jobs)))
        return self._obs()

    def _gather(self):
        days = self._next if self.pool is None else [f.result() for f in self._next]
        self._next = self._submit()
        self._start(days)

    # --- one bin for every day and its twin ----------------------------------------------------

    def _route(self, D, cap, noise, pre, sh0):
        """run_day's bin: D (od, C), cap/noise/pre (E, C), sh0 (od, R, C)."""
        C = D.shape[1]
        rate = (D + self.queue) * 4.0
        f = (sh0 * rate[:, None, :]).reshape(self.P, C)
        for k in range(self.iters):
            v = self.A @ f + pre
            tt = self.t0 * (1.0 + 0.15 * (v / cap) ** 4) * noise
            c = (self.AT @ tt).reshape(self.n_od, R, C)
            rel = c / c.min(dim=1, keepdim=True).values.clamp_min(30.0)
            w = torch.exp(-tm.LOGIT_BETA * (rel - 1.0)) * self.uniq
            y = w / w.sum(dim=1, keepdim=True) * rate[:, None, :]
            f = f + (y.reshape(self.P, C) - f) / (k + 2)
        v = self.A @ f + pre
        x = v / cap
        bott = torch.segment_reduce(x[self.col_idx], "max", lengths=self.path_len, axis=0)
        served = f / bott.clamp_min(1.0)
        unserved = tm.CARRY * (f - served).reshape(self.n_od, R, C).sum(dim=1) / 4.0
        self.queue = unserved
        return x, v, unserved

    def _meter(self, b, levels):
        forced = self.pool_v[:, :, -1].clone()
        self.pool_v = torch.roll(self.pool_v, 1, dims=2)
        self.pool_p = torch.roll(self.pool_p, 1, dims=2)
        self.pool_v[:, :, 0] = self.A_arr[:, :, b]
        self.pool_p[:, :, 0] = self.P_arr[:, :, b]
        r = self.meter_r[levels]  # (B, nT)
        rel = self.pool_v * r[:, :, None, None]
        released = (forced + rel.sum(dim=2)).sum(dim=1)  # (B, cod)
        self.pool_v = self.pool_v - rel
        self.pool_p = self.pool_p * (1.0 - r)[:, :, None]
        return released, self.pool_p.sum(dim=2)

    def step_async(self, actions):
        self._actions = np.asarray(actions)

    def step_wait(self):
        B, nT, nS, b, dev = self.num_envs, self.nT, self.nS, self.b, self.dev
        a = torch.as_tensor(self._actions, dtype=torch.int64, device=dev)
        meter, opening = a[:, :nT], a[:, nT:2 * nT]
        signs = a[:, 2 * nT:2 * nT + nS].float()
        marshals = a[:, 2 * nT + nS:].float()
        if b == 0:
            self.Emb, self.Epcu = self._emb(opening)
        released, held_t = self._meter(b, meter)
        Dc = torch.cat([self.Emb[:, b] + released,
                        self.Emb_n[:, b] + self.A_arr[:, :, b].sum(dim=1)]).T  # (cod, 2B)
        D = torch.cat([self.Dfix[:, b], self.Dfix[:, b]]).T.clone()  # (od, 2B)
        D[self.cod] += Dc
        on = (self.inc_b0 <= b) & (b < self.inc_b1)
        cap = self.cap * torch.where(self.inc_mask & on[None, :], self.inc_f[None, :], 1.0)
        cap_pol = cap * torch.where((marshals @ self.gate_mask).T > 0, pe.MARSHAL_CAP, 1.0)
        noise_pol = self.noise * torch.where((signs @ self.sign_mask).T > 0, pe.SIGN_FACTOR, 1.0)
        capc = torch.cat([cap_pol, cap], dim=1)
        noise = torch.cat([noise_pol, self.noise], dim=1)
        pre = self.pre[self.dtype, b].T.repeat(1, 2)
        sh0 = self.shares[self.skey, b].permute(1, 2, 0).repeat(1, 1, 2)
        x, v, unserved = self._route(D, capc, noise, pre, sh0)
        cx = torch.segment_reduce(x[self.corr_idx], "max", lengths=self.corr_len, axis=0)
        running = (torch.minimum(v, capc) * (self.t0 * 0.15 * x.clamp(max=1.5) ** 4)).sum(0)
        c = {"corridor_hours": (cx > tm.AT_RISK).sum(0).float() * 0.25,
             "vehicle_hours": running / 4.0 / 3600.0 + unserved.sum(0) * 0.25,
             "queue_hours": unserved.sum(0) * 0.25}
        held = held_t.sum(dim=1) * 0.25
        marsh = marshals.sum(dim=1) * 0.25
        C = pe.COSTS
        base = C["corridor_hour"] * c["corridor_hours"] + C["vehicle_hour"] * c["vehicle_hours"]
        sign_h = signs.sum(dim=1) * 0.25
        cost_pol = (base[:B] + C["held_pax_hour"] * held + C["marshal_hour"] * marsh
                    + C.get("sign_hour", 0.0) * sign_h)
        cost_nothing = base[B:]
        reward = -(cost_pol - cost_nothing) / pe.REWARD_SCALE
        for k in c:
            self.tot[k] += c[k][:B].double()
        self.tot["held_pax_hours"] += held.double()
        self.tot["marshal_hours"] += marsh.double()
        self.tot["sign_hours"] += sign_h.double()
        self.tot["cost"] += cost_pol.double()
        self.tot["nothing_cost"] += cost_nothing.double()
        self.last_cx = cx[:, :B].T
        self.signs, self.marshals = signs, marshals
        self.b += 1
        rew = reward.cpu().numpy().astype(np.float32)
        done = self.b >= N_BINS
        obs = self._obs()
        infos = [{} for _ in range(B)]
        if done:
            tot = {k: v.cpu().numpy() for k, v in self.tot.items()}
            for i in range(B):
                infos[i] = {"terminal_observation": obs[i],
                            "day_costs": {**{k: float(v[i]) for k, v in tot.items()},
                                          "date": self.meta[i][0], "day_seed": self.meta[i][1]}}
            self._gather()
            obs = self._obs()
        return obs, rew, np.full(B, done), infos

    def _obs(self) -> np.ndarray:
        B, b = self.num_envs, min(self.b, N_BINS - 1)
        dev = self.dev
        inc_now = (self.inc_mask.any(dim=0) & (self.inc_b0 <= b) & (b < self.inc_b1)).float()
        per_t = torch.stack([self.has_call, self.A_pcu[:, :, b:b + 2].sum(-1) / 200.0,
                             self.pool_v.sum(dim=(2, 3)) / 200.0,
                             self.Epcu[:, :, b:b + 2].sum(-1) / 200.0], dim=2).reshape(B, -1)
        o = torch.cat([torch.full((B, 1), b / N_BINS, device=dev),
                       torch.nn.functional.one_hot(self.dtype, 3).float(),
                       self.flags[:, :3], inc_now[:, None], self.flags[:, 3:4],
                       self.last_cx.clamp(0.0, 2.0), per_t, self.signs, self.marshals], dim=1)
        return o.clamp(0.0, 5.0).cpu().numpy().astype(np.float32)

    # --- VecEnv plumbing -------------------------------------------------------------------

    def reset(self):
        self._gather()
        return self._obs()

    def seed(self, seed=None):
        self.rng = np.random.default_rng(seed)
        return [seed] * self.num_envs

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(cancel_futures=True)

    def get_attr(self, attr_name, indices=None):
        return [getattr(self.proto, attr_name, None) for _ in self._idx(indices)]

    def set_attr(self, attr_name, value, indices=None):
        setattr(self.proto, attr_name, value)

    def env_method(self, method_name, *args, indices=None, **kwargs):
        return [getattr(self.proto, method_name)(*args, **kwargs) for _ in self._idx(indices)]

    def env_is_wrapped(self, wrapper_class, indices=None):
        return [False for _ in self._idx(indices)]

    def _idx(self, indices):
        if indices is None:
            return range(self.num_envs)
        return [indices] if isinstance(indices, int) else indices


def main(argv=None) -> None:
    """Benchmark and check: one batch of days on the device against CruiseDayEnv on the CPU."""
    import argparse
    import time

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--n", type=int, default=128, help="days per batch")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--check", type=int, default=2, help="days to compare with CruiseDayEnv")
    args = ap.parse_args(argv)
    ctx = pe.get_ctx()
    tasks = daysim.day_tasks()
    dates = pe.split_dates(tasks)["train"]
    t0 = time.perf_counter()
    env = BatchedCruiseDayEnv(args.n, dates, device=args.device, workers=args.workers, ctx=ctx)
    jobs = [(dates[i % len(dates)], 100 + i, 0) for i in range(args.n)]
    env.start_jobs(jobs)
    print(f"set up and first batch: {time.perf_counter() - t0:.1f} s", flush=True)
    proto = env.proto
    act = np.stack([proto.nothing() for _ in range(args.n)])
    act[1::2, : proto.nT] = 1
    act[1::2, 2 * proto.nT + proto.nS:] = 1
    t0 = time.perf_counter()
    for _ in range(N_BINS - 1):
        env.step_async(act)
        env.step_wait()
    if args.device == "cuda":
        torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    print(f"{N_BINS - 1} steps of {args.n} days (and their twins): {dt:.1f} s, "
          f"{args.n * (N_BINS - 1) / dt:.0f} day-steps a second", flush=True)
    env.step_async(act)
    _, rew, done, infos = env.step_wait()
    for i in range(args.check):
        d, s, _ = jobs[i]
        cpu = pe.CruiseDayEnv(ctx=ctx, baseline=False)
        cpu.reset(options={"date": d, "day_seed": s, "split": "train"})
        for _ in range(N_BINS):
            cpu.step(act[i])
        got = infos[i]["day_costs"]
        print(f"day {d} seed {s}: " + ", ".join(
            f"{k} gpu {got[k]:,.2f} cpu {cpu.totals[k]:,.2f}"
            for k in ("corridor_hours", "vehicle_hours", "held_pax_hours", "cost")), flush=True)
    env.close()


if __name__ == "__main__":
    main()
