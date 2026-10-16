// The walking graph: nodes in local metres, edges with length and footway width, shortest paths.

import { NODES, EDGES, WIDTHS, META, LAND, CHANNEL, VIEW } from "../../data/southampton.js";

const M_PER_DEG_LAT = 110540;

// Local equirectangular projection around META.origin: x east, y north, metres. Good to well under
// a metre across a 4 km city centre, which is all the visuals need.
export function project(lat, lon, origin = META.origin) {
  const k = 111320 * Math.cos((origin.lat * Math.PI) / 180);
  return { x: (lon - origin.lon) * k, y: (lat - origin.lat) * M_PER_DEG_LAT };
}

// Weidmann (1993) speed-density relation for pedestrians: free speed v0 at low density, falling to
// zero at jam density (5.4 p/m2). Floors at 0.08 m/s so a jammed crowd still creeps forward.
export function weidmannSpeed(v0, density) {
  if (density <= 0.05) return v0;
  const v = v0 * (1 - Math.exp(-1.913 * (1 / density - 1 / 5.4)));
  return Math.max(0.08, v);
}

// Fruin walkway level of service by density (p/m2).
export const LOS = [
  { grade: "A", max: 0.31 },
  { grade: "B", max: 0.43 },
  { grade: "C", max: 0.72 },
  { grade: "D", max: 1.08 },
  { grade: "E", max: 2.17 },
  { grade: "F", max: Infinity },
];

export function losGrade(density) {
  return LOS.find((l) => density <= l.max).grade;
}

export class Graph {
  constructor({ nodes = NODES, edges = EDGES, widths = WIDTHS } = {}) {
    this.nodes = new Map();
    this.edges = [];
    this.adj = new Map();
    for (const n of nodes) {
      const { x, y } = project(n.lat, n.lon);
      this.nodes.set(n.id, { ...n, x, y });
      this.adj.set(n.id, []);
    }
    for (const [a, b, cls, w] of edges) {
      const na = this.nodes.get(a);
      const nb = this.nodes.get(b);
      if (!na || !nb) throw new Error(`Edge ${a}-${b} names an unknown node`);
      const len = Math.max(8, Math.hypot(nb.x - na.x, nb.y - na.y));
      const edge = {
        id: this.edges.length,
        a,
        b,
        cls,
        len,
        width: w ?? widths[cls] ?? 3,
        count: 0, // agents on the edge now
        flowAB: 0, // smoothed people/min in each direction, for the flow arrows
        flowBA: 0,
        passAB: 0, // people entering this tick, folded into the smoothed flow
        passBA: 0,
        cost: 1, // multiplier the policy or an operator can apply (steering / closure)
      };
      this.edges.push(edge);
      this.adj.get(a).push({ edge, to: b });
      this.adj.get(b).push({ edge, to: a });
    }
    this.land = LAND.map((ring) => ring.map(([lat, lon]) => project(lat, lon)));
    this.channel = CHANNEL.map(([lat, lon]) => project(lat, lon));
    const lo = project(VIEW.lat[0], VIEW.lon[0]);
    const hi = project(VIEW.lat[1], VIEW.lon[1]);
    this.bounds = { minX: lo.x, minY: lo.y, maxX: hi.x, maxY: hi.y };
    this.meta = META;
    this._cache = new Map();
  }

  node(id) {
    return this.nodes.get(id);
  }

  byKind(kind) {
    return [...this.nodes.values()].filter((n) => n.kind === kind);
  }

  get venues() {
    return this.byKind("venue");
  }

  density(edge, peoplePerAgent = 1) {
    return (edge.count * peoplePerAgent) / (edge.len * edge.width);
  }

  // Dijkstra over walking time. Terminals, venues and exits are endpoints only: nobody walks
  // through a restaurant to reach the station. `weight(edge)` can add congestion or steering.
  path(from, to, weight = null) {
    const key = `${from}>${to}`;
    if (!weight && this._cache.has(key)) return this._cache.get(key);
    const { dist, prev } = this.dijkstra(from, weight, to, true);
    if (!dist.has(to)) return null;
    const segs = [];
    let cur = to;
    while (cur !== from) {
      const p = prev.get(cur);
      segs.unshift({ edge: p.edge, from: p.from, to: cur });
      cur = p.from;
    }
    const result = { segs, length: segs.reduce((s, g) => s + g.edge.len, 0) };
    if (!weight) this._cache.set(key, result);
    return result;
  }

  // Binary-heap Dijkstra, fast enough for a full OSM walking network (thousands of nodes).
  // With `endpointsOnly`, terminals, venues and exits are never walked through.
  dijkstra(from, weight = null, stopAt = null, endpointsOnly = true) {
    const dist = new Map([[from, 0]]);
    const prev = new Map();
    const done = new Set();
    const heap = new MinHeap();
    heap.push(0, from);
    while (heap.size) {
      const [d0, u] = heap.pop();
      if (done.has(u) || d0 > dist.get(u)) continue;
      done.add(u);
      if (u === stopAt) break;
      const kind = this.nodes.get(u).kind;
      if (endpointsOnly && u !== from && (kind === "venue" || kind === "exit" || kind === "terminal")) continue;
      for (const { edge, to: v } of this.adj.get(u)) {
        if (done.has(v) || edge.cost >= 1e6) continue;
        const d = d0 + edge.len * edge.cost * (weight ? weight(edge) : 1);
        if (d < (dist.get(v) ?? Infinity)) {
          dist.set(v, d);
          prev.set(v, { edge, from: u });
          heap.push(d, v);
        }
      }
    }
    return { dist, prev };
  }

  invalidatePaths() {
    this._cache.clear();
  }

  // Walking minutes between two nodes at a given speed (m/s).
  walkMinutes(from, to, speed = 1.3) {
    const p = this.path(from, to);
    return p ? p.length / speed / 60 : Infinity;
  }

  // Shortest-path distance from one node to every node; drives the isochrone rings.
  distancesFrom(from) {
    return this.dijkstra(from, null, null, true).dist;
  }
}

class MinHeap {
  constructor() {
    this.k = [];
    this.v = [];
  }

  get size() {
    return this.k.length;
  }

  push(key, val) {
    const k = this.k;
    const v = this.v;
    let i = k.length;
    k.push(key);
    v.push(val);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (k[p] <= key) break;
      k[i] = k[p];
      v[i] = v[p];
      i = p;
    }
    k[i] = key;
    v[i] = val;
  }

  pop() {
    const k = this.k;
    const v = this.v;
    const top = [k[0], v[0]];
    const lk = k.pop();
    const lv = v.pop();
    if (k.length) {
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        if (l >= k.length) break;
        const c = l + 1 < k.length && k[l + 1] < k[l] ? l + 1 : l;
        if (k[c] >= lk) break;
        k[i] = k[c];
        v[i] = v[c];
        i = c;
      }
      k[i] = lk;
      v[i] = lv;
    }
    return top;
  }
}
