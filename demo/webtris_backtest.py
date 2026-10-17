"""Learned cruise uplift on the M271, backtested against simple baselines on later held-out days.

Target: northbound M271 15-minute vehicle counts (National Highways WebTRIS) minus the median for
the same weekday and time on non-cruise days. A gradient-boosted quantile model learns that uplift
from turnaround passengers at the Eastern and Western Docks, time of day, weekday, school and bank
holidays, Southampton FC home matches and season. It is tested on Jan to Jun 2026 with a rolling
origin (refit at the start of each month on earlier days only) against three baselines: the last
comparable cruise day, a passenger-count-only linear model, and no cruise effect.

Sources, each fetched once and kept under data/cache or data/raw (both gitignored):
  - WebTRIS 15-minute counts, sites 7588 and 19974 (M271 northbound), via the public API.
  - Past cruise calls: Southampton VTS cruise schedule pages as captured by the Internet Archive.
    ABP content: personal reference only, ABP acknowledged; raw copies stay private and only
    aggregates are published. CruiseMapper is NOT used: its terms forbid automated collection.
  - Ship passenger capacity: Wikidata P1083 (CC0), matched on ship name.
  - Bank holidays: gov.uk (OGL v3). School holidays: Southampton City Council term dates
    (archived council pages, typed in below). Saints home league matches: football-data.co.uk.

    uv run --no-project --python 3.12 --with numpy --with pandas --with scikit-learn \
        python demo/webtris_backtest.py
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
RAW = ROOT / "data" / "raw"
OUT_JSON = ROOT / "demo" / "out" / "backtest.json"
OUT_DOC = ROOT / "docs" / "backtest.md"

START = date(2024, 1, 1)
END = date(2026, 6, 30)
TEST_START = date(2026, 1, 1)  # first held-out day; the target's medians use days before this only
UA = "sotonship26-backtest/0.1 (SotonShip 2026 hackathon, non-commercial research)"

# Northbound M271, stitched: 7588 to 22 Aug 2024, 19974 from 7 Oct 2024 (notes/data-spike.md s7).
SITES = {
    7588: "M271 northbound between J1 and M27 (WebTRIS 7588, 5550/1)",
    19974: "M271 northbound between A35 and J1 (WebTRIS 19974, 5120/1)",
}
WEBTRIS = "https://webtris.nationalhighways.co.uk/api/v1.0"
CDX = "https://web.archive.org/cdx/search/cdx"
WIKIDATA = "https://query.wikidata.org/sparql"
BANK_HOLIDAYS = "https://www.gov.uk/bank-holidays.json"
FOOTBALL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
TERM_SOURCE = (
    "https://www.southampton.gov.uk/schools-learning/school-information/school-term-dates/"
    "school-year-calendar-<year>/ (Internet Archive captures of Feb to Mar 2024)"
)

# Southampton City Council terms for maintained schools. Every day outside a term (weekends
# included) between the first and last listed term is a school holiday.
TERMS = [
    ("2023-09-04", "2023-10-20"), ("2023-10-30", "2023-12-15"), ("2024-01-02", "2024-02-09"),
    ("2024-02-19", "2024-03-28"), ("2024-04-15", "2024-05-24"), ("2024-06-03", "2024-07-24"),
    ("2024-09-02", "2024-10-25"), ("2024-11-04", "2024-12-20"), ("2025-01-06", "2025-02-14"),
    ("2025-02-24", "2025-04-04"), ("2025-04-22", "2025-05-23"), ("2025-06-02", "2025-07-22"),
    ("2025-09-03", "2025-10-24"), ("2025-11-03", "2025-12-19"), ("2026-01-05", "2026-02-13"),
    ("2026-02-23", "2026-03-27"), ("2026-04-13", "2026-05-22"), ("2026-06-01", "2026-07-22"),
]

BINS = 96
VALID_MIN_ROWS = 90
VALID_MIN_TOTAL = 1000


def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str, *, accept: str | None = None, tries: int = 4) -> tuple[int, bytes]:
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if accept:
        headers["Accept"] = accept
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                status, body = r.status, r.read()
            if body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            return status, body
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            wait = 65 if e.code == 429 else 10 * (attempt + 1)
        except (urllib.error.URLError, TimeoutError):
            wait = 10 * (attempt + 1)
        log(f"  {urllib.parse.urlsplit(url).netloc}: retry in {wait}s")
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def mtime_range(paths: list[Path]) -> tuple[str, str]:
    ts = sorted(datetime.fromtimestamp(p.stat().st_mtime, UTC) for p in paths)
    return ts[0].strftime("%Y-%m-%d"), ts[-1].strftime("%Y-%m-%d")


# --------------------------------------------------------------------------------------------
# WebTRIS
# --------------------------------------------------------------------------------------------


def months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def webtris_month(site: int, y: int, m: int) -> Path:
    path = CACHE / "webtris" / f"{site}_{y}{m:02d}.csv"
    if path.exists():
        return path
    first = date(y, m, 1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    url = (f"{WEBTRIS}/reports/{first:%d%m%Y}/to/{last:%d%m%Y}/daily"
           f"?sites={site}&page=1&page_size=5000")
    status, body = http_get(url, accept="application/json")
    rows = json.loads(body)["Rows"] if status == 200 and body.strip() else []
    df = pd.DataFrame({
        "date": [r["Report Date"][:10] for r in rows],
        "end": [r["Time Period Ending"][:5] for r in rows],
        "total": [r["Total Volume"] for r in rows],
        "len661": [r["661 - 1160 cm"] for r in rows],
        "len1160": [r["1160+ cm"] for r in rows],
        "mph": [r["Avg mph"] for r in rows],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    time.sleep(0.3)
    return path


def load_webtris() -> tuple[pd.DataFrame, dict]:
    """15-minute counts on valid days: site, date, bin (0 = 00:00-00:14), flow, big."""
    paths = [webtris_month(s, y, m) for s in SITES for y, m in months(START, END)]
    frames = []
    for p in paths:
        df = pd.read_csv(p)
        if df.empty:
            continue
        df["site"] = int(p.stem.split("_")[0])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df[pd.to_numeric(df["total"], errors="coerce").notna()].copy()
    df["flow"] = df["total"].astype(float)
    df["big"] = pd.to_numeric(df["len661"], errors="coerce").fillna(0) + pd.to_numeric(
        df["len1160"], errors="coerce").fillna(0)
    hh, mm = df["end"].str.slice(0, 2).astype(int), df["end"].str.slice(3, 5).astype(int)
    df["bin"] = (hh * 60 + mm + 1) // 15 - 1
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.drop_duplicates(["site", "date", "bin"])
    # A valid day has >= 90 of 96 intervals, > 1,000 vehicles and no zero interval in the daytime
    # (the M271 is never empty between 07:00 and 20:00; zeros there are sensor dropouts).
    g = df.groupby(["site", "date"])
    day = pd.DataFrame({"n": g.size(), "total": g["flow"].sum()})
    daytime = df[(df["bin"] >= 28) & (df["bin"] < 80)]
    day["zero_daytime"] = daytime.groupby(["site", "date"])["flow"].apply(lambda s: (s <= 0).any())
    day["valid"] = ((day["n"] >= VALID_MIN_ROWS) & (day["total"] > VALID_MIN_TOTAL)
                    & ~day["zero_daytime"].fillna(True))
    ok = day[day["valid"]].reset_index()[["site", "date"]]
    df = df.merge(ok, on=["site", "date"])
    # If both sensors are valid on a day (they are not, in this period), keep the later site.
    df = df[df["site"] == df.groupby("date")["site"].transform("max")]
    meta = {
        "source": "National Highways WebTRIS API (webtris.nationalhighways.co.uk), daily report",
        "sites": {str(k): v for k, v in SITES.items()},
        "retrieved": " to ".join(dict.fromkeys(mtime_range(paths))),
        "valid_days": {str(s): int(n)
                       for s, n in day[day["valid"]].groupby(level=0).size().items()},
        "valid_rule": f">= {VALID_MIN_ROWS} of 96 intervals, > {VALID_MIN_TOTAL} vehicles, "
                      "no zero interval 07:00-20:00",
    }
    return df[["site", "date", "bin", "flow", "big"]].reset_index(drop=True), meta


# --------------------------------------------------------------------------------------------
# Past cruise calls (Southampton VTS cruise schedule, as archived by the Internet Archive)
# --------------------------------------------------------------------------------------------


def vts_captures() -> list[tuple[str, str]]:
    """One capture per distinct page content (CDX digest), earliest timestamp first."""
    path = RAW / "vts_archive" / "cdx.json"
    if not path.exists():
        q = urllib.parse.urlencode([
            ("url", "southamptonvts.co.uk"), ("matchType", "domain"), ("output", "json"),
            ("filter", "original:.*LoadXmlFileWithTransform.*Cruise_Ships.*"),
            ("filter", "statuscode:200"), ("fl", "timestamp,original,digest"), ("limit", "5000"),
        ])
        _, body = http_get(f"{CDX}?{q}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    rows = sorted(json.loads(path.read_text(encoding="utf-8"))[1:])
    seen, out = set(), []
    lo = (START - timedelta(days=240)).strftime("%Y%m%d")
    hi = END.strftime("%Y%m%d")
    for ts, original, digest in rows:
        if digest in seen or not (lo <= ts[:8] <= hi):
            continue
        seen.add(digest)
        out.append((ts, original))
    return out


def vts_capture(ts: str, original: str) -> Path:
    path = RAW / "vts_archive" / f"{ts}.html"
    if not path.exists():
        _, body = http_get(f"https://web.archive.org/web/{ts}id_/{original}")
        path.write_bytes(body)
        time.sleep(3)
    return path


CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def parse_vts(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode(
        "utf-8", "replace")
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", text, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in CELL.findall(tr)]
        if len(cells) < 4:
            continue
        ship, arr, dep, berth = cells[:4]
        try:
            a = datetime.strptime(arr.split()[0], "%d-%b-%y").date()
            d = datetime.strptime(dep.split()[0], "%d-%b-%y").date()
        except (ValueError, IndexError):
            continue
        rows.append({"ship": ship.upper(), "arr": a, "dep": d, "berth": berth,
                     "arr_time": arr.split()[1] if len(arr.split()) > 1 else "",
                     "dep_time": dep.split()[1] if len(dep.split()) > 1 else ""})
    return pd.DataFrame(rows)


def berth_group(berth: str) -> str:
    m = re.match(r"\d+", berth or "")
    if not m:
        return "unknown"
    return "east" if int(m.group()) < 100 else "west"  # 38/9 QEII, 46 Ocean | 101, 102, 106


def sparql(query: str, path: Path) -> list[dict]:
    if not path.exists():
        _, body = http_get(f"{WIKIDATA}?format=json&query={urllib.parse.quote(query)}",
                           accept="application/sparql-results+json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        time.sleep(61)  # the public endpoint allows about one query a minute at the moment
    return json.loads(path.read_text(encoding="utf-8"))["results"]["bindings"]


def ship_capacity(ships: list[str]) -> tuple[dict[str, float], dict]:
    """Passenger capacity (Wikidata P1083) by normalised ship name.

    First every ship with an IMO number and a capacity; then, for names still missing, items whose
    English label is the ship's name. A name shared by several ships (Aurora, Britannia, ...) takes
    the largest: the ships calling at Southampton now are the big modern ones.
    """
    folder = CACHE / "wikidata"
    rows = sparql("""SELECT ?item ?label ?alt ?cap WHERE {
          ?item wdt:P458 ?imo; wdt:P1083 ?cap.
          ?item rdfs:label ?label. FILTER(lang(?label) = "en")
          OPTIONAL { ?item skos:altLabel ?alt. FILTER(lang(?alt) = "en") } }""",
                  folder / "ship_capacity.json")
    paths = [folder / "ship_capacity.json"]
    by_name: dict[str, dict[str, float]] = {}

    def add(rows: list[dict]) -> None:
        for b in rows:
            cap = float(b["cap"]["value"])
            if 100 <= cap <= 10000:
                for key in ("label", "alt"):
                    if key in b:
                        by_name.setdefault(norm(b[key]["value"]), {})[b["item"]["value"]] = cap

    add(rows)
    missing = sorted({s for s in ships if norm(s) not in by_name})
    if missing:
        key = "-".join(norm(s)[:6] for s in missing)[:120]
        labels = {v for s in missing for v in (s.title(), re.sub(r" Of The ", " of the ",
                                                                    s.title()))}
        values = " ".join(json.dumps(v) + "@en" for v in sorted(labels))
        path = folder / f"ship_capacity_by_label_{key}.json"
        add(sparql(f"""SELECT ?item ?label ?cap WHERE {{ VALUES ?label {{ {values} }}
              ?item rdfs:label ?label; wdt:P1083 ?cap. }}""", path))
        paths.append(path)
    caps = {n: max(v.values()) for n, v in by_name.items()}
    meta = {"source": "Wikidata P1083 (maximum capacity), CC0, query.wikidata.org",
            "retrieved": mtime_range(paths)[0]}
    return caps, meta


def norm(name: str) -> str:
    name = re.sub(r"^(MS|MV|M/S|SS|RMS)\s+", "", name.upper().strip())
    return re.sub(r"[^A-Z0-9]", "", name)


def load_calls() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Per-day turnaround passengers by dock group, and the per-call table behind them.

    Each day D uses the latest capture taken before D whose listing reaches D (the plan with the
    shortest lead). Days that no capture covers are unknown, not zero. Arriving passengers count
    on the arrival day, departing ones on the departure day; each is the ship's capacity.
    """
    captures = vts_captures()
    plans, paths = [], []
    for ts, original in captures:
        paths.append(vts_capture(ts, original))
        df = parse_vts(paths[-1])
        if df.empty:
            continue
        df["capture"] = datetime.strptime(ts[:8], "%Y%m%d").date()
        df["capture_ts"] = ts
        plans.append(df)
    plans = pd.concat(plans, ignore_index=True)
    reach = plans.groupby("capture")["arr"].max()
    log(f"  {len(reach)} VTS captures: " + ", ".join(
        f"{c:%d %b %Y} (to {r:%d %b %Y})" for c, r in reach.items()))

    caps, cap_meta = ship_capacity(list(plans["ship"].unique()))
    matched = {s: caps.get(norm(s)) for s in plans["ship"].unique()}
    known = [v for v in matched.values() if v]
    fallback = float(np.median(known)) if known else 3000.0

    days, calls = [], []
    for d in pd.date_range(START, END).date:
        cands = [c for c, r in reach.items() if c < d <= r]
        if not cands:
            continue
        c = max(cands)
        p = plans[(plans["capture"] == c) & ((plans["arr"] == d) | (plans["dep"] == d))]
        row = {"date": d, "capture": c, "lead_days": (d - c).days, "n_calls": len(p),
               "pax_east": 0.0, "pax_west": 0.0, "calls_east": 0, "calls_west": 0,
               "cap_imputed": 0}
        for r in p.itertuples():
            cap = matched.get(r.ship) or fallback
            share = 0.5 * ((r.arr == d) + (r.dep == d))  # disembark half, embark half
            g = berth_group(r.berth)
            for grp, w in ({g: 1.0} if g != "unknown" else {"east": 0.5, "west": 0.5}).items():
                row[f"pax_{grp}"] += w * share * cap
            if g != "unknown":
                row[f"calls_{g}"] += 1
            row["cap_imputed"] += int(matched.get(r.ship) is None)
            calls.append({"date": d, "ship": r.ship, "berth": r.berth, "group": g,
                          "capacity": cap, "cap_source": "wikidata" if matched.get(r.ship)
                          else "imputed median", "capture": r.capture_ts})
        days.append(row)
    days = pd.DataFrame(days)
    calls = pd.DataFrame(calls)
    RAW.mkdir(parents=True, exist_ok=True)
    calls.to_csv(RAW / "cruise_calls_history.csv", index=False)  # private: ABP content
    n_ships = len(matched)
    meta = {
        "source": "Southampton VTS cruise ship schedule (ABP), Internet Archive captures",
        "captures": [f"{c:%Y-%m-%d}" for c in reach.index],
        "days_known": int(len(days)),
        "days_in_period": int((END - START).days + 1),
        "calls": int(len(calls)),
        "ships": n_ships,
        "ships_with_capacity": int(sum(v is not None for v in matched.values())),
        "calls_capacity_imputed": int(days["cap_imputed"].sum()),
        "capacity_fallback": fallback,
        "capacity": cap_meta,
        "retrieved": " to ".join(dict.fromkeys(mtime_range(paths))),
        "terms": "ABP terms: personal reference, ABP acknowledged; raw data kept private",
    }
    return days, calls, meta


