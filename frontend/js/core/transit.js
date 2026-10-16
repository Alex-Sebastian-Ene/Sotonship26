// Buses: timetabled vehicles on fixed lines, late by an amount drawn from a lateness profile, and
// passengers who decide to ride when a bus beats walking.
//
// Each departure samples a lateness L (minutes) from DELAY_PROFILE[line][hour]. 40% of it is a late
// start and the rest is lost en route as a slower running speed, so a late bus is late at every
// stop and gets later along the line, as real ones do. Dwell time grows with people getting on and
// off, so a crowded bus loses time on top of that.

import { BUS_LINES, BUS_META, DELAY_PROFILE, DEFAULT_DELAY } from "../../data/buses.js";
import { hhmm } from "./schedule.js";
import { Rng } from "./rng.js";

const SCHED_SPEED = 4.5; // m/s the timetable assumes between stops, traffic included
const SCHED_DWELL = 25; // s the timetable allows at each stop
const DRIVE_SPEED = 5.2; // m/s an unhindered bus actually manages
const BUS_CAPACITY = 80; // people
const WALK_LIMIT_MIN = 9; // furthest anyone walks to or from a stop
const PATIENCE_MIN = 14; // half of this past one headway, people give up and walk

export { BUS_META };

// Buses keep to roads: no footway-only edges, no driving into the dock estate.
const busWeight = (e) => (e.cls === "door" || e.cls === "dock" || e.cls === "gate" ? Infinity : 1);

export class Transit {
  constructor(world, { lines = BUS_LINES, profile = DELAY_PROFILE, extraDelayMin = 0, seed = 26 } = {}) {
    this.world = world;
    this.graph = world.graph;
    this.profile = profile;
    this.extraDelayMin = extraDelayMin;
    this.rng = new Rng(seed * 31 + 7);
    this.lines = [];
    for (const def of lines) {
      const stops = def.stops.filter((id) => this.graph.node(id));
      if (stops.length < 2) continue;
      const dirs = [stops, [...stops].reverse()].map((order) => {
        const legs = [];
        const offsets = [0];
        let ok = true;
        for (let i = 1; i < order.length; i++) {
          const p = this.graph.path(order[i - 1], order[i], busWeight);
          if (!p) ok = false;
          legs.push(p);
          offsets.push(offsets[i - 1] + (p ? p.length / SCHED_SPEED : 0) + SCHED_DWELL);
        }
        return ok ? { order, legs, offsets, index: new Map(order.map((id, i) => [id, i])) } : null;
      });
      if (dirs.some((d) => !d)) continue; // a closure cut the line; drop it rather than teleport
      this.lines.push({ ...def, dirs, first: hhmm(def.first), last: hhmm(def.last), headway: def.headwayMin * 60 });
    }
    this.byId = new Map(this.lines.map((l) => [l.id, l]));
    this.stops = new Set(this.lines.flatMap((l) => l.dirs[0].order));

    // The day's timetable: every departure from either end.
    this.departures = [];
    for (const line of this.lines) {
      for (let dir = 0; dir < 2; dir++) {
        for (let t = line.first; t <= line.last; t += line.headway) {
          this.departures.push({ line, dir, sched: t + (dir ? line.headway / 2 : 0) });
        }
      }
    }
    this.departures.sort((a, b) => a.sched - b.sched);
    this.di = 0;
    this.buses = [];
    this.queues = new Map([...this.stops].map((s) => [s, []]));
    this.nextBus = 0;
    this.records = []; // { t, line, stop, delayMin } at every stop arrival
    const n = world.minutes;
    this.series = { waiting: new Float32Array(n), riding: new Float32Array(n), delay: new Float32Array(n) };
    this.totals = { boardings: 0, gaveUp: 0, leftBehind: 0 };
  }

  delayFor(lineId, t) {
    const hour = Math.floor(t / 3600);
    return this.profile[lineId]?.[hour] ?? DEFAULT_DELAY;
  }

  sampleLateness(lineId, t) {
    const { mean, p90 } = this.delayFor(lineId, t);
    const sd = Math.max(0.5, (p90 - mean) / 1.2816);
    // Right-skewed: lateness piles up, earliness is capped at two minutes.
    const z = this.rng.normal();
    const L = mean + sd * (z > 0 ? z * 1.25 : z * 0.6) + this.extraDelayMin;
    return Math.max(-2, Math.min(45, L));
  }

  // ---- passengers -------------------------------------------------------------------------

