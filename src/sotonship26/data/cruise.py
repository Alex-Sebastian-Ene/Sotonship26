"""Cruise schedule: which ships turn around at which terminal, when, and how full.

Expects a CSV with ``ship, terminal, arrival, departure, passengers`` and optionally ``length_m``
(times as ISO 8601 local times). Southampton VTS publishes cruise schedules on public web pages;
transcribe the days you need into this shape under ``data/raw/`` (gitignored: there is no API and
no permission to redistribute, so don't commit it) and record the date you collected it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CruiseCall:
    ship: str
    terminal: str
    arrival: datetime
    departure: datetime
    passengers: int  # lower-berth capacity, or the line's expected count if known
    length_m: float | None = None


def load_schedule(path: str | Path) -> list[CruiseCall]:
    df = pd.read_csv(path, parse_dates=["arrival", "departure"])
    has_length = "length_m" in df.columns
    return [
        CruiseCall(
            ship=str(row.ship),
            terminal=str(row.terminal),
            arrival=row.arrival.to_pydatetime(),
            departure=row.departure.to_pydatetime(),
            passengers=int(row.passengers),
            length_m=float(row.length_m) if has_length and pd.notna(row.length_m) else None,
        )
        for row in df.itertuples(index=False)
    ]