# --------------------------------------------------------------------------------------------
# Controls: bank holidays, school holidays, Southampton FC home matches
# --------------------------------------------------------------------------------------------


def bank_holidays() -> set[date]:
    path = CACHE / "bank_holidays.json"
    if not path.exists():
        _, body = http_get(BANK_HOLIDAYS, accept="application/json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    events = json.loads(path.read_text(encoding="utf-8"))["england-and-wales"]["events"]
    return {date.fromisoformat(e["date"]) for e in events}


def school_holiday(d: date) -> bool:
    terms = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in TERMS]
    if d < terms[0][0] or d > terms[-1][1]:
        raise ValueError(f"no term dates for {d}")
    return not any(a <= d <= b for a, b in terms)


def sfc_home_matches() -> tuple[dict[date, float], dict]:
    """Southampton FC home league matches: date -> kick-off hour (UK local)."""
    out: dict[date, float] = {}
    paths = []
    for season in ("2324", "2425", "2526"):
        for div in ("E0", "E1"):
            path = RAW / "football" / f"{season}_{div}.csv"
            if not path.exists():
                _, body = http_get(FOOTBALL.format(season=season, div=div))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                time.sleep(1)
            paths.append(path)
            df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace",
                             usecols=lambda c: c in ("Date", "Time", "HomeTeam"))
            for r in df[df["HomeTeam"] == "Southampton"].itertuples():
                d = datetime.strptime(r.Date, "%d/%m/%Y").date()
                hh, mm = (str(r.Time) if isinstance(r.Time, str) else "15:00").split(":")
                out[d] = int(hh) + int(mm) / 60
    meta = {"source": "football-data.co.uk results files (league matches only; cups missing)",
            "retrieved": mtime_range(paths)[0],
            "home_matches_in_period": sum(START <= d <= END for d in out)}
    return out, meta


