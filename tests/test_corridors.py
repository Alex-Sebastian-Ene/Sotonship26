import math

import networkx as nx

from sotonship26.corridors import (
    candidate_paths,
    corridor_edges,
    corridor_vc,
    gate_access_edges,
    locate_approaches,
)


def road(g: nx.DiGraph, u, v, *, length=100.0, name="", ref="") -> None:
    g.add_edge(u, v, length_m=length, cost=length / 10.0, name=name, ref=ref, capacity=100.0)


def grid(n: int = 4) -> nx.DiGraph:
    g = nx.DiGraph()
    for u, v in nx.grid_2d_graph(n, n).edges:
        road(g, u, v)
        road(g, v, u)
    for x, y in g.nodes:
        g.nodes[(x, y)]["pos"] = (100.0 * x, 100.0 * y)
    return g


def test_corridors_match_name_or_ref_tokens():
    g = nx.DiGraph()
    road(g, 1, 2, name="Millbrook Road West;Regents Park Road")
    road(g, 2, 3, ref="A33;A35")
    road(g, 3, 4, name="Shirley Road")
    corridors = corridor_edges(
        g,
        [
            {"id": "millbrook", "label": "A33 Millbrook Road", "names": ["Millbrook Road West"]},
            {"id": "a35", "refs": ["A35"]},
        ],
    )
    assert corridors["millbrook"].edges == ((1, 2),)
    assert corridors["millbrook"].label == "A33 Millbrook Road"
    assert corridors["a35"].edges == ((2, 3),)


def test_corridor_vc_is_the_worst_segment():
    g = nx.DiGraph()
    road(g, 1, 2, name="X")
    road(g, 2, 3, name="X")
    corridors = corridor_edges(g, [{"id": "x", "names": ["X"]}, {"id": "none", "names": ["Y"]}])
    vc = corridor_vc({(1, 2): 50.0, (2, 3): 120.0}, {(1, 2): 100.0, (2, 3): 100.0}, corridors)
    assert vc["x"] == 1.2
    assert math.isnan(vc["none"])


def test_gate_access_covers_both_directions_within_range():
    g = nx.DiGraph()
    for a, b in [(0, 1), (1, 2), (2, 3)]:
        road(g, a, b)
        road(g, b, a)
    edges = set(gate_access_edges(g, 0, 150.0))
    assert edges == {(0, 1), (1, 0)}


def test_candidate_paths_are_distinct_and_sensible():
    g = grid()
    paths = candidate_paths(g, (0, 0), (3, 3), k=3, max_overlap=0.5, max_detour=1.5)
    assert 2 <= len(paths) <= 3
    for p in paths:
        assert p[0] == (0, 0) and p[-1] == (3, 3)
        assert len(p) - 1 <= 1.5 * 6  # no path more than 1.5x the quickest (6 hops)
    sets = [set(zip(p, p[1:], strict=False)) for p in paths]
    for i in range(len(sets)):
        for j in range(i):
            assert len(sets[i] & sets[j]) <= 0.5 * len(sets[i])


def test_candidate_paths_drop_long_detours():
    g = nx.DiGraph()
    road(g, "s", "t", length=100.0)
    road(g, "s", "x", length=200.0)
    road(g, "x", "t", length=200.0)
    assert candidate_paths(g, "s", "t", k=5, max_detour=1.5) == [["s", "t"]]


def test_approach_picks_the_right_carriageway():
    """Dual carriageway with ref M1: n0->n1->n2 heads away from the gate, s2->s1->s0 towards it."""
    g = nx.DiGraph()
    for i in range(3):
        g.add_node(f"n{i}", pos=(0.0, 100.0 * i))
        g.add_node(f"s{i}", pos=(10.0, 100.0 * i))
    g.add_node("G", pos=(5.0, -100.0))
    road(g, "n0", "n1", ref="M1")
    road(g, "n1", "n2", ref="M1")
    road(g, "s2", "s1", ref="M1")
    road(g, "s1", "s0", ref="M1")
    road(g, "n2", "s2", ref="M1")  # turn round at the top
    road(g, "s0", "G")
    road(g, "G", "n0")
    found = locate_approaches(g, {"m1": ((5.0, 200.0), ["M1"])}, ["G"])
    assert found[("m1", "in")] == "s2"
    assert found[("m1", "out")] == "n2"
