"""Figure for the pitch: one test week at a WebTRIS site, learned forecast vs the planner rule.

    PYTHONPATH=src python scripts/plot_flow_forecast.py --site 20025 --week 2026-03-02
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from sotonship26.data import observed  # noqa: E402
from sotonship26.flow_forecast import LAG_DAYS, forecast, planner_rule, site_days  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--site", type=int, default=20025)
p.add_argument("--week", type=date.fromisoformat, default=date(2026, 3, 2))
args = p.parse_args()

flows = observed.load_flows([args.site], date(2024, 1, 1), date(2026, 6, 30))
dates, y = site_days(flows, args.site)
by_date = dict(zip(dates, y, strict=True))
published = dates <= args.week - timedelta(days=LAG_DAYS)
week = [args.week + timedelta(days=i) for i in range(7)]
fc = forecast(dates[published], y[published], week)

fig, ax = plt.subplots(figsize=(10, 3.4))
t = np.arange(7 * 96) / 96
actual = np.concatenate([by_date.get(d, np.full(96, np.nan)) for d in week])
rule = np.concatenate([planner_rule(d, by_date, LAG_DAYS) for d in week])
ax.fill_between(t, fc["lo80"], fc["hi80"], color="#2563eb", alpha=0.18, label="learned, 80% band")
ax.plot(t, fc["flow_veh"], color="#2563eb", lw=1.2, label="learned forecast")
ax.plot(t, rule, color="#94a3b8", lw=1, ls="--", label="planner rule (last year / recent)")
ax.plot(t, actual, color="#111827", lw=0.8, label="observed")
ax.set_xticks(np.arange(7) + 0.5, [d.strftime("%a %d %b") for d in week])
ax.set_ylabel("vehicles / 15 min")
name = observed.SITES[args.site]["name"]
ax.set_title(f"WebTRIS {args.site} ({name}): forecast made {LAG_DAYS} days ahead with only "
             "published data")
ax.legend(fontsize=7, ncol=4, loc="upper left")
fig.text(0.01, 0.01, "Contains National Highways data © Crown copyright and database right 2026, "
         "OGL v3.0", fontsize=6)
fig.tight_layout()
out = Path(__file__).resolve().parents[1] / "notes" / "figures" / f"flow_forecast_{args.site}.png"
fig.savefig(out, dpi=140)
print(out)