# --------------------------------------------------------------------------------------------
# Target: uplift = count - median for the same weekday and time on non-cruise days
# --------------------------------------------------------------------------------------------


def build_table(obs: pd.DataFrame, days: pd.DataFrame, bank: set[date],
                football: dict[date, float]) -> tuple[pd.DataFrame, dict]:
    """One row per site, day and 15-minute bin, on valid sensor days with a known call list."""
    df = obs.merge(days, on="date")
    d = pd.to_datetime(df["date"])
    df["dow"] = d.dt.dayofweek
    df["bank_hol"] = df["date"].isin(bank).astype(int)
    df["day_type"] = np.where(df["bank_hol"] == 1, 6, df["dow"])  # bank holidays act as Sundays
    df["school_hol"] = df["date"].map(school_holiday).astype(int)
    df["month"] = d.dt.month
    ko = df["date"].map(football)
    df["sfc_home"] = ko.notna().astype(int)
    df["since_ko"] = (df["bin"] + 0.5) / 4 - ko  # hours since kick-off; NaN without a match
    df["pax_east_k"] = df["pax_east"] / 1000
    df["pax_west_k"] = df["pax_west"] / 1000
    df["pax_k"] = df["pax_east_k"] + df["pax_west_k"]
    df["cruise"] = (df["n_calls"] > 0).astype(int)

    # Medians come from non-cruise, non-bank-holiday days before the test period only, per sensor,
    # weekday and bin, smoothed over neighbouring bins (some weekdays have few non-cruise days).
    base = df[(df["date"] < TEST_START) & (df["cruise"] == 0) & (df["bank_hol"] == 0)]
    med = base.groupby(["site", "day_type", "bin"])["flow"].median()
    med = med.groupby(level=[0, 1], group_keys=False).apply(
        lambda s: s.rolling(3, center=True, min_periods=1).mean())
    df = df.join(med.rename("median"), on=["site", "day_type", "bin"])
    df["uplift"] = df["flow"] - df["median"]
    n_base = base.groupby(["site", "day_type"])["date"].nunique()
    meta = {"non_cruise_days_per_weekday": {
        f"{SITES[s].split('(')[1].split(',')[0]}": {
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][k]: int(v)
            for k, v in n_base[s].items()} for s in n_base.index.levels[0]}}
    return df.dropna(subset=["median"]).reset_index(drop=True), meta