  // Best bus journey from `from` to `to`, or null when walking is as good. Passengers compare a
  // timetable estimate (half a headway's wait), not the live delay: most do not check an app.
  plan(agent, from, to) {
    const g = this.graph;
    const now = this.world.t;
    const walkDirect = g.walkMinutes(from, to, agent.speed);
    if (walkDirect < 8) return null;
    const luggage = agent.persona === "rail" || agent.persona === "embark";
    let best = null;
    for (const line of this.lines) {
      if (now < line.first - 600 || now > line.last + 1800) continue;
      for (let dir = 0; dir < 2; dir++) {
        const d = line.dirs[dir];
        for (const [i, board] of d.order.entries()) {
          const wIn = g.walkMinutes(from, board, agent.speed);
          if (wIn > WALK_LIMIT_MIN) continue;
          for (let j = i + 1; j < d.order.length; j++) {
            const alight = d.order[j];
            const wOut = alight === to ? 0 : g.walkMinutes(alight, to, agent.speed);
            if (wOut > WALK_LIMIT_MIN) continue;
            const ride = (d.offsets[j] - d.offsets[i]) / 60;
            const cost = wIn + line.headwayMin / 2 + ride + wOut;
            if (!best || cost < best.cost) best = { line: line.id, dir, board, alight, cost, ride, wIn, wOut };
          }
        }
      }
    }
    if (!best) return null;
    return best.cost < walkDirect * (luggage ? 0.95 : 0.7) ? best : null;
  }

  wait(agent) {
    agent.state = "wait";
    agent.waitStart = this.world.t;
    agent.seg = null;
    agent.queuePos = this.queues.get(agent.at).length;
    this.queues.get(agent.at).push(agent);
  }

  // ---- vehicles ---------------------------------------------------------------------------

  tick(dt) {
    const w = this.world;
    while (this.di < this.departures.length && this.departures[this.di].sched <= w.t + 3600) {
      const dep = this.departures[this.di++];
      const L = this.sampleLateness(dep.line.id, dep.sched);
      const d = dep.line.dirs[dep.dir];
      const run = d.offsets[d.offsets.length - 1];
      const enRoute = 0.6 * L * 60;
      dep.bus = {
        id: this.nextBus++,
        line: dep.line,
        dir: dep.dir,
        d,
        sched: dep.sched,
        lateness: L,
        startAt: dep.sched + 0.4 * L * 60,
        speedFactor: Math.max(0.35, Math.min(1.15, run / Math.max(60, run + enRoute))),
        k: 0, // index of the stop it is at or heading for
        si: 0,
        pos: 0,
        state: "pending",
        riders: [],
        delayNow: 0.4 * L,
        x: 0,
        y: 0,
        hx: 1,
        hy: 0,
      };
      this.pendingBuses = this.pendingBuses || [];
      this.pendingBuses.push(dep.bus);
    }
    if (this.pendingBuses?.length) {
      const still = [];
      for (const b of this.pendingBuses) {
        if (b.startAt <= w.t) {
          if (b.startAt + 1800 > w.start && b.startAt < w.end) this.startBus(b);
        } else still.push(b);
      }
      this.pendingBuses = still;
    }

    const alive = [];
    for (const b of this.buses) {
      if (b.state === "dwell") {
        if (w.t >= b.dwellUntil) this.depart(b);
      } else if (b.state === "drive") this.drive(b, dt);
      if (b.state !== "done") alive.push(b);
    }
    this.buses = alive;

    // Waiting passengers give up when they have waited too long or would now miss their deadline.
    for (const [stop, q] of this.queues) {
      if (!q.length) continue;
      const keep = [];
      for (const a of q) {
        if (a.state !== "wait") continue;
        const waited = (w.t - a.waitStart) / 60;
        const walkOn = this.graph.walkMinutes(stop, a.trip.target, a.speed);
        const patience = this.byId.get(a.trip.line).headwayMin + PATIENCE_MIN / 2;
        if (waited > patience || (a.deadline - w.t) / 60 < walkOn + 3) {
          this.totals.gaveUp++;
          a.trip = null;
          w.walkTo(a, a.target);
          w.emit("gaveUp", a);
        } else keep.push(a);
      }
      keep.forEach((a, i) => (a.queuePos = i));
      this.queues.set(stop, keep);
    }
  }

  startBus(b) {
    const first = this.graph.node(b.d.order[0]);
    b.x = first.x;
    b.y = first.y;
    b.state = "dwell";
    b.dwellUntil = this.world.t;
    this.buses.push(b);
    this.atStop(b);
  }

