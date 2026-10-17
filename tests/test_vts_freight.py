from datetime import date

import pandas as pd
import pytest

from sotonship26.data import vts_freight as vf

# SYNTHETIC feeds in the VTS XML shape: made-up ships, IMOs and agents, not real VTS rows (those
# can't be redistributed).


def _move(ship, imo, vtype, when, vt, origin, dest, gt, agent="TEST AGENCY"):
    return (
        f"<row><ship_name>{ship}</ship_name><type>{vtype}</type><eta_etd>{when}</eta_etd>"
        f"<dir>Nab</dir><origin>{origin}</origin><destination>{dest}</destination>"
        f"<draft>9.10</draft><agent>{agent}</agent><voyage_type>{vt}</voyage_type>"
        f"<lloyds_no.>{imo}</lloyds_no.><loa>200.00</loa><dwt>20000</dwt><gt>{gt}</gt>"
        f"<abp_port>Southampton</abp_port></row>"
    )


def _feed(*rows: str) -> bytes:
    return f"<exportResults><table><rows>{''.join(rows)}</rows></table></exportResults>".encode()


BOX = "Container Carrier (UCC)"
RORO = "Ro/Ro (URR)"
CARS = "Vehicle (MVE)"
PAX = "Passenger (MPR)"

EARLY = _feed(
    _move("TEST BOX ONE", "9000001", BOX, "18-Oct-2026 AM", "A", "Testport", "SCT1/2", 100000),
    _move("TEST BOX ONE", "9000001", BOX, "19-Oct-2026 07:30", "D", "SCT1/2", "Testport", 100000),
    _move("TEST CARS", "9000002", CARS, "18-Oct-2026 09:30", "A", "Testport", "35", 60000),
    _move("TEST CARS", "9000002", CARS, "18-Oct-2026 22:15", "D", "35", "Testport", 60000),
    _move("TEST RORO", "9000003", RORO, "20-Oct-2026 TBA", "A", "Testport", "105", 50000),
    _move("TEST RORO", "9000003", RORO, "20-Oct-2026 10:00", "M", "105", "102", 50000),
    _move("TEST LINER", "9000004", PAX, "18-Oct-2026 06:00", "A", "X", "106", 90000),
    _move("TEST STEAMER", "9000005", PAX, "18-Oct-2026 15:00", "M", "38", "110", 1700),
    _move("TEST TANKER", "9000006", "Tank (TTA)", "18-Oct-2026 11:15", "A", "X", "Esso Berth 4", 9),
    _move("TEST ISLAND", "9000007", "Passenger Ro/Ro (PRR)", "19-Oct-2026 AM", "M", "48",
          "Royal Pier", 3000, agent="RED FUNNEL FERRIES LTD"),
    _move("TEST BARGE", "", "Barge (OBA)", "19-Oct-2026 PM", "M", "46 O/S", "Moorings", 200),
    _move("TEST NODATE", "9000008", RORO, "TBA", "A", "X", "105", 1000),
)
# Two days later: TEST BOX ONE's time is fixed, TEST RORO's arrival confirmed, a new ship added.
LATE = _feed(
    _move("TEST BOX ONE", "9000001", BOX, "18-Oct-2026 06:00", "A", "Testport", "SCT1/2", 100000),
    _move("TEST BOX ONE", "9000001", BOX, "19-Oct-2026 07:30", "D", "SCT1/2", "Testport", 100000),
    _move("TEST RORO", "9000003", RORO, "20-Oct-2026 08:00", "A", "Testport", "105", 50000),
    _move("TEST BOX TWO", "9000009", BOX, "21-Oct-2026 19:00", "A", "Testport", "SCT5", 20000),
)

BERTHED = _feed(
    "<row><ship_name>TEST ALONGSIDE</ship_name><berth>101</berth>"
    "<estimated_departure_time>17-Oct-2026 14:00</estimated_departure_time><gt>47000</gt>"
    "<actual_arrival_time>17-Oct-2026 03:02</actual_arrival_time><lloyds_no.>9000010</lloyds_no.>"
    f"<type>{RORO}</type><agent>TEST AGENCY</agent></row>",
    "<row><ship_name>TEST WAITING</ship_name><berth>SCT5</berth>"
    "<estimated_departure_time>17-Oct-2026 PM</estimated_departure_time><gt>90000</gt>"
    "<actual_arrival_time>16-Oct-2026 10:42</actual_arrival_time><lloyds_no.>9000011</lloyds_no.>"
    f"<type>{BOX}</type><agent>TEST AGENCY</agent></row>",
    "<row><ship_name>TEST TUG</ship_name><berth>Esso Tug Berth</berth>"
    "<estimated_departure_time></estimated_departure_time><gt>600</gt>"
    "<actual_arrival_time>02-Oct-2026 14:40</actual_arrival_time><lloyds_no.></lloyds_no.>"
    "<type>Tug (XTG)</type><agent>TEST TOWAGE</agent></row>",
)

