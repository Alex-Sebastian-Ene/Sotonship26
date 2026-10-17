"""Day-to-day port lorries from Southampton VTS freight ship calls (SOT-24).

The DfT lorry fit (``traffic_model.calibrate_freight``) sets how many port lorries an average day
has. For days the VTS planned-movements feed covers in full (about five days ahead), that day's
container and ro-ro arrivals and departures reshape it:

    factor = 1 + SHRINK x (movements that day / mean movements over the covered days - 1)

Ship calls to lorries is an assumption, not fitted: a container waits in the terminal for days, so
a busy ship day spreads its lorries over several days. SHRINK halves the swing for that reason.
Days the feed does not cover in full keep factor 1.0, the DfT-fitted average. The movements come
from ``sotonship26.data.vts_freight.daily_freight_calls``. Source: Southampton VTS, ABP.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

SHRINK = 0.5
CREDIT = "Southampton VTS, ABP"


def freight_day_factors(days: pd.DataFrame | None, shrink: float = SHRINK) -> dict[str, dict]:
    """Factor per ISO date for the days ``days`` covers in full (``complete``), with the movement
    counts behind it. ``days`` has the columns of ``daily_freight_calls``."""
    if days is None or not len(days):
        return {}
    full = days[days["complete"].astype(bool)]
    mean = float(full["freight_moves"].mean()) if len(full) else 0.0
    if mean <= 0:
        return {}
    out = {}
    for r in full.itertuples(index=False):
        raw = r.freight_moves / mean
        out[pd.Timestamp(r.date).date().isoformat()] = {
            "factor": round(1.0 + shrink * (raw - 1.0), 3), "moves": int(r.freight_moves),
            "mean_moves": round(mean, 1), "unconfirmed": int(r.unconfirmed)}
    return out


def factor_on(factors: dict[str, dict], d: date) -> float:
    """The day's factor, 1.0 where the feed does not cover it."""
    return factors.get(d.isoformat(), {}).get("factor", 1.0)
