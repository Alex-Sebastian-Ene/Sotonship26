"""demo/ppo_stats.py: the statistics behind the page's "PPO in numbers" charts.

Synthetic episodes only, so it needs no PPO run:

    uv run pytest tests/test_ppo_stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "demo"
sys.path.insert(0, str(DEMO))
import ppo_stats as ps  # noqa: E402


def _episodes():
    rows = []
    for d, held in (("2026-10-19", True), ("2026-10-21", False)):
        for s in range(3):
            base = 1000.0 + 100 * s
            rows.append({"policy": "nothing", "date": d, "seed": str(s), "held_out": str(held),
                         "cost": base, "corridor_hours": 10.0, "vehicle_hours": 50.0,
                         "marshal_hours": 0.0, "sign_hours": 0.0})
            for p, dc in (("rule", 20.0), ("advisor", -10.0), ("ppo", -30.0 - s)):
                rows.append({"policy": p, "date": d, "seed": str(s), "held_out": str(held),
                             "cost": base + dc, "corridor_hours": 9.0, "vehicle_hours": 51.0,
                             "marshal_hours": 2.0, "sign_hours": 1.0})
    return rows


def test_paired_differences_line_up_with_days():
    st = ps.paired(_episodes())
    assert len(st["days"]) == 6
    assert [d["held_out"] for d in st["days"]] == [True] * 3 + [False] * 3
    assert st["diff"]["rule"]["cost"] == [20.0] * 6
    assert st["diff"]["ppo"]["cost"][:3] == [-30.0, -31.0, -32.0]
    assert st["diff"]["ppo"]["corridor_hours"] == [-1.0] * 6


def test_by_date_and_head_to_head():
    st = ps.paired(_episodes())
    by = {r["date"]: r for r in st["by_date"]}
    assert by["2026-10-19"]["held_out"] and not by["2026-10-21"]["held_out"]
    assert by["2026-10-19"]["ppo"]["cost"] == pytest.approx(-31.0)
    h = st["head_to_head"]["rule"]
    assert h["mean"] == pytest.approx(-51.0) and h["ppo_cheaper"] == 1.0 and h["n"] == 6
    assert h["lo"] <= h["mean"] <= h["hi"]


def test_curve_chunks_training_days():
    rows = [{"cost": 100 - i, "nothing_cost": 100, "steps": 96 * (i + 1), "seconds": 6 * i,
             "marshal_hours": i / 10} for i in range(200)]
    cv = ps.curve(rows, points=10)
    assert len(cv) == 10 and cv[-1]["days"] == 200 and cv[-1]["steps"] == 96 * 200
    assert cv[0]["mean"] < cv[-1]["mean"]  # saving grows as cost falls
    assert "marshal_hours" in cv[0] and "sign_hours" not in cv[0]


def test_bundle_skips_missing_parts():
    ppo = {"summary": {"all": {"ppo": {"n": 6, "better_days": 1.0,
                                       **{m: {"diff": -1.0, "diff_lo": -2.0, "diff_hi": 0.0}
                                          for m in ("cost", "corridor_hours")}}}},
           "train": {"timesteps": 1000, "days": 10, "seconds": 120}}
    st = ps.bundle(ppo, None, None, {"This run": ppo})
    assert "curve" not in st and "diff" not in st
    assert st["runs"][0]["cost_diff"] == -1.0 and st["runs"][0]["minutes"] == 2
    assert "synthetic" in st["source"]
