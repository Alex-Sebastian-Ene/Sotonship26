"""Robust PPO summaries with date-resampled intervals (demo/ppo_robust.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import ppo_robust as pr  # noqa: E402


def test_paired_differences_and_robust_stats(tmp_path):
    rows = ["policy,date,seed,held_out,corridor_hours,vehicle_hours,cost"]
    for date in ("2026-10-19", "2026-10-24", "2026-10-30"):
        for seed in range(5):
            rows.append(f"nothing,{date},{seed},True,10,100,60000")
            extra = 50 if seed == 0 else 0  # one extreme day per date
            rows.append(f"ppo,{date},{seed},True,{8 + extra},100,{50000 + extra * 5000}")
    path = tmp_path / "ep.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    res = pr.run(path)["results"]["held_out"]["ppo"]
    ch = res["corridor_hours"]
    assert ch["median"]["value"] == pytest.approx(-2.0)  # the typical day
    assert ch["mean"]["value"] == pytest.approx((-2 * 4 + 48) / 5)  # pulled up by the extreme days
    assert ch["trimmed"]["value"] < ch["mean"]["value"]
    assert ch["n_dates"] == 3 and ch["n_days"] == 15
    assert ch["mean"]["lo"] <= ch["mean"]["value"] <= ch["mean"]["hi"]
    money = res["money"]  # cost less the congestion weight: 50000 - 8 * 5000 vs 60000 - 10 * 5000
    assert money["median"]["value"] == pytest.approx(0.0)
