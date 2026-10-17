"""Compare National Highways' live NTIS predictions against their fused actuals.

The logger (scratchpad/uktu/logger.py -> data/raw/ntis/live.jsonl) captures, per
dock-approach link, the NTIS predicted-speed series (dataset 123, each row target-
timestamped) and the fused actual speed (dataset 115) as ground truth. Once a predicted
target time becomes past, its fused actual is known, so in principle we can measure how
good NTIS's own live forecast is: error and bias, broken out by lead time.

This is deliberately a measurement of NTIS against itself, not a head-to-head with our
forecaster (ours predicts flow per WebTRIS site; NTIS predicts speed per NTIS link, with
no link->site map, so they are not directly comparable).

Two subtleties, both handled here:

  1. Units/definition UNCONFIRMED -- the error numbers here are NOT a validated NTIS
     self-skill yet. The feed declares no units (both columns are raw ``::numeric``). The
     fused actual is km/h (its max exceeds the 70 mph UK motorway limit). predicted_speed
     read as km/h is physically impossible for free-flow motorway, so it is read as mph
     and converted x1.609 to km/h -- but even converted it runs far below the actual
     (predicted is roughly half the fused value, below it on almost every matched pair).
     That residual is much larger than the known space-mean-journey-time vs loop-spot-speed
     gap, so something is still wrong: either the unit is not mph either, predicted_speed
     is a different quantity, or the link<->bucket match is off. DATEX II mandates km/h, so
     this is confirmable only against raw DATEX XML / the feed owner. The report shows the
     converted (primary) and raw (diagnostic) numbers, labels them provisional, and says
     not to quote them until a clean overlap confirms the shape.
  2. Timestamp frame. The feed's ``bucket`` is Europe/London wall-clock (the dataset SQL
     casts ``AT TIME ZONE 'Europe/London'``), which the logger stored as epoch. Lead time
     is therefore computed in the London wall-clock domain (captured_at is converted to
     the same frame) so the two cancel. That same wall-clock frame is what joins this to
     WebTRIS and to our forecasts.

Each distinct predicted value for a target is scored once, at the earliest capture that
showed it (its longest realised lead); restart re-snapshots of an unchanged value are
collapsed.

CLI:  python -m sotonship26.ntis_score [--jsonl PATH] [--out notes/ntis-selfskill.md]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Lead-time buckets (minutes ahead of target that the prediction was captured).
LEAD_EDGES_MIN = (0, 15, 30, 60, 120, 240, 10_000)
# A predicted target is matched to the nearest fused actual within this tolerance.
MATCH_TOL_MIN = 7.5
# mph->km/h, used only as a diagnostic since the predicted unit is unconfirmed.
MPH_TO_KMH = 1.609
LONDON = ZoneInfo("Europe/London")


def load_rows(path: str | Path) -> list[dict]:
    """Read the logger's JSON-lines archive into a list of row dicts."""
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _wall_minutes(bucket_ms: int) -> float:
    """Feed bucket -> Europe/London wall-clock minutes-since-epoch.

    The logger stored the feed's already-localised wall-clock as epoch ms, so the ms
    value is the wall-clock numbers read as UTC. We keep working in that frame."""
    return bucket_ms / 60_000.0


