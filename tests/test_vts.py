from datetime import date, datetime

import pandas as pd
import pytest

from sotonship26.data import vts

# SYNTHETIC feed in the VTS XML shape: made-up ships and visits, not real VTS rows (those can't be
# redistributed). It covers a confirmed call, vague AM/PM/TBA times, an unknown berth and a
# duplicated visit.
FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<exportResults><table><rows>
<row><visit_id>1</visit_id><ship_name>TEST SHIP ONE</ship_name><lloyds_no.>1000001</lloyds_no.>
<voyage_state>P</voyage_state><arrival>17-Oct-26 05:45</arrival>
<departure>17-Oct-26 17:00</departure><berth>46</berth></row>
<row><visit_id>2</visit_id><ship_name>TEST SHIP TWO</ship_name><lloyds_no.>1000002</lloyds_no.>
<voyage_state>P</voyage_state><arrival>21-Oct-26 AM</arrival><departure>21-Oct-26 PM</departure>
<berth>38/9</berth></row>
<row><visit_id>3</visit_id><ship_name>TEST SHIP THREE</ship_name><lloyds_no.>1000003</lloyds_no.>
<voyage_state>P</voyage_state><arrival>20-Oct-26 TBA</arrival><departure>20-Oct-26 TBA</departure>
<berth>999</berth></row>
<row><visit_id>2</visit_id><ship_name>TEST SHIP TWO</ship_name><lloyds_no.>1000002</lloyds_no.>
<voyage_state>P</voyage_state><arrival>21-Oct-26 AM</arrival><departure>21-Oct-26 PM</departure>
<berth>38/9</berth></row>
</rows></table></exportResults>"""

COLLECTED = pd.Timestamp("2026-10-16T22:40:00Z")


def parse(capacities=None):
    return vts.parse_feed(FEED, COLLECTED, capacities=capacities or {})


def test_contract_columns_and_order():
    df = parse()
    assert list(df.columns) == vts.COLUMNS
    contract = ["ship", "terminal", "arrival", "departure", "passengers", "collected_at"]
    assert list(df.columns[:6]) == contract
    assert len(df) == 3  # duplicate visit dropped
    assert df["arrival"].is_monotonic_increasing
    assert str(df["arrival"].dt.tz) == "Europe/London"
    assert (df["collected_at"] == COLLECTED).all()


def test_confirmed_and_vague_times():
    df = parse().set_index("visit_id")
    one = df.loc["1"]
    assert one["time_confirmed"]
    assert one["arrival"].tz_localize(None) == pd.Timestamp("2026-10-17 05:45")
    two = df.loc["2"]
    assert not two["time_confirmed"]
    assert two["arrival"].time() == vts.VAGUE_TIMES["arrival"]["AM"]
    assert two["departure"].time() == vts.VAGUE_TIMES["departure"]["PM"]
    assert not df.loc["3", "time_confirmed"]


def test_terminals_from_berth():
    df = parse().set_index("visit_id")
    assert df.loc["1", "terminal"] == "Ocean Cruise Terminal"
    assert df.loc["2", "terminal"] == "QEII Cruise Terminal"
    assert df.loc["3", "terminal"] == vts.UNKNOWN_TERMINAL


def test_passengers_from_capacity_or_flagged_missing():
    df = parse({"1000001": (3000, "lower_berth_uncertain")}).set_index("visit_id")
    assert df.loc["1", "passengers"] == 3000
    assert df.loc["1", "passengers_source"] == "lower_berth_uncertain"
    assert pd.isna(df.loc["2", "passengers"])
    assert df.loc["2", "passengers_source"] == "missing"


def test_shipped_capacity_table_loads():
    caps = vts.load_capacities()
    assert len(caps) >= 22
    assert all(n > 0 and src.startswith("lower_berth") for n, src in caps.values())


def test_to_cruise_calls_skips_missing_passengers():
    df = parse({"1000001": (3000, "lower_berth")})
    with pytest.warns(UserWarning, match="no passenger figure"):
        calls = vts.to_cruise_calls(df)
    assert [c.ship for c in calls] == ["TEST SHIP ONE"]
    assert calls[0].arrival == datetime(2026, 10, 17, 5, 45)
    assert vts.to_cruise_calls(df, day=date(2026, 10, 17))[0].passengers == 3000


def test_horizon_and_collected_at_from_cache_name(tmp_path):
    assert vts.schedule_horizon(parse()) == date(2026, 10, 21)
    path = tmp_path / "sotcruiseship_20261016T224000Z.xml"
    path.write_bytes(FEED)
    assert vts.collected_at(path) == COLLECTED
    assert vts.latest_cached(tmp_path) == path


def test_load_schedule_falls_back_to_cache_when_fetch_fails(tmp_path, monkeypatch):
    (tmp_path / "sotcruiseship_20261016T224000Z.xml").write_bytes(FEED)

    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(vts, "fetch_feed", offline)
    with pytest.warns(UserWarning, match="using cache"):
        df = vts.load_schedule(raw_dir=tmp_path, refresh=True)
    assert len(df) == 3
    with pytest.raises(OSError):
        vts.load_schedule(raw_dir=tmp_path / "empty")
