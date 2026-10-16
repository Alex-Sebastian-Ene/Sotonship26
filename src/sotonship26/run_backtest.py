"""End to end on real data: WebTRIS flows + historic cruise calls -> uplift -> backtest -> model.

    python -m sotonship26.run_backtest --start 2024-01-01 --end 2026-06-30 --cutoff 2025-07-01

Writes runs/backtest/ (full outputs, not in git), notes/backtest.md and notes/figures/ (summary
for the team and the pitch) and models/uplift_ridge.json (what the app forecasts with).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from sotonship26 import uplift_model
from sotonship26.backtest import backtest_site, day_features, site_targets, skill
from sotonship26.data import cruise_history, observed
from sotonship26.uplift import detectability, observed_uplift

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "backtest"
NOTES = ROOT / "notes"


def md_table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def plot_detectability(det: pd.DataFrame, out: Path) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for site, g in det.groupby("site_id"):
        fig, ax = plt.subplots(figsize=(7, 3.2))
        for cruise, colour, label in ((True, "#c2410c", "cruise days"),
                                      (False, "#64748b", "no-cruise days")):
            s = g[g["cruise_day"] == cruise]
            if s.empty:
                continue
            ax.plot(s["hour"], s["mean_uplift_veh_per_hour"], color=colour,
                    label=f"{label} (n={s['n_days'].iloc[0]})")
            ax.fill_between(s["hour"], s["ci5"], s["ci95"], color=colour, alpha=0.2)
        ax.axhline(0, color="black", lw=0.5)
        name = observed.SITES.get(site, {}).get("name", "")
        ax.set_title(f"WebTRIS {site} {name}: traffic above the no-cruise reference")
        ax.set_xlabel("hour of day (local)")
        ax.set_ylabel("vehicles / hour")
        ax.legend(fontsize=8)
        fig.text(0.01, 0.01, "Contains National Highways data, OGL v3.0. Band: 90% bootstrap CI.",
                 fontsize=6)
        fig.tight_layout()
        path = out / f"detectability_{site}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        paths.append(path)
    return paths


def write_report(table: pd.DataFrame, det: pd.DataFrame, args, coverage: dict,
                 figures: list[Path]) -> Path:
    peak = (det[det["cruise_day"]].sort_values("mean_uplift_veh_per_hour", ascending=False)
            .groupby("site_id").head(1)
            [["site_id", "hour", "n_days", "mean_uplift_veh_per_hour", "ci5", "ci95"]])
    quiet = det[~det["cruise_day"]].groupby("site_id")["mean_uplift_veh_per_hour"]
    quiet = quiet.apply(lambda s: s.abs().max()).rename("max_abs_uplift_no_cruise").reset_index()
    peak = peak.merge(quiet, on="site_id", how="left")
    cruise_rows = table[table["days"] == "cruise_days"].sort_values(["site_id", "model"])
    cols = ["site_id", "model", "n_days", "mae_veh_per_15min", "skill_vs_best_baseline",
            "brier", "coverage80", "width80_veh"]
    lines = [
        "# Backtest: is cruise traffic visible, and can we predict it?",
        "",
        f"Generated {datetime.now():%a %d %b %Y %H:%M} by `python -m sotonship26.run_backtest "
        f"--start {args.start} --end {args.end} --cutoff {args.cutoff}`. Train on days before "
        f"{args.cutoff}, test on days from it. Traffic: National Highways WebTRIS 15-minute "
        "counts (OGL v3.0). Cruise calls: see `data/cruise_history.py` for source and coverage.",
        "",
        "## 1. Is the cruise effect visible at each sensor?",
        "",
        "Peak hourly uplift on cruise days with a 90% bootstrap interval over days, next to the "
        "largest hourly uplift on no-cruise days (which should be near zero). If the interval "
        "for cruise days includes zero, the sensor cannot see cruise traffic.",
        "",
        md_table(peak, "{:.0f}"),
        "",
        *[f"![{p.stem}](figures/{p.name})" for p in figures],
        "",
        "## 2. Test-period scores on cruise days (05:00-22:00 bins)",
        "",
        "`mae` is vehicles per 15 min. `skill` is 1 - MAE / best baseline MAE (above 0 means the "
        "learned model wins). `brier` scores P(uplift above the site's unusual-traffic "
        "threshold), lower is better. `coverage80` should be close to 0.80.",
        "",
        md_table(cruise_rows[cols]),
        "",
        "All-days scores (including days without ships, which checks false alarms) are in "
        "`runs/backtest/table.csv`.",
        "",
        "## 3. Data coverage",
        "",
        *[f"- {k}: {v}" for k, v in coverage.items()],
        "",
        "## Limits",
        "",
        "- WebTRIS publishes about 3.5 months late, so no observed counts exist for the demo "
        "weekend. Forecasts for future days use the model, and say so.",
        "- The sensors are 5-7 km from the dock gates on the motorway approaches. Roads closer "
        "to the docks have no public 15-minute counts, so their values are modelled, not "
        "measured.",
        "- School holidays and events other than cruises are not removed from the reference, so "
        "they add noise to the target.",
        "- Ship passenger numbers are capacities, not actual loads.",
    ]
    path = NOTES / "backtest.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    p.add_argument("--cutoff", type=date.fromisoformat, default=date(2025, 7, 1))
    p.add_argument("--sites", type=int, nargs="*", default=list(observed.SITES))
    args = p.parse_args(argv)
    RUNS.mkdir(parents=True, exist_ok=True)

    flows = observed.load_flows(args.sites, args.start, args.end)
    calls = cruise_history.load_calls(args.start, args.end)
    days = cruise_history.cruise_days(calls, args.start, args.end)
    if not ((days["n_calls"] > 0) & days["covered"]).any():
        print("No covered cruise days in range, so there is nothing to learn the cruise effect "
              "from. Add a permitted historic call list (data/raw/cruise_history/"
              "manual_calls.csv + manual_coverage.csv, see notes/cruise-history.md and SOT-21).")
        return 1
    up = observed_uplift(flows, days)
    up.to_csv(RUNS / "uplift.csv.gz", index=False)
    det = detectability(up)
    det.to_csv(RUNS / "detectability.csv", index=False)
    feats = day_features(days, calls)

    tables, models = [], []
    for site in args.sites:
        dates, y = site_targets(up, site)
        if len(dates) < 40:
            print(f"site {site}: only {len(dates)} usable days, skipped")
            continue
        res = backtest_site(site, dates, y, feats, args.cutoff)
        if res is None:
            print(f"site {site}: not enough days on one side of the cutoff, skipped")
            continue
        tables.append(res.table)
        models.append(uplift_model.fit_site(site, dates, y, feats, res.threshold))
        print(f"site {site}: train {res.n_train} days, test {res.n_test} days, "
              f"ridge lambda {res.ridge.lam if res.ridge else '-'}")
    if not tables:
        print("No site had enough usable days on both sides of the cutoff.")
        return 1
    table = skill(pd.concat(tables, ignore_index=True))
    table.to_csv(RUNS / "table.csv", index=False)
    table.to_csv(NOTES / "backtest_table.csv", index=False)
    uplift_model.save(models, {"trained": f"{datetime.now():%Y-%m-%d %H:%M}",
                               "data_start": str(args.start), "data_end": str(args.end),
                               "source": "WebTRIS (OGL v3.0) + historic cruise calls"})
    covered = days["covered"].astype(bool)
    coverage = {
        "days in range": len(days),
        "days with known schedule (covered)": int(covered.sum()),
        "cruise days (covered)": int(((days["n_calls"] > 0) & covered).sum()),
        "usable site-days (complete, good quality)": int(up.groupby(["site_id", "date"])
                                                         ["uplift_veh"].apply(
                                                             lambda s: s.notna().all()).sum()),
    }
    figures = plot_detectability(det, NOTES / "figures")
    report = write_report(table, det, args, coverage, figures)
    print(report.read_text())
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
