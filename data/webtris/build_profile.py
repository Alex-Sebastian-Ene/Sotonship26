"""Rebuild m271_speed_profile.csv from m271_speed_15min.csv.gz.

Provenance + reproducibility for the committed profile. Run from the repo root:

    uv run python data/webtris/build_profile.py

Derivation: group the full 15-min series by (site, local weekday, 15-min-of-day)
and take the median/15th-percentile speed, median flow, and count per cell. The
grain and the stats are a *default* speed prior, not a requested spec -- re-cut
by editing AGG / the groupby keys below (e.g. mean instead of median, a holiday
vs term split) if the forecast engine wants a different shape.

Source: National Highways WebTRIS (OGL v3.0); see README.md in this folder.
"""
from __future__ import annotations

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES = os.path.join(HERE, "m271_speed_15min.csv.gz")
OUT = os.path.join(HERE, "m271_speed_profile.csv")

# Per-cell aggregates. Edit here to re-cut the prior.
AGG = {
    "mph_median": ("mph", "median"),
    "mph_p15": ("mph", lambda s: s.quantile(0.15)),  # a "bad-but-not-worst" floor
    "flow_median": ("flow_veh", "median"),
    "n_speed": ("mph", "count"),
}
KEYS = ["site_id", "road", "direction", "weekday", "tod_min"]


def build() -> pd.DataFrame:
    df = pd.read_csv(SERIES)
    # bin_start carries mixed BST/GMT offsets -> parse as UTC, then local wall clock.
    local = pd.to_datetime(df["bin_start"], utc=True).dt.tz_convert("Europe/London")
    df["weekday"] = local.dt.dayofweek               # 0=Mon .. 6=Sun (local)
    df["tod_min"] = local.dt.hour * 60 + local.dt.minute
    g = df.groupby(KEYS).agg(**AGG).reset_index()
    return g.sort_values(KEYS).reset_index(drop=True)


def main() -> None:
    g = build()
    g.to_csv(OUT, index=False)
    print(f"rows={len(g)} bytes={os.path.getsize(OUT)} -> {OUT}")


if __name__ == "__main__":
    main()
