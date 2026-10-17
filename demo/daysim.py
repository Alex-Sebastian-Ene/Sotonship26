"""One sampled day of the cruise-day traffic model, kept in pieces and run one bin at a time.

Shared by demo/agents.py (individual vehicles and buses) and demo/ppo_env.py (the PPO decision
layer). It mirrors one sample of synthetic_demo.forecast() and the allocation in
traffic_model.run_day(), but keeps what those add up:

* demand per kind of trip (background_by_purpose: the same random draws, in the same order, as
  traffic_model.background, so the purposes add up to its matrix exactly);
* every cruise vehicle with its ship, leg, mode and time (cruise_vehicles: the same draws as
  synthetic_demo.sample_cruise, so the vehicles add up to its matrix exactly), which lets
  disembarkation be metered and check-in moved after the day is drawn;
* the allocation one 15-minute bin at a time (DaySim.step), so a policy can act between bins.
  With no actions it reproduces run_day.

tests/test_demo_agents_ppo.py checks the three "exactly" claims on a small network. If
synthetic_demo.sample_cruise or traffic_model.background change, those tests say so.
"""

from __future__ import annotations

import json
import math
import pickle
import sys
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synthetic_demo as sd  # noqa: E402
import traffic_model as tm  # noqa: E402

from sotonship26.demand.passengers import TurnaroundParams  # noqa: E402

N_BINS = tm.N_BINS
BIN_MIN = sd.BIN_MIN
DAY_START_MIN = tm.DAY_START_H * 60
CTX_PATH = sd.CACHE / "ctx.pkl"
KINDS = ("car", "park", "taxi", "coach")  # car: drop-off or pick-up; park: park and cruise
LEGS = ("dis", "emb")  # disembarking (morning) and embarking (afternoon) passengers
# How a cruise vehicle's minute is made from its ship's times (see cruise_times):
DIS, COACH_IN, EMB = 0, 1, 2


# --- loading the cached model --------------------------------------------------------------------

class _CtxUnpickler(pickle.Unpickler):
    """synthetic_demo.main() pickles Ctx while running as __main__; resolve it to the module."""

    def find_class(self, module, name):
        if module in ("__main__", "__mp_main__") and hasattr(sd, name):
            return getattr(sd, name)
        return super().find_class(module, name)


def load_ctx(path: Path = CTX_PATH, log=print) -> sd.Ctx:
    """The calibrated model synthetic_demo.py caches; built here (about a minute) if missing."""
    if not path.exists():
        log(f"{path} missing: building the model (demo/synthetic_demo.py caches it)")
        ctx, _ = sd.build_ctx(log)
        return ctx
    with open(path, "rb") as f:
        return _CtxUnpickler(f).load()


def day_tasks(cruise: dict | None = None) -> dict[str, dict]:
    """Each day of the forecast window with its ships, permits, match and school term, as in
    synthetic_demo.main() (calls are synthetic_demo.Call objects). ``cruise``: fitted cruise
    assumptions, if any (fitted_cruise)."""
    sched = sd.make_schedule(np.random.default_rng(sd.SEED))
    out = {}
    d = sd.FIRST_DAY
    while d <= sd.HORIZON:
        out[d.isoformat()] = {"date": d.isoformat(), "calls": list(sched[d]),
                              "closed": [p["corridor"] for p in sd.permits_on(d)],
                              "match": sd.match_on(d), "term": sd.in_term(d), "cruise": cruise}
        d += timedelta(days=1)
    return out


def task_json(task: dict) -> dict:
    """A day task in the dict form synthetic_demo.forecast() and advise() take."""
    calls = [{"ship": c.ship, "terminal": c.terminal, "arrival": c.arrival.isoformat(),
              "departure": c.departure.isoformat(), "pax": c.pax, "times": c.times}
             for c in task["calls"]]
    out = {"date": task["date"], "key": "base", "calls": calls, "closed": list(task["closed"]),
           "match": task["match"], "term": task["term"], "full": False, "paired": False}
    if task.get("cruise"):
        out["cruise"] = task["cruise"]
    return out


