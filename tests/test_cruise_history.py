from datetime import date

import pandas as pd

from sotonship26.data import cruise_history as ch
from sotonship26.data import vts

# SYNTHETIC feeds in the VTS XML shape: made-up ships and visits, not real VTS rows (those can't be
# redistributed). The later snapshot confirms visit 1's time and drops nothing.
EARLY = b"""<?xml version="1.0" encoding="utf-8"?>
<exportResults><table><rows>
<row><visit_id>1</visit_id><ship_name>TEST SHIP ONE</ship_name><lloyds_no.>1000001</lloyds_no.>
<arrival>05-Jun-24 TBA</arrival><departure>05-Jun-24 TBA</departure><berth>46</berth></row>
<row><visit_id>2</visit_id><ship_name>TEST SHIP TWO</ship_name><lloyds_no.>1000002</lloyds_no.>
<arrival>07-Jun-24 06:00</arrival><departure>07-Jun-24 17:00</departure><berth>106</berth></row>
</rows></table></exportResults>"""

LATE = b"""<?xml version="1.0" encoding="utf-8"?>
<exportResults><table><rows>
<row><visit_id>1</visit_id><ship_name>TEST SHIP ONE</ship_name><lloyds_no.>1000001</lloyds_no.>
<arrival>05-Jun-24 06:15</arrival><departure>05-Jun-24 16:30</departure><berth>46</berth></row>
<row><visit_id>3</visit_id><ship_name>TEST SHIP THREE</ship_name><lloyds_no.>1000003</lloyds_no.>
<arrival>07-Jun-24 07:00</arrival><departure>07-Jun-24 18:00</departure><berth>999</berth></row>
</rows></table></exportResults>"""

CAPS = {"1000001": (3000, "lower_berth"), "1000002": (2000, "lower_berth")}


def parsed(xml: bytes, ts: str) -> pd.DataFrame:
    return vts.parse_feed(xml, pd.Timestamp(ts), capacities=CAPS)


def test_dock_side():
    assert ch.dock_side("Mayflower Cruise Terminal") == "western"
    assert ch.dock_side("Ocean Cruise Terminal") == "eastern"
    assert ch.dock_side("unknown") == "unknown"


def test_union_keeps_latest_snapshot():
    early, late = parsed(EARLY, "2024-06-01T08:00Z"), parsed(LATE, "2024-06-04T08:00Z")
    calls = ch.union_snapshots([late, early])  # order of frames must not matter
    assert list(calls.columns) == ch.CALL_COLUMNS
    assert sorted(calls["ship"]) == ["TEST SHIP ONE", "TEST SHIP THREE", "TEST SHIP TWO"]
    one = calls.set_index("ship").loc["TEST SHIP ONE"]
    assert one["arrival"].tz_localize(None) == pd.Timestamp("2024-06-05 06:15")
    assert one["snapshot_ts"] == pd.Timestamp("2024-06-04T08:00Z")
    assert one["dock_side"] == "eastern"
    three = calls.set_index("ship").loc["TEST SHIP THREE"]
    assert three["dock_side"] == "unknown"
    assert pd.isna(three["passengers"])


def test_snapshot_window():
    df = parsed(EARLY, "2024-06-01T08:00Z")
    assert ch.snapshot_window(df, pd.Timestamp("2024-06-01T08:00Z")) == (
        date(2024, 6, 1),
        date(2024, 6, 7),
    )


def test_cruise_days_zero_call_days_and_coverage():
    calls = ch.union_snapshots([parsed(EARLY, "2024-06-01T08:00Z")])
    days = ch.cruise_days(
        calls, date(2024, 5, 30), date(2024, 6, 9), windows=[(date(2024, 6, 1), date(2024, 6, 7))]
    )
    assert list(days.columns) == ch.DAY_COLUMNS
    assert len(days) == 11
    d = days.set_index("date")
    assert d.loc[date(2024, 6, 5), "n_calls"] == 1
    assert d.loc[date(2024, 6, 5), "pax_eastern"] == 3000
    assert d.loc[date(2024, 6, 7), "pax_western"] == 2000
    # A day inside the window with no call is a known non-cruise day...
    assert d.loc[date(2024, 6, 6), "n_calls"] == 0 and d.loc[date(2024, 6, 6), "covered"]
    # ...a day outside every window is unknown, not "no cruise".
    assert not d.loc[date(2024, 5, 30), "covered"]
    assert not d.loc[date(2024, 6, 9), "covered"]


def test_load_calls_from_snapshot_dir(tmp_path):
    snaps = tmp_path / "vts_snapshots"
    snaps.mkdir()
    (snaps / "sotcruiseship_20240601T080000Z.xml").write_bytes(EARLY)
    (snaps / "sotcruiseship_20240604T080000Z.xml").write_bytes(LATE)
    calls = ch.load_calls(date(2024, 6, 1), date(2024, 6, 30), raw_dir=tmp_path)
    assert len(calls) == 3
    days = ch.cruise_days(calls)
    covered = days[days["covered"]]["date"]
    assert covered.min() == date(2024, 6, 1) and covered.max() == date(2024, 6, 7)


def test_manual_import_and_vts_precedence(tmp_path):
    snaps = tmp_path / "vts_snapshots"
    snaps.mkdir()
    (snaps / "sotcruiseship_20240604T080000Z.xml").write_bytes(LATE)
    (tmp_path / "manual_calls.csv").write_text(
        "ship,arrival,berth,passengers,source\n"
        "Test Ship One,2024-06-05 06:00,46,2500,council\n"
        "Test Ship Four,2024-05-20,101,,council\n"
    )
    (tmp_path / "manual_coverage.csv").write_text(
        "start,end,source\n2024-05-15,2024-05-31,council\n"
    )
    calls = ch.load_calls(date(2024, 5, 1), date(2024, 6, 30), raw_dir=tmp_path)
    by_ship = calls.set_index("ship")
    assert by_ship.loc["TEST SHIP ONE", "source"] == "vts_feed"  # official row wins
    assert by_ship.loc["TEST SHIP FOUR", "dock_side"] == "western"
    assert by_ship.loc["TEST SHIP FOUR", "passengers_source"] == "missing"
    days = ch.cruise_days(calls).set_index("date")
    assert days.loc[date(2024, 5, 20), "covered"] and days.loc[date(2024, 5, 20), "n_calls"] == 1
    assert not days.loc[date(2024, 5, 10), "covered"]
