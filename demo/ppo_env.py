"""Gymnasium environment for the PPO decision layer: one sampled turnaround day, one step per
15 minutes from 05:00 to 20:00 (60 steps).

Each episode is one sampled day of the traffic model, drawn as the forecast draws its samples
(daysim.sample_day: weather, incidents, everyday traffic noise, driver perception and the cruise
traffic of that date's real VTS calls). Every step routes one bin with run_day's logic
(daysim.DaySim) after applying the action:

* metering, per terminal: each 15 minutes release all, 70% or 40% of the disembarked
  passengers waiting to leave (their pick-up cars, taxis, park-and-cruise cars and coaches wait
  with them). Nobody is held more than 90 minutes. The port and the cruise line own this lever.
* check-in opening, per terminal: open check-in 60 or 30 minutes earlier, as planned, or 30
  minutes later, closing time unchanged. Chosen at the first step (05:00) and fixed for the day.
  The cruise line owns this lever.
* signs, per sign location (the page's five): drivers see the links of that location's corridors
  as SIGN_FACTOR slower when they choose routes (travel times do not change).
* marshals, per dock gate in use: MARSHAL_CAP more capacity on the gate's access links.

Cost of a step in pounds (stated assumptions, see COSTS):

    5,000 x corridor-hours above 85% of capacity (a weight standing for the risk that a road at
          its limit locks up, which average delay misses; chosen so that on a busy day it counts
          about as much as delay; the traffic team should set it)
  +    15 x vehicle-hours of delay: vehicles the point queue carries into the next 15 minutes
          (each waits 15 minutes) plus slower running of the traffic that gets through each link
          (BPR, load capped at 1.5 as in traffic_model.delay_minutes)
  +    15 x passenger-hours held in a terminal
  +   120 x gate-hours with marshals (four marshals at 30 pounds an hour)
  +    25 x sign location-hours (operator time; and a sign left on all day gets ignored)

Check-in moves have no cost of their own. (A first run with free signs left them on all day.) Reward = -(cost - cost of doing nothing on
the same sampled day in the same bin) / REWARD_SCALE. Subtracting doing nothing cannot change
which policy is best, since no action affects it, but it removes most of the day-to-day noise.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daysim  # noqa: E402
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

N_BINS = tm.N_BINS
SIGN_GROUPS = ["Western approach", "Town Quay and Eastern Docks", "City centre",
               "North and east", "Motorway"]
METER = (1.0, 0.7, 0.4)  # share of waiting passengers released per 15 minutes
OPEN_SHIFT = (-60, -30, 0, 30)  # minutes to move check-in opening
NOTHING_OPEN = OPEN_SHIFT.index(0)
SIGN_FACTOR = 1.3  # assumed: signed links look 30% slower to drivers choosing a route
MARSHAL_CAP = 1.25  # assumed: marshals add 25% to a gate's access capacity
MAX_HOLD_BINS = 6  # 90 minutes
COSTS = {"corridor_hour": 5000.0, "vehicle_hour": 15.0, "held_pax_hour": 15.0,
         "marshal_hour": 120.0, "sign_hour": 25.0}
REWARD_SCALE = 10_000.0
SHARES_PATH = sd.CACHE / "ppo_shares.pkl"
DAY_KEY = 4242  # random streams: [DAY_KEY, split, day seed]
SPLITS = {"train": 0, "test": 1, "page": 2}

_CTX = None


def get_ctx(log=print):
    global _CTX
    if _CTX is None:
        _CTX = daysim.load_ctx(log=log)
    return _CTX


def split_dates(tasks: dict) -> dict[str, list[str]]:
    """Ship days in the window: every fourth (from the third) is held out for testing."""
    ships = sorted(k for k, t in tasks.items() if t["calls"])
    test = ships[2::4]
    return {"train": [d for d in ships if d not in test], "test": test}


def load_shares(path: Path = SHARES_PATH) -> dict:
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return {}


class CruiseDayEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, dates: list[str] | None = None, split: str = "train",
                 baseline: bool = True, cruise: dict | None = None, iters: int = 3,
                 shares: dict | None = None, ctx=None):
        super().__init__()
        self.ctx = ctx or get_ctx()
        m = self.ctx.m
        self.m = m
        self.tasks = daysim.day_tasks(cruise)
        self.dates = dates or split_dates(self.tasks)["train"]
        self.split = SPLITS[split]
        self.baseline, self.iters = baseline, iters
        self.shares = shares if shares is not None else load_shares()
        self.terminals = [t for t in sd.TERMINALS if t in self.ctx.terminal_gate]
        self.gates = list(self.ctx.gates)
        corr_ids = [c[0] for c in self.ctx.corr]
        self.corr_ids = corr_ids
        self.gate_corr = [corr_ids.index(f"gate{g}") for g in self.gates]
        self.gate_edges = [np.asarray(self.ctx.corr[i][3]) for i in self.gate_corr]
        self.sign_groups = [g for g in SIGN_GROUPS if any(c[2] == g for c in self.ctx.corr)]
        self.sign_corr = [[i for i, c in enumerate(self.ctx.corr) if c[2] == g]
                          for g in self.sign_groups]
        self.sign_mask = []
        for idx in self.sign_corr:
            mask = np.zeros(len(m.t0), bool)
            for i in idx:
                mask[self.ctx.corr[i][3]] = True
            self.sign_mask.append(mask)
        self.cod = np.asarray(self.ctx.cruise_ods)
        self.cod_pos = np.full(m.n_od, -1)
        self.cod_pos[self.cod] = np.arange(len(self.cod))
        nT, nS, nG = len(self.terminals), len(self.sign_groups), len(self.gates)
        self.nT, self.nS, self.nG = nT, nS, nG
        self.action_space = spaces.MultiDiscrete([len(METER)] * nT + [len(OPEN_SHIFT)] * nT
                                                 + [2] * nS + [2] * nG)
        self.n_corr = len(self.ctx.corr)
        n_obs = 1 + 3 + 5 + self.n_corr + 4 * nT + nS + nG
        self.observation_space = spaces.Box(0.0, 5.0, shape=(n_obs,), dtype=np.float32)
        self.day = None

    # --- actions ---------------------------------------------------------------------------

    def nothing(self) -> np.ndarray:
        return np.array([0] * self.nT + [NOTHING_OPEN] * self.nT + [0] * (self.nS + self.nG))

    def rule(self) -> np.ndarray:
        """Signs where a corridor of that location was above 85% of capacity in the last 15
        minutes; marshals at a gate whose access was."""
        a = self.nothing()
        hot = self.last_cx > tm.AT_RISK
        for k, idx in enumerate(self.sign_corr):
            a[2 * self.nT + k] = int(hot[idx].any())
        for k, i in enumerate(self.gate_corr):
            a[2 * self.nT + self.nS + k] = int(hot[i])
        return a

    def decode(self, action) -> dict:
        a = np.asarray(action, int)
        nT, nS = self.nT, self.nS
        return {"meter": a[:nT], "open": a[nT:2 * nT], "signs": a[2 * nT:2 * nT + nS],
                "marshals": a[2 * nT + nS:]}

    # --- episode ---------------------------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        options = options or {}
        date_ = options.get("date") or str(self.np_random.choice(self.dates))
        day_seed = options.get("day_seed")
        if day_seed is None:
            day_seed = int(self.np_random.integers(2**31 - 1))
        split = SPLITS[options["split"]] if "split" in options else self.split
        task = self.tasks[date_]
        key = daysim.shares_key(task)
        shares0 = self.shares.get(key)
        if shares0 is None:
            shares0 = self.shares[key] = daysim.base_shares(self.ctx, task)
        rng = np.random.default_rng([DAY_KEY, split, day_seed])
        self.day = day = daysim.sample_day(self.ctx, task, rng, shares0)
        self.task, self.date, self.day_seed = task, date_, day_seed
        self.plan = options.get("plan")
        self._setup_cruise()
        self.sim = daysim.DaySim(self.m, shares0, day.pre, self.iters)
        self.last_cx = np.zeros(self.n_corr)
        self.signs = np.zeros(self.nS, int)
        self.marshals = np.zeros(self.nG, int)
        self.open = np.full(self.nT, NOTHING_OPEN)
        H = MAX_HOLD_BINS
        self.pool = np.zeros((self.nT, H, len(self.cod)))
        self.ppool = np.zeros((self.nT, H))
        self.totals = {k: 0.0 for k in ("corridor_hours", "vehicle_hours", "queue_hours",
                                        "held_pax_hours", "marshal_hours", "sign_hours", "cost")}
        self.log = []
        self.base_cost = self._nothing_costs() if self.baseline else np.zeros(N_BINS)
        return self._obs(), {"date": date_, "day_seed": day_seed}

    def _setup_cruise(self):
        day, veh, calls = self.day, self.day.veh, self.task["calls"]
        m, nT = self.m, self.nT
        dis = [p[0] for p in self.plan] if self.plan else None
        emb = [p[1] for p in self.plan] if self.plan else None
        self.dis_shift, self.emb_shift = dis, emb
        t = daysim.cruise_times(veh, day.params, dis_shift=dis, emb_shift=emb)
        b = daysim.bin_index(t)
        ok = (b >= 0) & (b < N_BINS) & (veh["j"] >= 0)
        self.call_term = np.array([self.terminals.index(c.terminal) for c in calls], int)
        vt = self.call_term[veh["call"]] if len(calls) else np.zeros(0, int)
        self.veh_term = vt
        is_emb = veh["leg"] == 1
        self.D_un = daysim.vehicles_matrix(m.n_od, veh, t, mask=~veh["metered"] & ~is_emb)
        self.A = np.zeros((nT, N_BINS, len(self.cod)))
        self.P = np.zeros((nT, N_BINS))
        k = ok & veh["metered"]
        assert (self.cod_pos[veh["j"][k]] >= 0).all(), "a cruise vehicle off the cruise pairs"
        np.add.at(self.A, (vt[k], b[k], self.cod_pos[veh["j"][k]]), veh["pcu"][k])
        np.add.at(self.P, (vt[k], b[k]), veh["pax"][k])
        self.has_call = np.zeros(nT)
        self.has_call[np.unique(self.call_term)] = 1.0
        self._set_emb(np.full(nT, NOTHING_OPEN))
        self.Dc_nothing = daysim.vehicles_matrix(m.n_od, veh, t)

    def _set_emb(self, open_idx):
        veh, n_calls = self.day.veh, len(self.task["calls"])
        shift = np.array([OPEN_SHIFT[open_idx[self.call_term[c]]] for c in range(n_calls)], float)
        t = daysim.cruise_times(self.day.veh, self.day.params, dis_shift=self.dis_shift,
                                emb_shift=self.emb_shift, open_shift=shift if n_calls else None)
        is_emb = veh["leg"] == 1
        self.D_emb = daysim.vehicles_matrix(self.m.n_od, veh, t, mask=is_emb)
        b = daysim.bin_index(t)
        k = is_emb & (b >= 0) & (b < N_BINS) & (veh["j"] >= 0)
        self.E = np.zeros((self.nT, N_BINS))
        np.add.at(self.E, (self.veh_term[k], b[k]), veh["pcu"][k])

    def _costs(self, out, cap, held_pax, marshals, signs=0) -> dict:
        ctx, m = self.ctx, self.m
        x = out["x"]
        cx = np.maximum.reduceat(x[ctx.corr_idx], ctx.corr_ptr)
        served = np.minimum(out["v"], cap)  # vehicles per hour getting through each link
        running = float(served @ (m.t0 * 0.15 * np.minimum(x, 1.5) ** 4)) / 4.0 / 3600.0
        queue = out["held"] * 0.25  # carried into the next 15 minutes
        c = {"corridor_hours": float((cx > tm.AT_RISK).sum()) * 0.25,
             "vehicle_hours": running + queue, "queue_hours": queue,
             "held_pax_hours": held_pax * 0.25, "marshal_hours": marshals * 0.25,
             "sign_hours": signs * 0.25}
        c["cost"] = (COSTS["corridor_hour"] * c["corridor_hours"]
                     + COSTS["vehicle_hour"] * c["vehicle_hours"]
                     + COSTS["held_pax_hour"] * c["held_pax_hours"]
                     + COSTS["marshal_hour"] * c["marshal_hours"]
                     + COSTS.get("sign_hour", 0.0) * c["sign_hours"])
        return c, cx

    def _nothing_costs(self) -> np.ndarray:
        day = self.day
        sim = daysim.DaySim(self.m, day.shares0, day.pre, self.iters)
        out = np.zeros(N_BINS)
        Dfix = day.Dbg + day.Dm
        for b in range(N_BINS):
            cap = daysim.cap_at(day.cap, day.events, b)
            o = sim.step(Dfix[b] + self.Dc_nothing[b], cap, day.noise)
            out[b] = self._costs(o, cap, 0.0, 0)[0]["cost"]
        return out

    def _meter(self, b: int, levels) -> tuple[np.ndarray, list[float]]:
        released = np.zeros(len(self.cod))
        held = []
        for ti in range(self.nT):
            pool, ppool = self.pool[ti], self.ppool[ti]
            forced = pool[-1].copy()
            pool[:] = np.roll(pool, 1, axis=0)
            ppool[:] = np.roll(ppool, 1)
            pool[0], ppool[0] = self.A[ti, b], self.P[ti, b]
            r = METER[levels[ti]]
            rel = pool * r
            released += forced + rel.sum(axis=0)
            pool -= rel
            ppool *= 1.0 - r
            held.append(float(ppool.sum()))
        return released, held

    def step(self, action):
        day, b, act = self.day, self.sim.b, self.decode(action)
        if b == 0:
            self.open = act["open"].copy()
            if (self.open != NOTHING_OPEN).any():
                self._set_emb(self.open)
        released, held_t = self._meter(b, act["meter"])
        held = sum(held_t)
        Dc = self.D_un[b] + self.D_emb[b]
        Dc[self.cod] += released
        cap = daysim.cap_at(day.cap, day.events, b)
        self.marshals = act["marshals"].copy()
        if self.marshals.any():
            cap = cap.copy() if cap is day.cap else cap
            on = np.unique(np.concatenate([self.gate_edges[k] for k in np.flatnonzero(self.marshals)]))
            cap[on] *= MARSHAL_CAP  # once per link, even where two gates share one
        self.signs = act["signs"].copy()
        noise = day.noise
        if self.signs.any():
            mask = np.zeros(len(self.m.t0), bool)
            for k in np.flatnonzero(self.signs):
                mask |= self.sign_mask[k]
            noise = noise * np.where(mask, SIGN_FACTOR, 1.0)
        out = self.sim.step(day.Dbg[b] + day.Dm[b] + Dc, cap, noise)
        c, cx = self._costs(out, cap, held, int(self.marshals.sum()), int(self.signs.sum()))
        self.last_cx = cx
        for k, v in c.items():
            self.totals[k] += v
        self.log.append({"meter": act["meter"].tolist(), "signs": self.signs.tolist(),
                         "marshals": self.marshals.tolist(), "held_pax": held, "held_t": held_t,
                         "cost": c["cost"], "nothing": float(self.base_cost[b])})
        reward = -(c["cost"] - self.base_cost[b]) / REWARD_SCALE
        done = self.sim.b >= N_BINS
        info = {k: v for k, v in c.items()}
        if done:
            info["day_costs"] = {**self.totals, "nothing_cost": float(self.base_cost.sum()),
                                 "date": self.date, "day_seed": self.day_seed}
        return self._obs(), float(reward), done, False, info

    def _obs(self) -> np.ndarray:
        day, b = self.day, min(self.sim.b, N_BINS - 1)
        incident = any(b0 <= b < b1 for _, b0, b1, _ in day.events)
        o = [b / N_BINS, *np.eye(3)[day.dtype], float(self.task["term"]),
             float(bool(self.task["match"])), float(day.wet), float(incident),
             float(bool(self.task["closed"]))]
        o += np.clip(self.last_cx, 0.0, 2.0).tolist()
        for ti in range(self.nT):
            o += [self.has_call[ti], self.A[ti, b:b + 2].sum() / 200.0,
                  self.pool[ti].sum() / 200.0, self.E[ti, b:b + 2].sum() / 200.0]
        o += self.signs.tolist() + self.marshals.tolist()
        return np.clip(np.asarray(o, np.float32), 0.0, 5.0)
