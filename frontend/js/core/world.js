// The simulation loop shared by every view: spawn passengers from ship plans, move them along the
// walking graph with density-dependent speed, let them dwell at venues, ask the policy where next.

import { Graph, weidmannSpeed } from "./graph.js";
import { PERSONAS, HeuristicPolicy } from "./policy.js";
import { Rng } from "./rng.js";

export class World {
  constructor({
    graph = new Graph(),
    plan = [],
    policy = new HeuristicPolicy(),
    seed = 26,
    start = 6 * 3600,
    end = 20 * 3600,
    peoplePerAgent = 4,
    congestionRouting = false,
    weather = "dry",
    meta = {},
  } = {}) {
    this.graph = graph;
    this.plan = [...plan].sort((a, b) => a.t - b.t);
    this.policy = policy;
    this.seed = seed;
    this.start = start;
    this.end = end;
    this.t = start;
    this.ppa = peoplePerAgent;
    this.congestionRouting = congestionRouting;
    this.weather = weather;
    this.meta = meta;
    this.policyRng = new Rng(seed * 7 + 1);
    this.pi = 0;
    this.nextId = 0;
    this.agents = [];
    this.finished = [];
    this.listeners = new Set();
    for (const e of graph.edges) {
      e.count = 0;
      e.flowAB = e.flowBA = e.passAB = e.passBA = 0;
    }

    const minutes = Math.ceil((end - start) / 60) + 1;
    this.minutes = minutes;
    this.occupancy = new Map();
    this.venueStats = new Map();
    for (const v of graph.venues) {
      this.occupancy.set(v.id, 0);
      this.venueStats.set(v.id, {
        arrivals: 0,
        turnedAway: 0,
        revenue: 0,
        lostRevenue: 0,
        peak: 0,
        series: new Float32Array(minutes),
      });
    }
    this.series = {
      walking: new Float32Array(minutes),
      dwelling: new Float32Array(minutes),
    };
    this.totals = { spawned: 0, arrived: 0, late: 0, decisions: 0 };
    this.lastMinute = -1;
  }

