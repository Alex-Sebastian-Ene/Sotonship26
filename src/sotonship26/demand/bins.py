from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Mapping
from datetime import datetime

import numpy as np

from sotonship26.routing import Flow

FlowsByBin = dict[int, list[Flow]]


def minutes_since(t: datetime, day_start: datetime) -> float:
    return (t - day_start).total_seconds() / 60.0


def add_binned(
    flows: dict[int, list[Flow]],
    minutes: np.ndarray,
    source: Hashable,
    target: Hashable,
    bin_minutes: float,
    n_bins: int,
) -> None:
    """Histogram individual departure times into per-bin flows; times outside the day drop out."""
    bins = np.floor(np.asarray(minutes) / bin_minutes).astype(int)
    bins = bins[(bins >= 0) & (bins < n_bins)]
    counts = np.bincount(bins, minlength=n_bins)
    for b in np.flatnonzero(counts):
        flows[int(b)].append(Flow(source, target, float(counts[b])))


def merge(*parts: Mapping[int, list[Flow]]) -> FlowsByBin:
    out: dict[int, list[Flow]] = defaultdict(list)
    for part in parts:
        for b, flows in part.items():
            out[b].extend(flows)
    return dict(out)