def daily(df: pd.DataFrame, col: str) -> pd.Series:
    """Whole-day uplift per date: mean over the bins present, times 96 (valid days miss <= 6)."""
    return df.groupby("date")[col].mean() * BINS


# --------------------------------------------------------------------------------------------
# Models. Each returns, for the rows of a test frame, a point forecast of the 15-minute uplift
# and a predictive distribution (quantiles, or the point plus a sample of past residuals).
# --------------------------------------------------------------------------------------------

QS = np.array([0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95])
CRUISE = ["pax_east_k", "pax_west_k"]
CONTEXT = ["bin", "dow", "bank_hol", "school_hol", "month", "sfc_home", "since_ko"]


def gbm(quantile: float, features: list[str]):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
        min_samples_leaf=200, l2_regularization=1.0, random_state=26,
        categorical_features=[f == "dow" for f in features],
        monotonic_cst=[1 if f in CRUISE else 0 for f in features])


class GBMQuantile:
    """Gradient-boosted quantile regression of the 15-minute uplift (one model per quantile).

    Passenger features are constrained to raise the uplift, never lower it.
    """

    def __init__(self, features: list[str], qs: np.ndarray | list[float] = QS):
        self.features, self.qs = features, np.asarray(qs)

    def fit(self, train: pd.DataFrame) -> GBMQuantile:
        x, y = train[self.features], train["uplift"]
        self.models = [gbm(q, self.features).fit(x, y) for q in self.qs]
        return self

    def quantiles(self, df: pd.DataFrame) -> np.ndarray:
        q = np.column_stack([m.predict(df[self.features]) for m in self.models])
        return np.sort(q, axis=1)  # repair any quantile crossing

    def point(self, df: pd.DataFrame) -> np.ndarray:
        return self.models[int(np.flatnonzero(self.qs == 0.5)[0])].predict(df[self.features])


class PaxOnly:
    """Linear model per 15-minute bin on the day's total turnaround passengers."""

    def fit(self, train: pd.DataFrame) -> PaxOnly:
        self.coef = {}
        for b, g in train.groupby("bin"):
            x = np.column_stack([np.ones(len(g)), g["pax_k"]])
            self.coef[b] = np.linalg.lstsq(x, g["uplift"].to_numpy(), rcond=None)[0]
        return self

    def point(self, df: pd.DataFrame) -> np.ndarray:
        c = np.array([self.coef[b] for b in df["bin"]])
        return c[:, 0] + c[:, 1] * df["pax_k"].to_numpy()


class NoCruise:
    """No cruise effect: the non-cruise median, so zero uplift."""

    def fit(self, train: pd.DataFrame) -> NoCruise:
        return self

    def point(self, df: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(df))


def comparable_day(day: dict, history: pd.DataFrame) -> date | None:
    """Latest earlier day of the same weekday type with the same calls per dock group, else the
    same number of calls, else within one call, else any (the brief's baseline)."""
    h = history[(history["date"] < day["date"]) & (history["day_type"] == day["day_type"])]
    for rule in (
        (h["calls_east"] == day["calls_east"]) & (h["calls_west"] == day["calls_west"]),
        h["n_calls"] == day["n_calls"],
        (h["n_calls"] - day["n_calls"]).abs() <= 1,
        h["n_calls"] >= 0,
    ):
        if rule.any():
            return h.loc[rule, "date"].max()
    return None


class LastComparable:
    """Copy the 15-minute uplift profile of the last comparable cruise day observed before."""

    def fit(self, table: pd.DataFrame) -> LastComparable:
        # The baseline may look at any day observed before the forecast day, test days included.
        self.days = table.groupby("date").first().reset_index()
        self.profile = table.set_index(["date", "bin"])["uplift"]
        return self

    def point(self, df: pd.DataFrame) -> np.ndarray:
        out = np.full(len(df), np.nan)
        for d, idx in df.groupby("date").indices.items():
            row = self.days[self.days["date"] == d].iloc[0].to_dict()
            ref = comparable_day(row, self.days)
            if ref is not None:
                prof = self.profile.loc[ref]
                out[idx] = prof.reindex(df["bin"].iloc[idx]).fillna(0.0).to_numpy()
        return out


# --------------------------------------------------------------------------------------------
# Backtest: rolling origin, refit at the start of each test month on earlier days only
# --------------------------------------------------------------------------------------------

T15 = 50.0  # "busy interval": uplift above 50 vehicles in 15 minutes (~90th pct, training cruise)
TDAY = 2000.0  # "big cruise day": uplift above 2,000 vehicles in the day (~10% of daily flow)
MODELS = {
    "model": "Learned model (gradient-boosted quantiles)",
    "last_comparable": "Last comparable cruise day",
    "pax_only": "Passenger count only (linear)",
    "no_cruise": "No cruise effect",
    "ablation": "Same model without cruise inputs",
}
FOLDS = 4


def oof_points(make, train: pd.DataFrame) -> np.ndarray:
    """Out-of-fold point forecasts for the training rows, in contiguous blocks of days."""
    out = np.empty(len(train))
    for block in np.array_split(np.sort(train["date"].unique()), FOLDS):
        mask = train["date"].isin(block).to_numpy()
        out[mask] = make().fit(train[~mask]).point(train[mask])
    return out


