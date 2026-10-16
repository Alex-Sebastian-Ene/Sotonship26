"""Gymnasium environment for managing crowds and craft through a turnaround day.

One episode is one sampled day, one step per time bin. Before each bin is routed with PathFinder the
agent sets two kinds of lever:

* a steering weight in [0, 1] per controllable edge (stewards, signage, a temporary barrier) that
  scales the edge's cost by up to ``max_cost_scale``;
* a metering fraction in [0, 1] of the bin's new demand to hold back a bin (staggered
  disembarkation, holding craft at a marina).

Reward is minus the total overload (utilisation above 1, summed over edges) minus ``hold_cost`` per
mean bin's worth of demand held back, so the agent learns when delay is worth clear streets.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sotonship26.forecast import Day
from sotonship26.routing import Edge, Flow, route

OBS_CAP = 10.0


class CongestionEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        sample_day: Callable[[np.random.Generator], Day],
        controllable: Sequence[Edge],
        n_bins: int,
        *,
        max_cost_scale: float = 5.0,
        hold_cost: float = 0.05,
        routing: Mapping | None = None,
    ):
        self.sample_day = sample_day
        self.controllable = list(controllable)
        self.n_bins = n_bins
        self.max_cost_scale = max_cost_scale
        self.hold_cost = hold_cost
        self.routing = dict(routing or {})
        k = len(self.controllable)
        self.action_space = spaces.Box(0.0, 1.0, shape=(k + 1,), dtype=np.float32)
        self.observation_space = spaces.Box(0.0, OBS_CAP, shape=(k + 2,), dtype=np.float32)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self.day = self.sample_day(self.np_random)
        total = sum(f.volume for flows in self.day.flows.values() for f in flows)
        self.bin_scale = max(total / self.n_bins, 1.0)
        self.t = 0
        self.backlog: dict[tuple, float] = {}
        self.last_util = np.zeros(len(self.controllable))
        return self._obs(), {}

    def step(self, action):
        action = np.clip(np.asarray(action, dtype=float), 0.0, 1.0)
        steer, hold = action[:-1], float(action[-1])
        if self.t == self.n_bins - 1:
            hold = 0.0  # everyone still waiting goes in the last bin

        demand: dict[tuple, float] = defaultdict(float, self.backlog)
        self.backlog = {}
        for f in self.day.flows.get(self.t, []):
            demand[(f.source, f.target)] += f.volume * (1.0 - hold)
            if hold > 0:
                self.backlog[(f.source, f.target)] = (
                    self.backlog.get((f.source, f.target), 0.0) + f.volume * hold
                )
        flows = [Flow(s, t, v) for (s, t), v in demand.items() if v > 0]

        overload = 0.0
        self.last_util = np.zeros(len(self.controllable))
        if flows:
            scale = {
                e: 1.0 + w * (self.max_cost_scale - 1.0)
                for e, w in zip(self.controllable, steer, strict=True)
            }
            result = route(self.day.graph_for_bin(self.t), flows, cost_scale=scale, **self.routing)
            util = result.utilisation()
            overload = sum(max(0.0, u - 1.0) for u in util.values())
            self.last_util = np.array(
                [util.get(e, util.get(e[::-1], 0.0)) for e in self.controllable]
            )

        held = sum(self.backlog.values())
        reward = -overload - self.hold_cost * held / self.bin_scale
        self.t += 1
        terminated = self.t >= self.n_bins
        info = {"overload": overload, "held": held}
        return self._obs(), float(reward), terminated, False, info

    def _obs(self) -> np.ndarray:
        backlog = sum(self.backlog.values()) / self.bin_scale
        obs = np.concatenate([self.last_util, [backlog, self.t / self.n_bins]])
        return np.clip(obs, 0.0, OBS_CAP).astype(np.float32)
