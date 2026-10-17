from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from sotonship26.data import observed
from sotonship26.forecast import simulator as sim

DAY = date(2026, 10, 24)
CALL = {
    "ship": "IONA",
    "terminal": "Ocean Cruise Terminal",
    "arrival": "2026-10-24T06:30+01:00",
    "departure": "2026-10-24T17:00+01:00",
    "passengers": 5200,
}


class Identity:
    def transform(self, lon, lat):
        return lon, lat


def fake_demo(probe_vph=40.0, fail=False):
    seen = {}
    sd = SimpleNamespace(CTX=None, MODE_MEAN=np.array(sim.SimParams().mode_shares), seen=seen)

    def forecast(task):
        seen.update(
            task=task,
            mode_mean=sd.MODE_MEAN.copy(),
            scale=sd.CTX.m.scale,
            scale_ext=sd.CTX.m.scale_ext,
            ctx=sd.CTX,
        )
        if fail:
            raise RuntimeError("boom")
        return {"probe": np.full(60, probe_vph)}

    sd.forecast = forecast
    sd.m271_probe = lambda m: [7, 8]
    sd.match_on = lambda d: None
    sd.in_term = lambda d: False
    sd.frame_origin = lambda: (0.0, 1000.0, Identity())
    return sd


def fake_ctx():
    return SimpleNamespace(m=SimpleNamespace(scale=1.0, scale_ext=2.0, scale_freight=3.0))


@pytest.fixture
def demo(monkeypatch):
    sd = fake_demo()
    monkeypatch.setattr(sim, "demo_module", lambda: sd)
    return sd


def test_rows_bins_and_units(demo):
    out = sim.simulate_uplift(DAY, calls=[CALL], ctx=fake_ctx())
    assert list(out.columns) == sim.COLUMNS
    assert len(out) == 96 and set(out["site_id"]) == {19974}
    assert str(out["bin_start"].dt.tz) == "Europe/London"
    assert out["bin_start"].iloc[0] == pd.Timestamp("2026-10-24 00:00", tz="Europe/London")
    u = out["uplift_veh"].to_numpy()
    assert (u[:20] == 0).all() and (u[80:] == 0).all()
    assert np.allclose(u[20:80], 10.0)  # 40 veh/h -> 10 per 15 minutes
    assert demo.seen["task"]["probe"] == [7, 8] and demo.seen["task"]["paired"]


def test_params_reach_the_demo_and_are_restored(demo):
    ctx = fake_ctx()
    p = sim.SimParams(
        mode_shares=(0.4, 0.2, 0.2, 0.15, 0.05),
        county_share=0.6,
        disembark_shift_min=30.0,
        background_scale=1.1,
    )
    sim.simulate_uplift(DAY, p, calls=[CALL], ctx=ctx, samples=3)
    assert np.allclose(demo.seen["mode_mean"], p.mode_shares)
    assert demo.seen["scale"] == pytest.approx(1.1) and demo.seen["scale_ext"] == pytest.approx(2.2)
    assert demo.seen["task"]["cruise"] == {"road": 1.0, "county": 0.6, "dis_shift": 30.0}
    assert demo.seen["task"]["n"] == 3 and demo.seen["ctx"] is ctx
    assert np.allclose(demo.MODE_MEAN, sim.SimParams().mode_shares)
    assert (ctx.m.scale, ctx.m.scale_ext, ctx.m.scale_freight) == (1.0, 2.0, 3.0)
    assert demo.CTX is None


def test_state_is_restored_when_the_demo_fails(monkeypatch):
    sd = fake_demo(fail=True)
    monkeypatch.setattr(sim, "demo_module", lambda: sd)
    ctx = fake_ctx()
    with pytest.raises(RuntimeError):
        sim.simulate_uplift(DAY, sim.SimParams(background_scale=1.5), calls=[CALL], ctx=ctx)
    assert (ctx.m.scale, ctx.m.scale_ext, sd.CTX) == (1.0, 2.0, None)


def test_no_ships_means_zero_without_running(demo):
    other_day = {**CALL, "arrival": "2026-10-25T06:30+00:00", "departure": "2026-10-25T17:00+00:00"}
    out = sim.simulate_uplift(DAY, calls=[other_day], ctx=fake_ctx())
    assert (out["uplift_veh"] == 0).all() and "task" not in demo.seen


