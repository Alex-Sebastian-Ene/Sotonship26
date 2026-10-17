import gzip
import json
from datetime import date

import pandas as pd

from sotonship26.data import observed


def row(day: str, end: str, volume: str = "311", long1: str = "7", long2: str = "19") -> dict:
    return {
        "Site Name": "5120/1",
        "Report Date": f"{day}T00:00:00",
        "Time Period Ending": end,
        "Time Interval": "30",
        "0 - 520 cm": "237",
        "521 - 660 cm": "48",
        "661 - 1160 cm": long1,
        "1160+ cm": long2,
        "Avg mph": "51",
        "Total Volume": volume,
    }


def test_bin_start_is_fifteen_minutes_before_the_end_time():
    frame = observed.rows_to_frame(
        [row("2025-09-13", "07:44:00"), row("2025-09-13", "00:14:59"),
         row("2025-09-13", "23:59:59")],
        19974,
    )
    starts = [t.strftime("%Y-%m-%d %H:%M %Z") for t in frame["bin_start"]]
    assert starts == ["2025-09-13 07:30 BST", "2025-09-13 00:00 BST", "2025-09-13 23:45 BST"]
    assert frame["flow_veh"].tolist() == [311, 311, 311]
    assert frame["long_veh"].tolist() == [26, 26, 26]
    assert (frame["site_id"] == 19974).all()


def test_blank_volume_is_missing_not_zero():
    frame = observed.rows_to_frame([row("2025-09-01", "00:14:59", volume="", long1="", long2="")],
                                   7588)
    assert pd.isna(frame["flow_veh"].iloc[0])
    assert pd.isna(frame["long_veh"].iloc[0])


def test_fall_back_day_repeats_bins_bst_first_then_gmt():
    rows = [row("2025-10-26", "01:14:00", volume="10"), row("2025-10-26", "01:14:00", volume="20")]
    frame = observed.rows_to_frame(rows, 19974)
    utc = frame["bin_start"].dt.tz_convert("UTC").dt.strftime("%H:%M").tolist()
    assert utc == ["00:00", "01:00"]
    assert frame["bin_start"].is_unique


def test_spring_forward_day_has_no_01_hour():
    rows = [row("2026-03-29", "00:59:00"), row("2026-03-29", "02:14:00")]
    frame = observed.rows_to_frame(rows, 19974)
    gap = frame["bin_start"].iloc[1] - frame["bin_start"].iloc[0]
    assert gap == pd.Timedelta(minutes=15)


def full_day(day: str, n: int) -> list[dict]:
    ends = [f"{(15 * (i + 1) - 1) // 60 % 24:02d}:{(15 * (i + 1) - 1) % 60:02d}:00"
            for i in range(n)]
    return [row(day, end, volume=str(i)) for i, end in enumerate(ends)]


def test_full_day_is_placed_by_position_despite_irregular_end_times():
    rows = full_day("2024-10-16", 96)
    rows[51]["Time Period Ending"] = "12:55:00"  # really the 12:45 bin
    rows[68]["Time Period Ending"] = "17:01:00"  # really the 17:00 bin
    frame = observed.rows_to_frame(rows, 19974)
    assert len(frame) == 96 and frame["bin_start"].is_unique
    by_volume = dict(zip(frame["flow_veh"], frame["bin_start"].dt.strftime("%H:%M"), strict=True))
    assert by_volume[51] == "12:45" and by_volume[68] == "17:00"


def test_full_fall_back_day_has_100_distinct_bins():
    frame = observed.rows_to_frame(full_day("2025-10-26", 100), 19974)
    assert len(frame) == 100 and frame["bin_start"].is_unique
    assert frame["bin_start"].iloc[-1].strftime("%H:%M %Z") == "23:45 GMT"


def test_empty_rows_give_empty_frame():
    assert observed.rows_to_frame([], 19974).empty


def test_load_flows_reads_cache_and_flags_good_days(tmp_path, monkeypatch):
    site_dir = tmp_path / "19974"
    site_dir.mkdir()
    report = {"Header": {"row_count": 2, "links": []},
              "Rows": [row("2025-09-01", "07:44:00"), row("2025-09-02", "07:44:00")]}
    quality = {"row_count": 2, "Qualities": [{"Date": "2025-09-01T00:00:00", "Quality": 100},
                                             {"Date": "2025-09-02T00:00:00", "Quality": 40}]}
    with gzip.open(site_dir / "2025-09.json.gz", "wt") as fh:
        json.dump(report, fh)
    with gzip.open(site_dir / "2025-09.quality.json.gz", "wt") as fh:
        json.dump(quality, fh)
    monkeypatch.setattr(observed, "CACHE_DIR", tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("tried to download")

    monkeypatch.setattr(observed, "_get_json", no_network)
    flows = observed.load_flows([19974], date(2025, 9, 1), date(2025, 9, 2))
    assert flows["good_day"].tolist() == [True, False]
    assert flows["date"].tolist() == [date(2025, 9, 1), date(2025, 9, 2)]


def test_sites_cover_both_dock_approaches():
    approaches = {s["approach"] for s in observed.SITES.values()}
    assert approaches == {"western", "eastern"}


def _day_flows(site_id: int, day: str, flow: int) -> pd.DataFrame:
    """One full non-DST day: 96 fifteen-minute bins at a constant flow, flagged a good day."""
    bins = pd.date_range(f"{day} 00:00", periods=96, freq="15min", tz="Europe/London")
    return pd.DataFrame({"site_id": site_id, "bin_start": bins, "flow_veh": flow,
                         "good_day": True})


def test_observed_uplift_is_flow_minus_same_weekday_time_median_on_non_cruise_days():
    # Five Mondays in Sep 2025 (no DST change); the middle one is a cruise day. A Tuesday with a
    # huge flow is a non-cruise day of a different weekday, so it must not touch the baseline.
    site = 19974
    ref_mondays = {"2025-09-01": 100, "2025-09-08": 102, "2025-09-22": 104, "2025-09-29": 106}
    cruise_monday, cruise_flow = "2025-09-15", 150
    other_weekday = "2025-09-16"  # Tuesday
    flows = pd.concat(
        [_day_flows(site, day, flow) for day, flow in ref_mondays.items()]
        + [_day_flows(site, cruise_monday, cruise_flow), _day_flows(site, other_weekday, 999)],
        ignore_index=True,
    )
    all_days = [*ref_mondays, cruise_monday, other_weekday]
    days = pd.DataFrame({
        "date": [date.fromisoformat(d) for d in all_days],
        "n_calls": [0] * len(ref_mondays) + [1, 0],  # only the cruise Monday has a ship
        "covered": True,
    })

    up = observed.observed_uplift(flows, days)
    day_rows = up[(up["site_id"] == site)
                  & (up["date"] == date.fromisoformat(cruise_monday))]

    # median of the four reference Mondays' flows (100, 102, 104, 106) = 103, per bin
    assert (day_rows["baseline_veh"] == 103.0).all()
    assert (day_rows["uplift_veh"] == cruise_flow - 103.0).all()  # 150 - 103 = 47
    assert (day_rows["n_refs"] == 4).all()  # the Tuesday is excluded: different weekday
    assert day_rows["is_cruise_day"].all()
    assert len(day_rows) == 96
