"""Bus timetables and live lateness from bustimes.org.

bustimes.org republishes the Bus Open Data Service (timetables and live vehicle positions) with a
public JSON API. We use two parts of it:

* ``/vehicles.json?xmin=&ymin=&xmax=&ymax=``: buses inside a bounding box right now, each with its
  position, line and (usually) the ``trip_id`` of the timetabled journey it is running;
* ``/api/trips/<id>/``: that trip's stops with locations and aimed times.

How late a bus is = when it was seen at a point on its route minus when the timetable has it there,
interpolating between the two stops it is between. Where a vehicle record already carries a delay
we keep that as well, for comparison. Field names follow the API as it looked when this was written
(16 Oct 2026, unverified against a live response because the site was not reachable from the build
environment); the parsers accept the obvious alternatives and skip records they cannot read.

Be polite: bustimes.org is run by one person. Requests are spaced at least ``min_interval_s`` apart
and trips are cached on disk, since a trip's timetable does not change during the day. The data is
derived from BODS (Open Government Licence v3.0); check bustimes.org's own terms before
redistributing anything beyond aggregates.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

API_ROOT = "https://bustimes.org"
LONDON = ZoneInfo("Europe/London")
# lon/lat box around the city centre, the docks and the main corridors into town
SOUTHAMPTON_BBOX = (-1.445, 50.885, -1.365, 50.935)
USER_AGENT = "sotonship26/0.1 (SotonShip 2026 hackathon; cruise-day demand research)"


@dataclass(frozen=True)
class TripStop:
    atco: str
    name: str
    lat: float
    lon: float
    aimed: datetime  # aimed departure, or arrival at the last stop


@dataclass(frozen=True)
class Trip:
    id: str
    line: str
    operator: str
    stops: tuple[TripStop, ...]


@dataclass(frozen=True)
class Sighting:
    observed_at: datetime
    vehicle: str
    line: str
    trip_id: str | None
    lat: float
    lon: float
    heading: float | None
    destination: str
    reported_delay_s: float | None  # if the feed itself reports one


@dataclass(frozen=True)
class Lateness:
    observed_at: datetime
    vehicle: str
    line: str
    trip_id: str
    delay_s: float  # positive = late
    off_route_m: float  # distance from the timetabled route; large values mean a poor match
    next_stop: str
    reported_delay_s: float | None


class BustimesClient:
    def __init__(
        self,
        root: str = API_ROOT,
        cache_dir: str | Path | None = "data/cache/bustimes",
        min_interval_s: float = 1.5,
        timeout_s: float = 30.0,
    ):
        self.root = root.rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self._last = 0.0

    def get_json(self, path: str, params: Mapping[str, object] | None = None):
        wait = self.min_interval_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = f"{self.root}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.load(response)
        finally:
            self._last = time.monotonic()

    def vehicles(self, bbox: Sequence[float] = SOUTHAMPTON_BBOX) -> list[Sighting]:
        xmin, ymin, xmax, ymax = bbox
        payload = self.get_json(
            "/vehicles.json", {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
        )
        return parse_vehicles(payload)

    def trip(self, trip_id: str, service_day: date) -> Trip | None:
        raw = None
        cached = self.cache_dir / "trips" / f"{trip_id}.json" if self.cache_dir else None
        if cached and cached.exists():
            raw = json.loads(cached.read_text(encoding="utf-8"))
        else:
            raw = self.get_json(f"/api/trips/{trip_id}/")
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(raw), encoding="utf-8")
        return parse_trip(raw, service_day)


# ---- parsing ---------------------------------------------------------------------------------


def parse_vehicles(payload) -> list[Sighting]:
    items = payload.get("results", payload) if isinstance(payload, dict) else payload
    out = []
    for v in items or []:
        try:
            lon, lat = _coords(v)
            when = _parse_datetime(v.get("datetime"))
        except (KeyError, TypeError, ValueError):
            continue
        service = v.get("service") or {}
        vehicle = v.get("vehicle") or {}
        trip = v.get("trip_id") or (v.get("trip") or {}).get("id")
        out.append(
            Sighting(
                observed_at=when,
                vehicle=str(vehicle.get("name") or vehicle.get("url") or v.get("id")),
                line=str(service.get("line_name") or v.get("line_name") or "?"),
                trip_id=str(trip) if trip else None,
                lat=lat,
                lon=lon,
                heading=_float_or_none(v.get("heading")),
                destination=str(v.get("destination") or ""),
                reported_delay_s=_float_or_none(v.get("delay")),
            )
        )
    return out


def parse_trip(raw: Mapping, service_day: date) -> Trip | None:
    stops = []
    for t in raw.get("times") or []:
        stop = t.get("stop") or {}
        loc = stop.get("location")
        aimed = t.get("aimed_departure_time") or t.get("aimed_arrival_time")
        if not loc or not aimed:
            continue  # stops without coordinates or times cannot be matched
        stops.append(
            TripStop(
                atco=str(stop.get("atco_code") or stop.get("id") or ""),
                name=str(stop.get("name") or ""),
                lon=float(loc[0]),
                lat=float(loc[1]),
                aimed=_service_time(service_day, aimed),
            )
        )
    if len(stops) < 2:
        return None
    service = raw.get("service") or {}
    operator = raw.get("operator") or {}
    return Trip(
        id=str(raw.get("id")),
        line=str(service.get("line_name") or "?"),
        operator=str(operator.get("name") or operator.get("noc") or ""),
        stops=tuple(stops),
    )


def _coords(v: Mapping) -> tuple[float, float]:
    c = v.get("coordinates") or (v.get("geometry") or {}).get("coordinates")
    return float(c[0]), float(c[1])


def _parse_datetime(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=LONDON)


def _service_time(day: date, hhmm: str) -> datetime:
    """Timetable clock time on a service day; GTFS-style times past 24:00 roll into tomorrow."""
    parts = [int(p) for p in hhmm.split(":")]
    h, m = parts[0], parts[1]
    s = parts[2] if len(parts) > 2 else 0
    base = datetime(day.year, day.month, day.day, tzinfo=LONDON)
    return base + timedelta(hours=h, minutes=m, seconds=s)


def _float_or_none(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---- lateness --------------------------------------------------------------------------------


def _local_xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    return lon * 111320 * math.cos(math.radians(lat0)), lat * 110540


def estimate_lateness(s: Sighting, trip: Trip, max_off_route_m: float = 250.0) -> Lateness | None:
    """Project the sighting onto the trip's stop-to-stop polyline and compare with the timetable.

    Returns None when the bus is further than ``max_off_route_m`` from every segment (diverted, at
    the depot, or the trip id is wrong).
    """
    lat0 = trip.stops[0].lat
    px, py = _local_xy(s.lat, s.lon, lat0)
    best = None
    for a, b in zip(trip.stops, trip.stops[1:], strict=False):
        ax, ay = _local_xy(a.lat, a.lon, lat0)
        bx, by = _local_xy(b.lat, b.lon, lat0)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        f = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(px - (ax + f * dx), py - (ay + f * dy))
        if best is None or d < best[0]:
            best = (d, a, b, f)
    d, a, b, f = best
    if d > max_off_route_m:
        return None
    scheduled = a.aimed + (b.aimed - a.aimed) * f
    return Lateness(
        observed_at=s.observed_at,
        vehicle=s.vehicle,
        line=trip.line if trip.line != "?" else s.line,
        trip_id=trip.id,
        delay_s=(s.observed_at - scheduled).total_seconds(),
        off_route_m=d,
        next_stop=b.name,
        reported_delay_s=s.reported_delay_s,
    )


def collect_once(client: BustimesClient, bbox=SOUTHAMPTON_BBOX) -> list[Lateness]:
    out = []
    for s in client.vehicles(bbox):
        if not s.trip_id:
            continue
        local = s.observed_at.astimezone(LONDON)
        # A trip seen just after midnight may belong to yesterday's service day.
        for day in (local.date(), local.date() - timedelta(days=1)):
            trip = client.trip(s.trip_id, day)
            est = trip and estimate_lateness(s, trip)
            if est and abs(est.delay_s) < 3 * 3600:
                out.append(est)
                break
    return out


# ---- aggregation for the frontend -----------------------------------------------------------


@dataclass(frozen=True)
class DelayProfile:
    line: str
    hour: int
    n: int
    mean_min: float
    p50_min: float
    p90_min: float
    share_over_5_min: float


def delay_profiles(rows: Iterable[Lateness], min_n: int = 5) -> list[DelayProfile]:
    """Lateness per line and hour of day. One bus seen many times in an hour counts once per
    sighting, so a slow crawl through town weighs more than a quick pass; this is deliberate,
    because passengers at stops experience the bus for that long."""
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in rows:
        groups[(r.line, r.observed_at.astimezone(LONDON).hour)].append(r.delay_s / 60)
    out = []
    for (line, hour), xs in sorted(groups.items()):
        if len(xs) < min_n:
            continue
        xs.sort()
        out.append(
            DelayProfile(
                line=line,
                hour=hour,
                n=len(xs),
                mean_min=sum(xs) / len(xs),
                p50_min=xs[len(xs) // 2],
                p90_min=xs[min(len(xs) - 1, int(0.9 * len(xs)))],
                share_over_5_min=sum(x > 5 for x in xs) / len(xs),
            )
        )
    return out


def lateness_to_row(r: Lateness) -> dict:
    d = asdict(r)
    d["observed_at"] = r.observed_at.isoformat()
    return d


def lateness_from_row(d: Mapping) -> Lateness:
    def opt(x):
        return None if x in (None, "") else float(x)

    return Lateness(
        observed_at=datetime.fromisoformat(d["observed_at"]),
        vehicle=d["vehicle"],
        line=d["line"],
        trip_id=d["trip_id"],
        delay_s=float(d["delay_s"]),
        off_route_m=float(d["off_route_m"]),
        next_stop=d["next_stop"],
        reported_delay_s=opt(d.get("reported_delay_s")),
    )
