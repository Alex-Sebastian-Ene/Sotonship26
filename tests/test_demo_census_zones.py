"""Zone homes and jobs from Census 2021 counts per MSOA (traffic_model.census_zone_weights)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("scipy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import traffic_model as tm  # noqa: E402


def zone(name, xy):
    return tm.Centroid(name, "zone", 0, xy)


def test_census_counts_are_shared_by_land_use_and_kept_whole():
    zones = [zone("West", (1000, 1000)), zone("East", (4000, 1000))]
    msoas = [{"msoa": "A", "x": 1500, "y": 1000, "residents": 900, "jobs": 100},
             {"msoa": "B", "x": 4000, "y": 1200, "residents": 300, "jobs": 600}]
    samples = [("residential", 1000, 1000, 2.0),  # in A, nearest West
               ("residential", 2400, 1000, 1.0),  # in A, nearest West
               ("residential", 2600, 1000, 1.0),  # in A (nearer its centroid), nearest East
               ("residential", 4000, 1000, 5.0),  # in B, nearest East
               ("industrial", 4100, 1000, 10.0),  # B's jobs
               ("residential", 9000, 1000, 50.0)]  # outside the 6 km frame: left out
    tm.census_zone_weights(zones, samples, (6000, 3000), msoas, log=lambda *_: None)
    west, east = zones
    assert west.homes + east.homes == pytest.approx(1200)  # every resident placed once
    assert west.homes == pytest.approx(900 * 3 / 4) and east.homes == pytest.approx(900 / 4 + 300)
    # A has no job land use, so its 100 jobs go to its nearest zone; B's 600 sit on its industry
    assert west.jobs == pytest.approx(100) and east.jobs == pytest.approx(600)


def test_motorway_gateways_name_their_next_count():
    assert set(tm.MOTORWAY_NEXT) == {"M27 west", "M27 east", "M3 north"}
    assert all(isinstance(k, int) for ids in tm.MOTORWAY_NEXT.values() for k in ids)


def test_university_term_takes_ten_percent_off_only_in_term():
    from datetime import date

    assert tm.uni_term_factor(date(2026, 10, 19)) == pytest.approx(0.9)
    assert tm.uni_term_factor(date(2026, 12, 12)) == pytest.approx(0.9)  # last day of term
    assert tm.uni_term_factor(date(2026, 12, 14)) == 1.0  # Christmas vacation
    assert tm.uni_term_factor(date(2027, 1, 4)) == pytest.approx(0.9)


def test_wet_day_chance_uses_the_forecast_then_climatology(monkeypatch):
    from datetime import date

    import synthetic_demo as sd

    monkeypatch.setattr(sd, "WEATHER", {"p_rain": {"2026-10-20": 0.88, "2026-11-01": None}})
    assert sd.p_wet(date(2026, 10, 20)) == pytest.approx(0.88)
    assert sd.p_wet(date(2026, 11, 1)) == sd.P_WET[11]  # no forecast that day
    assert sd.p_wet(date(2026, 12, 5)) == sd.P_WET[12]
    dry = sd.day_multipliers(date(2026, 10, 21), False)
    wet = sd.day_multipliers(date(2026, 10, 21), True)
    assert dry["internal"] == pytest.approx(sd.DRY_DEMAND)
    assert wet["internal"] == pytest.approx(sd.WET_DEMAND)