def page_data(path: Path) -> dict | None:
    """The data block of a page synthetic_demo.py built, or None."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    tag = '<script id="demo-data" type="application/json">'
    i = text.find(tag)
    if i < 0:
        return None
    j = text.find("</script>", i)
    return json.loads(text[i + len(tag):j])


def fitted_cruise(page: dict | None) -> dict | None:
    """Cruise assumptions fitted to the learned M271 uplift, when the page has them."""
    fit = ((page or {}).get("meta") or {}).get("cruise_fit") or {}
    return fit.get("params")


def shares_key(task: dict) -> tuple:
    d = date.fromisoformat(task["date"])
    return (tm.daytype(d.weekday()), tuple(sorted(task["closed"])), task["match"], task["term"])


def base_shares(ctx: sd.Ctx, task: dict) -> np.ndarray:
    """Route shares to warm-start from (synthetic_demo.base_shares, cached per process)."""
    dtype, closed, kick, term = shares_key(task)
    return sd.base_shares(ctx, dtype, set(closed), kick, term)


# --- demand ----------------------------------------------------------------------------------

def background_by_purpose(m: tm.Model, dtype: int, rng: np.random.Generator | None = None,
                          term: bool = True, spread: float = 1.0, mult: dict | None = None):
    """traffic_model.background, keeping each kind of trip apart.

    Returns ({purpose: (vehicles per bin, OD weights)}, groups). A purpose's demand matrix is the
    outer product of the two; added up in PURPOSES order they give background()'s matrix, because
    the random numbers are drawn in the same order.
    """
    parts, groups = {}, {}
    od_mult, day, shared = 1.0, 1.0, 1.0
    if rng is not None:
        day = rng.lognormal(0.0, tm.NOISE["day"] * spread)
        shared = tm.ar1(rng, N_BINS, tm.NOISE["shared_bin"] * spread, tm.NOISE["shared_rho"])
        z = m.zone_kernel @ rng.normal(0.0, tm.NOISE["zone"] * spread, m.zone_kernel.shape[0])
        zf = np.exp(z)
        oz, dz = m.od_zone[:, 0], m.od_zone[:, 1]
        od_mult = (np.where(oz >= 0, zf[np.maximum(oz, 0)], 1.0)
                   * np.where(dz >= 0, zf[np.maximum(dz, 0)], 1.0))
    for key, group, _, _, totals, profiles in tm.PURPOSES:
        if key in tm.SCHOOL_KEYS and not (term and dtype == 0):
            continue
        prof = tm.bin_profile(tm.PROFILES[profiles[0 if dtype == 0 else 1]])
        total = totals[dtype] * (m.scale_ext if group in tm.EXTERNAL else m.scale) * day
        if mult:
            total *= mult.get(group, mult.get("all", 1.0))
        if rng is not None:
            total *= rng.lognormal(0.0, tm.NOISE["purpose"] * spread)
            prof = prof * tm.ar1(rng, N_BINS, tm.NOISE["bin"] * spread, tm.NOISE["rho"]) * shared
        parts[key] = (prof * total, m.purpose_od[key] * od_mult)
        groups[group] = groups.get(group, 0) + prof * total
    return parts, groups


def parts_matrix(m: tm.Model, parts: dict) -> np.ndarray:
    D = np.zeros((N_BINS, m.n_od))
    for bins, odw in parts.values():
        D += np.outer(bins, odw)
    return D


def cruise_setup(ctx: sd.Ctx, cruise: dict | None):
    """Mode shares, origin sets and extra disembarkation minutes for the cruise assumptions.

    synthetic_demo gains fitted cruise assumptions (CRUISE_DEFAULT, cruise_sets, the cruise=
    argument of sample_cruise) on another branch; this follows them when they are there and uses
    the plain constants otherwise.
    """
    m = ctx.m
    if not hasattr(sd, "CRUISE_DEFAULT"):
        return sd.MODE_MEAN, m.sets, 0.0
    c = {**sd.CRUISE_DEFAULT, **(cruise or {})}
    mode_mean = sd.MODE_MEAN.copy()
    mode_mean[:3] *= c["road"]
    mode_mean[3:] *= (1 - mode_mean[:3].sum()) / mode_mean[3:].sum()
    return mode_mean, {**m.sets, **sd.cruise_sets(ctx, c["county"])}, float(c["dis_shift"])


def cruise_vehicles(ctx: sd.Ctx, calls, rng: np.random.Generator, p: TurnaroundParams,
                    cruise: dict | None = None) -> dict:
    """Every cruise vehicle of the day, drawn exactly as synthetic_demo.sample_cruise draws them.

    Returns column arrays, one entry per vehicle: call, leg (0 dis, 1 emb), how its minute is made
    (DIS, COACH_IN, EMB), the random position u in its window, a fixed offset in minutes, the OD
    index j (-1 if the model has no such pair), kind (KINDS index), PCU, passengers it carries
    away from the terminal (for metering) and whether metering holds it. Per call: the
    disembarkation start and check-in window with no shifts ("start", "lo", "hi").
    """
    mode_mean, sets, dis_extra = cruise_setup(ctx, cruise)
    cols = {k: [] for k in ("call", "leg", "how", "u", "post", "j", "kind", "pcu", "pax", "metered")}
    start0, lo0, hi0 = [], [], []

    def add(u, post, key, gate, direction, pcu, ci, leg, how, kind, pax, metered, o=None):
        n = len(u)
        if n == 0:
            return None
        if o is None:
            ids, probs = sets[key]
            o = rng.choice(len(ids), size=n, p=probs)
        j = ctx.luts[key][gate][direction][o]
        for k, v in (("call", ci), ("leg", leg), ("how", how), ("post", post), ("kind", kind),
                     ("pcu", pcu), ("pax", pax), ("metered", metered)):
            cols[k].append(np.full(n, v))
        cols["u"].append(np.asarray(u, float))
        cols["j"].append(np.asarray(j))
        return o

    for ci, c in enumerate(calls):
        gate = ctx.terminal_gate[c.terminal]
        berths = c.pax if c.pax else rng.uniform(*sd.UNKNOWN_PAX_RANGE)
        arr, dep = sd.minutes(c.arrival), sd.minutes(c.departure)
        start0.append(arr + rng.normal(0.0, p.arrival_delay_sd_min) + p.disembark_start_min)
        lo0.append(dep - p.embark_open_before_dep_min)
        hi0.append(dep - p.embark_close_before_dep_min)
        for leg in (0, 1):
            people = int(round(berths * rng.beta(*p.load_factor_beta)))
            n_car, n_park, n_taxi, n_coach, _ = rng.multinomial(
                people, rng.dirichlet(mode_mean * sd.MODE_CONC))
            cars = round(n_car / sd.PEOPLE_PER["car"])
            parks = round(n_park / sd.PEOPLE_PER["park"])
            taxis = round(n_taxi / sd.PEOPLE_PER["taxi"])
            coaches = math.ceil(n_coach / sd.PEOPLE_PER["coach"])
            per_coach = n_coach / max(coaches, 1)
            if leg == 0:  # disembarking: drivers come to collect, then leave with passengers
                u = rng.beta(2.0, 3.0, cars)
                o = add(u, -20.0, "car_from", gate, "in", 1.0, ci, 0, DIS, 0, 0.0, True)
                if o is not None:
                    add(u, 5.0, "car_from", gate, "out", 1.0, ci, 0, DIS, 0,
                        sd.PEOPLE_PER["car"], True, o)
                u = rng.beta(2.0, 3.0, parks)
                add(u, 10.0, "car_from", gate, "out", 1.0, ci, 0, DIS, 1,
                    sd.PEOPLE_PER["park"], True)
                u = rng.beta(2.0, 3.0, taxis)
                add(u, -15.0, "taxi_rank", gate, "in", 1.0, ci, 0, DIS, 2, 0.0, True)
                add(u, 0.0, "taxi_far", gate, "out", 1.0, ci, 0, DIS, 2, sd.PEOPLE_PER["taxi"], True)
                # empty coaches arrive before disembarkation starts and wait: not metered
                o = add(rng.random(coaches), 0.0, "coach_from", gate, "in", sd.COACH_PCU, ci, 0,
                        COACH_IN, 3, 0.0, False)
                if o is not None:
                    add(rng.beta(2.0, 3.0, coaches), 20.0, "coach_from", gate, "out", sd.COACH_PCU,
                        ci, 0, DIS, 3, per_coach, True, o)
            else:  # embarking: check-in window
                u = rng.beta(2.0, 2.0, cars)
                o = add(u, 0.0, "car_from", gate, "in", 1.0, ci, 1, EMB, 0, 0.0, False)
                if o is not None:
                    add(u, 15.0, "car_from", gate, "out", 1.0, ci, 1, EMB, 0, 0.0, False, o)
                add(rng.beta(2.0, 2.0, parks), -10.0, "car_from", gate, "in", 1.0, ci, 1, EMB, 1,
                    0.0, False)
                u = rng.beta(2.0, 2.0, taxis)
                add(u, 0.0, "taxi_far", gate, "in", 1.0, ci, 1, EMB, 2, 0.0, False)
                add(u, 10.0, "taxi_rank", gate, "out", 1.0, ci, 1, EMB, 2, 0.0, False)
                u = rng.beta(2.0, 2.0, coaches)
                o = add(u, 0.0, "coach_from", gate, "in", sd.COACH_PCU, ci, 1, EMB, 3, 0.0, False)
                if o is not None:
                    add(u, 20.0, "coach_from", gate, "out", sd.COACH_PCU, ci, 1, EMB, 3, 0.0, False, o)
    dtypes = {"call": int, "leg": int, "how": int, "u": float, "post": float, "j": int,
              "kind": int, "pcu": float, "pax": float, "metered": bool}
    out = {k: (np.concatenate(v).astype(dtypes[k]) if v else np.zeros(0, dtypes[k]))
           for k, v in cols.items()}
    out["start"], out["lo"], out["hi"] = (np.asarray(start0, float), np.asarray(lo0, float),
                                          np.asarray(hi0, float))
    out["dis_extra"] = dis_extra
    out["gate"] = np.array([ctx.terminal_gate[c.terminal] for c in calls], int)
    out["terminal"] = [c.terminal for c in calls]
    return out


def cruise_times(veh: dict, p: TurnaroundParams, dis_shift=None, emb_shift=None,
                 open_shift=None) -> np.ndarray:
    """Minute of day of each cruise vehicle.

    dis_shift moves a call's disembarkation start; emb_shift moves its whole check-in window
    (synthetic_demo.advise's two levers); open_shift opens check-in earlier (negative) or later
    with the close unchanged (the PPO lever). Arrays per call, minutes; None is no change.
    With no shifts the minutes equal sample_cruise's to the last bit.
    """
    n_calls = len(veh["start"])

    def per_call(a):
        return np.zeros(n_calls) if a is None else np.asarray(a, float)

    ds, es, os_ = per_call(dis_shift), per_call(emb_shift), per_call(open_shift)
    c = veh["call"]
    start = (veh["start"] + ds) + veh.get("dis_extra", 0.0)
    lo = veh["lo"] + es + os_
    hi = veh["hi"] + es
    t = np.empty(len(c))
    how = veh["how"]
    k = how == DIS
    t[k] = (start[c[k]] + p.disembark_duration_min * veh["u"][k]) + veh["post"][k]
    k = how == COACH_IN
    t[k] = ((start[c[k]] - 30) + 120 * veh["u"][k]) + veh["post"][k]
    k = how == EMB
    t[k] = (lo[c[k]] + (hi[c[k]] - lo[c[k]]) * veh["u"][k]) + veh["post"][k]
    return t


def bin_index(t) -> np.ndarray:
    return np.floor((np.asarray(t) - DAY_START_MIN) / BIN_MIN).astype(int)


def vehicles_matrix(n_od: int, veh: dict, t: np.ndarray, mask=None) -> np.ndarray:
    """Cruise vehicles per bin and OD (PCU), as sample_cruise builds it; vehicles outside
    05:00-20:00 or on a pair the model lacks are left out, as there."""
    D = np.zeros((N_BINS, n_od))
    b = bin_index(t)
    ok = (b >= 0) & (b < N_BINS) & (veh["j"] >= 0)
    if mask is not None:
        ok &= mask
    np.add.at(D, (b[ok], veh["j"][ok]), veh["pcu"][ok])
    return D


def turnaround_params(d: date) -> TurnaroundParams:
    """forecast()'s turnaround parameters: arrival delays widen with lead time."""
    base = TurnaroundParams()
    return replace(base, arrival_delay_sd_min=base.arrival_delay_sd_min * sd.lead_spread(d))


# --- one sampled day -------------------------------------------------------------------------

@dataclass
class SampledDay:
    task: dict
    date: date
    dtype: int
    params: TurnaroundParams
    wet: bool
    cap: np.ndarray  # after permits and weather, before incidents
    events: list  # (edges, first bin, end bin, capacity factor)
    noise: np.ndarray  # perceived travel time factor per edge
    parts: dict  # purpose -> (vehicles per bin, OD weights)
    groups: dict
    Dbg: np.ndarray
    Dm: np.ndarray
    veh: dict
    pre: np.ndarray | None
    shares0: np.ndarray
    extra: dict = field(default_factory=dict)

    def cruise_matrix(self, n_od: int, **shifts) -> np.ndarray:
        return vehicles_matrix(n_od, self.veh, cruise_times(self.veh, self.params, **shifts))


def sample_day(ctx: sd.Ctx, task: dict, rng: np.random.Generator,
               shares0: np.ndarray | None = None) -> SampledDay:
    """Draw one day as one sample of synthetic_demo.forecast() draws it (same order of draws:
    weather, incident, perception, everyday traffic, match, cruise)."""
    m = ctx.m
    d = date.fromisoformat(task["date"])
    dtype = tm.daytype(d.weekday())
    closed, kick, term = set(task["closed"]), task["match"], task["term"]
    cap0 = sd.capacity(ctx, closed)
    if shares0 is None:
        shares0 = base_shares(ctx, task)
    spread = sd.lead_spread(d)
    params = turnaround_params(d)
    segs = ctx.extra["segs"]
    major = [i for i, sg in enumerate(segs) if sg["cls"] in sd.MAJOR_CLASSES]
    major_w = np.array([sum(m.length[e] for e in segs[i]["edges"]) for i in major], float)
    major_w /= major_w.sum()

    wet = bool(rng.random() < sd.P_WET.get(d.month, 0.5))
    cap = cap0 * (sd.WET_CAPACITY if wet else 1.0)
    events = []
    if rng.random() < sd.INCIDENT_P:
        seg = segs[major[rng.choice(len(major), p=major_w)]]
        b0 = int(rng.integers(0, N_BINS - 4))
        events.append((np.asarray(seg["edges"]), b0, b0 + int(rng.integers(4, 9)), 0.55))
    noise = rng.lognormal(-sd.PERCEPTION_SD**2 / 2, sd.PERCEPTION_SD, len(m.t0))
    parts, groups = background_by_purpose(m, dtype, rng, term=term, spread=spread,
                                          mult=sd.day_multipliers(d, wet))
    Dbg = parts_matrix(m, parts)
    Dm = tm.match_demand(m, sd.kickoff_hours(kick), rng) if kick else np.zeros_like(Dbg)
    # no calls draws nothing, as forecast() skips sample_cruise then
    veh = cruise_vehicles(ctx, task["calls"], rng, params, task.get("cruise"))
    return SampledDay(task=task, date=d, dtype=dtype, params=params, wet=wet, cap=cap,
                      events=events, noise=noise, parts=parts, groups=groups, Dbg=Dbg, Dm=Dm,
                      veh=veh, pre=m.pre.get(dtype), shares0=shares0)


# --- allocation one bin at a time ------------------------------------------------------------

def cap_at(cap: np.ndarray, events, b: int) -> np.ndarray:
    """Capacity in bin b with incidents applied, as run_day does it."""
    capb = cap
    for edges, b0, b1, factor in events:
        if b0 <= b < b1:
            capb = capb.copy() if capb is cap else capb
            capb[edges] *= factor
    return capb


class DaySim:
    """traffic_model.run_day, one 15-minute bin per call to step()."""

    def __init__(self, m: tm.Model, shares0: np.ndarray, pre: np.ndarray | None = None,
                 iters: int = 3):
        self.m, self.shares0, self.pre, self.iters = m, shares0, pre, iters
        self.b = 0
        self.queue = np.zeros(m.n_od)

    def step(self, D_b: np.ndarray, cap_b: np.ndarray, noise: np.ndarray | None = None) -> dict:
        """Route bin self.b's new demand plus the queue carried over; returns the bin's flows."""
        m, b = self.m, self.b
        veh = D_b + self.queue
        rate = veh * 4.0
        pb = self.pre[b] if self.pre is not None else 0.0
        f = tm.equilibrium_bin(m, rate, cap_b, self.shares0[b], self.iters, pb, noise)
        v = m.A @ f + pb
        x = v / cap_b
        bottleneck = np.maximum.reduceat(x[m.col_idx], m.col_ptr)
        served = f / np.maximum(bottleneck, 1.0)
        unserved = tm.CARRY * (f - served).reshape(m.n_od, tm.ROUTES).sum(axis=1) / 4.0
        with np.errstate(invalid="ignore", divide="ignore"):
            sh = np.where(rate[:, None] > 0, f.reshape(m.n_od, tm.ROUTES) / rate[:, None],
                          self.shares0[b])
        self.queue = unserved
        self.b += 1
        return {"x": x, "v": v, "f": f, "share": sh, "held": float(unserved.sum()),
                "queue": np.maximum(v - cap_b, 0.0) / 4.0}


# --- one vehicle along its route -------------------------------------------------------------

MAX_HOLD_BINS = 8  # a vehicle waits at most two hours in one queue


def bin_of(t_min: float) -> int:
    return min(N_BINS - 1, max(0, int((t_min - DAY_START_MIN) // BIN_MIN)))


def wait_in_queue(X: np.ndarray, ahead, tau: float, rng: np.random.Generator) -> float:
    """Minute a held vehicle leaves its queue: a random minute of the next bin, or of a later one
    while the links ``ahead`` stay over capacity (each further bin with run_day's chance
    CARRY (1 - 1/x)), at most MAX_HOLD_BINS bins."""
    nb = bin_of(tau) + 1
    for _ in range(MAX_HOLD_BINS - 1):
        if nb >= N_BINS:
            break
        xn = float(X[nb, ahead].max())
        if not (xn > 1.0 and rng.random() < tm.CARRY * (1.0 - 1.0 / xn)):
            break
        nb += 1
    return max(tau, DAY_START_MIN + BIN_MIN * (nb + rng.random()))


def traverse(m: tm.Model, edges, t_start: float, X: np.ndarray, rng: np.random.Generator,
             speed: float = 1.0, hold: bool = True):
    """Drive one vehicle along a list of edges from minute t_start through a day's V/C X.

    Each link takes its free-flow time (divided by ``speed``) times the BPR factor at the link's
    load in the 15 minutes the vehicle reaches it, with the load capped at 1.5 as in
    traffic_model.delay_minutes. Queues follow run_day's carry-over: in its first 15 minutes the
    trip's worst link has load x; with probability CARRY x (1 - 1/x) the vehicle does not get
    through it in that bin, waits at that link and leaves at a random minute of the next bin, and
    may be held again with the same rule there (at most MAX_HOLD_BINS).

    Returns (minute it enters each edge plus the arrival minute, the hold as (edge position,
    minute it reached the queue, minute it left) or None, extra seconds per edge over free flow).
    """
    n = len(edges)
    times = np.empty(n + 1)
    extra = np.zeros(n)
    tau = float(t_start)
    held_at, rec = None, None
    if hold and n:
        xp = X[bin_of(tau), edges]
        k = int(np.argmax(xp))
        xb = float(xp[k])
        if xb > 1.0 and rng.random() < tm.CARRY * (1.0 - 1.0 / xb):
            held_at = k
    for i, e in enumerate(edges):
        if i == held_at:
            arrive = tau
            tau = wait_in_queue(X, edges[i:], tau, rng)
            extra[i] += (tau - arrive) * 60.0
            rec = (i, arrive, tau)
        times[i] = tau
        x = min(float(X[bin_of(tau), e]), 1.5)
        ff = m.t0[e] / speed
        run = ff * (1.0 + 0.15 * x**4)
        extra[i] += run - ff
        tau += run / 60.0
    times[n] = tau
    return times, rec, extra
