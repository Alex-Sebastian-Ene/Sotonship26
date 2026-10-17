"""Cruise uplift at WebTRIS sites from the demo traffic simulator (SOT-10).

``simulate_uplift(day, params, sites)`` runs the demo's Monte Carlo (``demo/synthetic_demo.py``)
for one day with and without the ships on the same random draws, and reports what a loop counter
at each WebTRIS site would see the ships add: vehicles per 15 minutes, 96 bins per day, in the
shape ``data.observed.observed_uplift`` returns. This is the parametric simulator the calibration
(``calibrate.py``, SOT-8) fits to observed uplift. ``SimParams`` holds the knobs the demo has.

Random draws are seeded by the date, so every parameter guess sees the same sampled days and the
fit's objective is smooth. The demo simulates 05:00-20:00; other bins are zero.

This drives the demo in-process: it loads the demo's model cache once
(``data/cache/southampton/ctx.pkl``, written by ``demo/synthetic_demo.py``) and calls
``synthetic_demo.forecast``. The demo's module state is borrowed for each call and restored
afterwards, so calls are not thread-safe.
"""

from __future__ import annotations

import contextlib
import math
import pickle
import sys
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "demo"
CTX_PATH = ROOT / "data" / "cache" / "southampton" / "ctx.pkl"
LONDON = "Europe/London"
BINS_PER_DAY = 96
FIRST_BIN = 20  # the demo's day starts at 05:00, bin 20 of 96
MODES = ("car", "park", "taxi", "coach", "other")
DEFAULT_SITES = (19974,)
MAX_SITE_DIST_M = 400.0  # a site must lie this close to a link of its road and direction
COLUMNS = ["site_id", "date", "tod_bin", "bin_start", "uplift_veh"]

# Search ranges for calibrate.py, around the demo's defaults and its own M271 fit grid.
SPACE: dict[str, tuple[float, float]] = {
    "mode_share_car": (0.10, 0.45),
    "mode_share_coach": (0.05, 0.40),
    "county_share": (0.50, 0.95),
    "disembark_shift_min": (0.0, 90.0),
    "background_scale": (0.80, 1.20),
}
_ALIASES = {"arrival_offset_min": "disembark_shift_min"}


@dataclass(frozen=True)
class SimParams:
    """Every cruise-traffic guess the demo simulator exposes; the defaults are the demo's."""

    # share of cruise passengers by how they travel: car drop-off, park and cruise, taxi, coach,
    # other (walking, rail); demo MODE_MEAN
    mode_shares: tuple[float, float, float, float, float] = (0.22, 0.28, 0.20, 0.25, 0.05)
    # share of cruise cars and taxis that come from the county gateways rather than the city's
    # zones (the demo's "county")
    county_share: float = 0.8
    # minutes added to when disembarkation traffic starts leaving (the demo's "dis_shift")
    disembark_shift_min: float = 0.0
    # multiplies all everyday traffic, in both runs of each pair
    background_scale: float = 1.0

    def __post_init__(self):
        if len(self.mode_shares) != len(MODES) or min(self.mode_shares) < 0:
            raise ValueError(
                f"mode_shares needs {len(MODES)} non-negative shares ({', '.join(MODES)})"
            )
        if not math.isclose(sum(self.mode_shares), 1.0, abs_tol=1e-6):
            raise ValueError("mode_shares must sum to 1")
        if not 0.0 <= self.county_share <= 1.0:
            raise ValueError("county_share must be between 0 and 1")
        if self.background_scale <= 0:
            raise ValueError("background_scale must be positive")

    @classmethod
    def from_knobs(cls, knobs: Mapping[str, float]) -> SimParams:
        """Build from flat calibration knobs (the ``SPACE`` names).

        ``mode_share_<mode>`` fixes that mode's share; modes not given keep their default ratios
        and share what is left. ``arrival_offset_min`` is accepted for ``disembark_shift_min``.
        The demo has no west/east approach split, so ``approach_share_western`` is refused: use
        ``county_share``.
        """
        base = cls()
        given: dict[str, float] = {}
        other: dict[str, float] = {}
        names = {f.name for f in fields(cls)} - {"mode_shares"}
        for key, value in knobs.items():
            key = _ALIASES.get(key, key)
            if key.startswith("mode_share_") and key[len("mode_share_") :] in MODES:
                given[key[len("mode_share_") :]] = float(value)
            elif key in names:
                other[key] = float(value)
            elif key == "approach_share_western":
                raise ValueError("the demo has no west/east approach split; use county_share")
            else:
                raise ValueError(
                    f"unknown knob {key!r}; accepted: {sorted(SPACE)} and mode_share_<mode>"
                )
        fixed = sum(given.values())
        if fixed > 1.0 + 1e-9:
            raise ValueError("given mode shares add up to more than 1")
        free = [m for m in MODES if m not in given]
        free_total = sum(base.mode_shares[MODES.index(m)] for m in free)
        shares = []
        for i, m in enumerate(MODES):
            if m in given:
                shares.append(given[m])
            elif free_total > 0:
                shares.append(base.mode_shares[i] / free_total * (1.0 - fixed))
            else:
                shares.append((1.0 - fixed) / len(free))
        return cls(mode_shares=tuple(shares), **other)


