# Documents

Start with the [brief](brief.md), then the [design decisions](decisions.md).

| Document | What it covers |
| --- | --- |
| [brief.md](brief.md) | The project in two pages: problem, user, what we built, results, limits, business case |
| [decisions.md](decisions.md) | Each design decision, why we made it and the evidence |
| [design.md](design.md) | The original plan from Friday night, kept as written |
| [backtest.md](backtest.md) | The learned cruise effect on the M271 against three baselines, 179 held-out days |
| [ridge-history.md](ridge-history.md) | Does adding past traffic help, at realistic publication delays? |
| [agents-and-ppo.md](agents-and-ppo.md) | Individual vehicles and buses, and the PPO decision layer with its tests and ablation |
| [ppo-results-aa8eae9.md](ppo-results-aa8eae9.md), [ppo-robust-aa8eae9.md](ppo-robust-aa8eae9.md) | The PPO results we quote: re-scored on the corrected demand, 18 Oct 2026, with date-resampled intervals |
| [ppo-results.md](ppo-results.md), [-gpu](ppo-results-gpu.md), [-gpu2](ppo-results-gpu2.md) | Earlier PPO runs A, B and C, superseded by the aa8eae9 re-score |
| [west-side-counts.md](west-side-counts.md) | Why the model over-predicted the M271 and the Redbridge Causeway, and the fixes |
| [queues.md](queues.md) | The Portswood Road bus check and the capacity change it led to |
| [sumo-check.md](sumo-check.md) | The macro model against the Eclipse SUMO microsimulator |

Evaluation notes and research are in [../notes](../notes): the everyday traffic forecast
([flow-forecast.md](../notes/flow-forecast.md)), how the learning works
([ml-walkthrough.md](../notes/ml-walkthrough.md)), past cruise calls
([cruise-history.md](../notes/cruise-history.md)), observed noise, camera counts, freight feeds,
NTIS scoring and the local evidence behind the brief ([local-evidence.md](../notes/local-evidence.md)).
