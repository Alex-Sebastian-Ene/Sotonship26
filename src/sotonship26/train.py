"""Train a PPO policy that meters and steers flows through a sampled turnaround day."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

from sotonship26.config import load_config
from sotonship26.rl import CongestionEnv
from sotonship26.synthetic import SCENARIOS


def make_env(name: str, routing: dict) -> CongestionEnv:
    scenario = SCENARIOS[name]
    graph = scenario.build_graph()
    return CongestionEnv(
        partial(scenario.sample_day, graph=graph),
        scenario.controllable,
        scenario.n_bins,
        routing=routing,
    )


def main(argv: list[str] | None = None) -> None:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="streets")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--timesteps", type=int, help="default from config")
    parser.add_argument("--n-envs", type=int, help="default from config")
    parser.add_argument("--n-steps", type=int, help="rollout length per env (default from config)")
    parser.add_argument("--device", default=None, help="cpu, cuda or auto (default from config)")
    parser.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    rl = cfg["rl"]
    routing = {**cfg["routing"], "max_iters": rl["routing_max_iters"]}
    env = make_vec_env(
        lambda: make_env(args.scenario, routing),
        n_envs=args.n_envs or rl["n_envs"],
        seed=rl["seed"],
    )
    model = PPO(
        "MlpPolicy",
        env,
        n_steps=args.n_steps or rl["n_steps"],
        seed=rl["seed"],
        device=args.device or rl["device"],
        tensorboard_log=str(args.out / "tensorboard"),
        verbose=1,
    )
    model.learn(total_timesteps=args.timesteps or rl["timesteps"], tb_log_name=args.scenario)
    path = args.out / f"ppo_{args.scenario}"
    model.save(path)
    print(f"Saved {path}.zip")


if __name__ == "__main__":
    main()