  on(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit(type, payload) {
    for (const fn of this.listeners) fn(type, payload);
  }

  get done() {
    return this.t >= this.end;
  }

  get minuteIndex() {
    return Math.min(this.minutes - 1, Math.max(0, Math.floor((this.t - this.start) / 60)));
  }

  // Advance by dt seconds of simulated time, in sub-steps short enough that nobody skips an edge.
  advance(dt) {
    let left = Math.min(dt, this.end - this.t);
    while (left > 1e-6) {
      const h = Math.min(left, 4);
      this.tick(h);
      left -= h;
    }
  }

  tick(dt) {
    this.t += dt;
    while (this.pi < this.plan.length && this.plan[this.pi].t <= this.t) {
      const spec = this.plan[this.pi++];
      if (spec.t >= this.start) this.spawn(spec);
    }

    const alive = [];
    for (const a of this.agents) {
      a.px = a.x;
      a.py = a.y;
      if (a.state === "walk") this.walk(a, dt);
      else if (a.state === "dwell" && this.t >= a.dwellUntil) this.leaveVenue(a);
      if (a.state !== "done") alive.push(a);
    }
    this.agents = alive;

    const k = 1 - Math.exp(-dt / 240);
    const perMin = (this.ppa * 60) / dt;
    for (const e of this.graph.edges) {
      e.flowAB += (e.passAB * perMin - e.flowAB) * k;
      e.flowBA += (e.passBA * perMin - e.flowBA) * k;
      e.passAB = e.passBA = 0;
    }

    const m = this.minuteIndex;
    if (m !== this.lastMinute) {
      this.lastMinute = m;
      let walking = 0;
      let dwelling = 0;
      for (const a of this.agents) a.state === "walk" ? walking++ : dwelling++;
      this.series.walking[m] = walking * this.ppa;
      this.series.dwelling[m] = dwelling * this.ppa;
      for (const [id, occ] of this.occupancy) {
        const s = this.venueStats.get(id);
        s.series[m] = occ;
        s.peak = Math.max(s.peak, occ);
      }
      this.emit("minute", m);
    }
  }

  spawn(spec) {
    const p = PERSONAS[spec.persona];
    const id = spec.id ?? this.nextId;
    this.nextId = Math.max(this.nextId, id) + 1;
    const rng = new Rng(this.seed * 100003 + id);
    const origin = this.graph.node(spec.origin);
    const a = {
      id,
      traceId: spec.traceId,
      persona: spec.persona,
      ship: spec.ship,
      origin: spec.origin,
      sink: spec.sink,
      spawnT: this.t,
      deadline: spec.deadline,
      budget: spec.deadline - spec.t,
      speed: p.speed * rng.uniform(0.85, 1.15),
      lane: rng.uniform(-1, 1),
      orbit: rng.uniform(0, Math.PI * 2),
      rng,
      at: spec.origin,
      state: "idle",
      visits: [],
      avoid: new Set(),
      history: [],
      decisionCount: 0,
      x: origin.x,
      y: origin.y,
      px: origin.x,
      py: origin.y,
    };
    this.agents.push(a);
    this.totals.spawned++;
    this.decide(a);
    return a;
  }

  decide(a) {
    const ctx = {
      graph: this.graph,
      now: this.t,
      occupancy: this.occupancy,
      rng: this.policyRng,
      weather: this.weather,
      world: this,
    };
    const d = this.policy.decide(a, ctx);
    this.totals.decisions++;
    a.decisionCount++;
    const top = [...d.probs].sort((x, y) => y[1] - x[1]).slice(0, 8);
    a.history.push({ t: this.t, at: a.at, choice: d.choice, probs: top, dwell: d.dwell });
    a.pendingDwell = d.dwell;
    this.emit("decision", { agent: a, decision: d });

    if (d.choice === a.at) return this.arrive(a);
    const weight = this.congestionRouting
      ? (e) => 1 + 3 * Math.min(2, this.graph.density(e, this.ppa))
      : null;
    const path = this.graph.path(a.at, d.choice, weight);
    if (!path) {
      // Destination cut off (an operator closed the only way there): count it and drop them.
      a.state = "done";
      this.emit("stranded", a);
      return;
    }
    a.target = d.choice;
    a.path = path;
    a.si = 0;
    a.pos = 0;
    a.state = "walk";
    this.enterEdge(a);
  }

  enterEdge(a) {
    const seg = a.path.segs[a.si];
    seg.edge.count++;
    if (seg.from === seg.edge.a) seg.edge.passAB++;
    else seg.edge.passBA++;
  }

  walk(a, dt) {
    let seg = a.path.segs[a.si];
    let move = weidmannSpeed(a.speed, this.graph.density(seg.edge, this.ppa)) * dt;
    while (move > 0) {
      const room = seg.edge.len - a.pos;
      if (move < room) {
        a.pos += move;
        break;
      }
      move -= room;
      seg.edge.count--;
      a.si++;
      a.pos = 0;
      if (a.si >= a.path.segs.length) {
        const end = this.graph.node(seg.to);
        a.x = end.x;
        a.y = end.y;
        a.at = seg.to;
        this.arrive(a);
        return;
      }
      seg = a.path.segs[a.si];
      this.enterEdge(a);
    }
    const f = this.graph.node(seg.from);
    const t = this.graph.node(seg.to);
    const r = a.pos / seg.edge.len;
    a.x = f.x + (t.x - f.x) * r;
    a.y = f.y + (t.y - f.y) * r;
    a.seg = seg;
    a.frac = r;
  }

  arrive(a) {
    const node = this.graph.node(a.at);
    if (a.at === a.sink) {
      a.state = "done";
      if (this.t > a.deadline + 60) {
        a.late = true;
        this.totals.late++;
      }
      this.totals.arrived++;
      this.finished.push(a);
      this.emit("finished", a);
      return;
    }
    if (node.kind !== "venue") return this.decide(a);

    const s = this.venueStats.get(node.id);
    const occ = this.occupancy.get(node.id);
    if (occ + this.ppa > node.capacity) {
      s.turnedAway += this.ppa;
      s.lostRevenue += node.spend * this.ppa;
      a.avoid.add(node.id);
      this.emit("turnedAway", { agent: a, venue: node });
      return this.decide(a);
    }
    this.occupancy.set(node.id, occ + this.ppa);
    s.arrivals += this.ppa;
    s.revenue += node.spend * this.ppa;
    a.visits.push(node.id);
    a.state = "dwell";
    a.seg = null;
    const p = PERSONAS[a.persona];
    let dwell = (a.pendingDwell ?? a.rng.lognormal(node.dwell * p.dwellMul, 0.35)) * 60;
    const back = this.graph.walkMinutes(node.id, a.sink, a.speed) * 60;
    dwell = Math.max(5 * 60, Math.min(dwell, a.deadline - this.t - back));
    a.dwellUntil = this.t + dwell;
    a.x = node.x;
    a.y = node.y;
  }

  leaveVenue(a) {
    this.occupancy.set(a.at, this.occupancy.get(a.at) - this.ppa);
    this.decide(a);
  }

  // Everything the backend needs to replay or score this run. Probabilities are the top options
  // at each decision, as given by whichever policy made it.
  exportTrace() {
    const all = [...this.finished, ...this.agents];
    return {
      meta: {
        format: "sotonship26.trace/1",
        policy: this.policy.name,
        seed: this.seed,
        generated: new Date().toISOString(),
        synthetic: true,
        peoplePerAgent: this.ppa,
        start: this.start,
        end: this.end,
        ...this.meta,
      },
      agents: all
        .sort((x, y) => x.id - y.id)
        .map((a) => ({
          id: a.id,
          persona: a.persona,
          ship: a.ship,
          origin: a.origin,
          sink: a.sink,
          spawn: Math.round(a.spawnT),
          deadline: Math.round(a.deadline),
          decisions: a.history.map((h) => ({
            t: Math.round(h.t),
            at: h.at,
            choice: h.choice,
            probs: Object.fromEntries(h.probs.map(([id, p]) => [id, +p.toFixed(4)])),
          })),
        })),
    };
  }
}

// Turn a trace back into a spawn plan, so a recorded episode can be watched again.
export function planFromTrace(trace) {
  return trace.agents
    .map((a) => ({
      id: a.id,
      traceId: a.id,
      t: a.spawn,
      origin: a.origin,
      persona: a.persona,
      sink: a.sink,
      deadline: a.deadline,
      ship: a.ship,
    }))
    .sort((x, y) => x.t - y.t);
}
