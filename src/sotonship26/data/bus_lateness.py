"""Observed bus lateness around Southampton from bustimes.org's live vehicle positions.

bustimes.org republishes the Bus Open Data Service (BODS) live vehicle feed. Its public
``/vehicles.json?xmin=&ymin=&xmax=&ymax=`` endpoint lists the buses inside a box right now, each
with its position, line, journey and a ``delay`` in seconds against the timetable (positive =
late), which bustimes.org works out from the bus's progress between stops. We use that endpoint
only: bustimes.org's robots.txt disallows ``/api/`` and ``/trips/``, so we do not fetch timetables
from it (demo/buses.py takes them from BODS directly).

This complements demo/buses.py, which simulates buses on the model's roads: here the lateness is
observed, so it can check the model on the day. Raw sightings stay in data/raw/buses (gitignored);
only aggregates go further. Source data: BODS, Open Government Licence v3.0, via bustimes.org.
Requests are spaced at least ``min_interval_s`` apart: the site is run by one person.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

API_ROOT = "https://bustimes.org"
LONDON = ZoneInfo("Europe/London")
# lon/lat box: the city centre, the docks and the main corridors into town (Portswood included)
SOUTHAMPTON_BBOX = (-1.445, 50.885, -1.365, 50.935)
USER_AGENT = "sotonship26/0.1 (SotonShip 2026 hackathon; cruise-day traffic research)"
# Named areas for the page (lon_min, lat_min, lon_max, lat_max), drawn by hand round each place,
# so approximate. A sighting outside all of them counts only in the per-line figures.
AREAS = {
    "docks": (-1.418, 50.892, -1.392, 50.904),  # Town Quay, Platform Rd, Dock Gate 4, West Quay Rd
    "city_centre": (-1.412, 50.904, -1.394, 50.914),
    "portswood": (-1.402, 50.918, -1.385, 50.932),  # Portswood Rd, the council's bus check
}


@dataclass(frozen=True)
class Sighting:
    observed_at: datetime  # when the bus reported its position
    collected_at: datetime  # when we fetched it
    vehicle: str
    line: str
    journey: str
    destination: str
    lat: float
    lon: float
    delay_s: float | None  # bustimes.org's delay against the timetable; positive = late
    next_stop: str


class BustimesClient:
    def __init__(self, root: str = API_ROOT, min_interval_s: float = 30.0, timeout_s: float = 30.0):
        self.root = root.rstrip("/")
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self._last = 0.0

    def get_json(self, path: str, params: Mapping[str, object] | None = None):
        if path.startswith(("/api/", "/trips/")):
            raise ValueError(f"{path} is disallowed by bustimes.org's robots.txt")
        wait = self.min_interval_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = f"{self.root}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                return json.load(response)
        finally:
            self._last = time.monotonic()

    def vehicles(self, bbox: Sequence[float] = SOUTHAMPTON_BBOX) -> list[Sighting]:
        xmin, ymin, xmax, ymax = bbox
        payload = self.get_json("/vehicles.json",
                                {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})
        return parse_vehicles(payload, collected_at=datetime.now(LONDON))


def _float(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def parse_vehicles(payload, collected_at: datetime) -> list[Sighting]:
    """Sightings from a /vehicles.json response; records that can't be read are skipped."""
    items = payload.get("results", payload) if isinstance(payload, dict) else payload
    out = []
    for v in items or []:
        try:
            lon, lat = (float(c) for c in v["coordinates"][:2])
            when = datetime.fromisoformat(str(v["datetime"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        service, vehicle, progress = (v.get(k) or {} for k in ("service", "vehicle", "progress"))
        out.append(Sighting(
            observed_at=when if when.tzinfo else when.replace(tzinfo=LONDON),
            collected_at=collected_at,
            vehicle=str(vehicle.get("name") or vehicle.get("url") or v.get("id")),
            line=str(service.get("line_name") or v.get("line_name") or "?"),
            journey=str(v.get("journey_id") or v.get("trip_id") or ""),
            destination=str(v.get("destination") or ""),
            lat=lat, lon=lon, delay_s=_float(v.get("delay")),
            next_stop=str(progress.get("next_stop") or ""),
        ))
    return out


def area_of(s: Sighting) -> str | None:
    for name, (x0, y0, x1, y1) in AREAS.items():
        if x0 <= s.lon <= x1 and y0 <= s.lat <= y1:
            return name
    return None


# ---- aggregation -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Profile:
    key: str  # a line name, an area name, or "all"
    hour: int  # local hour of day, or -1 for the whole collection window
    n: int  # bus journeys seen (each journey counts once per key and hour)
    mean_min: float
    p50_min: float
    p90_min: float
    share_over_5_min: float


def _pct(xs: list[float], q: float) -> float:
    return xs[min(len(xs) - 1, int(q * len(xs)))]


# bustimes.org's delay is only as good as its match between a bus and a timetabled trip. These
# readings are not lateness and are left out before anything is summarised (``clean``):
MAX_ABS_DELAY_S = 3600.0  # over an hour late or early: matched to the wrong trip or day
MAX_STALE_S = 600.0  # position over 10 minutes old when fetched: the bus stopped reporting
STILL_M, STILL_S = 40.0, 600.0  # within 40 m for 10 minutes: laid over at a stand or parked
JUMP_SLACK_S = 120.0  # the delay moves in steps at stops; allow two minutes of slack


def _metres(a: Sighting, b: Sighting) -> float:
    dy = (a.lat - b.lat) * 111_320.0
    dx = (a.lon - b.lon) * 111_320.0 * 0.63  # cos(50.9 deg)
    return (dx * dx + dy * dy) ** 0.5


def clean(rows: Iterable[Sighting]) -> tuple[list[Sighting], dict[str, int]]:
    """The readings that measure lateness, and how many were left out for each reason.

    * ``repeat``: the same report fetched again (the bus hadn't reported between polls).
    * ``no_delay``: bustimes.org gave no delay.
    * ``over_an_hour``: more than an hour late or early.
    * ``stale``: the position was over 10 minutes old when fetched.
    * ``laid_over``: the bus had stood within 40 m for 10 minutes or more, so it was at a stand
      or parked and its delay against the last trip keeps growing without meaning anything.
    * ``rematched``: the delay of one journey moved more than the bus could: up by more than the
      time that passed (a bus can't fall behind faster than standing still), or down by more than
      twice the time that passed plus five minutes. bustimes.org then switched the bus to another
      trip, so none of that journey's readings can be trusted.
    """
    dropped: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, datetime]] = set()
    journeys: dict[tuple[str, str], list[Sighting]] = defaultdict(list)
    for r in rows:
        if (r.vehicle, r.observed_at) in seen:
            dropped["repeat"] += 1
            continue
        seen.add((r.vehicle, r.observed_at))
        if r.delay_s is None:
            dropped["no_delay"] += 1
        elif abs(r.delay_s) > MAX_ABS_DELAY_S:
            dropped["over_an_hour"] += 1
        elif (r.collected_at - r.observed_at).total_seconds() > MAX_STALE_S:
            dropped["stale"] += 1
        else:
            journeys[(r.vehicle, r.journey)].append(r)
    out = []
    for (_, journey), rs in journeys.items():
        rs.sort(key=lambda r: r.observed_at)
        kept, anchor = [], rs[0]
        for r in rs:
            if _metres(r, anchor) > STILL_M:
                anchor = r
            if (r.observed_at - anchor.observed_at).total_seconds() >= STILL_S:
                dropped["laid_over"] += 1
            else:
                kept.append(r)
        # without a journey id a vehicle's trips run together, so its delay resets between trips
        if journey and any(_jumped(a, b) for a, b in zip(kept, kept[1:], strict=False)):
            dropped["rematched"] += len(kept)
            continue
        out.extend(kept)
    return out, dict(dropped)


def _jumped(a: Sighting, b: Sighting) -> bool:
    dt = (b.observed_at - a.observed_at).total_seconds()
    dd = b.delay_s - a.delay_s
    return dd > dt + JUMP_SLACK_S or dd < -(2 * dt + 300.0)


def profiles(rows: Iterable[Sighting], by: str = "line", min_n: int = 3, hourly: bool = True,
             max_abs_delay_s: float = MAX_ABS_DELAY_S) -> list[Profile]:
    """Lateness per line (``by="line"``), per area (``by="area"``) or over every bus
    (``by="all"``), and hour. Pass readings through ``clean`` first.

    A bus is polled every minute or so, so the same journey shows up many times; each journey
    counts once per key and hour, with the median of its delays in that hour, so slow buses don't
    weigh more than quick ones and one odd reading doesn't set a journey's figure.
    ``hourly=False`` pools the whole window (hour -1)."""
    seen: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for r in rows:
        if r.delay_s is None or abs(r.delay_s) > max_abs_delay_s:
            continue
        key = r.line if by == "line" else "all" if by == "all" else area_of(r)
        if key is None:
            continue
        k = (key, r.observed_at.astimezone(LONDON).hour if hourly else -1, r.journey or r.vehicle)
        seen[k].append(r.delay_s)
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for (key, hour, _), ds in seen.items():
        groups[(key, hour)].append(median(ds) / 60)
    out = []
    for (key, hour), xs in sorted(groups.items()):
        if len(xs) < min_n:
            continue
        xs.sort()
        out.append(Profile(key, hour, len(xs), sum(xs) / len(xs), median(xs), _pct(xs, 0.9),
                           sum(x >= 5 for x in xs) / len(xs)))
    return out


# ---- storage ---------------------------------------------------------------------------------

COLUMNS = [f.name for f in fields(Sighting)]


def append_csv(path: str | Path, rows: Iterable[Sighting]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    n = 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        for r in rows:
            d = asdict(r)
            d["observed_at"] = r.observed_at.isoformat()
            d["collected_at"] = r.collected_at.isoformat()
            w.writerow(d)
            n += 1
    return n


def read_csv(path: str | Path) -> list[Sighting]:
    out = []
    with open(path, encoding="utf-8") as f:
        for d in csv.DictReader(f):
            out.append(Sighting(
                observed_at=datetime.fromisoformat(d["observed_at"]),
                collected_at=datetime.fromisoformat(d["collected_at"]),
                vehicle=d["vehicle"], line=d["line"], journey=d["journey"],
                destination=d["destination"], lat=float(d["lat"]), lon=float(d["lon"]),
                delay_s=_float(d["delay_s"] or None), next_stop=d["next_stop"]))
    return out
