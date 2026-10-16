"""Monte Carlo congestion forecast for a scenario: overload probability per edge and time bin."""

from __future__ import annotations

import argparse
from datetime import timedelta
from functools import partial
from pathlib import Path

import pandas as pd

from sotonship26.config import load_config
from sotonship26.forecast import forecast
from sotonship26.synthetic import SCENARIOS


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="streets")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--n", type=int, help="Monte Carlo scenarios (default from config)")
    parser.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    scenario = SCENARIOS[args.scenario]
    graph = scenario.build_graph()
    result = forecast(
        partial(scenario.sample_day, graph=graph),
        n_scenarios=args.n or cfg["forecast"]["n_scenarios"],
        seed=cfg["forecast"]["seed"],
        threshold=cfg["forecast"]["overload_threshold"],
        routing=cfg["routing"],
    )

    def clock(df: pd.DataFrame) -> pd.DataFrame:
        times = [scenario.day_start + timedelta(minutes=b * scenario.bin_minutes) for b in df.bin]
        return df.assign(time=[t.strftime("%H:%M") for t in times])

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"forecast_{args.scenario}"
    clock(result.edges).to_csv(f"{stem}_edges.csv", index=False)
    print(f"SYNTHETIC TEST SCENARIO '{args.scenario}': not Southampton data.\n")
    print(f"Top overload risks ({args.scenario}):")
    print(clock(result.hotspots(10)).to_string(index=False))
    if not result.held.empty:
        clock(result.held).to_csv(f"{stem}_held.csv", index=False)
        print("\nWhere traffic is held up most often:")
        print(clock(result.held.head(10)).to_string(index=False))
    print(f"\nWrote {stem}_*.csv")


if __name__ == "__main__":
    main()