def demo_module() -> ModuleType:
    """``demo/synthetic_demo.py`` as a module (it puts ``src/`` on the path itself)."""
    if str(DEMO) not in sys.path:
        sys.path.insert(0, str(DEMO))
    import synthetic_demo

    return synthetic_demo


class _DemoUnpickler(pickle.Unpickler):
    """ctx.pkl is written by synthetic_demo run as a script, so its classes are pickled as
    ``__main__``; resolve them from the module instead."""

    def find_class(self, module, name):
        if module == "__main__":
            return getattr(demo_module(), name)
        return super().find_class(module, name)


_CONTEXTS: dict[str, object] = {}


def load_context(path: str | Path | None = None, *, build: bool = False):
    """The demo's model context (network, zones, routes), cached per process.

    Reads ``path`` (default ``data/cache/southampton/ctx.pkl``). ``build=True`` builds it fresh
    with ``synthetic_demo.build_ctx`` instead, which needs the OpenStreetMap, census and DfT
    caches the demo makes on its first run.
    """
    path = Path(path or CTX_PATH)
    key = str(path.resolve())
    if key in _CONTEXTS and not build:
        return _CONTEXTS[key]
    if build:
        ctx, _ = demo_module().build_ctx(log=lambda *a: None)
    elif path.exists():
        with open(path, "rb") as f:
            ctx = _DemoUnpickler(f).load()
    else:
        raise FileNotFoundError(
            f"{path} not found: run demo/synthetic_demo.py once, or pass build=True"
        )
    _CONTEXTS[key] = ctx
    return ctx


def site_links(m, site_id: int, sd: ModuleType | None = None) -> list[int]:
    """Model links a WebTRIS site counts on.

    19974 uses the demo's own ``m271_probe``, so it matches the demo's M271 fit exactly. Other
    sites take the motorway link of their road and direction nearest the site's position.
    """
    sd = sd or demo_module()
    if site_id == 19974:
        return list(sd.m271_probe(m))
    from sotonship26.data.observed import SITES

    if site_id not in SITES:
        raise ValueError(f"unknown WebTRIS site {site_id}; known: {sorted(SITES)}")
    meta = SITES[site_id]
    x0, y1, to_bng = sd.frame_origin()
    e, n = to_bng.transform(meta["lon"], meta["lat"])
    point = np.array([e - x0, y1 - n])  # the page grid: metres east of x0, metres south of y1
    heading = {
        "northbound": (0, -1),
        "southbound": (0, 1),
        "eastbound": (1, 0),
        "westbound": (-1, 0),
    }[meta["direction"]]
    best, best_d = None, math.inf
    for k in range(len(m.t0)):
        if meta["road"] not in m.ref[k].split(";") or m.cls[k] != "motorway":
            continue
        c = np.asarray(m.coords[k], float)
        if (c[-1] - c[0]) @ np.asarray(heading, float) <= 0:
            continue
        d = _distance_to_line(point, c)
        if d < best_d:
            best, best_d = k, d
    if best is None or best_d > MAX_SITE_DIST_M:
        raise ValueError(
            f"site {site_id} ({meta['road']} {meta['direction']}) has no model link "
            f"within {MAX_SITE_DIST_M:.0f} m"
        )
    return [best]


def _distance_to_line(p: np.ndarray, line: np.ndarray) -> float:
    a, b = line[:-1], line[1:]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0.0, 1.0)
    return float(np.min(np.hypot(*(a + ab * t[:, None] - p).T)))


