// Page furniture shared by the simulations: the top bar, the venue table, map tooltips.

import { PERSONAS } from "./policy.js";
import { clock } from "./schedule.js";
import { stressColor } from "./render.js";
import { themeToggle, Tooltip, fmt, gbp } from "./ui.js";

export const SIMS = [
  { href: "swarm.html", label: "Swarm", blurb: "One ship disembarks. Watch walkers find the station, the cafés and the shops." },
  { href: "day.html", label: "Turnaround Day", blurb: "Four ships, 05:00 to 20:00, ending in an hourly staffing plan per venue." },
  { href: "policy.html", label: "Policy Lens", blurb: "Follow one passenger and see every option the policy weighed at each decision." },
  { href: "compare.html", label: "Compare", blurb: "Run two scenarios side by side on the same seed: rain, a closed gate, staggered disembarkation." },
  { href: "skyline.html", label: "Skyline", blurb: "Isometric city where each venue rises with the people inside it." },
  { href: "buses.html", label: "Buses", blurb: "Timetabled buses that run late, passengers who wait for them, and what late buses cost." },
];

export function mountBar(current) {
  const bar = document.querySelector("header.bar");
  bar.innerHTML = `
    <a class="brand" href="index.html"><b>Gangway</b><span>Southampton shore flow</span></a>
    <nav class="sims" aria-label="Simulations">
      ${SIMS.map((s) => `<a href="${s.href}"${s.href === current ? ' aria-current="page"' : ""}>${s.label}</a>`).join("")}
    </nav>
    <button class="btn" id="theme" type="button">Theme</button>`;
  themeToggle(bar.querySelector("#theme"));
}

export function pill(text, color) {
  return `<span class="pill" style="--dot:${color}">${text}</span>`;
}

export function venueRows(world, pal, { selected, metric = "now" } = {}) {
  const rows = world.graph.venues.map((v) => {
    const occ = world.occupancy.get(v.id);
    const s = world.venueStats.get(v.id);
    const fill = occ / v.capacity;
    const staff = v.perStaff ? Math.max(2, Math.ceil(occ / v.perStaff)) : "–";
    return { v, occ, s, fill, staff };
  });
  rows.sort((a, b) => (metric === "now" ? b.occ - a.occ : b.s.arrivals - a.s.arrivals));
  return rows
    .map(
      ({ v, occ, s, fill, staff }) => `
      <tr data-id="${v.id}" class="${selected === v.id ? "sel" : ""}">
        <td>${v.name}</td>
        <td><div class="meter" title="${Math.round(fill * 100)}% full"><i style="width:${Math.min(100, fill * 100)}%;background:${stressColor(pal, fill)}"></i></div></td>
        <td class="num">${fmt(occ)}</td>
        <td class="num">${fmt(s.arrivals)}</td>
        <td class="num">${staff}</td>
      </tr>`,
    )
    .join("");
}

export function venueTableHead() {
  return `<thead><tr><th>Venue</th><th>Fill</th><th class="num">Now</th><th class="num">In</th><th class="num">Staff</th></tr></thead>`;
}

export function describeNode(n, world) {
  if (n.kind === "venue") {
    const occ = world.occupancy.get(n.id);
    const s = world.venueStats.get(n.id);
    return `<div class="tt-h">${n.name}</div>
      <div>${n.category} · capacity ${n.capacity} · dwell ~${n.dwell} min</div>
      <div class="row">Inside now<b>${fmt(occ)}</b></div>
      <div class="row">Arrivals today<b>${fmt(s.arrivals)}</b></div>
      <div class="row">Turned away<b>${fmt(s.turnedAway)}</b></div>
      <div class="row">Peak<b>${fmt(s.peak)}</b></div>
      <div class="row">Spend so far<b>${gbp(s.revenue)}</b></div>`;
  }
  if (n.kind === "terminal") return `<div class="tt-h">${n.name}</div><div>Berth ${n.berth}</div>`;
  if (n.kind === "gate") return `<div class="tt-h">${n.name}</div><div>Port estate pinch point</div>`;
  if (n.kind === "exit") return `<div class="tt-h">${n.name}</div><div>Onward ${n.mode}</div>`;
  return `<div class="tt-h">${n.name}</div>`;
}

export function describeAgent(a, world) {
  const p = PERSONAS[a.persona];
  const g = world.graph;
  const where =
    a.state === "dwell"
      ? `at ${g.node(a.at).name}`
      : a.state === "wait"
        ? `waiting at ${g.node(a.at).name} for the ${a.trip.line}`
        : `${a.trip ? "heading for the bus to" : "walking to"} ${g.node(a.target)?.name ?? "?"}`;
  return `<div class="tt-h">Passenger #${a.id} · ${p.label}</div>
    <div>${where}</div>
    <div class="row">Heading for<b>${g.node(a.sink).name}</b></div>
    <div class="row">Must be there by<b>${clock(a.deadline)}</b></div>
    <div class="row">Visited<b>${a.visits.length}</b></div>
    <div>${world.ppa > 1 ? `1 dot = ${world.ppa} people` : ""}</div>`;
}

export function describeBus(b, world) {
  const d = b.d;
  const next = world.graph.node(d.order[Math.min(b.k, d.order.length - 1)]);
  const late = b.delayNow;
  const status = late > 1 ? `${late.toFixed(1)} min late` : late < -1 ? `${(-late).toFixed(1)} min early` : "on time";
  return `<div class="tt-h">${b.line.id} ${b.line.name} → ${b.dir ? b.line.from : b.line.to}</div>
    <div>${status} · ${b.state === "dwell" ? "at" : "next stop"} ${next.name}</div>
    <div class="row">Timetabled departure<b>${clock(b.sched)}</b></div>
    <div class="row">On board<b>${b.riders.length * world.ppa}</b></div>`;
}

export function mapTooltips(renderer, getWorld) {
  const tip = new Tooltip();
  renderer.on("hover", (hit) => {
    const world = getWorld();
    if (!hit || !world) return tip.hide();
    if (hit.type === "bus") return tip.show(describeBus(hit.bus, world), hit.clientX, hit.clientY);
    if (hit.type === "node" && hit.node.kind === "junction") {
      const tr = world.transit;
      const waiting = tr?.queues.get(hit.node.id)?.length ?? 0;
      const lines = tr?.lines.filter((l) => l.dirs[0].index.has(hit.node.id)).map((l) => `${l.id} ${l.name}`) ?? [];
      return tip.show(
        `<div class="tt-h">Bus stop · ${hit.node.name}</div><div>${lines.join("<br>")}</div><div class="row">Waiting<b>${waiting * world.ppa}</b></div>`,
        hit.clientX,
        hit.clientY,
      );
    }
    const html = hit.type === "agent" ? describeAgent(hit.agent, world) : describeNode(hit.node, world);
    tip.show(html, hit.clientX, hit.clientY);
  });
  return tip;
}

export function bindRange(id, fmtFn, onChange) {
  const input = document.getElementById(id);
  const out = document.querySelector(`output[for="${id}"]`);
  const update = () => {
    if (out) out.textContent = fmtFn(+input.value);
  };
  input.addEventListener("input", () => {
    update();
    onChange?.(+input.value, false);
  });
  input.addEventListener("change", () => onChange?.(+input.value, true));
  update();
  return input;
}
