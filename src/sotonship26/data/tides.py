"""UKHO ADMIRALTY tide predictions.

``fetch_events`` calls the ADMIRALTY UK Tidal API (the free Discovery tier gives high and low waters
for the next 7 days) using the key in ``UKHO_API_KEY``. ``height_at`` interpolates between events
with a half-cosine. Southampton's double high water and young-flood stand make that a rough fit
between events, so replace it with a proper tidal curve (higher API tiers or harmonic constants)
before relying on mid-tide depths.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

API_ROOT = "https://admiraltyapi.azure-api.net/uktidalapi/api/V1"


@dataclass(frozen=True)
class TidalEvent:
    time: datetime
    height_m: float  # above chart datum
    kind: str  # "HighWater" or "LowWater"


def fetch_events(
    station_id: str, days: int = 7, api_key: str | None = None, timeout: float = 30.0
) -> list[TidalEvent]:
    key = api_key or os.environ["UKHO_API_KEY"]
    request = urllib.request.Request(
        f"{API_ROOT}/Stations/{station_id}/TidalEvents?duration={days}",
        headers={"Ocp-Apim-Subscription-Key": key},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return [
        TidalEvent(datetime.fromisoformat(e["DateTime"]), float(e["Height"]), e["EventType"])
        for e in payload
    ]


def height_at(events: Sequence[TidalEvent], t: datetime) -> float:
    """Tide height at ``t`` by half-cosine interpolation between the surrounding events."""
    times = [e.time for e in events]
    if not times[0] <= t <= times[-1]:
        raise ValueError(f"{t} is outside the predicted range {times[0]} to {times[-1]}")
    i = min(bisect.bisect_right(times, t), len(events) - 1)
    before, after = events[i - 1], events[i]
    frac = (t - before.time) / (after.time - before.time)
    return before.height_m + (after.height_m - before.height_m) * (1 - math.cos(math.pi * frac)) / 2