def residuals(train: pd.DataFrame, point: np.ndarray) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Past errors of a forecaster: 15-minute ones by hour of day, and whole-day ones."""
    ok = ~np.isnan(point)
    t = train[ok].assign(p=point[ok])
    r = (t["uplift"] - t["p"]).to_numpy()
    hour = t["bin"].to_numpy() // 4
    by_hour = {h: np.sort(r[hour == h]) for h in range(24)}
    r_day = np.sort((daily(t, "uplift") - daily(t, "p")).to_numpy())
    return by_hour, r_day


def exceed(sorted_res: np.ndarray, gap: np.ndarray) -> np.ndarray:
    """P(point + residual > threshold) for each gap = threshold - point."""
    return 1 - np.searchsorted(sorted_res, gap, side="right") / len(sorted_res)


def forecast(name: str, train: pd.DataFrame, test: pd.DataFrame,
             table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """15-minute and daily forecasts (point, 80% band, P(above threshold)) for one model."""
    q = None
    if name in ("model", "ablation"):
        feats = CONTEXT + CRUISE if name == "model" else CONTEXT
        m = GBMQuantile(feats).fit(train)
        point, q = m.point(test), m.quantiles(test)
        _, r_day = residuals(train, oof_points(lambda: GBMQuantile(feats, [0.5]), train))
    elif name == "pax_only":
        point = PaxOnly().fit(train).point(test)
        by_hour, r_day = residuals(train, oof_points(PaxOnly, train))
    elif name == "no_cruise":
        point = NoCruise().point(test)
        by_hour, r_day = residuals(train, NoCruise().point(train))
    else:
        lc = LastComparable().fit(table)
        point = np.nan_to_num(lc.point(test))  # no earlier comparable day: no uplift
        by_hour, r_day = residuals(train, lc.point(train))
    rows = test[["date", "bin", "uplift", "cruise", "day_type"]].assign(point=point)
    if q is not None:
        rows["lo"], rows["hi"] = q[:, 1], q[:, 5]
        rows["p_exceed"] = [1 - np.interp(T15, qi, QS, left=0.025, right=0.975) for qi in q]
    else:
        hour = rows["bin"].to_numpy() // 4
        lo, hi, pe = (np.empty(len(rows)) for _ in range(3))
        for h in range(24):
            k = hour == h
            r = by_hour[h]
            lo[k], hi[k] = point[k] + np.quantile(r, 0.1), point[k] + np.quantile(r, 0.9)
            pe[k] = exceed(r, T15 - point[k])
        rows["lo"], rows["hi"], rows["p_exceed"] = lo, hi, pe
    g = rows.groupby("date")
    days = pd.DataFrame({"uplift": daily(rows, "uplift"), "point": daily(rows, "point"),
                         "cruise": g["cruise"].first(), "day_type": g["day_type"].first()})
    days["lo"] = days["point"] + np.quantile(r_day, 0.1)
    days["hi"] = days["point"] + np.quantile(r_day, 0.9)
    days["p_exceed"] = exceed(r_day, TDAY - days["point"].to_numpy())
    return rows.assign(model=name), days.reset_index().assign(model=name)


def backtest(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    test_days = sorted(d for d in table["date"].unique() if d >= TEST_START)
    origins = sorted({date(d.year, d.month, 1) for d in test_days})
    rows, days, splits = [], [], []
    for i, origin in enumerate(origins):
        nxt = origins[i + 1] if i + 1 < len(origins) else END + timedelta(days=1)
        train = table[table["date"] < origin]
        test = table[(table["date"] >= origin) & (table["date"] < nxt)]
        splits.append({"origin": origin.isoformat(), "train_days": int(train["date"].nunique()),
                       "test_days": int(test["date"].nunique())})
        log(f"  origin {origin}: train {splits[-1]['train_days']} days, "
            f"test {splits[-1]['test_days']} days")
        for name in MODELS:
            r, d = forecast(name, train, test, table)
            rows.append(r)
            days.append(d)
    return pd.concat(rows, ignore_index=True), pd.concat(days, ignore_index=True), splits


def scores(f: pd.DataFrame, threshold: float) -> dict:
    hit = (f["uplift"] > threshold).astype(float)
    inside = (f["uplift"] >= f["lo"]) & (f["uplift"] <= f["hi"])
    return {
        "mae": round(float((f["uplift"] - f["point"]).abs().mean()), 1),
        "brier": round(float(((f["p_exceed"] - hit) ** 2).mean()), 4),
        "coverage80": round(float(inside.mean()), 3),
        "band_width": round(float((f["hi"] - f["lo"]).mean()), 1),
        "base_rate": round(float(hit.mean()), 3),
    }


SUBSETS = {
    "all": lambda f: f,
    "cruise_days": lambda f: f[f["cruise"] == 1],
    "non_cruise_days": lambda f: f[f["cruise"] == 0],
    "weekends_and_bank_holidays": lambda f: f[f["day_type"] >= 5],
}


def summarise(rows: pd.DataFrame, days: pd.DataFrame) -> dict:
    out = {}
    for level, frame, thr in (("per_15min", rows, T15), ("per_day", days, TDAY)):
        out[level] = {}
        for sub, pick in SUBSETS.items():
            f = pick(frame)
            out[level][sub] = {"days": int(f["date"].nunique()),
                               **{m: scores(f[f["model"] == m], thr) for m in MODELS}}
    return out


def bootstrap(rows: pd.DataFrame, days: pd.DataFrame, n: int = 2000) -> dict:
    """90% interval of the MAE difference (model minus each other), resampling test days."""
    rng = np.random.default_rng(26)
    err15 = rows.assign(e=(rows["uplift"] - rows["point"]).abs()).pivot_table(
        index="date", columns="model", values="e", aggfunc="mean")
    errd = days.assign(e=(days["uplift"] - days["point"]).abs()).pivot(
        index="date", columns="model", values="e")
    out = {}
    for level, err in (("per_15min", err15), ("per_day", errd)):
        idx = rng.integers(0, len(err), size=(n, len(err)))
        out[level] = {}
        for b in MODELS:
            if b == "model":
                continue
            diff = (err["model"] - err[b]).to_numpy()
            lo, hi = np.quantile(diff[idx].mean(axis=1), [0.05, 0.95])
            out[level][b] = {"mae_diff": round(float(diff.mean()), 1),
                             "ci90": [round(float(lo), 1), round(float(hi), 1)],
                             "model_better": bool(hi < 0), "model_worse": bool(lo > 0)}
    return out


def effect_grid(table: pd.DataFrame) -> dict:
    """What the model, refit on every day, says turnarounds add on an October term-time weekend:
    daily uplift by passengers (split evenly between the docks) and a 15-minute profile."""
    feats = CONTEXT + CRUISE
    model = GBMQuantile(feats).fit(table)
    _, r_day = residuals(table, oof_points(lambda: GBMQuantile(feats, [0.5]), table))

    def day(dow: int, east: float, west: float) -> pd.DataFrame:
        return pd.DataFrame({"bin": np.arange(BINS), "dow": dow, "bank_hol": 0, "school_hol": 0,
                             "month": 10, "sfc_home": 0, "since_ko": np.nan,
                             "pax_east_k": east, "pax_west_k": west})

    grid = {}
    for dow, label in ((5, "saturday"), (6, "sunday")):
        base = model.point(day(dow, 0, 0)).sum()
        grid[label] = []
        for pax in (0, 2.5, 5, 7.5, 10, 12.5, 15):
            p = model.point(day(dow, pax / 2, pax / 2)).sum()
            grid[label].append({"passengers": int(pax * 1000), "uplift_day": round(float(p)),
                                "cruise_part": round(float(p - base)),
                                "band80": [round(float(p + np.quantile(r_day, 0.1))),
                                           round(float(p + np.quantile(r_day, 0.9)))]})
    q = model.quantiles(day(5, 5, 5))
    profile = [{"hour": h, "q10": round(float(q[4 * h:4 * h + 4, 1].mean()), 1),
                "q50": round(float(q[4 * h:4 * h + 4, 3].mean()), 1),
                "q90": round(float(q[4 * h:4 * h + 4, 5].mean()), 1)} for h in range(24)]
    profiles = {}
    for dow, label in ((5, "saturday"), (6, "sunday"), (2, "wednesday")):
        base_q = model.point(day(dow, 0, 0))
        profiles[label] = {key: [round(float(v), 1) for v in model.point(day(dow, e, w)) - base_q]
                           for key, e, w in (("east_5k", 5, 0), ("west_5k", 0, 5),
                                             ("both_10k", 5, 5))}
    return {"fitted_on_days": int(table["date"].nunique()),
            "cruise_profiles": {
                "unit": "extra vehicles per 15 minutes from the ships (median model, with ships "
                        "minus without), M271 northbound, from 00:00",
                "context": "October, school term, no bank holiday or home match",
                "profiles": profiles},
            "context": "an October Saturday or Sunday in school term, with no bank holiday or "
                       "home match",
            "daily": grid,
            "profile_saturday_10k_passengers": {
                "unit": "vehicles per 15 minutes, hourly mean of the 15-minute quantiles",
                "rows": profile}}


# --------------------------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------------------------

BASELINES = ("last_comparable", "pax_only", "no_cruise")


def verdict(results: dict, boot: dict) -> list[str]:
    """Plain sentences on whether the learned model beats each baseline, from the numbers."""
    out = []
    for level, unit in (("per_day", "whole-day uplift"), ("per_15min", "15-minute uplift")):
        r, b = results[level]["all"], boot[level]
        m = r["model"]["mae"]
        for name in (*BASELINES, "ablation"):
            o = r[name]["mae"]
            pct = 100 * (o - m) / o
            ci = b[name]["ci90"]
            if b[name]["model_better"]:
                how = f"beats {MODELS[name].lower()} by {pct:.0f}% (90% interval of the gap " \
                      f"{ci[0]:+.0f} to {ci[1]:+.0f}, excludes zero)"
            elif b[name]["model_worse"]:
                how = f"is worse than {MODELS[name].lower()} by {-pct:.0f}% (90% interval " \
                      f"{ci[0]:+.0f} to {ci[1]:+.0f})"
            else:
                how = f"is not clearly different from {MODELS[name].lower()} ({pct:+.0f}%, 90% " \
                      f"interval of the gap {ci[0]:+.0f} to {ci[1]:+.0f} includes zero)"
            out.append(f"{unit.capitalize()}, MAE {m:,.0f} vs {o:,.0f}: the model {how}.")
    return out


def card(results: dict, boot: dict, table: pd.DataFrame) -> dict:
    """The few sentences the page's Backtest card shows."""
    r, rq = results["per_day"]["all"], results["per_15min"]["all"]
    n = r["days"]
    m, ab = r["model"]["mae"], r["ablation"]["mae"]
    sig_d, sig_q = boot["per_day"]["ablation"]["model_better"], boot["per_15min"]["ablation"][
        "model_better"]
    gain_d = 100 * (ab - m) / ab
    gain_q = 100 * (rq["ablation"]["mae"] - rq["model"]["mae"]) / rq["ablation"]["mae"]
    gain_b = 100 * (r["ablation"]["brier"] - r["model"]["brier"]) / r["ablation"]["brier"]
    beats = all(boot["per_day"][b]["model_better"] for b in BASELINES)
    last = max(table["date"])
    return {
        "status": "run",
        "eyebrow": f"Backtest: {n} held-out days, {TEST_START:%b %Y} to {last:%b %Y}",
        "headline": (
            f"{'Beats' if beats else 'Does not beat'} all three baselines on whole-day uplift: "
            f"error {m:,.0f} vehicles a day, against {r['last_comparable']['mae']:,.0f} for the "
            f"last comparable cruise day, {r['pax_only']['mae']:,.0f} for passengers only and "
            f"{r['no_cruise']['mae']:,.0f} for no cruise effect."),
        "caveat": (
            f"Most of that gain is the calendar (weekday, month, holidays): without ship "
            f"passengers the same model scores {ab:,.0f}. The ship schedule cuts the error by a "
            f"further {gain_d:.0f}% a day ({'significant' if sig_d else 'not significant'}) and "
            f"{gain_q:.0f}% per 15 minutes ({'significant' if sig_q else 'not significant'}), "
            f"and the Brier score for a day above {TDAY:,.0f} vehicles by {gain_b:.0f}%."),
        "where": (
            "Observed on the M271 northbound (National Highways WebTRIS 19974), 4 to 7 km from "
            f"the terminals; counts end {last:%d %b %Y}. Past calls from archived ABP schedules."),
        "coverage80": f"{100 * r['model']['coverage80']:.0f}% of held-out days fell inside "
                      f"the 80% band ({100 * rq['model']['coverage80']:.0f}% of 15-minute "
                      "intervals).",
    }


