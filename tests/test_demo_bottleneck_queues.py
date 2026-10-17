"""run_day keeps traffic that cannot get through waiting at its route's bottleneck (SOT-30).

A chain of three links, one origin-destination pair, the middle link a bottleneck: the queue
loads the bottleneck and the links after it, not the link before it, and a counter sees each
vehicle once.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
import scipy.sparse as sp  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import traffic_model as tm  # noqa: E402

E0, E1, E2 = 0, 1, 2


def chain(caps) -> tm.Model:
    """Nodes 0-1-2-3 in a line, one route 0 -> 3 (padded to ROUTES copies of itself)."""
    eu, ev = np.array([0, 1, 2]), np.array([1, 2, 3])
    length = np.full(3, 1000.0)
    xy = np.array([[0.0, 0.0], [1000.0, 0.0], [2000.0, 0.0], [3000.0, 0.0]])
    paths = [[E0, E1, E2]] * tm.ROUTES
    rows = np.concatenate([np.asarray(p) for p in paths])
    cols = np.repeat(np.arange(len(paths)), [len(p) for p in paths])
    A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(3, len(paths)))
    uniq = np.zeros((1, tm.ROUTES), bool)
    uniq[0, 0] = True
    cents = [tm.Centroid("A", "zone", 0, (0, 0)), tm.Centroid("B", "zone", 3, (3000, 0))]
    return tm.Model(xy=xy, eu=eu, ev=ev, t0=length / (30 / 3.6), cap=np.asarray(caps, float),
                    length=length, cls=["primary"] * 3, name=["a", "b", "c"], ref=[""] * 3,
                    coords=[[tuple(xy[u]), tuple(xy[v])] for u, v in zip(eu, ev, strict=True)],
                    centroids=cents, ods=[(0, 1)], od_index={(0, 1): 0}, purpose_od={},
                    paths=paths, A=A, AT=A.T.tocsr(), col_idx=rows,
                    col_ptr=np.arange(0, len(rows), 3), uniq=uniq)


def one_wave(vehicles: float = 100.0) -> np.ndarray:
    D = np.zeros((tm.N_BINS, 1))
    D[0, 0] = vehicles
    return D


def test_queue_waits_at_the_bottleneck():
    m = chain([2000.0, 200.0, 2000.0])
    res, _ = tm.run_day(m, one_wave(), m.cap, tm.initial_shares(m), 3,
                        want=("x", "count", "held"))
    # 400 veh/h meet 200 veh/h: half get through, CARRY of the other 50 wait at the middle link
    assert res["x"][0, E1] == pytest.approx(2.0)
    assert res["held"][0] == pytest.approx(tm.CARRY * 50)
    # next 15 minutes: the 40 waiting load the bottleneck and the link after it, not the one before
    q = tm.CARRY * 50 * 4.0
    np.testing.assert_allclose(res["x"][1], [0.0, q / 200.0, q / 2000.0])
    np.testing.assert_allclose(res["count"][1], [0.0, q, q])
    assert res["held"][1] == pytest.approx(0.0)


def test_each_vehicle_counted_once():
    m = chain([2000.0, 200.0, 2000.0])
    res, _ = tm.run_day(m, one_wave(), m.cap, tm.initial_shares(m), 3, want=("count",))
    # every vehicle passes every link once: 50 at capacity, 10 more within the 15 minutes (those
    # not still waiting), 40 after waiting
    np.testing.assert_allclose(res["count"].sum(axis=0) / 4.0, 100.0)
    np.testing.assert_allclose(res["count"][0], [400.0, 240.0, 240.0])


def test_queue_moves_to_a_worse_link_ahead():
    m = chain([2000.0, 200.0, 2000.0])
    events = [(np.array([E2]), 1, 2, 0.05)]  # the last link drops to 100 veh/h for one bin
    res, _ = tm.run_day(m, one_wave(), m.cap, tm.initial_shares(m), 3,
                        want=("x", "count", "held"), events=events)
    q = tm.CARRY * 50 * 4.0  # 160 veh/h waiting at the middle link
    assert res["x"][1, E2] == pytest.approx(q / 100.0)
    # all of it gets past the middle link (0.8 of its capacity), 100 veh/h and those not still
    # waiting past the last
    np.testing.assert_allclose(res["count"][1], [0.0, q, 100.0 + (1 - tm.CARRY) * (q - 100.0)])
    held = tm.CARRY * (q - 100.0) / 4.0
    assert res["held"][1] == pytest.approx(held)
    # and then it waits at the last link only
    np.testing.assert_allclose(res["x"][2], [0.0, 0.0, held * 4.0 / 2000.0])


def test_cruise_share_follows_the_queue():
    m = chain([2000.0, 200.0, 2000.0])
    D = one_wave()
    D[1, 0] = 30.0
    cruise = D * np.where(np.arange(tm.N_BINS) == 0, 0.25, 0.0)[:, None]
    res, _ = tm.run_day(m, D, m.cap, tm.initial_shares(m), 3, cruise=cruise,
                        want=("count", "cruise_count", "cruise_edge", "cruise_path"))
    # bin 0 is a quarter cruise; in bin 1 only the queue from bin 0 carries any
    np.testing.assert_allclose(res["cruise_count"][0], 0.25 * res["count"][0])
    q = tm.CARRY * 50 * 4.0
    np.testing.assert_allclose(res["cruise_edge"][1], [0.0, 0.25 * q, 0.25 * q])
    assert res["cruise_path"][1].sum() == pytest.approx(0.0)  # no cruise trips set off in bin 1
    np.testing.assert_allclose(res["cruise_count"].sum(axis=0)[E0] / 4.0, 25.0)


def test_free_flow_day_is_unchanged():
    """Without a link over capacity nothing is held, and count equals load."""
    m = chain([2000.0, 2000.0, 2000.0])
    D = np.full((tm.N_BINS, 1), 50.0)
    res, _ = tm.run_day(m, D, m.cap, tm.initial_shares(m), 3, want=("x", "count", "held"))
    np.testing.assert_allclose(res["count"], res["x"] * m.cap)
    assert res["held"].max() == 0.0