def demo_calls(day: date, calls=None) -> list[dict]:
    """Ship calls turning around on ``day``, in the demo's task format.

    ``calls`` is a frame or list of dicts with the columns of ``vts.load_schedule()`` /
    ``cruise_history.load_calls()`` (ship, terminal, arrival, departure, passengers), or None
    to read the live VTS schedule. As in the demo, a call belongs to its arrival day. Terminals
    outside the model are skipped with a warning.
    """
    if calls is None:
        from sotonship26.data.vts import load_schedule

        calls = load_schedule()
    df = pd.DataFrame(calls)
    if df.empty:
        return []
    out = []
    for r in df.itertuples(index=False):
        arr, dep = _local(r.arrival), _local(r.departure)
        if arr.date() != day:
            continue
        terminal = str(r.terminal).replace(" Cruise Terminal", "").strip()
        if terminal not in {"Ocean", "QEII", "Mayflower", "City", "Horizon"}:
            warnings.warn(
                f"{r.ship}: terminal {r.terminal!r} is outside the model, skipped", stacklevel=2
            )
            continue
        pax = getattr(r, "passengers", None)
        pax = None if pax is None or pd.isna(pax) else int(pax)
        out.append(
            {
                "ship": str(r.ship),
                "terminal": terminal,
                "arrival": arr.isoformat(timespec="minutes"),
                "departure": dep.isoformat(timespec="minutes"),
                "pax": pax,
            }
        )
    return out


def _local(t) -> datetime:
    """A naive Europe/London wall-clock time, as the demo uses."""
    ts = pd.Timestamp(t)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(LONDON).tz_localize(None)
    return ts.to_pydatetime()


@contextlib.contextmanager
def _borrowed(sd: ModuleType, ctx, params: SimParams):
    """Point the demo at ``ctx`` with ``params`` applied, and put everything back afterwards."""
    m = ctx.m
    saved = (sd.CTX, sd.MODE_MEAN, m.scale, m.scale_ext, getattr(m, "scale_freight", None))
    try:
        sd.CTX = ctx
        sd.MODE_MEAN = np.asarray(params.mode_shares, float)
        m.scale = saved[2] * params.background_scale
        m.scale_ext = saved[3] * params.background_scale
        if saved[4] is not None:
            m.scale_freight = saved[4] * params.background_scale
        yield
    finally:
        sd.CTX, sd.MODE_MEAN, m.scale, m.scale_ext = saved[:4]
        if saved[4] is not None:
            m.scale_freight = saved[4]


def simulate_uplift(
    day: date | str,
    params: SimParams | None = None,
    sites: Iterable[int] = DEFAULT_SITES,
    *,
    samples: int = 8,
    calls=None,
    ctx=None,
) -> pd.DataFrame:
    """Modelled cruise uplift per WebTRIS site and 15-minute bin for one day.

    Columns: site_id, date, tod_bin (0-95), bin_start (tz-aware Europe/London), uplift_veh
    (vehicles per 15 minutes the ships add, as a counter at the site would see them). ``calls``
    as in ``demo_calls``; ``ctx`` defaults to ``load_context()``.
    """
    day = pd.Timestamp(day).date()
    params = params or SimParams()
    sd = demo_module()
    ctx = ctx if ctx is not None else load_context()
    task_calls = demo_calls(day, calls)
    starts = pd.date_range(pd.Timestamp(day), periods=BINS_PER_DAY, freq="15min").tz_localize(
        LONDON, ambiguous="NaT", nonexistent="shift_forward"
    )
    frames = []
    with _borrowed(sd, ctx, params):
        for site in sites:
            uplift = np.zeros(BINS_PER_DAY)
            if task_calls:
                task = {
                    "date": day.isoformat(),
                    "key": f"uplift {site}",
                    "calls": task_calls,
                    "full": False,
                    "paired": True,
                    "closed": [],
                    "match": sd.match_on(day),
                    "n": int(samples),
                    "term": sd.in_term(day),
                    "probe": site_links(ctx.m, site, sd),
                    "cruise": {
                        "road": 1.0,
                        "county": params.county_share,
                        "dis_shift": params.disembark_shift_min,
                    },
                }
                probe = np.asarray(sd.forecast(task).get("probe", 0.0), float)  # veh/h per bin
                uplift[FIRST_BIN : FIRST_BIN + probe.size] = probe / 4.0
            frames.append(
                pd.DataFrame(
                    {
                        "site_id": site,
                        "date": day,
                        "tod_bin": np.arange(BINS_PER_DAY),
                        "bin_start": starts,
                        "uplift_veh": uplift,
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)[COLUMNS]


def simulator(
    params: Mapping[str, float],
    days,
    *,
    sites: Iterable[int] = DEFAULT_SITES,
    samples: int = 8,
    calls=None,
    ctx=None,
) -> pd.DataFrame:
    """``calibrate.Simulator``: flat knobs (``SPACE`` names) and days to uplift rows.

    For past days pass ``calls`` (all calls, e.g. ``cruise_history.load_calls()``); the live VTS
    schedule only reaches about three months ahead, so without them past days show no ships.
    """
    p = SimParams.from_knobs(params)
    if calls is None:
        from sotonship26.data.vts import load_schedule

        calls = load_schedule()
    return pd.concat(
        [simulate_uplift(d, p, sites, samples=samples, calls=calls, ctx=ctx) for d in days],
        ignore_index=True,
    )
