"""The SUMO check's own pieces (demo/sumo_demand.py, demo/sumo_compare.py) on toy inputs.

Needs no SUMO, network or cached data:

    uv run --with scipy --with shapely pytest tests/test_sumo_check.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("scipy")
from scipy.spatial import cKDTree  # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "demo"
sys.path.insert(0, str(DEMO))
import sumo_compare as sc  # noqa: E402
import sumo_demand as sdm  # noqa: E402


def test_whole_keeps_the_expected_totals():
    rng = np.random.default_rng(1)
    lam = rng.gamma(0.5, 2.0, size=(60, 40))
    draws = np.stack([sdm.whole(lam, rng) for _ in range(400)])
    assert np.all((draws == np.floor(lam)) | (draws == np.floor(lam) + 1))
    assert abs(draws.sum(axis=(1, 2)).mean() - lam.sum()) < 0.01 * lam.sum()


def test_densify_spacing_and_heading():
    pts, hd = sdm.densify(np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]]), step=10.0)
    assert len(pts) == 15
    assert np.allclose(hd[:10], 0.0) and np.allclose(hd[10:], math.pi / 2)


def toy_net(shapes: dict[str, list]):
    ids = list(shapes)
    shape = [np.asarray(shapes[i], float) for i in ids]
    mid = np.array([s.mean(axis=0) for s in shape])
    return SimpleNamespace(ids=ids, shape=shape, tree=cKDTree(mid),
                           page_to_xy=lambda p: np.asarray(p, float).reshape(-1, 2))


def test_match_edges_keeps_the_direction():
    """A macro edge running east matches the eastbound SUMO edge beside it, not the westbound
    one on the same road, nor a road 200 m away."""
    m = SimpleNamespace(coords=[[(0, 0), (300, 0)]])
    net = toy_net({"east": [(0, 3), (150, 3), (300, 3)], "west": [(300, -3), (0, -3)],
                   "far": [(0, 200), (300, 200)]})
    assert sdm.match_edges(net, m, [0]) == {"east": 0}


def test_macro_corridor_splits_directions_and_caps_flow():
    x = np.zeros((60, 3))
    x[10] = [0.5, 1.5, 2.0]
    mac = {"x": x, "cap": np.array([1000.0, 1000.0, 2000.0]), "t0": np.array([60.0, 60.0, 60.0]),
           "queue": np.maximum(x - 1, 0) * 250, "length": np.array([500.0, 500.0, 500.0])}
    out = sc.macro_corridor(mac, [0, 1, 2], {"0": True, "1": True, "2": False})
    assert out["NB"]["vc"][10] == 1.5 and out["SB"]["vc"][10] == 2.0
    assert out["NB"]["flow"][10] == 750.0  # median of 500 and 1000 (capped at capacity)
    assert out["NB"]["demand"][10] == 1000.0
    # BPR running time on both NB links plus the point-queue wait at the worst link (V/C 1.5)
    run = (60 * 0.15 * 0.5**4 + 60 * 0.15 * 1.5**4) / 60
    assert out["NB"]["delay"][10] == pytest.approx(run + 15 * 0.5)


def test_agreement_counts():
    pairs = [(1.2, 0.3), (1.2, 0.9), (0.5, 0.4), (0.5, 0.95)]
    ag = sc.agreement(pairs)
    assert ag["jammed"] == {**ag["jammed"], "both": 1, "macro_only": 1, "sumo_only": 1,
                            "neither": 1}
