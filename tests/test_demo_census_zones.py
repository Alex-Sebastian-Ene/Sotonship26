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


def test_peak_spreading_moves_what_cannot_fit_and_keeps_totals():
    from types import SimpleNamespace

    import numpy as np
    import scipy.sparse as sp

    # one OD pair on one route over one link of 100 veh/h; its other two routes are unused
    A = sp.csr_matrix(([1.0], ([0], [0])), shape=(1, tm.ROUTES))
    m = SimpleNamespace(n_od=1, A=A, AT=A.T.tocsr())
    shares = np.zeros((tm.N_BINS, 1, tm.ROUTES))
    shares[:, 0, 0] = 1.0
    D = np.zeros((tm.N_BINS, 1))
    D[10, 0] = 50.0  # 200 veh/h for a 15-minute bin: twice what fits
    out, f = tm.spread_peaks(m, {1: D, 0: D.copy()}, np.array([100.0]), shares)
    assert out.sum() == pytest.approx(100.0)  # nothing lost
    # the commuter-like half spreads to the bins either side, never further; the school run stays
    assert out[10, 0] < 100.0 and out[9, 0] > 0 and out[11, 0] > 0
    assert out[[8, 12], 0].sum() == 0
    assert f[1][10, 0] < 1.0 and f[0][10, 0] == 1.0