T_EARLY = pd.Timestamp("2026-10-17T08:00Z")
T_LATE = pd.Timestamp("2026-10-19T08:00Z")


def early() -> pd.DataFrame:
    with pytest.warns(UserWarning, match="TEST NODATE"):
        return vf.parse_extract(EARLY, T_EARLY)


def late() -> pd.DataFrame:
    return vf.parse_extract(LATE, T_LATE)


def test_parse_extract_columns_and_types():
    df = early()
    assert list(df.columns) == vf.EXTRACT_COLUMNS
    assert len(df) == 11 and df.attrs["skipped_rows"] == 1
    assert str(df["time"].dt.tz) == "Europe/London"
    assert (df["collected_at"] == T_EARLY).all()
    assert df["time"].is_monotonic_increasing
    assert df["imo"].map(type).eq(str).all()
    assert df["gt"].dtype == "Float64" and df["loa"].dtype == "Float64"
    assert set(df["direction"]) == {"arrival", "departure", "shift"}


def test_vague_times_flagged_with_stand_in():
    df = early().set_index(["ship", "direction"])
    box = df.loc[("TEST BOX ONE", "arrival")]
    assert not box["time_confirmed"]
    assert box["time"].tz_localize(None) == pd.Timestamp("2026-10-18 09:00")
    cars = df.loc[("TEST CARS", "arrival")]
    assert cars["time_confirmed"]
    assert cars["time"].tz_localize(None) == pd.Timestamp("2026-10-18 09:30")
    assert not df.loc[("TEST RORO", "arrival"), "time_confirmed"]


def test_berth_is_the_port_end():
    df = early().set_index(["ship", "direction"])
    assert df.loc[("TEST BOX ONE", "arrival"), "berth"] == "SCT1/2"
    assert df.loc[("TEST BOX ONE", "departure"), "berth"] == "SCT1/2"
    assert df.loc[("TEST CARS", "departure"), "berth"] == "35"
    assert df.loc[("TEST RORO", "shift"), "berth"] == "102"


def test_categories():
    df = early().drop_duplicates("ship").set_index("ship")
    assert df.loc["TEST BOX ONE", "category"] == "container"
    assert df.loc["TEST CARS", "category"] == "roro"
    assert df.loc["TEST RORO", "category"] == "roro"
    assert df.loc["TEST LINER", "category"] == "cruise"
    assert df.loc["TEST STEAMER", "category"] == "other"  # small MPR, not a cruise ship
    assert df.loc["TEST TANKER", "category"] == "bulk_tanker"
    assert df.loc["TEST ISLAND", "category"] == "ferry"  # Red Funnel ro-pax
    assert df.loc["TEST BARGE", "category"] == "other"
    assert df["lorry_relevant"].sum() == 3


@pytest.mark.parametrize(
    "vtype, agent, expected",
    [
        ("Ro/Ro/C.C. (URC)", "", "roro"),
        ("Passenger Ro/Ro (PRR)", "TEST AGENCY", "roro"),
        ("Ferry (OFY)", "", "ferry"),
        ("Lng (LNG)", "", "bulk_tanker"),
        ("Bulk Carrier (BBU)", "", "bulk_tanker"),  # unseen code, bulk prefix
        ("General Cargo (GGC)", "", "other"),
        ("AUV (Autonomous Unmanned Vehicle)", "", "other"),
        ("", "", "other"),
    ],
)
def test_category_codes(vtype, agent, expected):
    assert vf.category(vtype, agent) == expected


@pytest.mark.parametrize(
    "berth, area",
    [
        ("SCT1", "container_terminal"),
        ("SCT2/3", "container_terminal"),
        ("204", "container_terminal"),
        ("101", "western_docks"),
        ("104W", "western_docks"),
        ("Western Docks", "western_docks"),
        ("KGV Dock West Side", "western_docks"),
        ("38/9", "eastern_docks"),
        ("46 O/S", "eastern_docks"),
        ("40/41", "eastern_docks"),
        ("Eastern Docks (R.Test)", "eastern_docks"),
        ("Esso Berth 4", "fawley"),
        ("SGL3", "unknown"),
        ("Town Quay Berth 65", "unknown"),
        ("150", "unknown"),
        ("", "unknown"),
    ],
)
def test_berth_area(berth, area):
    assert vf.berth_area(berth) == area


