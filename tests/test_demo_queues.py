"""Counted roads in the demo model (traffic_model.anchor_counts): capacity above the counts, and
local traffic topped up link by link (docs/queues.md).

Runs on the 3 x 3 toy network of test_demo_agents_ppo.py:

    uv run --with scipy --with shapely pytest tests/test_demo_queues.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import traffic_model as tm  # noqa: E402

from test_demo_agents_ppo import toy_ctx  # noqa: E402

SITE = {"label": "Count Road (toy)", "names": ["Count Road"],
        "weekday": {"am": (200, 220), "pm": (150, 150), "day": (1200, 1200)},
        "saturday": {"am": (100, 100), "pm": (120, 120), "day": (900, 900)}}


@pytest.fixture(scope="module")
def counted():
    """The toy model with the west column of links (both ways) named and counted."""
    m = toy_ctx().m
    m.name = ["Count Road" if {a, b} <= {0, 3, 6} and abs(a - b) == 3 else nm
              for a, b, nm in zip(m.eu, m.ev, m.name, strict=True)]
    cap_before = m.cap.copy()
    notes = tm.anchor_counts(m, [SITE], [], log=lambda *_: None)
    return m, cap_before, notes


def test_capacity_is_the_count_plus_headroom(counted):
    m, cap_before, notes = counted
    for d, north in ((0, True), (1, False)):
        peak = max(SITE["weekday"][p][d] / 3.0 * 1.15 for p in ("am", "pm"))
        want = max(tm.MIN_CAP, 0.95 * peak) * tm.COUNT_HEADROOM
        ks = [k for k in tm.road_edges(m, ["Count Road"]) if tm.heading_north(m, k) == north]
        assert ks
        assert np.allclose(m.cap[ks], np.minimum(cap_before[ks], want))
    assert {n["dir"] for n in notes} == {"northbound", "southbound"}


def test_local_traffic_tops_each_link_up_to_the_count(counted):
    """Each link carries the count (times UNI_TERM) at least: local traffic fills the gap on links
    below it, and links already above it get none."""
    m, _, _ = counted
    v = tm.flows(m, tm.background(m, 0)[0], m.cap)
    pre = m.pre[0]
    topped_up_and_left = 0
    for north in (True, False):
        ks = [k for k in tm.road_edges(m, ["Count Road"]) if tm.heading_north(m, k) == north]
        for b in range(tm.N_BINS):
            got = v[b, ks] + pre[b, ks]
            filled = pre[b, ks] > 0
            if filled.any():
                level = got[filled][0]
                assert np.allclose(got[filled], level)
                assert (v[b, ks][~filled] >= level - 1e-9).all()
                topped_up_and_left += bool((~filled).any())
    assert topped_up_and_left > 0  # some bins top one link up and leave a busier one alone
