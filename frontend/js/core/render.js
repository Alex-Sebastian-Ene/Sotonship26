// Canvas renderer for the walking graph and its passengers. One renderer per <canvas>; every
// simulation page builds on it. Colours come from CSS custom properties so both themes work.

import { PERSONAS, PERSONA_ORDER } from "./policy.js";
import { losGrade } from "./graph.js";

const TAU = Math.PI * 2;
const fmtInt = (n) => Math.round(n).toLocaleString("en-GB");

function cssVar(name, el = document.documentElement) {
  return getComputedStyle(el).getPropertyValue(name).trim();
}

export function readPalette() {
  const p = {};
  for (const k of [
    "bg", "surface", "ink", "ink-2", "muted", "hairline", "accent",
    "map-water", "map-shallow", "map-land", "map-coast", "map-street", "map-dock", "map-channel",
    "map-halo", "map-terminal", "map-heat",
    "good", "warning", "serious", "critical",
    "seq-1", "seq-2", "seq-3", "seq-4", "seq-5", "seq-6",
  ]) p[k] = cssVar(`--${k}`);
  p.persona = {};
  for (const id of PERSONA_ORDER) p.persona[id] = cssVar(`--p-${id}`);
  p.dark = cssVar("color-scheme").includes("dark");
  return p;
}

export function stressColor(pal, fill) {
  if (fill >= 1) return pal.critical;
  if (fill >= 0.85) return pal.serious;
  if (fill >= 0.6) return pal.warning;
  return pal.good;
}

const LOS_KEY = { A: null, B: "good", C: "good", D: "warning", E: "serious", F: "critical" };

