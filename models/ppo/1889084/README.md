# PPO decision layer, run 1889084

The trained policy behind the "learned policy's plan" on the forecast page. Copied from Iridis
(`/scratch/ase1g23/sotonship26-agents-ppo/runs/ppo/1889084/`), so anyone can build the full page
without access to the cluster.

- `model.zip`: Stable-Baselines3 2.9.0 PPO (PyTorch 2.14.1), saved by `demo/train_ppo.py train`.
- `train.json`: training settings and the training dates. 8,000,000 timesteps over 133,376 sampled
  days, 128 parallel environments on one NVIDIA A100 (about 44 minutes), seed 26. This is run C, with
  the sign cost; method and results are in `docs/agents-and-ppo.md` and `docs/ppo-results.md`.

The weights hold no schedule data. The policy's plan for each day comes from running it on that
day's simulated traffic, so build the page outputs yourself for your own schedule:

```
uv sync --extra cpu
uv run python demo/train_ppo.py evaluate --model models/ppo/1889084/model.zip --workers 4
uv run python demo/train_ppo.py ablation --model models/ppo/1889084/model.zip --workers 4
uv run python demo/page_extras.py --page demo/out/demo.html --template demo/page.html \
    --ppo demo/out/ppo.json --ablation demo/out/ppo_ablation.json --out demo/out/demo_final.html
```

`demo/out/` stays gitignored: its JSON names ships and times from the VTS schedule, which is not
ours to redistribute. Loading the model on a CPU-only machine works (`PPO.load(..., device="cpu")`).
