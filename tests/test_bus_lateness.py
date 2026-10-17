"""Observed bus lateness from bustimes.org's vehicle feed (src/sotonship26/data/bus_lateness.py).

Synthetic payloads shaped like a real /vehicles.json response (17 Oct 2026); no network."""

from __future__ import annotations

from datetime import datetime

import pytest

from sotonship26.data.bus_lateness import (
    LONDON,
    BustimesClient,
    append_csv,
    area_of,
    parse_vehicles,
    profiles,
    read_csv,
)

NOW = datetime(2026, 10, 17, 12, 47, tzinfo=LONDON)


def bus(journey, line, delay, lon=-1.405, lat=50.898, when="2026-10-17T12:46:32+01:00"):
    return {"id": 1, "journey_id": journey, "coordinates": [lon, lat], "heading": 341,
            "datetime": when, "destination": "Hythe", "trip_id": 6, "service_id": 4,
            "service": {"url": "/services/8", "line_name": line},
            "progress": {"prev_stop": "1980SN121022", "next_stop": "1980SN120518"},
            "delay": delay, "vehicle": {"url": "/vehicles/x", "name": f"bus {journey}"}}


def test_parse_reads_the_fields_and_skips_bad_records():
    rows = parse_vehicles([bus(1, "8", 89), {"no": "coords"}, bus(2, "16", None)], NOW)
    assert [r.line for r in rows] == ["8", "16"]
    assert rows[0].delay_s == 89.0 and rows[1].delay_s is None
    assert rows[0].journey == "1" and rows[0].next_stop == "1980SN120518"
    assert rows[0].observed_at.utcoffset().total_seconds() == 3600


def test_areas():
    docks, = parse_vehicles([bus(1, "8", 0, lon=-1.404, lat=50.897)], NOW)
    far, = parse_vehicles([bus(2, "8", 0, lon=-1.37, lat=50.886)], NOW)
    assert area_of(docks) == "docks" and area_of(far) is None


def test_profiles_count_each_journey_once_per_hour():
    payload = [bus(1, "8", 60, when="2026-10-17T12:10:00+01:00"),
               bus(1, "8", 600, when="2026-10-17T12:50:00+01:00"),  # same journey, later: kept
               bus(2, "8", 120, when="2026-10-17T12:20:00+01:00"),
               bus(3, "8", 0, when="2026-10-17T12:30:00+01:00"),
               bus(4, "8", 99999, when="2026-10-17T12:30:00+01:00"),  # bad match: dropped
               bus(5, "16", 60, when="2026-10-17T12:30:00+01:00")]
    rows = parse_vehicles(payload, NOW)
    p, = profiles(rows, by="line")  # line 16 has one journey, below min_n
    assert (p.key, p.hour, p.n) == ("8", 12, 3)
    assert p.mean_min == pytest.approx((10 + 2 + 0) / 3)
    assert p.share_over_5_min == pytest.approx(1 / 3)
    whole = profiles(rows, by="area", min_n=1, hourly=False)
    assert [(q.key, q.hour, q.n) for q in whole] == [("docks", -1, 4)]


def test_csv_round_trip(tmp_path):
    rows = parse_vehicles([bus(1, "8", 89), bus(2, "U1A", None)], NOW)
    path = tmp_path / "b.csv"
    assert append_csv(path, rows) == 2 and append_csv(path, rows[:1]) == 1
    back = read_csv(path)
    assert back[:2] == rows and len(back) == 3


def test_client_refuses_paths_robots_disallows():
    with pytest.raises(ValueError):
        BustimesClient(min_interval_s=0).get_json("/api/trips/1/")
