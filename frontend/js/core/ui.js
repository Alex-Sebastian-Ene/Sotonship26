// Small UI pieces shared by the simulation pages: theme toggle, clock loop, charts, tooltips.

import { clock } from "./schedule.js";
import { PERSONAS, PERSONA_ORDER } from "./policy.js";

export const $ = (sel, root = document) => root.querySelector(sel);

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function fmt(n) {
  if (n >= 10000) return `${(n / 1000).toFixed(0)}K`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  if (n > 0 && n < 10 && !Number.isInteger(n)) return n.toFixed(1);
  return `${Math.round(n)}`;
}

export function gbp(n) {
  return `£${Math.round(n).toLocaleString("en-GB")}`;
}

// System -> light -> dark. "System" leaves data-theme unset so prefers-color-scheme decides.
export function themeToggle(button) {
  const order = ["system", "light", "dark"];
  let mode = "system";
  try {
    mode = localStorage.getItem("soton-theme") || "system";
  } catch {}
  const apply = () => {
    if (mode === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
    button.textContent = `Theme: ${mode}`;
  };
  apply();
  button.addEventListener("click", () => {
    mode = order[(order.indexOf(mode) + 1) % order.length];
    try {
      localStorage.setItem("soton-theme", mode);
    } catch {}
    apply();
  });
}

// requestAnimationFrame loop that advances simulated time at `speed` sim-seconds per real second.
export function loop(step) {
  let last = performance.now();
  let running = true;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const frame = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    step(running ? dt : 0, now);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
  return {
    get running() {
      return running;
    },
    set running(v) {
      running = v;
    },
    reduced,
  };
}

export function legend(el, ids = PERSONA_ORDER) {
  el.innerHTML = ids
    .map(
      (id) =>
        `<span class="key"><svg width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">${glyph(PERSONAS[id].shape, `var(--p-${id})`)}</svg>${PERSONAS[id].label}</span>`,
    )
    .join("");
}

export function glyph(shape, color) {
  switch (shape) {
    case "square":
      return `<rect x="-4" y="-4" width="8" height="8" fill="${color}"/>`;
    case "diamond":
      return `<path d="M0-5L5 0L0 5L-5 0Z" fill="${color}"/>`;
    case "triangle":
      return `<path d="M0-5L4.6 3.4L-4.6 3.4Z" fill="${color}"/>`;
    case "cross":
      return `<path d="M-4-4L4 4M4-4L-4 4" stroke="${color}" stroke-width="2"/>`;
    case "ring":
      return `<circle r="3.6" fill="none" stroke="${color}" stroke-width="2"/>`;
    default:
      return `<circle r="4.2" fill="${color}"/>`;
  }
}

export class Tooltip {
  constructor() {
    this.el = document.createElement("div");
    this.el.className = "tooltip";
    this.el.hidden = true;
    document.body.appendChild(this.el);
  }

  show(html, x, y) {
    this.el.innerHTML = html;
    this.el.hidden = false;
    const r = this.el.getBoundingClientRect();
    const left = Math.min(window.innerWidth - r.width - 12, x + 14);
    const top = y + r.height + 20 > window.innerHeight ? y - r.height - 10 : y + 14;
    this.el.style.left = `${Math.max(8, left)}px`;
    this.el.style.top = `${Math.max(8, top)}px`;
  }

  hide() {
    this.el.hidden = true;
  }
}

// Time-series chart on a canvas: x = simulated minutes, one or more series, 2px lines with a 10%
// wash, hairline grid, an emphasised end-dot, crosshair + tooltip on hover.
export class TimeChart {
  constructor(canvas, { start, minutes, yLabel = "", capacity = null } = {}) {
    this.canvas = canvas;
    this.start = start;
    this.minutes = minutes;
    this.yLabel = yLabel;
    this.capacity = capacity;
    this.series = [];
    this.hoverX = null;
    this.tip = new Tooltip();
    canvas.addEventListener("pointermove", (e) => {
      this.hoverX = e.offsetX;
      this.draw();
    });
    canvas.addEventListener("pointerleave", () => {
      this.hoverX = null;
      this.tip.hide();
      this.draw();
    });
    new ResizeObserver(() => this.draw()).observe(canvas);
  }

  // series: [{ label, color, data: Float32Array, upTo }]
  set(series, upTo, extra = {}) {
    this.series = series;
    this.upTo = upTo;
    Object.assign(this, extra);
    this.draw();
  }

  draw() {
    const c = this.canvas;
    const r = c.getBoundingClientRect();
    if (!r.width) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.round(r.width * dpr);
    c.height = Math.round(r.height * dpr);
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = r.width;
    const H = r.height;
    const L = 34;
    const R = 10;
    const T = 10;
    const B = 20;
    const font = css("--font-data");
    g.clearRect(0, 0, W, H);
    const upTo = Math.max(1, this.upTo ?? this.minutes);
    let ymax = this.capacity ?? 0;
    for (const s of this.series) for (let i = 0; i < upTo; i++) ymax = Math.max(ymax, s.data[i]);
    ymax = niceMax(ymax || 10);
    const x = (m) => L + ((W - L - R) * m) / (this.minutes - 1);
    const y = (v) => T + (H - T - B) * (1 - v / ymax);

    g.font = `10px ${font}`;
    g.fillStyle = css("--muted");
    g.strokeStyle = css("--hairline");
    g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const v = (ymax * i) / 4;
      g.beginPath();
      g.moveTo(L, Math.round(y(v)) + 0.5);
      g.lineTo(W - R, Math.round(y(v)) + 0.5);
      g.stroke();
      g.fillText(fmt(v), 4, y(v) + 3);
    }
    const firstHour = Math.ceil(this.start / 3600);
    const stepH = W < 380 ? 3 : 2;
    for (let h = firstHour; (h * 3600 - this.start) / 60 < this.minutes; h += 1) {
      if (h % stepH) continue;
      const m = (h * 3600 - this.start) / 60;
      g.fillText(`${String(h).padStart(2, "0")}:00`, x(m) - 14, H - 5);
    }
    if (this.capacity) {
      g.strokeStyle = css("--critical");
      g.setLineDash([4, 3]);
      g.beginPath();
      g.moveTo(L, y(this.capacity));
      g.lineTo(W - R, y(this.capacity));
      g.stroke();
      g.setLineDash([]);
      g.fillStyle = css("--ink-2");
      g.fillText("capacity", W - R - 46, y(this.capacity) - 4);
    }

    for (const s of this.series) {
      const n = Math.min(upTo, s.data.length);
      g.beginPath();
      for (let i = 0; i < n; i++) i ? g.lineTo(x(i), y(s.data[i])) : g.moveTo(x(i), y(s.data[i]));
      g.lineWidth = 2;
      g.lineJoin = "round";
      g.strokeStyle = s.color;
      g.stroke();
      g.lineTo(x(n - 1), y(0));
      g.lineTo(x(0), y(0));
      g.closePath();
      g.globalAlpha = 0.1;
      g.fillStyle = s.color;
      g.fill();
      g.globalAlpha = 1;
      if (n > 1) {
        g.beginPath();
        g.arc(x(n - 1), y(s.data[n - 1]), 4, 0, Math.PI * 2);
        g.fillStyle = s.color;
        g.fill();
        g.lineWidth = 2;
        g.strokeStyle = css("--surface");
        g.stroke();
      }
    }

    if (this.hoverX !== null && this.hoverX > L) {
      const m = Math.round(((this.hoverX - L) / (W - L - R)) * (this.minutes - 1));
      if (m >= 0 && m < upTo) {
        g.strokeStyle = css("--muted");
        g.beginPath();
        g.moveTo(x(m), T);
        g.lineTo(x(m), H - B);
        g.stroke();
        const rows = this.series
          .map((s) => `<div class="row"><i style="background:${s.color}"></i>${s.label}<b>${fmt(s.data[m])}</b></div>`)
          .join("");
        const rect = this.canvas.getBoundingClientRect();
        this.tip.show(`<div class="tt-h">${clock(this.start + m * 60)}</div>${rows}`, rect.left + x(m), rect.top + 10);
      }
    }
  }
}