def _captured_wall_minutes(captured_at: str) -> float:
    """Capture timestamp (true UTC) -> Europe/London wall-clock minutes-since-epoch,
    matching the frame the feed's bucket is in."""
    dt = datetime.fromisoformat(captured_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    wall = dt.astimezone(LONDON).replace(tzinfo=None)
    return wall.replace(tzinfo=UTC).timestamp() / 60.0


def fused_actuals(rows: list[dict]) -> dict[tuple[str, int], float]:
    """(link_id, bucket_ms) -> actual speed. Fused values are not revised, so a later
    capture of the same bucket overwrites with the same value."""
    out: dict[tuple[str, int], float] = {}
    for r in rows:
        if r.get("source") == "fused" and r.get("value") is not None:
            out[(r["link_id"], int(r["bucket_ms"]))] = float(r["value"])
    return out


def _nearest_actual(
    actuals: dict[tuple[str, int], float], link: str, target_ms: int
) -> float | None:
    """Nearest fused actual to a predicted target, within MATCH_TOL_MIN."""
    tol_ms = MATCH_TOL_MIN * 60_000
    best: tuple[float, float] | None = None  # (abs_dist_ms, value)
    for (lnk, bkt), val in actuals.items():
        if lnk != link:
            continue
        dist = abs(bkt - target_ms)
        if dist <= tol_ms and (best is None or dist < best[0]):
            best = (dist, val)
    return best[1] if best else None


def build_pairs(rows: list[dict]) -> list[dict]:
    """One scored pair per distinct predicted value for a target that has a matching
    actual, taken at the earliest capture showing that value (longest realised lead).

    Returns dicts: link_id, target_ms, lead_min, predicted, actual, abs_err, err.
    """
    actuals = fused_actuals(rows)
    # Collapse restart re-snapshots: keep the max lead seen for each (link,target,value).
    best_lead: dict[tuple[str, int, float], float] = {}
    for r in rows:
        if r.get("source") != "predicted" or r.get("value") is None:
            continue
        target_ms = int(r["bucket_ms"])
        lead = _wall_minutes(target_ms) - _captured_wall_minutes(r["captured_at"])
        if lead <= 0:  # captured at or after the target: not a forecast
            continue
        key = (r["link_id"], target_ms, round(float(r["value"]), 3))
        if lead > best_lead.get(key, 0.0):
            best_lead[key] = lead

    pairs: list[dict] = []
    for (link, target_ms, pred), lead in best_lead.items():
        actual = _nearest_actual(actuals, link, target_ms)
        if actual is None:
            continue
        pairs.append({
            "link_id": link, "target_ms": target_ms, "lead_min": lead,
            "predicted": pred, "actual": actual,
            "abs_err": abs(pred - actual), "err": pred - actual,
        })
    return pairs


def _agg(pairs: list[dict]) -> dict:
    """MAE / bias / RMSE / means over a set of pairs."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "mae": None, "bias": None, "rmse": None,
                "mean_pred": None, "mean_actual": None}
    mae = sum(p["abs_err"] for p in pairs) / n
    bias = sum(p["err"] for p in pairs) / n
    rmse = (sum(p["err"] ** 2 for p in pairs) / n) ** 0.5
    return {
        "n": n, "mae": mae, "bias": bias, "rmse": rmse,
        "mean_pred": sum(p["predicted"] for p in pairs) / n,
        "mean_actual": sum(p["actual"] for p in pairs) / n,
    }


def score_by_lead(pairs: list[dict], edges=LEAD_EDGES_MIN) -> dict:
    """Overall plus per-lead-bucket aggregates, and link/target coverage."""
    by_lead = []
    for lo, hi in zip(edges, edges[1:], strict=False):
        chunk = [p for p in pairs if lo < p["lead_min"] <= hi]
        a = _agg(chunk)
        a["lead_lo"], a["lead_hi"] = lo, hi
        by_lead.append(a)
    n_below = sum(1 for p in pairs if p["err"] < 0)
    return {
        "overall": _agg(pairs),
        "by_lead": by_lead,
        "n_links": len({p["link_id"] for p in pairs}),
        "n_targets": len({(p["link_id"], p["target_ms"]) for p in pairs}),
        "frac_pred_below_actual": (n_below / len(pairs)) if pairs else None,
    }


def _fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def _date_range(rows: list[dict]) -> tuple[str, str] | None:
    caps = [r["captured_at"] for r in rows if r.get("captured_at")]
    return (min(caps), max(caps)) if caps else None


def render_report(rows: list[dict], pairs: list[dict], scored: dict) -> str:
    rng = _date_range(rows)
    rng_s = f"{rng[0]} - {rng[1]}" if rng else "no data"
    ov = scored["overall"]
    lines = [
        "# NTIS predicted vs fused actual - diagnostics (NOT a validated self-skill yet)",
        "",
        "NTIS's own live forecast vs its fused actual on the Southampton dock-approach",
        "links (M27 / M271 / M3), from our forward log of the owner-permitted mobilityflow",
        "feed. Source: NTIS via mobilityflow (OGL / National Highways).",
        "",
        "> Units/definition UNCONFIRMED - do not quote any error below as NTIS's skill.",
        "> Fused actual is km/h (confirmed). predicted_speed carries no unit; read as **mph",
        "> and converted x1.609 to km/h** it still runs far below the actual (predicted is",
        "> roughly half the fused value, below it on almost every pair). That residual is",
        "> much larger than the known space-mean vs loop-spot-speed gap, so either the unit",
        "> is still wrong, predicted_speed is a different quantity, or the link<->bucket",
        "> match is off. DATEX II mandates km/h; confirm against raw DATEX XML / the feed",
        "> owner first. Treat as provisional - a mechanism, not a validated number yet.",
        "",
        f"- capture window (Europe/London wall-clock buckets): {rng_s}",
        f"- scored pairs: {ov['n']}  (links {scored['n_links']}, "
        f"distinct targets {scored['n_targets']})",
    ]
    if ov["n"]:
        # Primary read: predicted is mph -> convert to km/h to compare with fused.
        conv = [{**p, "predicted": p["predicted"] * MPH_TO_KMH,
                 "err": p["predicted"] * MPH_TO_KMH - p["actual"],
                 "abs_err": abs(p["predicted"] * MPH_TO_KMH - p["actual"])} for p in pairs]
        cscored = score_by_lead(conv)
        cov = cscored["overall"]
        lines += [
            f"- mean predicted {_fmt(ov['mean_pred'])} mph "
            f"(= {_fmt(ov['mean_pred'] * MPH_TO_KMH)} km/h) vs mean actual "
            f"{_fmt(ov['mean_actual'])} km/h",
            f"- predicted below actual on {cscored['frac_pred_below_actual'] * 100:.0f}% "
            "of pairs after conversion",
            "",
            "Skill (predicted mph -> km/h vs fused km/h):",
            f"- MAE {_fmt(cov['mae'])} km/h  bias {_fmt(cov['bias'])} km/h  "
            f"RMSE {_fmt(cov['rmse'])} km/h",
            f"- diagnostic, no conversion (both raw): MAE {_fmt(ov['mae'])}  "
            f"bias {_fmt(ov['bias'])}",
            "",
            "By realised lead (predicted mph -> km/h):",
            "| lead ahead (min) | n | MAE | bias | RMSE |",
            "|---|---|---|---|---|",
        ]
        for b in cscored["by_lead"]:
            if b["n"] == 0:
                continue
            hi = "+" if b["lead_hi"] >= 10_000 else str(int(b["lead_hi"]))
            label = f"{int(b['lead_lo'])}-{hi}"
            lines.append(
                f"| {label} | {b['n']} | {_fmt(b['mae'])} | {_fmt(b['bias'])} | {_fmt(b['rmse'])} |"
            )
    else:
        lines += [
            "",
            "No scored pairs yet: predicted targets whose fused actual is already known",
            "accrue as target times pass. Re-run once the log has more overlap.",
        ]
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare NTIS live predictions vs fused actuals.")
    ap.add_argument("--jsonl", default="data/raw/ntis/live.jsonl",
                    help="logger JSON-lines archive")
    ap.add_argument("--out", default="notes/ntis-selfskill.md",
                    help="markdown report to write (aggregates only, safe to commit)")
    args = ap.parse_args(argv)

    path = Path(args.jsonl)
    if not path.exists():
        print(f"no archive at {path}; run the logger first")
        return 1
    rows = load_rows(path)
    pairs = build_pairs(rows)
    scored = score_by_lead(pairs)
    report = render_report(rows, pairs, scored)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"{len(rows)} rows -> {len(pairs)} scored pairs; report -> {out}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
