"""Numbers for docs/queues.md from one cluster/iridis/bus_check.slurm run: the count fits (from the
build log), corridor-hours at risk (from the page) and the Portswood bus check (bus_*.json).

    python demo/queue_report.py demo/out/check [--page demo/out/demo.html]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daysim  # noqa: E402

DAYS = ("2026-10-21", "2026-10-24", "2026-11-07", "2026-11-16")


def fits(log: str) -> None:
    print("count fits (build log):")
    for pat in (r"calibrate DfT: chose .*", r"calibrate: chose .*", r"calibrate freight: chose .*"):
        found = re.findall(pat, log)
        for line in found[-1:] if "DfT" not in pat else found:
            print("  " + line)
    for line in re.findall(r"capacity .*", log):
        print("  " + line)
    for line in re.findall(r"  DfT +\d+ .*", log)[-12:]:
        print(" " + line)
    roads = r"  (?:Portswood|Highfield|St Denys|Bevois).*weekday +(?:am|pm) .*"
    for line in re.findall(roads, log):
        print(" " + line)


def risk(page: dict) -> None:
    days = [d for d in page["days"] if not d.get("beyond")]
    corr = [c["id"] for c in page["corridors"]]
    hrs = {c: np.mean([np.sum(d["p85"][c]) / 100 / 4 for d in days]) for c in corr}
    bg = {c: np.mean([np.sum(d["bg85"][c]) / 100 / 4 for d in days]) for c in corr}
    print(f"corridor-hours at risk (V/C > {page['meta']['at_risk']}), mean per day over "
          f"{len(days)} days: {np.mean([d['score'] for d in days]):.1f} with ships, "
          f"{np.mean([d['bg_score'] for d in days]):.1f} without")
    up = [d["score"] - d["bg_score"] for d in days if d.get("calls")]
    print(f"  cruise uplift on ship days: mean {np.mean(up):.2f} corridor-h ({len(up)} days)")
    print("  by corridor (with ships / without):")
    for c in sorted(corr, key=lambda c: -hrs[c]):
        if hrs[c] >= 0.05:
            print(f"    {c:12s} {hrs[c]:5.2f} / {bg[c]:5.2f}")
    by = {d["date"]: d for d in days}
    for k in DAYS:
        if k in by:
            d = by[k]
            print(f"  {k}: {d['score']:.1f} with ships, {d['bg_score']:.1f} without; "
                  f"Portswood Road {np.sum(d['p85']['portswood']) / 400:.2f} h; "
                  f"vehicles held over a bin {sum(d['held'])}")


def bus(path: Path) -> None:
    s = json.loads(path.read_text(encoding="utf-8"))
    print(f"{path.name}: {s['date']}, UNI_TERM {s['uni_term']}, {s['n']} sampled days "
          "(model min different to timetable / council; 5+ min share, whole day)")
    for r in s["rows"]:
        cells = [f"{r[p]['diff']:5.1f}/{r['council'][p]:4.1f}" if r[p] else "  -  "
                 for p in ("am", "pm")]
        print(f"  Bluestar {r['route']:2s} {r['dir']:10s} AM {cells[0]}  PM {cells[1]}  "
              f"5+ {100 * (r['five'] or 0):4.1f}%/{100 * r['council']['five']:4.1f}%")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    ap.add_argument("--page", type=Path, default=HERE / "out" / "demo.html")
    args = ap.parse_args(argv)
    log = args.dir / "build.log"
    if log.exists():
        fits(log.read_text(encoding="utf-8"))
    page = daysim.page_data(args.page)
    if page:
        risk(page)
    for p in sorted(args.dir.glob("bus_*.json")):
        bus(p)


if __name__ == "__main__":
    main()