def test_from_knobs():
    p = sim.SimParams.from_knobs(
        {
            "mode_share_car": 0.30,
            "county_share": 0.7,
            "arrival_offset_min": 45,
            "background_scale": 0.9,
        }
    )
    d = sim.SimParams()
    assert p.mode_shares[0] == pytest.approx(0.30) and sum(p.mode_shares) == pytest.approx(1.0)
    rest = np.array(d.mode_shares[1:]) / sum(d.mode_shares[1:]) * 0.70
    assert np.allclose(p.mode_shares[1:], rest)
    assert (p.county_share, p.disembark_shift_min, p.background_scale) == (0.7, 45.0, 0.9)
    with pytest.raises(ValueError, match="county_share"):
        sim.SimParams.from_knobs({"approach_share_western": 0.5})
    with pytest.raises(ValueError, match="unknown knob"):
        sim.SimParams.from_knobs({"nonsense": 1})
    with pytest.raises(ValueError, match="more than 1"):
        sim.SimParams.from_knobs({"mode_share_car": 0.8, "mode_share_coach": 0.4})


def test_params_are_checked():
    with pytest.raises(ValueError):
        sim.SimParams(mode_shares=(0.5, 0.5, 0.5, 0.0, 0.0))
    with pytest.raises(ValueError):
        sim.SimParams(county_share=1.5)


def test_demo_calls_maps_terminals_and_days():
    calls = [
        CALL,
        {**CALL, "ship": "VENTURA", "terminal": "Mayflower"},
        {**CALL, "ship": "MYSTERY", "terminal": "Somewhere Else"},
        {**CALL, "ship": "LATER", "arrival": "2026-10-25T06:30+00:00"},
    ]
    with pytest.warns(UserWarning, match="outside the model"):
        out = sim.demo_calls(DAY, pd.DataFrame(calls))
    assert [c["ship"] for c in out] == ["IONA", "VENTURA"]
    assert out[0] == {
        "ship": "IONA",
        "terminal": "Ocean",
        "arrival": "2026-10-24T06:30",
        "departure": "2026-10-24T17:00",
        "pax": 5200,
    }


def test_site_links_by_road_direction_and_distance(monkeypatch):
    sd = fake_demo()
    monkeypatch.setitem(
        observed.SITES,
        99001,
        {"road": "M271", "direction": "northbound", "lat": 500.0, "lon": 100.0},
    )
    monkeypatch.setitem(
        observed.SITES,
        99002,
        {"road": "M271", "direction": "northbound", "lat": 500.0, "lon": 5000.0},
    )
    # site 99001 sits at grid (100, 500); y runs south, so northbound means y falls
    m = SimpleNamespace(
        t0=[1, 1, 1],
        ref=["M271", "M271", "M27"],
        cls=["motorway"] * 3,
        coords=[
            [(110, 400), (110, 600)],  # southbound, close
            [(120, 600), (120, 400)],  # northbound, close
            [(100, 600), (100, 400)],
        ],
    )  # northbound but the M27
    assert sim.site_links(m, 99001, sd) == [1]
    assert sim.site_links(m, 19974, sd) == [7, 8]
    with pytest.raises(ValueError, match="no model link"):
        sim.site_links(m, 99002, sd)
    with pytest.raises(ValueError, match="unknown WebTRIS site"):
        sim.site_links(m, 12345, sd)


def test_simulator_matches_calibrate_contract(demo):
    out = sim.simulator(
        {"mode_share_car": 0.25}, [DAY, date(2026, 10, 25)], calls=[CALL], samples=1, ctx=fake_ctx()
    )
    assert len(out) == 192 and {"site_id", "date", "tod_bin", "uplift_veh"} <= set(out.columns)


needs_ctx = pytest.mark.skipif(not sim.CTX_PATH.exists(), reason="demo model cache not built here")


@needs_ctx
def test_real_demo_calibration_saturday():
    sd = sim.demo_module()
    assert np.allclose(sd.MODE_MEAN, sim.SimParams().mode_shares)
    calls = [
        {
            "ship": "Calibration East",
            "terminal": "Ocean",
            "arrival": "2026-10-24T06:30",
            "departure": "2026-10-24T17:00",
            "passengers": 5000,
        },
        {
            "ship": "Calibration West",
            "terminal": "Mayflower",
            "arrival": "2026-10-24T06:30",
            "departure": "2026-10-24T17:00",
            "passengers": 5000,
        },
    ]
    out = sim.simulate_uplift(DAY, calls=calls, samples=2)
    assert len(out) == 96 and out["uplift_veh"].iloc[20:80].sum() > 0
