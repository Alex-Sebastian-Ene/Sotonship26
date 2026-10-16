"""Passenger flows on a cruise turnaround day.

A turnaround ship disembarks its arriving passengers through the morning and embarks the next
sailing's from late morning until shortly before departure. Only the share who walk (to the station,
the city centre, Town Quay) load the streets; coach, car and taxi passengers leave from the
terminal forecourt. Every number in ``TurnaroundParams`` is a starting guess to calibrate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from sotonship26.data.cruise import CruiseCall
from sotonship26.demand.bins import FlowsByBin, add_binned, minutes_since


@dataclass(frozen=True)
class TurnaroundParams:
    walk_share: float = 0.3
    load_factor_beta: tuple[float, float] = (18.0, 2.0)  # mean 0.9
    arrival_delay_sd_min: float = 20.0
    disembark_start_min: float = 45.0  # after the ship is alongside
    disembark_duration_min: float = 210.0
    embark_open_before_dep_min: float = 360.0
    embark_close_before_dep_min: float = 90.0


def turnaround_flows(
    call: CruiseCall,
    terminal: Hashable,
    destinations: Mapping[Hashable, float],
    *,
    rng: np.random.Generator,
    day_start: datetime,
    bin_minutes: float,
    n_bins: int,
    params: TurnaroundParams | None = None,
) -> FlowsByBin:
    """Sample one day's walking flows for ``call``: terminal -> destinations, then back."""
    params = params or TurnaroundParams()
    names = list(destinations)
    shares = np.array([destinations[d] for d in names], dtype=float)
    shares /= shares.sum()
    flows: dict[int, list] = defaultdict(list)

    delay = rng.normal(0.0, params.arrival_delay_sd_min)
    start = minutes_since(call.arrival, day_start) + delay + params.disembark_start_min
    for dest, k in zip(names, rng.multinomial(_walkers(call, rng, params), shares), strict=True):
        t = start + params.disembark_duration_min * rng.beta(2.0, 3.0, size=k)
        add_binned(flows, t, terminal, dest, bin_minutes, n_bins)

    dep = minutes_since(call.departure, day_start)
    lo = dep - params.embark_open_before_dep_min
    hi = dep - params.embark_close_before_dep_min
    for dest, k in zip(names, rng.multinomial(_walkers(call, rng, params), shares), strict=True):
        t = lo + (hi - lo) * rng.beta(2.0, 2.0, size=k)
        add_binned(flows, t, dest, terminal, bin_minutes, n_bins)
    return dict(flows)


def _walkers(call: CruiseCall, rng: np.random.Generator, params: TurnaroundParams) -> int:
    aboard = round(call.passengers * rng.beta(*params.load_factor_beta))
    return int(rng.binomial(aboard, params.walk_share))