// Smallest "nice" maximum that splits into four clean ticks.
function niceMax(v) {
  const step = v / 4;
  const p = 10 ** Math.floor(Math.log10(step));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= step) return 4 * m * p;
  return 40 * p;
}

// Hourly column chart: forecast staff per hour as columns, flat roster as a reference line.
export function drawStaffChart(canvas, hours, flat, nowHour) {
  const r = canvas.getBoundingClientRect();
  if (!r.width) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = r.width;
  const H = r.height;
  const L = 26;
  const B = 18;
  const T = 16;
  const font = css("--font-data");
  g.clearRect(0, 0, W, H);
  const max = Math.max(4, flat, ...hours.map((h) => h.staff ?? 0));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const band = (W - L - 4) / hours.length;
  const bw = Math.min(24, band * 0.62);
  g.font = `10px ${font}`;
  g.strokeStyle = css("--hairline");
  for (let i = 0; i <= max; i += Math.max(1, Math.ceil(max / 4))) {
    g.beginPath();
    g.moveTo(L, Math.round(y(i)) + 0.5);
    g.lineTo(W, Math.round(y(i)) + 0.5);
    g.stroke();
    g.fillStyle = css("--muted");
    g.fillText(String(i), 6, y(i) + 3);
  }
  hours.forEach((h, i) => {
    const cx = L + band * i + band / 2;
    if (i % 2 === 0 || band > 30) {
      g.fillStyle = css("--muted");
      g.fillText(String(h.hour).padStart(2, "0"), cx - 6, H - 4);
    }
    if (h.staff === null) return;
    const top = y(h.staff);
    const bottom = y(0);
    g.fillStyle = h.hour === nowHour ? css("--accent") : css("--seq-3");
    roundTop(g, cx - bw / 2, top, bw, bottom - top, 4);
    g.fill();
  });
  g.strokeStyle = css("--ink");
  g.setLineDash([5, 3]);
  g.lineWidth = 1.5;
  g.beginPath();
  g.moveTo(L, y(flat));
  g.lineTo(W, y(flat));
  g.stroke();
  g.setLineDash([]);
  g.fillStyle = css("--ink-2");
  const label = `flat roster ${flat}`;
  g.fillText(label, W - g.measureText(label).width - 4, y(flat) - 4);
}

function roundTop(g, x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  g.beginPath();
  g.moveTo(x, y + h);
  g.lineTo(x, y + r);
  g.quadraticCurveTo(x, y, x + r, y);
  g.lineTo(x + w - r, y);
  g.quadraticCurveTo(x + w, y, x + w, y + r);
  g.lineTo(x + w, y + h);
  g.closePath();
}

export function lineKeys(series) {
  return series
    .map((s) => `<span class="line-key"><i style="background:${s.color}"></i>${s.label}</span>`)
    .join("");
}