export class Renderer {
  constructor(canvas, graph, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.graph = graph;
    this.opts = {
      mode: "flat", // flat | iso
      labels: true,
      flows: true,
      loads: true,
      heat: false,
      trails: true,
      agents: true,
      junctions: false,
      isochrone: null, // node id to draw walking-time bands from
      skyline: false,
      agentSize: 2.2,
      colorBy: "persona", // persona | state
      ...opts,
    };
    this.cam = { zoom: 1, panX: 0, panY: 0 };
    this.pal = readPalette();
    this.static = document.createElement("canvas");
    this.heatCanvas = document.createElement("canvas");
    this.staticDirty = true;
    this.listeners = {};
    this.time = 0;
    this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas);
    const themeChanged = () => {
      this.pal = readPalette();
      this.staticDirty = true;
    };
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", themeChanged);
    new MutationObserver(themeChanged).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    this.bindPointer();
  }

  on(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  emit(type, payload) {
    for (const fn of this.listeners[type] || []) fn(payload);
  }

  set(opts) {
    const staticKeys = ["mode", "isochrone", "junctions"];
    if (staticKeys.some((k) => k in opts && opts[k] !== this.opts[k])) this.staticDirty = true;
    Object.assign(this.opts, opts);
    if ("mode" in opts) this.fit();
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.w = Math.max(50, r.width);
    this.h = Math.max(50, r.height);
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
    this.static.width = this.canvas.width;
    this.static.height = this.canvas.height;
    this.heatCanvas.width = Math.ceil(this.w / 3);
    this.heatCanvas.height = Math.ceil(this.h / 3);
    this.fit();
  }

  // ---- projection ----------------------------------------------------------------------------

  fit() {
    const b = this.graph.bounds;
    const iso = this.opts.mode === "iso";
    this.theta = iso ? (-32 * Math.PI) / 180 : 0;
    this.squash = iso ? 0.52 : 1;
    const corners = [
      [b.minX, b.minY], [b.maxX, b.minY], [b.minX, b.maxY], [b.maxX, b.maxY],
    ].map(([x, y]) => this.rot(x, y));
    const xs = corners.map((c) => c[0]);
    const ys = corners.map((c) => c[1]);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    const pad = 0.92;
    this.base = Math.min((this.w * pad) / spanX, (this.h * pad) / spanY);
    if (iso) this.base *= 1.25;
    this.mid = [(Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2];
    this.staticDirty = true;
    this.heatClear = true;
  }

  rot(x, y) {
    const c = Math.cos(this.theta);
    const s = Math.sin(this.theta);
    return [x * c - y * s, (x * s + y * c) * this.squash];
  }

  get scale() {
    return this.base * this.cam.zoom;
  }

  // World metres (+ optional height in px) to CSS pixels.
  toScreen(x, y, z = 0) {
    const [rx, ry] = this.rot(x, y);
    const s = this.scale;
    return [
      this.w / 2 + (rx - this.mid[0]) * s + this.cam.panX,
      this.h / 2 - (ry - this.mid[1]) * s + this.cam.panY - z,
    ];
  }

  centerOn(x, y, ease = 1) {
    const [sx, sy] = this.toScreen(x, y);
    this.cam.panX += (this.w / 2 - sx) * ease;
    this.cam.panY += (this.h / 2 - sy) * ease;
    if (ease >= 1) this.staticDirty = true;
    else this.staticDirty = true;
  }

  // ---- input ---------------------------------------------------------------------------------

  bindPointer() {
    const c = this.canvas;
    const pts = new Map();
    let moved = 0;
    let pinch = null;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, [e.offsetX, e.offsetY]);
      moved = 0;
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), zoom: this.cam.zoom };
      }
    });
    c.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) {
        this.emit("hover", this.pick(e.offsetX, e.offsetY, e));
        return;
      }
      const [px, py] = pts.get(e.pointerId);
      const dx = e.offsetX - px;
      const dy = e.offsetY - py;
      pts.set(e.pointerId, [e.offsetX, e.offsetY]);
      moved += Math.abs(dx) + Math.abs(dy);
      if (pts.size === 2 && pinch) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        this.zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (pinch.zoom * d) / pinch.d / this.cam.zoom);
      } else if (pts.size === 1) {
        this.cam.panX += dx;
        this.cam.panY += dy;
        this.staticDirty = true;
        this.heatClear = true;
        this.emit("pan");
      }
    });
    const end = (e) => {
      if (pts.has(e.pointerId) && moved < 6 && pts.size === 1) {
        this.emit("pick", this.pick(e.offsetX, e.offsetY, e));
      }
      pts.delete(e.pointerId);
      if (pts.size < 2) pinch = null;
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", () => this.emit("hover", null));
    c.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.zoomAt(e.offsetX, e.offsetY, Math.exp(-e.deltaY * 0.0015));
      },
      { passive: false },
    );
  }

  zoomAt(sx, sy, factor) {
    const z = Math.min(8, Math.max(0.6, this.cam.zoom * factor));
    const f = z / this.cam.zoom;
    this.cam.panX = sx - this.w / 2 - (sx - this.w / 2 - this.cam.panX) * f;
    this.cam.panY = sy - this.h / 2 - (sy - this.h / 2 - this.cam.panY) * f;
    this.cam.zoom = z;
    this.staticDirty = true;
    this.heatClear = true;
    this.emit("pan");
  }

  resetView() {
    this.cam = { zoom: 1, panX: 0, panY: 0 };
    this.fit();
  }

  pick(sx, sy, e) {
    let best = null;
    let bd = 10;
    if (this.world && this.opts.agents) {
      for (const a of this.world.agents) {
        if (a.state === "ride") continue;
        const [ax, ay] = this.agentScreen(a);
        const d = Math.hypot(ax - sx, ay - sy);
        if (d < bd) {
          bd = d;
          best = { type: "agent", agent: a };
        }
      }
    }
    for (const b of this.world?.transit?.buses ?? []) {
      const [bx, by] = this.toScreen(b.x, b.y);
      const d = Math.hypot(bx - sx, by - sy);
      if (d < 12 && d < bd + 4) {
        bd = d;
        best = { type: "bus", bus: b };
      }
    }
    if (!best || bd > 5) {
      const stops = this.world?.transit?.stops;
      for (const n of this.graph.nodes.values()) {
        if (n.kind === "junction" && !stops?.has(n.id)) continue;
        const [nx, ny] = this.toScreen(n.x, n.y);
        const d = Math.hypot(nx - sx, ny - sy);
        if (d < 16 && d < bd + 6) {
          bd = d;
          best = { type: "node", node: n };
        }
      }
    }
    return best ? { ...best, sx, sy, clientX: e?.clientX, clientY: e?.clientY } : null;
  }

  // ---- drawing -------------------------------------------------------------------------------

  drawStatic() {
    const g = this.static.getContext("2d");
    const pal = this.pal;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.fillStyle = pal["map-water"];
    g.fillRect(0, 0, this.w, this.h);

    const ring = (pts) => {
      g.beginPath();
      pts.forEach((p, i) => {
        const [x, y] = this.toScreen(p.x, p.y);
        i ? g.lineTo(x, y) : g.moveTo(x, y);
      });
      g.closePath();
    };
    // Shallow band hugging the shore, as on an Admiralty chart, then the land itself.
    const s = this.scale;
    g.lineJoin = "round";
    for (const pts of this.graph.land) {
      ring(pts);
      g.strokeStyle = pal["map-shallow"];
      g.lineWidth = Math.max(6, 120 * s);
      g.stroke();
    }
    for (const pts of this.graph.land) {
      ring(pts);
      g.fillStyle = pal["map-land"];
      g.fill();
      g.strokeStyle = pal["map-coast"];
      g.lineWidth = 1;
      g.stroke();
    }

    // Dredged channel
    g.beginPath();
    this.graph.channel.forEach((p, i) => {
      const [x, y] = this.toScreen(p.x, p.y);
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    });
    g.setLineDash([6, 5]);
    g.strokeStyle = pal["map-channel"];
    g.lineWidth = 1.2;
    g.stroke();
    g.setLineDash([]);
    const c0 = this.graph.channel[2];
    const [lx, ly] = this.toScreen(c0.x, c0.y);
    g.font = `italic 10px ${cssVar("--font-data")}`;
    g.fillStyle = pal["map-channel"];
    g.fillText("Dredged channel", lx + 8, ly + 14);
    g.fillText("RIVER TEST", ...this.toScreen(-1450, 1150));
    g.fillText("RIVER ITCHEN", ...this.toScreen(1150, 900));

    // Iso: a soft drop shadow under land gives the plane some depth.
    if (this.opts.mode === "iso") {
      g.save();
      g.globalAlpha = 0.25;
      g.translate(0, 6);
      for (const pts of this.graph.land) {
        ring(pts);
        g.fillStyle = pal["map-coast"];
        g.fill();
      }
      g.restore();
      for (const pts of this.graph.land) {
        ring(pts);
        g.fillStyle = pal["map-land"];
        g.fill();
      }
    }

    // Isochrone bands or plain streets
    const iso = this.opts.isochrone ? this.graph.distancesFrom(this.opts.isochrone) : null;
    for (const e of this.graph.edges) {
      const [ax, ay] = this.toScreen(this.graph.node(e.a).x, this.graph.node(e.a).y);
      const [bx, by] = this.toScreen(this.graph.node(e.b).x, this.graph.node(e.b).y);
      g.beginPath();
      g.moveTo(ax, ay);
      g.lineTo(bx, by);
      g.lineCap = "round";
      if (iso) {
        const d = Math.min(iso.get(e.a) ?? Infinity, iso.get(e.b) ?? Infinity) + e.len / 2;
        const minutes = d / 1.3 / 60;
        const band = Math.min(6, Math.floor(minutes / 5) + 1);
        g.strokeStyle = pal[`seq-${7 - band}`] || pal["map-street"];
        g.lineWidth = 3 + e.width * 0.25;
      } else {
        g.strokeStyle = e.cls === "dock" ? pal["map-dock"] : pal["map-street"];
        g.lineWidth = Math.max(1.4, Math.min(7, e.width * 0.6 * Math.sqrt(this.cam.zoom)));
        if (e.cls === "dock") g.setLineDash([3, 3]);
      }
      if (e.cost >= 1e6) {
        g.strokeStyle = pal.critical;
        g.setLineDash([2, 4]);
      }
      g.stroke();
      g.setLineDash([]);
    }
    if (iso) {
      const o = this.graph.node(this.opts.isochrone);
      const [ox, oy] = this.toScreen(o.x, o.y);
      g.font = `600 10px ${cssVar("--font-data")}`;
      for (const n of this.graph.nodes.values()) {
        if (n.kind !== "junction" && n.kind !== "gate") continue;
        const m = Math.round((iso.get(n.id) ?? Infinity) / 1.3 / 60);
        if (!Number.isFinite(m) || m % 5 > 1 || m === 0) continue;
        const [x, y] = this.toScreen(n.x, n.y);
        this.halo(g, `${m} min`, x + 5, y - 5);
      }
      g.beginPath();
      g.arc(ox, oy, 9, 0, TAU);
      g.strokeStyle = pal.ink;
      g.lineWidth = 1.5;
      g.stroke();
    }
    this.staticDirty = false;
  }

  // Label beside a node, honouring the node's preferred side (data: lab = left|above|below).
  label(g, n, text, x, y, r, color) {
    const w = g.measureText(text).width;
    const at = {
      left: [x - r - 5 - w, y + 3.5],
      above: [x - w / 2, y - r - 6],
      below: [x - w / 2, y + r + 13],
    }[n.lab] ?? [x + r + 5, y + 3.5];
    this.halo(g, text, at[0], at[1], color);
  }

  halo(g, text, x, y, color = this.pal.ink) {
    g.lineWidth = 3;
    g.strokeStyle = this.pal["map-halo"];
    g.lineJoin = "round";
    g.strokeText(text, x, y);
    g.fillStyle = color;
    g.fillText(text, x, y);
  }

  edgeScreen(e) {
    const a = this.graph.node(e.a);
    const b = this.graph.node(e.b);
    const [ax, ay] = this.toScreen(a.x, a.y);
    const [bx, by] = this.toScreen(b.x, b.y);
    const len = Math.hypot(bx - ax, by - ay) || 1;
    return { ax, ay, bx, by, nx: -(by - ay) / len, ny: (bx - ax) / len, len };
  }

  agentScreen(a) {
    if (a.state === "wait") {
      const n = this.graph.node(a.at);
      const [x, y] = this.toScreen(n.x, n.y);
      const i = a.queuePos ?? 0;
      return [x + 8 + (i % 10) * 3.2, y - 7 - Math.floor(i / 10) * 3.2];
    }
    if (a.state === "ride" && a.bus) return this.toScreen(a.bus.x, a.bus.y);
    if (a.state === "dwell") {
      const n = this.graph.node(a.at);
      const [x, y] = this.toScreen(n.x, n.y);
      const r = this.venueRadius(n) + 4 + ((a.id * 7) % 4) * 2.4;
      const ang = a.orbit + this.time * 0.00025 * (a.id % 2 ? 1 : -1);
      return [x + Math.cos(ang) * r, y + Math.sin(ang) * r * this.squash];
    }
    const [x, y] = this.toScreen(a.x, a.y);
    const es = a.seg && this.edgeCache?.[a.seg.edge.id];
    if (!es) return [x, y];
    const dir = a.seg.from === a.seg.edge.a ? 1 : -1;
    // Keep left/right of the walking direction so opposing streams separate visibly.
    const lane = (Math.abs(a.lane) * 0.8 + 0.2) * dir * Math.min(6, 1.2 + a.seg.edge.width * 0.4);
    return [x + es.nx * lane, y + es.ny * lane];
  }

  venueRadius(n) {
    return Math.max(6, Math.min(15, Math.sqrt(n.capacity) * 0.32)) * Math.min(1.6, Math.sqrt(this.cam.zoom));
  }

  draw(world, overlay = {}) {
    this.world = world;
    this.time = performance.now();
    const g = this.ctx;
    const pal = this.pal;
    if (this.staticDirty) this.drawStatic();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.drawImage(this.static, 0, 0);
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    this.edgeCache = this.graph.edges.map((e) => this.edgeScreen(e));
    const ppa = world?.ppa ?? 1;

    if (world && this.opts.heat) this.drawHeat(world);

    // Crowd load on each edge, coloured by Fruin level of service
    if (world && this.opts.loads) {
      g.lineCap = "round";
      for (const e of this.graph.edges) {
        if (!e.count) continue;
        const es = this.edgeCache[e.id];
        const dens = this.graph.density(e, ppa);
        const key = LOS_KEY[losGrade(dens)];
        g.strokeStyle = key ? pal[key] : pal.accent;
        g.globalAlpha = Math.min(0.85, 0.18 + Math.sqrt(e.count * ppa) * 0.05);
        g.lineWidth = Math.min(14, 2 + Math.sqrt(e.count * ppa) * 0.7);
        g.beginPath();
        g.moveTo(es.ax, es.ay);
        g.lineTo(es.bx, es.by);
        g.stroke();
      }
      g.globalAlpha = 1;
    }

    // Moving chevrons in the direction people are walking
    if (world && this.opts.flows) {
      g.setLineDash([2, 9]);
      g.lineCap = "round";
      for (const e of this.graph.edges) {
        const es = this.edgeCache[e.id];
        for (const [flow, sign] of [[e.flowAB, 1], [e.flowBA, -1]]) {
          if (flow < 0.5) continue;
          const off = sign * 2.5;
          const [x0, y0, x1, y1] =
            sign > 0 ? [es.ax, es.ay, es.bx, es.by] : [es.bx, es.by, es.ax, es.ay];
          g.beginPath();
          g.moveTo(x0 + es.nx * off, y0 + es.ny * off);
          g.lineTo(x1 + es.nx * off, y1 + es.ny * off);
          g.lineDashOffset = -(this.time * 0.02) % 11;
          g.strokeStyle = pal.ink;
          g.globalAlpha = Math.min(0.75, 0.15 + flow / 60);
          g.lineWidth = Math.min(3, 1 + flow / 40);
          g.stroke();
        }
      }
      g.setLineDash([]);
      g.globalAlpha = 1;
    }

    if (overlay.path) this.drawPath(overlay.path, overlay.pathColor ?? pal.accent);
    if (overlay.history) this.drawHistory(overlay.history);

    if (world?.transit && this.opts.buses !== false) this.drawRoutes(world.transit, overlay);
    this.drawNodes(world, overlay);
    if (world?.transit && this.opts.buses !== false) this.drawBuses(world.transit, overlay);
    if (world && this.opts.agents) this.drawAgents(world, overlay);
    if (overlay.fan) this.drawFan(overlay.fan);
    if (this.opts.skyline && world) this.drawSkyline(world, overlay);
    if (overlay.selectedAgent) this.drawSelection(overlay.selectedAgent);
  }

  drawHeat(world) {
    const h = this.heatCanvas;
    const hg = h.getContext("2d");
    if (this.heatClear) {
      hg.clearRect(0, 0, h.width, h.height);
      this.heatClear = false;
    }
    hg.globalCompositeOperation = "destination-out";
    hg.fillStyle = "rgba(0,0,0,0.035)";
    hg.fillRect(0, 0, h.width, h.height);
    hg.globalCompositeOperation = "source-over";
    hg.fillStyle = this.pal["map-heat"];
    hg.globalAlpha = 0.07;
    for (const a of world.agents) {
      const [x, y] = this.agentScreen(a);
      hg.beginPath();
      hg.arc(x / 3, y / 3, 2.2, 0, TAU);
      hg.fill();
    }
    hg.globalAlpha = 1;
    const g = this.ctx;
    g.save();
    g.imageSmoothingEnabled = true;
    g.globalAlpha = 0.6;
    g.filter = "blur(4px)";
    g.drawImage(h, 0, 0, this.w, this.h);
    g.restore();
  }

  drawNodes(world, overlay) {
    const g = this.ctx;
    const pal = this.pal;
    const font = cssVar("--font-data");
    for (const n of this.graph.nodes.values()) {
      const [x, y] = this.toScreen(n.x, n.y);
      if (n.kind === "junction") {
        if (!this.opts.junctions) continue;
        g.fillStyle = pal["map-coast"];
        g.fillRect(x - 1.5, y - 1.5, 3, 3);
        continue;
      }
      const hot = overlay.selectedNode === n.id || overlay.highlight?.has?.(n.id);
      if (n.kind === "venue") {
        if (this.opts.skyline) continue;
        const r = this.venueRadius(n);
        const occ = world?.occupancy.get(n.id) ?? 0;
        const fill = occ / n.capacity;
        this.hexPath(g, x, y, r);
        g.fillStyle = pal.surface;
        g.fill();
        if (fill > 0) {
          g.save();
          this.hexPath(g, x, y, r);
          g.clip();
          g.beginPath();
          g.moveTo(x, y);
          g.arc(x, y, r + 2, -Math.PI / 2, -Math.PI / 2 + TAU * Math.min(1, fill));
          g.closePath();
          g.fillStyle = stressColor(pal, fill);
          g.fill();
          g.restore();
        }
        this.hexPath(g, x, y, r);
        g.strokeStyle = hot ? pal.accent : pal.ink;
        g.lineWidth = hot ? 2.5 : 1.2;
        g.stroke();
        if (this.opts.labels) {
          g.font = `500 10.5px ${font}`;
          this.label(g, n, n.name, x, y, r, pal["ink-2"]);
        }
      } else if (n.kind === "terminal") {
        g.save();
        g.translate(x, y);
        g.rotate(-0.35);
        g.beginPath();
        g.moveTo(-13, -4.5);
        g.lineTo(9, -4.5);
        g.quadraticCurveTo(16, 0, 9, 4.5);
        g.lineTo(-13, 4.5);
        g.closePath();
        g.fillStyle = pal["map-terminal"];
        g.fill();
        g.strokeStyle = hot ? pal.accent : pal.ink;
        g.lineWidth = hot ? 2.5 : 1;
        g.stroke();
        g.restore();
        if (this.opts.labels) {
          g.font = `600 10px ${font}`;
          const label = `${n.name.replace(" Cruise Terminal", "").toUpperCase()} · ${n.berth}`;
          if (n.lab) this.label(g, n, label, x, y, 6, pal.ink);
          else this.halo(g, label, x - 16, y + 18, pal.ink);
        }
      } else if (n.kind === "gate") {
        g.fillStyle = pal.ink;
        g.fillRect(x - 5, y - 1.8, 10, 3.6);
        if (this.opts.labels) {
          g.font = `500 9.5px ${font}`;
          this.halo(g, n.name.replace("Dock Gate ", "Gate "), x + 7, y - 5, pal.muted);
        }
      } else if (n.kind === "exit") {
        g.beginPath();
        g.rect(x - 5.5, y - 5.5, 11, 11);
        g.fillStyle = pal.ink;
        g.fill();
        g.fillStyle = pal.surface;
        g.font = `700 8px ${font}`;
        g.fillText(n.mode === "rail" ? "R" : "F", x - 2.6, y + 3);
        if (this.opts.labels) {
          g.font = `500 10px ${font}`;
          this.label(g, n, n.name, x, y, 6, pal["ink-2"]);
        }
      }
    }
  }

  // Bus lines as thin parallel strokes (one per line, offset so shared streets show every line),
  // with a stop sign at each stop.
  drawRoutes(transit, overlay) {
    const g = this.ctx;
    const pal = this.pal;
    const n = transit.lines.length;
    g.lineCap = "round";
    g.lineJoin = "round";
    transit.lines.forEach((line, li) => {
      const off = (li - (n - 1) / 2) * 3;
      const hot = overlay.selectedLine === line.id;
      g.beginPath();
      for (const leg of line.dirs[0].legs) {
        for (const [i, seg] of leg.segs.entries()) {
          const es = this.edgeCache[seg.edge.id];
          const sgn = seg.from === seg.edge.a ? 1 : -1;
          const [fx, fy] = sgn > 0 ? [es.ax, es.ay] : [es.bx, es.by];
          const [tx, ty] = sgn > 0 ? [es.bx, es.by] : [es.ax, es.ay];
          const ox = es.nx * off * sgn;
          const oy = es.ny * off * sgn;
          if (i === 0) g.moveTo(fx + ox, fy + oy);
          else g.lineTo(fx + ox, fy + oy);
          g.lineTo(tx + ox, ty + oy);
        }
      }
      g.strokeStyle = hot ? pal.accent : pal["ink-2"];
      g.globalAlpha = hot ? 0.9 : 0.35;
      g.lineWidth = hot ? 3 : 1.6;
      g.stroke();
      g.globalAlpha = 1;
    });
    const font = cssVar("--font-data");
    for (const id of transit.stops) {
      const s = this.graph.node(id);
      const [x, y] = this.toScreen(s.x, s.y);
      const hot = overlay.selectedStop === id;
      g.beginPath();
      g.arc(x, y, hot ? 6 : 4.5, 0, TAU);
      g.fillStyle = pal.surface;
      g.fill();
      g.lineWidth = hot ? 2.5 : 1.6;
      g.strokeStyle = hot ? pal.accent : pal.ink;
      g.stroke();
      g.beginPath();
      g.arc(x, y, 1.6, 0, TAU);
      g.fillStyle = hot ? pal.accent : pal.ink;
      g.fill();
      if (overlay.stopLabels) {
        g.font = `500 9.5px ${font}`;
        const lines = transit.lines.filter((l) => l.dirs[0].index.has(id)).map((l) => l.id).join(" ");
        this.halo(g, lines, x - 6, y + 14, pal.muted);
      }
    }
  }

  // Buses: oriented along the street, filled by how late they are, with a load bar inside.
  drawBuses(transit, overlay) {
    const g = this.ctx;
    const pal = this.pal;
    const font = cssVar("--font-data");
    const z = Math.min(1.6, Math.sqrt(this.cam.zoom));
    const L = 9 * z;
    const W = 4 * z;
    for (const b of transit.buses) {
      const [x, y] = this.toScreen(b.x, b.y);
      const [x2, y2] = this.toScreen(b.x + b.hx * 10, b.y + b.hy * 10);
      const ang = Math.atan2(y2 - y, x2 - x);
      const late = b.delayNow;
      const fill = late > 5 ? pal.critical : late > 3 ? pal.serious : late > 1 ? pal.warning : pal.good;
      g.save();
      g.translate(x, y);
      g.rotate(ang);
      g.beginPath();
      g.roundRect(-L, -W, 2 * L, 2 * W, 2.5);
      g.fillStyle = fill;
      g.fill();
      g.lineWidth = overlay.selectedBus === b ? 2.5 : 1.2;
      g.strokeStyle = overlay.selectedBus === b ? pal.accent : pal.ink;
      g.stroke();
      const load = Math.min(1, (b.riders.length * this.world.ppa) / 80);
      if (load > 0) {
        g.fillStyle = pal.ink;
        g.globalAlpha = 0.55;
        g.fillRect(-L + 2, -1.2, (2 * L - 4) * load, 2.4);
        g.globalAlpha = 1;
      }
      g.restore();
      g.font = `700 9.5px ${font}`;
      this.halo(g, b.line.id, x - 6, y - W - 5, pal.ink);
    }
  }

  hexPath(g, x, y, r) {
    g.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i + Math.PI / 6;
      const px = x + Math.cos(a) * r;
      const py = y + Math.sin(a) * r * this.squash;
      i ? g.lineTo(px, py) : g.moveTo(px, py);
    }
    g.closePath();
  }

  drawAgents(world, overlay) {
    const g = this.ctx;
    const pal = this.pal;
    const s = this.opts.agentSize * Math.min(1.8, Math.sqrt(this.cam.zoom));
    const groups = new Map();
    for (const a of world.agents) {
      if (a.state === "ride") continue; // drawn as the bus they are on
      let key = a.persona;
      if (this.opts.colorBy === "state") key = a.state === "dwell" ? "dwell" : a.late ? "late" : "walk";
      if (overlay.dim && overlay.dim(a)) key = "dim";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    }
    const colorFor = (key) =>
      key === "dim" ? pal.hairline : key === "dwell" ? pal.muted : key === "walk" ? pal.accent : key === "late" ? pal.critical : pal.persona[key];

    if (this.opts.trails) {
      g.lineCap = "round";
      g.lineWidth = Math.max(1, s * 0.7);
      for (const [key, list] of groups) {
        g.strokeStyle = colorFor(key);
        g.globalAlpha = 0.35;
        g.beginPath();
        for (const a of list) {
          if (a.state !== "walk" || !a.seg) continue;
          const [x, y] = this.agentScreen(a);
          const es = this.edgeCache[a.seg.edge.id];
          const dir = a.seg.from === a.seg.edge.a ? 1 : -1;
          const tail = Math.min(10, 3 + a.speed * 4);
          g.moveTo(x, y);
          g.lineTo(x - ((es.bx - es.ax) / es.len) * tail * dir, y - ((es.by - es.ay) / es.len) * tail * dir);
        }
        g.stroke();
      }
      g.globalAlpha = 1;
    }

    for (const [key, list] of groups) {
      const shape = PERSONAS[key]?.shape ?? "circle";
      g.fillStyle = colorFor(key);
      g.strokeStyle = colorFor(key);
      g.beginPath();
      for (const a of list) {
        const [x, y] = this.agentScreen(a);
        this.shapePath(g, this.opts.colorBy === "persona" ? shape : "circle", x, y, s);
      }
      if (shape === "cross" || shape === "ring") {
        g.lineWidth = Math.max(1.2, s * 0.6);
        g.stroke();
      } else g.fill();
    }
  }

  shapePath(g, shape, x, y, s) {
    switch (shape) {
      case "square":
        g.rect(x - s * 0.85, y - s * 0.85, s * 1.7, s * 1.7);
        break;
      case "diamond":
        g.moveTo(x, y - s * 1.2);
        g.lineTo(x + s * 1.2, y);
        g.lineTo(x, y + s * 1.2);
        g.lineTo(x - s * 1.2, y);
        g.closePath();
        break;
      case "triangle":
        g.moveTo(x, y - s * 1.2);
        g.lineTo(x + s * 1.1, y + s * 0.8);
        g.lineTo(x - s * 1.1, y + s * 0.8);
        g.closePath();
        break;
      case "cross":
        g.moveTo(x - s, y - s);
        g.lineTo(x + s, y + s);
        g.moveTo(x + s, y - s);
        g.lineTo(x - s, y + s);
        break;
      case "ring":
        g.moveTo(x + s, y);
        g.arc(x, y, s, 0, TAU);
        break;
      default:
        g.moveTo(x + s, y);
        g.arc(x, y, s, 0, TAU);
    }
  }

  drawPath(path, color) {
    const g = this.ctx;
    g.beginPath();
    for (const [i, seg] of path.entries()) {
      const f = this.graph.node(seg.from);
      const t = this.graph.node(seg.to);
      const [fx, fy] = this.toScreen(f.x, f.y);
      const [tx, ty] = this.toScreen(t.x, t.y);
      if (i === 0) g.moveTo(fx, fy);
      g.lineTo(tx, ty);
    }
    g.strokeStyle = color;
    g.lineWidth = 3;
    g.globalAlpha = 0.8;
    g.setLineDash([7, 4]);
    g.lineDashOffset = -(this.time * 0.03) % 11;
    g.stroke();
    g.setLineDash([]);
    g.globalAlpha = 1;
  }

  drawHistory(nodes) {
    const g = this.ctx;
    if (nodes.length < 2) return;
    g.beginPath();
    nodes.forEach((id, i) => {
      const n = this.graph.node(id);
      const [x, y] = this.toScreen(n.x, n.y);
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    });
    g.strokeStyle = this.pal.muted;
    g.lineWidth = 1.5;
    g.setLineDash([1, 4]);
    g.stroke();
    g.setLineDash([]);
  }

  // Policy fan: one spoke from the agent to each option it weighed, thickness = probability.
  drawFan({ from, probs, chosen }) {
    const g = this.ctx;
    const pal = this.pal;
    const font = cssVar("--font-data");
    const [ox, oy] = from;
    const sorted = [...probs].sort((a, b) => b[1] - a[1]);
    for (const [i, [id, p]] of sorted.entries()) {
      const n = this.graph.node(id);
      if (!n) continue;
      const [x, y] = this.toScreen(n.x, n.y);
      g.beginPath();
      g.moveTo(ox, oy);
      const mx = (ox + x) / 2 - (y - oy) * 0.12;
      const my = (oy + y) / 2 + (x - ox) * 0.12;
      g.quadraticCurveTo(mx, my, x, y);
      g.strokeStyle = id === chosen ? pal.accent : pal.ink;
      g.globalAlpha = 0.2 + 0.8 * Math.sqrt(p);
      g.lineWidth = 1 + 9 * p;
      g.stroke();
      g.globalAlpha = 1;
      if (i < 4 && p > 0.03) {
        g.font = `700 11px ${font}`;
        this.halo(g, `${Math.round(p * 100)}%`, mx - 10, my, id === chosen ? pal.accent : pal.ink);
      }
    }
  }

  drawSelection(a) {
    const g = this.ctx;
    const [x, y] = this.agentScreen(a);
    const r = 9 + Math.sin(this.time * 0.006) * 1.5;
    g.beginPath();
    g.arc(x, y, r, 0, TAU);
    g.strokeStyle = this.pal.accent;
    g.lineWidth = 2;
    g.stroke();
  }

  // Iso view: each venue becomes a hexagonal prism, height = people inside.
  drawSkyline(world, overlay) {
    const g = this.ctx;
    const pal = this.pal;
    const font = cssVar("--font-data");
    const venues = this.graph.venues
      .map((n) => ({ n, s: this.toScreen(n.x, n.y) }))
      .sort((a, b) => a.s[1] - b.s[1]);
    const k = overlay.heightScale ?? 0.22;
    // Only the busiest towers (and the selected one) get a label, so the skyline stays legible.
    const labelled = new Set(
      [...venues]
        .sort((a, b) => (world.occupancy.get(b.n.id) ?? 0) - (world.occupancy.get(a.n.id) ?? 0))
        .slice(0, overlay.labelTop ?? 5)
        .map((v) => v.n.id),
    );
    if (overlay.selectedNode) labelled.add(overlay.selectedNode);
    for (const { n, s } of venues) {
      const [x, y] = s;
      const occ = world.occupancy.get(n.id) ?? 0;
      const fill = occ / n.capacity;
      const staffNow = n.perStaff ? Math.max(2, Math.ceil(occ / n.perStaff)) : 0;
      const value = overlay.metric === "staff" ? staffNow * 14 : occ;
      const h = Math.max(3, value * k * Math.sqrt(this.cam.zoom));
      const r = this.venueRadius(n) * 1.1;
      const pts = [];
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i;
        pts.push([x + Math.cos(a) * r, y + Math.sin(a) * r * this.squash]);
      }
      const col = stressColor(pal, fill);
      // Capacity ghost: the height at which the venue is full
      const capValue = overlay.metric === "staff" ? (n.perStaff ? Math.ceil(n.capacity / n.perStaff) * 14 : 0) : n.capacity;
      const cap = capValue * k * Math.sqrt(this.cam.zoom);
      // Glass envelope: the tower's height when the venue is full
      if (cap > h && cap < 320) {
        g.beginPath();
        pts.forEach(([px, py], i) => (i ? g.lineTo(px, py - cap) : g.moveTo(px, py - cap)));
        g.closePath();
        for (const i of [0, 3]) {
          g.moveTo(pts[i][0], pts[i][1] - h);
          g.lineTo(pts[i][0], pts[i][1] - cap);
        }
        g.strokeStyle = pal.muted;
        g.setLineDash([2, 3]);
        g.lineWidth = 1;
        g.stroke();
        g.setLineDash([]);
      }
      // Visible side faces (front three), then the top
      for (let i = 0; i < 6; i++) {
        const [x0, y0] = pts[i];
        const [x1, y1] = pts[(i + 1) % 6];
        if ((y0 + y1) / 2 < y) continue;
        g.beginPath();
        g.moveTo(x0, y0);
        g.lineTo(x1, y1);
        g.lineTo(x1, y1 - h);
        g.lineTo(x0, y0 - h);
        g.closePath();
        g.fillStyle = col;
        g.fill();
        g.fillStyle = pal.ink;
        g.globalAlpha = i % 2 ? 0.28 : 0.12;
        g.fill();
        g.globalAlpha = 1;
      }
      g.beginPath();
      pts.forEach(([px, py], i) => (i ? g.lineTo(px, py - h) : g.moveTo(px, py - h)));
      g.closePath();
      g.fillStyle = col;
      g.fill();
      g.strokeStyle = overlay.selectedNode === n.id ? pal.accent : pal.ink;
      g.lineWidth = overlay.selectedNode === n.id ? 2.4 : 0.8;
      g.stroke();
      if (this.opts.labels && labelled.has(n.id)) {
        g.font = `600 10px ${font}`;
        const tag = n.perStaff ? `${n.name} · ${fmtInt(occ)} in · ${staffNow} staff` : `${n.name} · ${fmtInt(occ)}`;
        this.halo(g, tag, x + r + 3, y - h - 4, pal.ink);
      }
    }
  }
}
