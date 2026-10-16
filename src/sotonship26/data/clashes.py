"""Things that load the same roads as a cruise turnaround: home matches at St Mary's (for now).

``saints_fixtures.csv`` lists Southampton FC men's home fixtures from 17 Oct 2026 to 29 Jan 2027,
taken from the club's fixtures page on 16 Oct 2026 by the research desk (SOT-18), with TV-moved
kick-offs applied. Not yet in it: the FA Cup third round (drawn later) and women's games at
St Mary's. Roadworks permits aren't loaded: Street Manager has no bulk query, so the what-if screen
takes a permit typed in by the officer.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURES_CSV = Path(__file__).resolve().parent / "saints_fixtures.csv"


def load_fixtures(path: str | Path = FIXTURES_CSV) -> pd.DataFrame:
    """Home fixtures: ``date`` (datetime.date), ``kickoff`` ("HH:MM"), competition, opponent,
    source_url, retrieved."""
    df = pd.read_csv(path, dtype=str)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df
