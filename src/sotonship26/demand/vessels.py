"""Ferry and leisure-craft movements on Southampton Water.

Ferries run to a timetable (Red Funnel to Cowes, the Hythe ferry); leisure craft are Poisson trips
between marinas and moorings, scaled by an optional per-bin profile (busier on summer afternoons).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from sotonship26.demand.bins import FlowsByBin, add_binned, minutes_since
from sotonship26.routing import Flow


@dataclass(frozen=True)
class FerryRun:
    origin: Hashable
    destination: Hashable
    depart: datetime


def ferry_flows(
    runs: Iterable[FerryRun], *, day_start: datetime, bin_minutes: float, n_bins: int
) -> FlowsByBin:
    flows: dict[int, list[Flow]] = defaultdict(list)
    for run in runs:
        t = np.array([minutes_since(run.depart, day_start)])
        add_binned(flows, t, run.origin, run.destination, bin_minutes, n_bins)
    return dict(flows)


def leisure_flows(
    trips_per_hour: Mapping[tuple[Hashable, Hashable], float],
    *,
    rng: np.random.Generator,
    bin_minutes: float,
    n_bins: int,
    profile: np.ndarray | None = None,
) -> FlowsByBin:
    scale = np.ones(n_bins) if profile is None else np.asarray(profile, dtype=float)
    flows: dict[int, list[Flow]] = defaultdict(list)
    for (origin, dest), rate in trips_per_hour.items():
        counts = rng.poisson(rate * bin_minutes / 60.0 * scale)
        for b in np.flatnonzero(counts):
            flows[int(b)].append(Flow(origin, dest, float(counts[b])))
    return dict(flows)
