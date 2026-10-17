import json

import pandas as pd
import pytest

from sotonship26.data import dft

# SYNTHETIC fixture: made-up count points shaped like the DfT AADF-by-direction API rows. Not real
# DfT data. Point 9001 sits at the docks, 9002 about 2 km north, 9003 about 11 km away.
SYNTHETIC_ROWS = [
    {
        "count_point_id": 9001,
        "year": year,
        "road_name": "A33",
        "road_category": "PA",
        "road_type": "Major",
        "start_junction_road_name": "Synthetic Rd",
        "end_junction_road_name": "Made Up St",
        "latitude": "50.8985",
        "longitude": "-1.4040",
        "link_length_km": "0.5",
        "estimation_method": "Counted",
        "direction_of_travel": direction,
        "cars_and_taxis": flow - 100,
        "buses_and_coaches": 10,
        "lgvs": 60,
        "all_hgvs": 30,
        "all_motor_vehicles": flow,
    }
    for year, direction, flow in [
        (2022, "N", 10000),
        (2023, "N", 11000),
        (2021, "S", 9000),
        (2022, "S", 9500),
    ]
] + [
    {
        "count_point_id": 9002,
        "year": 2023,
        "road_name": "U",
        "road_category": "MCU",
        "road_type": "Minor",
        "start_junction_road_name": None,
        "end_junction_road_name": None,
        "latitude": "50.9165",
        "longitude": "-1.4040",
        "link_length_km": None,
        "estimation_method": "Estimated",
        "direction_of_travel": "C",
        "cars_and_taxis": 900,
        "buses_and_coaches": 5,
        "lgvs": 80,
        "all_hgvs": 15,
        "all_motor_vehicles": 1000,
    },
    {
        "count_point_id": 9003,
        "year": 2023,
        "road_name": "M27",
        "road_category": "TM",
        "road_type": "Major",
        "start_junction_road_name": "J5",
        "end_junction_road_name": "J7",
        "latitude": "50.9975",
        "longitude": "-1.4040",
        "link_length_km": "3.1",
        "estimation_method": "Counted",
        "direction_of_travel": "E",
        "cars_and_taxis": 50000,
        "buses_and_coaches": 300,
        "lgvs": 9000,
        "all_hgvs": 4000,
        "all_motor_vehicles": 63300,
    },
]
STAMP = "20261016T201500Z"


@pytest.fixture
def cache_dir(tmp_path):
    payload = {"source": "synthetic", "licence": dft.LICENCE, "data": SYNTHETIC_ROWS}
    path = tmp_path / f"aadf_by_direction_la137_{STAMP}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _no_fetch(*args, **kwargs):
    raise AssertionError("tests must not hit the network")


def test_column_contract(cache_dir, monkeypatch):
    monkeypatch.setattr(dft, "fetch_aadf", _no_fetch)
    df = dft.load_aadf(raw_dir=cache_dir)
    assert list(df.columns) == dft.COLUMNS
    assert df["latitude"].dtype == float
    assert df["link_length_km"].dtype == float
    assert str(df["year"].dtype) == "Int64"
    assert str(df["all_motor_vehicles"].dtype) == "Int64"


def test_radius_filter(cache_dir, monkeypatch):
    monkeypatch.setattr(dft, "fetch_aadf", _no_fetch)
    df = dft.load_aadf(radius_km=4.0, raw_dir=cache_dir)
    assert set(df["count_point_id"]) == {9001, 9002}
    assert df["distance_km"].max() <= 4.0
    near = df.loc[df["count_point_id"] == 9002, "distance_km"].iloc[0]
    assert near == pytest.approx(2.0, abs=0.05)

    wide = dft.load_aadf(radius_km=20.0, raw_dir=cache_dir)
    assert set(wide["count_point_id"]) == {9001, 9002, 9003}

    tight = dft.load_aadf(radius_km=0.5, raw_dir=cache_dir)
    assert set(tight["count_point_id"]) == {9001}


def test_latest_only(cache_dir, monkeypatch):
    monkeypatch.setattr(dft, "fetch_aadf", _no_fetch)
    latest = dft.load_aadf(radius_km=0.5, raw_dir=cache_dir)
    by_dir = dict(zip(latest["direction_of_travel"], latest["year"], strict=True))
    assert by_dir == {"N": 2023, "S": 2022}
    assert len(latest) == 2

    every_year = dft.load_aadf(radius_km=0.5, raw_dir=cache_dir, latest_only=False)
    assert len(every_year) == 4


def test_collected_at_from_file_name(cache_dir, monkeypatch):
    monkeypatch.setattr(dft, "fetch_aadf", _no_fetch)
    expected = pd.Timestamp("2026-10-16 20:15:00", tz="UTC")
    assert dft.collected_at(cache_dir / f"aadf_by_direction_la137_{STAMP}.json") == expected
    df = dft.load_aadf(raw_dir=cache_dir)
    assert (df["collected_at"] == expected).all()
    assert str(df["collected_at"].dt.tz) == "UTC"


def test_newest_cache_wins(cache_dir, monkeypatch):
    monkeypatch.setattr(dft, "fetch_aadf", _no_fetch)
    newer = {"data": SYNTHETIC_ROWS[:1]}
    (cache_dir / "aadf_by_direction_la137_20261017T090000Z.json").write_text(json.dumps(newer))
    df = dft.load_aadf(raw_dir=cache_dir, latest_only=False)
    assert len(df) == 1
    assert df["collected_at"].iloc[0] == pd.Timestamp("2026-10-17 09:00:00", tz="UTC")


def test_falls_back_to_cache_when_fetch_fails(cache_dir, monkeypatch):
    def broken_fetch(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(dft, "fetch_aadf", broken_fetch)
    with pytest.warns(UserWarning, match="DfT fetch failed"):
        df = dft.load_aadf(refresh=True, raw_dir=cache_dir)
    assert set(df["count_point_id"]) == {9001, 9002}


def test_raises_without_cache_when_fetch_fails(tmp_path, monkeypatch):
    def broken_fetch(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(dft, "fetch_aadf", broken_fetch)
    with pytest.raises(OSError):
        dft.load_aadf(raw_dir=tmp_path)


def test_fetch_follows_pages_and_caches(tmp_path, monkeypatch):
    pages = {
        1: {"current_page": 1, "last_page": 2, "data": SYNTHETIC_ROWS[:3]},
        2: {"current_page": 2, "last_page": 2, "data": SYNTHETIC_ROWS[3:]},
    }
    seen = []

    def fake_get(url, timeout):
        page = int(url.rsplit("=", 1)[1])
        seen.append(page)
        return pages[page]

    monkeypatch.setattr(dft, "_get_json", fake_get)
    path = dft.fetch_aadf(raw_dir=tmp_path)
    assert seen == [1, 2]
    assert dft._CACHE_NAME.search(path.name)
    assert len(json.loads(path.read_text(encoding="utf-8"))["data"]) == len(SYNTHETIC_ROWS)
