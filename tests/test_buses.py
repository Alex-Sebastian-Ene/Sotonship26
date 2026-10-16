from datetime import date, datetime, timedelta

import pytest

from sotonship26.data.buses import (
    LONDON,
    Sighting,
    delay_profiles,
    estimate_lateness,
    lateness_from_row,
    lateness_to_row,
    parse_trip,
    parse_vehicles,
)

DAY = date(2026, 10, 17)

# Shaped like bustimes.org's /api/trips/<id>/ response (only the fields we read).
TRIP = {
    "id": 123,
    "service": {"line_name": "U1"},
    "operator": {"name": "Unilink"},
    "times": [
        {
            "stop": {"atco_code": "A", "name": "Town Quay", "location": [-1.4044, 50.8966]},
            "aimed_departure_time": "10:00",
        },
        {
            "stop": {"atco_code": "B", "name": "Bargate", "location": [-1.4043, 50.9026]},
            "aimed_departure_time": "10:10",
        },
        {
            "stop": {"atco_code": "C", "name": "No location", "location": None},
            "aimed_departure_time": "10:12",
        },
        {
            "stop": {"atco_code": "D", "name": "Civic Centre", "location": [-1.4045, 50.9082]},
            "aimed_arrival_time": "10:20",
        },
    ],
}


def sighting(lat, lon, hh, mm):
    return Sighting(
        observed_at=datetime(2026, 10, 17, hh, mm, tzinfo=LONDON),
        vehicle="bus 1",
        line="U1",
        trip_id="123",
        lat=lat,
        lon=lon,
        heading=None,
        destination="Civic Centre",
        reported_delay_s=None,
    )


def test_parse_trip_skips_stops_without_location():
    trip = parse_trip(TRIP, DAY)
    assert [s.atco for s in trip.stops] == ["A", "B", "D"]
    assert trip.line == "U1" and trip.operator == "Unilink"
    assert trip.stops[-1].aimed == datetime(2026, 10, 17, 10, 20, tzinfo=LONDON)


def test_times_past_midnight_roll_into_next_day():
    raw = {**TRIP, "times": [{**t, "aimed_departure_time": "24:10"} for t in TRIP["times"][:2]]}
    assert parse_trip(raw, DAY).stops[0].aimed.date() == DAY + timedelta(days=1)


def test_lateness_interpolates_between_stops():
    trip = parse_trip(TRIP, DAY)
    # Halfway from Town Quay (10:00) to Bargate (10:10) should be 10:05; seen at 10:08.
    est = estimate_lateness(sighting(50.8996, -1.40435, 10, 8), trip)
    assert est.delay_s == pytest.approx(180, abs=10)
    assert est.next_stop == "Bargate"
    assert est.off_route_m < 5


def test_off_route_bus_is_not_matched():
    trip = parse_trip(TRIP, DAY)
    assert estimate_lateness(sighting(50.8996, -1.38, 10, 8), trip) is None


def test_parse_vehicles_tolerates_bad_records():
    payload = [
        {
            "coordinates": [-1.40, 50.90],
            "datetime": "2026-10-17T09:08:00Z",
            "trip_id": 9,
            "service": {"line_name": "1"},
            "vehicle": {"name": "Bluestar 123"},
            "delay": 120,
        },
        {"coordinates": None, "datetime": "2026-10-17T09:08:00Z"},
    ]
    (v,) = parse_vehicles(payload)
    assert v.line == "1" and v.trip_id == "9" and v.reported_delay_s == 120
    assert v.observed_at.utcoffset() == timedelta(0)


def test_profiles_and_csv_round_trip():
    trip = parse_trip(TRIP, DAY)
    rows = [estimate_lateness(sighting(50.8996, -1.40435, 10, m), trip) for m in range(5, 11)]
    (p,) = delay_profiles(rows, min_n=5)
    assert p.line == "U1" and p.hour == 10 and p.n == 6
    assert p.p50_min <= p.p90_min
    row = {k: "" if v is None else str(v) for k, v in lateness_to_row(rows[0]).items()}
    assert lateness_from_row(row) == rows[0]