  drive(b, dt) {
    const leg = b.d.legs[b.k - 1];
    let move = DRIVE_SPEED * b.speedFactor * dt;
    let seg = leg.segs[b.si];
    while (move > 0) {
      const room = seg.edge.len - b.pos;
      if (move < room) {
        b.pos += move;
        break;
      }
      move -= room;
      b.si++;
      b.pos = 0;
      if (b.si >= leg.segs.length) {
        const n = this.graph.node(seg.to);
        b.x = n.x;
        b.y = n.y;
        b.state = "dwell";
        this.atStop(b);
        return;
      }
      seg = leg.segs[b.si];
    }
    const f = this.graph.node(seg.from);
    const t = this.graph.node(seg.to);
    const r = b.pos / seg.edge.len;
    b.x = f.x + (t.x - f.x) * r;
    b.y = f.y + (t.y - f.y) * r;
    const len = Math.hypot(t.x - f.x, t.y - f.y) || 1;
    b.hx = (t.x - f.x) / len;
    b.hy = (t.y - f.y) / len;
  }

  atStop(b) {
    const w = this.world;
    const stop = b.d.order[b.k];
    const delayMin = (w.t - (b.sched + b.d.offsets[b.k])) / 60;
    b.delayNow = delayMin;
    if (w.t >= w.start) this.records.push({ t: w.t, line: b.line.id, stop, delayMin, bus: b.id });

    let moved = 0;
    const off = [];
    const stay = [];
    for (const a of b.riders) (a.trip.alight === stop ? off : stay).push(a);
    b.riders = stay;
    for (const a of off) {
      moved++;
      a.at = stop;
      a.trip = null;
      const n = this.graph.node(stop);
      a.x = n.x;
      a.y = n.y;
      if (a.target === stop) w.arrive(a);
      else w.walkTo(a, a.target);
    }

    const last = b.k === b.d.order.length - 1;
    if (!last) {
      const cap = Math.floor(BUS_CAPACITY / w.ppa);
      const q = this.queues.get(stop);
      const left = [];
      for (const a of q) {
        const ok =
          a.state === "wait" &&
          a.trip.line === b.line.id &&
          a.trip.dir === b.dir &&
          b.d.index.get(a.trip.alight) > b.k;
        if (ok && b.riders.length < cap) {
          a.state = "ride";
          a.bus = b;
          b.riders.push(a);
          moved++;
          this.totals.boardings++;
        } else {
          if (ok) this.totals.leftBehind++;
          left.push(a);
        }
      }
      left.forEach((a, i) => (a.queuePos = i));
      this.queues.set(stop, left);
    }
    b.dwellUntil = w.t + 15 + 2 * moved * w.ppa;
    if (last) b.state = "done";
  }

  depart(b) {
    b.k++;
    b.si = 0;
    b.pos = 0;
    b.state = "drive";
  }

  sample(m) {
    let waiting = 0;
    for (const q of this.queues.values()) waiting += q.length;
    let riding = 0;
    let delay = 0;
    for (const b of this.buses) {
      riding += b.riders.length;
      delay += b.delayNow;
    }
    this.series.waiting[m] = waiting * this.world.ppa;
    this.series.riding[m] = riding * this.world.ppa;
    this.series.delay[m] = this.buses.length ? delay / this.buses.length : 0;
  }

  // Next departures from a stop, the way a real-time board shows them.
  board(stop, horizonMin = 45) {
    const w = this.world;
    const rows = [];
    for (const line of this.lines) {
      for (let dir = 0; dir < 2; dir++) {
        const d = line.dirs[dir];
        const k = d.index.get(stop);
        if (k === undefined || k === d.order.length - 1) continue;
        for (let t = line.first + (dir ? line.headway / 2 : 0); t <= line.last; t += line.headway) {
          const due = t + d.offsets[k];
          if (due < w.t - 600 || due > w.t + horizonMin * 60) continue;
          const bus = this.findBus(line.id, dir, t);
          if (bus && bus.k > k) continue; // already gone
          const delay = bus ? Math.max(0, bus.delayNow) : 0;
          const expected = due + delay * 60;
          if (expected < w.t - 30) continue;
          rows.push({
            line: line.id,
            dest: dir ? line.from : line.to,
            due,
            expected,
            tracked: !!bus,
            delay,
          });
        }
      }
    }
    return rows.sort((a, b) => a.expected - b.expected).slice(0, 8);
  }

  findBus(lineId, dir, sched) {
    for (const b of this.buses) if (b.line.id === lineId && b.dir === dir && b.sched === sched) return b;
    return null;
  }
}
