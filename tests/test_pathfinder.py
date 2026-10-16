import networkx as nx

from sotonship26.routing import Flow, route


def diamond(cap_top: float = 10.0, cap_bottom: float = 10.0) -> nx.Graph:
    g = nx.Graph()
    g.add_edge("s", "a", cost=1.0, capacity=cap_top)
    g.add_edge("a", "t", cost=1.0, capacity=cap_top)
    g.add_edge("s", "b", cost=1.5, capacity=cap_bottom)
    g.add_edge("b", "t", cost=1.5, capacity=cap_bottom)
    return g


def test_uncongested_flow_takes_cheapest_path():
    result = route(diamond(), [Flow("s", "t", 5.0)])
    assert result.paths == [["s", "a", "t"]]
    assert not result.overloaded()


def test_negotiation_spreads_flows_over_alternatives():
    result = route(diamond(), [Flow("s", "t", 8.0), Flow("s", "t", 8.0)])
    assert {tuple(p) for p in result.paths} == {("s", "a", "t"), ("s", "b", "t")}
    assert not result.overloaded()


def test_unavoidable_overload_is_reported():
    result = route(diamond(cap_top=1.0, cap_bottom=1.0), [Flow("s", "t", 5.0)])
    assert result.overloaded()


def test_cost_scale_steers_flow_away():
    result = route(diamond(), [Flow("s", "t", 1.0)], cost_scale={("a", "s"): 10.0})
    assert result.paths == [["s", "b", "t"]]


def test_cut_off_flow_is_held_nearest_its_target():
    g = nx.path_graph(4)
    for n in g.nodes:
        g.nodes[n]["pos"] = (float(n), 0.0)
    nx.set_edge_attributes(g, 1.0, "cost")
    nx.set_edge_attributes(g, 10.0, "capacity")
    result = route(nx.restricted_view(g, [], [(2, 3)]), [Flow(0, 3, 2.0)])
    assert result.paths == [[0, 1, 2]]
    assert result.held == {2: 2.0}