def split_meta(table: pd.DataFrame, splits: list[dict]) -> dict:
    def describe(f: pd.DataFrame) -> dict:
        d = f.groupby("date").first()
        return {"from": str(min(d.index)), "to": str(max(d.index)), "days": int(len(d)),
                "cruise_days": int(d["cruise"].sum()),
                "weekend_or_bank_holiday_days": int((d["day_type"] >= 5).sum()),
                "calls": int(d["n_calls"].sum()),
                "sites": sorted(int(s) for s in d["site"].unique())}

    return {"train_first_origin": describe(table[table["date"] < TEST_START]),
            "test": describe(table[table["date"] >= TEST_START]),
            "refits": splits,
            "rule": "rolling origin: at the start of each test month the models are refit on every "
                    "day before it; the last-comparable-day baseline may use any day observed "
                    "before the forecast day"}


LIMITS = [
    "The M271 sensors are 4 to 7 km from the terminals and northbound only (traffic leaving the "
    "docks). No public count exists at the dock gates, Platform Road or West Quay Road.",
    "WebTRIS currently stops at 29 Jun 2026, so nothing after that date can be checked.",
    "Past calls come from archived provisional plans (ABP), not actual berthings. 2026 calls are "
    "from the 8 Dec 2025 plan. Days no archived plan covers (Jul 2024, Jan to Aug 2025) are left "
    "out, not treated as zero. CruiseMapper, which could fill some gaps, forbids automated "
    "collection and is not used.",
    "Every call is treated as a full turnaround at the ship's maximum capacity (Wikidata P1083; "
    "definitions vary between lower berths and maximum). Transit calls, real load factors and "
    "the share of passengers who drive are unknown. Ships without a Wikidata capacity "
    "(Arvia, Disney Fantasy and a few small ships) get the median.",
    "Few non-cruise Fridays and Saturdays exist in the training period (1 to 5 per sensor), so "
    "the non-cruise median for those days is noisy. All models share this target.",
    "Not controlled: weather, incidents and closures, roadworks, port freight (container and car "
    "lorries use the M271), cup matches and other events. Season enters only through the month.",
    "The test period is six months of one sensor (19974) in one year; the cruise season in it is "
    "April to June only.",
]


