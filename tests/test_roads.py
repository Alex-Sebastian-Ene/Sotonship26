import networkx as nx
import pytest

from sotonship26.data.roads import build_roads, road_class

CLASSES = {"trunk": [1800, 70, 1], "primary": [1400, 45, 1], "tertiary": [1000, 35, 1]}


def osm_like() -> nx.MultiDiGraph:
    """Projected osmnx-style multigraph: a two-way primary a<->b, one-way trunk b->c, one-way
    primary c->a, a residential spur c<->d, and a one-way stub a->e that cannot get back."""
    g = nx.MultiDiGraph(crs="EPSG:27700")
    for n, (x, y) in {
        "a": (0, 0),
        "b": (1000, 0),
        "c": (500, 800),
        "d": (500, 900),
        "e": (-500, 0),
    }.items():
        g.add_node(n, x=float(x), y=float(y))
    two_way = {
        "highway": "primary",
        "lanes": "4",
        "oneway": False,
        "maxspeed": "30 mph",
        "length": 1000.0,
        "name": "Western Esplanade",
    }
    g.add_edge("a", "b", **two_way)
    g.add_edge("b", "a", **two_way)
    g.add_edge("a", "b", highway="primary", length=1000.0, maxspeed="20 mph")  # slower duplicate
    g.add_edge(
        "b",
        "c",
        highway=["trunk_link", "trunk"],
        lanes="2",
        oneway=True,
        length=950.0,
        ref=["A33", "A35"],
    )
    g.add_edge("c", "a", highway="primary", oneway=True, length=950.0, name=["Canute Road", None])
    g.add_edge("c", "d", highway="residential", oneway=False, length=100.0)
    g.add_edge("d", "c", highway="residential", oneway=False, length=100.0)
    g.add_edge("a", "e", highway="primary", oneway=True, length=500.0)
    return g


def test_two_way_road_splits_lanes_and_uses_the_posted_limit():
    g = build_roads(osm_like(), classes=CLASSES, bin_minutes=15)
    e = g["a"]["b"]
    assert e["lanes"] == 2  # OSM lanes=4 counts both directions
    assert e["speed_kph"] == pytest.approx(30 * 1.609 * 0.9)
    assert e["cost"] == pytest.approx(1000 / (e["speed_kph"] / 3.6))
    assert e["capacity"] == pytest.approx(2 * 1400 * 15 / 60)
    assert e["name"] == "Western Esplanade"
    assert g.graph["crs"] == "EPSG:27700"


def test_one_way_keeps_its_lanes_and_best_class():
    e = build_roads(osm_like(), classes=CLASSES, bin_minutes=15)["b"]["c"]
    assert e["road_class"] == "trunk"
    assert e["lanes"] == 2
    assert e["speed_kph"] == 70  # no maxspeed tag: class default
    assert e["ref"] == "A33;A35"


def test_graph_is_directed_and_strongly_connected():
    g = build_roads(osm_like(), classes=CLASSES, bin_minutes=15)
    assert g.is_directed()
    assert set(g.nodes) == {"a", "b", "c"}  # d is a minor road, e cannot get back
    assert not g.has_edge("a", "c")  # c->a is one-way
    assert nx.is_strongly_connected(g)
    assert g.nodes["c"]["pos"] == (500.0, 800.0)
    assert g["c"]["a"]["name"] == "Canute Road"


def test_minor_roads_near_a_gate_are_kept_as_access():
    g = build_roads(
        osm_like(), classes=CLASSES, bin_minutes=15, keep_near=[(500, 900)], keep_near_m=150
    )
    assert g["c"]["d"]["road_class"] == "access"
    assert g["c"]["d"]["capacity"] == pytest.approx(1000 * 15 / 60)  # lowest-capacity class


def test_parallel_edges_keep_the_quicker():
    g = build_roads(osm_like(), classes=CLASSES, bin_minutes=15)
    assert g["a"]["b"]["speed_kph"] == pytest.approx(30 * 1.609 * 0.9)


def test_road_class_ignores_unknown_values():
    assert road_class(["service", "tertiary", "primary"], list(CLASSES)) == "primary"
    assert road_class("footway", list(CLASSES)) is None
