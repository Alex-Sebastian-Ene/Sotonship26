"""From parked-car counts to the park-and-cruise share.

Cruise passengers who drive and park leave the car for the whole voyage: parked on the morning
they embark, collected on the morning they come back. So the cars in a dock's cruise car parks at
the moment an image is taken are

    cars = base + share x (passengers on that dock's voyages still at sea) / people_per_car

where ``base`` is staff, short-stay and other parking. A voyage runs from a ship's departure on one
Southampton call to its arrival on the next call of the same ship. On the embark and return days
only part of the cars are there, by time of day (check-in fills the car parks late morning to
mid-afternoon; disembarking passengers leave early to mid-morning).

``fit_share`` estimates ``share`` and ``base`` per dock by least squares over all counted images
and gives a bootstrap 80% range. With one image per day this measures the on-site share only:
passengers using off-site park-and-ride or meet-and-greet firms are not in these car parks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

DOCK_OF_TERMINAL = {
    "Ocean": "east",
    "QEII": "east",
    "Queen Elizabeth": "east",
    "Mayflower": "west",
    "City": "west",
    "Horizon": "west",
}
PEOPLE_PER_CAR = 2.4
MAX_VOYAGE_DAYS = 21  # a gap longer than this is not one voyage (ship left the region)
DEFAULT_VOYAGE_DAYS = 7
EMBARK_WINDOW_H = (10.5, 15.5)  # check-in: cars arrive evenly in this window on embark day
RETURN_WINDOW_H = (7.0, 11.0)  # disembarkation: cars leave evenly in this window on return day


@dataclass(frozen=True)
class Voyage:
    ship: str
    dock: str
    embark: datetime  # departure from Southampton
    back: datetime  # arrival back in Southampton (next call of the same ship)
    passengers: float


def dock_of(terminal: str) -> str:
    for key, dock in DOCK_OF_TERMINAL.items():
        if terminal.startswith(key):
            return dock
    raise KeyError(f"unknown terminal {terminal!r}")


def voyages(calls: pd.DataFrame) -> list[Voyage]:
    """Voyages from Southampton calls (columns ship, terminal, arrival, departure, passengers)."""
    out = []
    df = calls.sort_values(["ship", "arrival"])
    for ship, g in df.groupby("ship"):
        rows = g.to_dict("records")
        for i, r in enumerate(rows):
            nxt = rows[i + 1]["arrival"] if i + 1 < len(rows) else None
            dep = pd.Timestamp(r["departure"]).to_pydatetime()
            if nxt is not None and (pd.Timestamp(nxt) - pd.Timestamp(dep)).days <= MAX_VOYAGE_DAYS:
                back = pd.Timestamp(nxt).to_pydatetime()
            else:
                back = dep + timedelta(days=DEFAULT_VOYAGE_DAYS)
            pax = float(r["passengers"]) if pd.notna(r["passengers"]) else np.nan
            out.append(Voyage(str(ship), dock_of(str(r["terminal"])), dep, back, pax))
    return out


def _ramp(h: float, lo: float, hi: float) -> float:
    return float(np.clip((h - lo) / (hi - lo), 0.0, 1.0))


def parked_fraction(v: Voyage, when: datetime) -> float:
    """Share of the voyage's parked cars present at ``when``."""
    h = when.hour + when.minute / 60
    if when.date() < v.embark.date() or when.date() > v.back.date():
        return 0.0
    if when.date() == v.embark.date():
        return _ramp(h, *EMBARK_WINDOW_H)
    if when.date() == v.back.date():
        return 1.0 - _ramp(h, *RETURN_WINDOW_H)
    return 1.0


def passengers_away(vs: list[Voyage], when: datetime, dock: str) -> float:
    """Passengers on ``dock``'s voyages whose cars would be parked at ``when``."""
    return float(
        sum(
            v.passengers * parked_fraction(v, when)
            for v in vs
            if v.dock == dock and not np.isnan(v.passengers)
        )
    )


@dataclass
class ShareFit:
    dock: str
    share: float
    share_p10: float
    share_p90: float
    base: float
    n_images: int
    resid_sd: float

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def fit_share(
    counts: pd.DataFrame, vs: list[Voyage], boot: int = 2000, seed: int = 26
) -> list[ShareFit]:
    """Fit cars = base + share x passengers_away / PEOPLE_PER_CAR per dock.

    ``counts`` has columns ``when`` (image time, local), ``dock`` and ``cars`` (cars counted in that
    dock's cruise car parks; multi-storey top decks only, so keep the same car parks every image).
    """
    rng = np.random.default_rng(seed)
    out = []
    for dock, g in counts.groupby("dock"):
        x = (
            np.array(
                [passengers_away(vs, pd.Timestamp(w).to_pydatetime(), dock) for w in g["when"]]
            )
            / PEOPLE_PER_CAR
        )
        y = g["cars"].to_numpy(float)
        if len(y) < 3 or np.ptp(x) == 0:
            raise ValueError(
                f"{dock}: need at least 3 images with different numbers of passengers away"
            )

        def solve(xx, yy):
            a = np.column_stack([np.ones_like(xx), xx])
            (b0, b1), *_ = np.linalg.lstsq(a, yy, rcond=None)
            return max(b0, 0.0), float(np.clip(b1, 0.0, 1.0))

        base, share = solve(x, y)
        draws = []
        for _ in range(boot):
            idx = rng.integers(0, len(y), len(y))
            if np.ptp(x[idx]) > 0:
                draws.append(solve(x[idx], y[idx])[1])
        resid = y - (base + share * x)
        out.append(
            ShareFit(
                dock,
                share,
                float(np.percentile(draws, 10)),
                float(np.percentile(draws, 90)),
                base,
                len(y),
                float(resid.std(ddof=2)) if len(y) > 2 else float("nan"),
            )
        )
    return out


def simulate_counts(
    vs: list[Voyage],
    times: list[datetime],
    share: dict[str, float],
    base: dict[str, float],
    noise_sd: float = 15.0,
    seed: int = 1,
) -> pd.DataFrame:
    """Synthetic counts for testing the fit (never shown as observed)."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in times:
        for dock in share:
            mean = base[dock] + share[dock] * passengers_away(vs, t, dock) / PEOPLE_PER_CAR
            rows.append({"when": t, "dock": dock, "cars": max(0.0, mean + rng.normal(0, noise_sd))})
    return pd.DataFrame(rows)