def write_doc(r: dict) -> None:
    res, sp = r["results"], r["split"]

    def table(level: str, sub: str) -> list[str]:
        unit = "vehicles per 15 minutes" if level == "per_15min" else "vehicles per day"
        thr = r["thresholds"][level]
        rows = [f"| Forecaster | MAE ({unit}) | Brier, uplift > {thr:,.0f} | "
                f"80% band coverage | Band width |", "|---|---|---|---|---|"]
        for m in MODELS:
            s = res[level][sub][m]
            rows.append(f"| {MODELS[m]} | {s['mae']:,.1f} | {s['brier']:.3f} | "
                        f"{100 * s['coverage80']:.0f}% | {s['band_width']:,.0f} |")
        return rows

    eff = r["effect"]
    sat = {e["passengers"]: e for e in eff["daily"]["saturday"]}
    sun = {e["passengers"]: e for e in eff["daily"]["sunday"]}
    tr, te = sp["train_first_origin"], sp["test"]
    src = r["sources"]
    lines = [
        "# Backtest: learned cruise uplift on the M271",
        "",
        f"Generated {r['generated']} by `demo/webtris_backtest.py` (written with Claude Code; "
        "see the README provenance section). Summary numbers for the page are in "
        "`demo/out/backtest.json`.",
        "",
        "## Summary",
        "",
        f"- {r['card']['eyebrow']}. {r['card']['headline']}",
        f"- {r['card']['caveat']}",
        f"- {r['card']['coverage80']}",
        f"- {r['card']['where']} Dock-gate traffic itself is not observable from any public "
        "source, so this is a test on a proxy.",
        "",
        "## What was tested",
        "",
        "**Observable.** Vehicles per 15 minutes on the M271 northbound, National Highways "
        "WebTRIS sites 7588 (Jan to Aug 2024) and 19974 (from Oct 2024). Northbound is traffic "
        "leaving towards the M27; the sensors are 4 to 7 km from the terminals.",
        "",
        "**Target.** Cruise uplift: the count minus the median for the same weekday and 15 "
        "minutes on non-cruise days (bank holidays use the Sunday median). Medians come only "
        f"from days before {TEST_START:%d %b %Y}, per sensor.",
        "",
        "**Learned model.** Gradient-boosted quantile regression (scikit-learn "
        "HistGradientBoosting, quantiles 5% to 95%) of the 15-minute uplift on: turnaround "
        "passengers at the Eastern Docks (berths 38/39, 46) and Western Docks (101, 102, 106), "
        "time of day, weekday, bank holiday, school holiday, month, and Southampton FC home "
        "league matches (with hours since kick-off). The uplift may only rise with passengers.",
        "",
        "**Baselines.** (1) Last comparable cruise day: the 15-minute uplift of the latest "
        "earlier day of the same weekday with the same calls per dock group (else same number of "
        "calls, else within one); it may use any day already observed, including earlier test "
        "days. (2) Passenger count only: a straight line per 15-minute slot on the day's total "
        "turnaround passengers. (3) No cruise effect: zero uplift. An extra row, the same "
        "learned model without the passenger inputs, shows how much of the gain is the cruise "
        "information rather than the calendar.",
        "",
        "**Uncertainty.** The learned model's 15-minute bands are its own 10% and 90% quantiles. "
        "Baselines, and every whole-day band, use each forecaster's own past errors on training "
        "days (out-of-fold for fitted models). Brier scores use the same distributions.",
        "",
        f"**Split.** Training before {TEST_START:%d %b %Y}: {tr['days']} days ({tr['from']} to "
        f"{tr['to']}), {tr['cruise_days']} with calls, {tr['calls']} calls. Held out: "
        f"{te['days']} days ({te['from']} to {te['to']}), {te['cruise_days']} with calls, "
        f"{te['weekend_or_bank_holiday_days']} weekend or bank-holiday days, {te['calls']} "
        "calls. Rolling origin: every model is refit on all earlier days at the start of each "
        "test month ("
        + ", ".join(f"{s['origin'][:7]}: {s['train_days']} train / {s['test_days']} test days"
                    for s in sp["refits"]) + "). Thresholds (50 vehicles per 15 minutes, 2,000 "
        "per day) and model settings were fixed from training data before the test run.",
        "",
        "## Results on held-out days",
        "",
        f"### Whole-day uplift, all {res['per_day']['all']['days']} test days",
        "",
        *table("per_day", "all"),
        "",
        f"### Whole-day uplift, {res['per_day']['cruise_days']['days']} test days with calls",
        "",
        *table("per_day", "cruise_days"),
        "",
        f"### 15-minute uplift, all {res['per_15min']['all']['days']} test days",
        "",
        *table("per_15min", "all"),
        "",
        f"### 15-minute uplift, {res['per_15min']['weekends_and_bank_holidays']['days']} weekend "
        "and bank-holiday test days",
        "",
        *table("per_15min", "weekends_and_bank_holidays"),
        "",
        "MAE: mean absolute error. Brier: mean squared error of the forecast probability that the "
        "uplift is above the threshold (lower is better; base rates "
        f"{100 * res['per_day']['all']['model']['base_rate']:.0f}% of days and "
        f"{100 * res['per_15min']['all']['model']['base_rate']:.0f}% of 15-minute intervals). "
        "Coverage: share of observations inside the 80% band (should be near 80%).",
        "",
        "## Verdict",
        "",
        *[f"- {v}" for v in r["verdict"]],
        "",
        "Intervals are from 2,000 bootstrap resamples of test days (paired, so both forecasters "
        "are scored on the same days).",
        "",
        "## What the model learned",
        "",
        f"Refit on all {eff['fitted_on_days']} days, for {eff['context']}; passengers are split "
        "evenly between the docks. The steps are those of a tree model: it is flat where the "
        "training data had few days.",
        "",
        "| Turnaround passengers | Saturday uplift (80% band) | of which cruise | "
        "Sunday uplift (80% band) | of which cruise |",
        "|---|---|---|---|---|",
        *[f"| {p:,} | {sat[p]['uplift_day']:,} ({sat[p]['band80'][0]:,} to "
          f"{sat[p]['band80'][1]:,}) | {sat[p]['cruise_part']:+,} | {sun[p]['uplift_day']:,} "
          f"({sun[p]['band80'][0]:,} to {sun[p]['band80'][1]:,}) | {sun[p]['cruise_part']:+,} |"
          for p in sat],
        "",
        "\"Of which cruise\" is the model's forecast minus its forecast for the same day with no "
        "ships. It is a forecast for October 2026, which cannot be checked against counts until "
        "WebTRIS publishes data after 29 Jun 2026.",
        "",
        "## Data, with collection dates",
        "",
        *[f"- **{s['name']}**: {s['detail']} Retrieved {s['retrieved']}. {s['licence']}"
          for s in src],
        "",
        f"Non-cruise days behind the medians (before {TEST_START:%d %b %Y}): "
        + "; ".join(f"{site}: " + ", ".join(f"{k} {v}" for k, v in d.items())
                    for site, d in r["target"]["non_cruise_days_per_weekday"].items()) + ".",
        "",
        "## Limits",
        "",
        *[f"- {x}" for x in LIMITS],
        "",
        "## Reproduce",
        "",
        "```bash",
        "uv run --no-project --python 3.12 --with numpy --with pandas --with scikit-learn "
        "python demo/webtris_backtest.py",
        "```",
        "",
        "Downloads are cached under `data/cache/` and `data/raw/` (gitignored); a second run "
        "makes no requests. Raw VTS captures and the rebuilt call list stay private (ABP terms).",
        "",
    ]
    OUT_DOC.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args()
    started = time.time()
    log("WebTRIS counts")
    obs, web = load_webtris()
    log("Past cruise calls")
    days, _, calls = load_calls()
    log("Controls")
    bank = bank_holidays()
    football, fb = sfc_home_matches()
    table, target = build_table(obs, days, bank, football)
    log(f"Backtest on {table['date'].nunique()} days")
    rows, day_rows, splits = backtest(table)
    results = summarise(rows, day_rows)
    boot = bootstrap(rows, day_rows)
    log("Learned effect")
    effect = effect_grid(table)
    report = {
        "title": "Backtest: learned cruise uplift on the M271 northbound",
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "script": "demo/webtris_backtest.py",
        "observable": "Vehicles per 15 minutes, M271 northbound (WebTRIS 7588 then 19974)",
        "target": {"definition": "count minus the median for the same weekday and 15 minutes on "
                                 "non-cruise days before the test period, per sensor",
                   **target},
        "models": MODELS,
        "thresholds": {"per_15min": T15, "per_day": TDAY},
        "split": split_meta(table, splits),
        "results": results,
        "bootstrap": boot,
        "verdict": verdict(results, boot),
        "card": card(results, boot, table),
        "effect": effect,
        "sources": [
            {"name": "National Highways WebTRIS",
             "detail": f"15-minute counts {START} to {END}; valid days: "
                       + ", ".join(f"site {k} {v}" for k, v in web["valid_days"].items())
                       + f" (valid = {web['valid_rule']}).",
             "retrieved": web["retrieved"],
             "licence": "Listed by DfT as free and open; Open Government Licence assumed, not "
                        "confirmed on the WebTRIS site."},
            {"name": "Southampton VTS cruise ship schedule (ABP), Internet Archive captures",
             "detail": f"{calls['calls']} calls on {calls['days_known']} of "
                       f"{calls['days_in_period']} days from captures dated "
                       f"{', '.join(calls['captures'][-4:])}.",
             "retrieved": calls["retrieved"],
             "licence": "ABP terms: personal reference, ABP acknowledged. Raw pages and the "
                        "call list stay private; only aggregates are published."},
            {"name": "Wikidata ship capacity (P1083)",
             "detail": f"{calls['ships_with_capacity']} of {calls['ships']} ships matched by "
                       f"name; {calls['calls_capacity_imputed']} of {calls['calls']} calls use "
                       f"the median ({calls['capacity_fallback']:,.0f}).",
             "retrieved": calls["capacity"]["retrieved"], "licence": "CC0."},
            {"name": "Bank holidays, gov.uk", "detail": "England and Wales.",
             "retrieved": mtime_range([CACHE / "bank_holidays.json"])[0],
             "licence": "Open Government Licence v3.0."},
            {"name": "School holidays, Southampton City Council",
             "detail": f"Term dates 2023-24 to 2025-26 typed in from {TERM_SOURCE}.",
             "retrieved": "2026-10-16", "licence": "Council web pages."},
            {"name": "Southampton FC home league matches, football-data.co.uk",
             "detail": f"{fb['home_matches_in_period']} home league matches in the period; cup "
                       "matches are missing.",
             "retrieved": fb["retrieved"], "licence": "Free download; source credited."},
        ],
        "limits": LIMITS,
        "runtime_s": round(time.time() - started),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    write_doc(report)
    log(f"Wrote {OUT_JSON.relative_to(ROOT)} and {OUT_DOC.relative_to(ROOT)} "
        f"in {report['runtime_s']} s")
    for v in report["verdict"]:
        log(f"  {v}")


if __name__ == "__main__":
    sys.exit(main())