def test_parse_berthed():
    df = vf.parse_berthed(BERTHED, T_EARLY)
    assert list(df.columns) == vf.BERTHED_COLUMNS
    d = df.set_index("ship")
    assert d.loc["TEST ALONGSIDE", "area"] == "western_docks"
    assert d.loc["TEST ALONGSIDE", "time_confirmed"]
    assert d.loc["TEST ALONGSIDE", "arrival"].tz_localize(None) == pd.Timestamp("2026-10-17 03:02")
    assert str(df["departure"].dt.tz) == "Europe/London"
    assert not d.loc["TEST WAITING", "time_confirmed"]
    assert d.loc["TEST WAITING", "departure"].hour == vf.VAGUE_TIMES["PM"].hour
    assert d.loc["TEST WAITING", "category"] == "container"
    assert pd.isna(d.loc["TEST TUG", "departure"]) and not d.loc["TEST TUG", "time_confirmed"]
    assert d.loc["TEST TUG", "imo"] == "" and d.loc["TEST TUG", "category"] == "other"


def test_union_keeps_latest_snapshot():
    union = vf.union_extracts([late(), early()])  # frame order must not matter
    box = union[(union["ship"] == "TEST BOX ONE") & (union["direction"] == "arrival")]
    assert len(box) == 1
    assert box["time_confirmed"].item()
    assert box["collected_at"].item() == T_LATE
    # TEST CARS is only in the early snapshot: kept.
    assert (union["ship"] == "TEST CARS").sum() == 2
    # Blank IMO rows are keyed on the name and still kept.
    assert (union["ship"] == "TEST BARGE").sum() == 1


def test_daily_freight_calls():
    days = vf.daily_freight_calls([early(), late()])
    assert list(days.columns) == vf.DAY_COLUMNS
    d = days.set_index("date")
    assert list(d.index) == [date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20),
                             date(2026, 10, 21)]
    oct18 = d.loc[date(2026, 10, 18)]
    assert oct18["container_arr"] == 1 and oct18["container_arr_gt"] == 100000
    assert oct18["roro_arr"] == 1 and oct18["roro_dep"] == 1
    assert oct18["freight_moves"] == 3 and oct18["freight_gt"] == 220000
    oct20 = d.loc[date(2026, 10, 20)]
    assert oct20["roro_arr"] == 1  # arrival once, shift not counted
    assert oct20["unconfirmed"] == 0  # the late snapshot confirmed it
    assert d.loc[date(2026, 10, 21), "container_arr"] == 1
    # Early window 18-20 Oct, late window 20-21 Oct: all four days listed in full.
    assert d["complete"].all()


def test_day_of_snapshot_is_not_complete():
    days = vf.daily_freight_calls([late()]).set_index("date")
    assert not days.loc[date(2026, 10, 19), "complete"]  # taken that morning
    assert days.loc[date(2026, 10, 20), "complete"]
    assert vf.daily_freight_calls([]).empty


def test_snapshot_and_cli_offline(tmp_path, monkeypatch, capsys):
    bodies = {vf.EXTRACT_URL: LATE, vf.BERTHED_URL: BERTHED}
    monkeypatch.setattr(vf, "_download", lambda url, timeout: bodies[url])
    paths = vf.snapshot(tmp_path)
    assert sorted(p.name.split("_")[0] for p in paths) == ["sotberthed", "sotextract"]
    stamp = paths[0].name.split("_")[1]
    assert all(p.name.endswith(stamp) for p in paths)
    assert vf.collected_at(paths[0]) == vf.collected_at(paths[1])
    vf.main(["--raw-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Southampton VTS, ABP" in out and "container/ro-ro" in out


def test_snapshot_refuses_error_page(tmp_path, monkeypatch):
    monkeypatch.setattr(vf, "_download", lambda url, timeout: b"<html>oops")
    with pytest.raises(Exception):  # noqa: B017 - ParseError subclasses vary
        vf.snapshot(tmp_path)
    assert not list(tmp_path.glob("*.xml"))


def test_collected_at_from_file_name(tmp_path):
    path = tmp_path / "sotextract_20261017T085638Z.xml"
    path.write_bytes(LATE)
    assert vf.collected_at(path) == pd.Timestamp("2026-10-17T08:56:38Z")
    assert (vf.parse_extract(path)["collected_at"] == vf.collected_at(path)).all()
