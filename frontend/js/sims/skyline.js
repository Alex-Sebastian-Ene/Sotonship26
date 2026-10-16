// Skyline: isometric city, each venue a tower whose height is its demand.

import { Graph } from "../core/graph.js";
import { World } from "../core/world.js";
import { Renderer, stressColor } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { SAMPLE_DAY, planDay, clock, hhmm } from "../core/schedule.js";
import { $, loop, legend, TimeChart, css, fmt } from "../core/ui.js";
import { mountBar, mapTooltips, bindRange, pill } from "../core/page.js";

mountBar("skyline.html");
legend($("#legend"));

const START = hhmm("06:00");
const END = hhmm("20:00");
const graph = new Graph();
const renderer = new Renderer($("#map"), graph, {
  mode: "iso",
  skyline: true,
  flows: false,
  loads: true,
  agentSize: 1.6,
  trails: false,
});
let speed = 300;
let metric = "people";
let heightScale = 0.22;

const plan = planDay(SAMPLE_DAY.ships, new Rng(26), { peoplePerAgent: 3 });
const world = new World({ graph, plan, seed: 26, start: START, end: END, peoplePerAgent: 3 });
const staffSeries = new Float32Array(world.minutes);
let staffPeak = 0;

function staffNeeded() {
  let total = 0;
  for (const v of graph.venues) if (v.perStaff) total += Math.max(2, Math.ceil(world.occupancy.get(v.id) / v.perStaff));
  return total;
}
world.on((type, m) => {
  if (type !== "minute") return;
  staffSeries[m] = staffNeeded();
  staffPeak = Math.max(staffPeak, staffSeries[m]);
});
world.advance(hhmm("10:30") - START);

bindRange("speed", (v) => `${v}×`, (v) => (speed = v));
bindRange("hscale", (v) => v.toFixed(2), (v) => (heightScale = v));
for (const b of document.querySelectorAll("[data-metric]")) {
  b.addEventListener("click", () => {
    metric = b.dataset.metric;
    for (const o of document.querySelectorAll("[data-metric]")) o.setAttribute("aria-pressed", String(o === b));
  });
}
for (const b of document.querySelectorAll("[data-layer]")) {
  b.addEventListener("click", () => {
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(on));
    renderer.set({ [b.dataset.layer]: on });
  });
}
const pal = renderer.pal;
$("#fill-key").innerHTML = [
  ["Under 60% full", 0.3],
  ["60–85%", 0.7],
  ["85–100%", 0.9],
  ["Full", 1],
]
  .map(([t, f]) => pill(t, stressColor(pal, f)))
  .join("");

let selected = null;
renderer.on("pick", (hit) => {
  selected = hit?.type === "node" && hit.node.kind === "venue" ? hit.node.id : null;
});
mapTooltips(renderer, () => world);

const playBtn = $("#play");
const l = loop((dt) => {
  if (!world.done) world.advance(dt * speed);
  renderer.draw(world, { metric, heightScale, selectedNode: selected });
  $("#clock").textContent = clock(world.t);
});
playBtn.addEventListener("click", () => {
  l.running = !l.running;
  playBtn.textContent = l.running ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(l.running));
});
$("#reset-view").addEventListener("click", () => renderer.resetView());

const tl = new TimeChart($("#tl"), { start: START, minutes: world.minutes });

function refresh() {
  const now = staffNeeded();
  $("#staff-now").textContent = fmt(now);
  $("#staff-peak").textContent = fmt(staffPeak);
  $("#sub").textContent = `${fmt(world.agents.length * world.ppa)} passengers ashore`;
  const rows = graph.venues
    .filter((v) => v.perStaff)
    .map((v) => {
      const occ = world.occupancy.get(v.id);
      return { v, occ, staff: Math.max(2, Math.ceil(occ / v.perStaff)), fill: occ / v.capacity };
    })
    .sort((a, b) => b.staff - a.staff);
  $("#table").innerHTML =
    `<thead><tr><th>Venue</th><th>Fill</th><th class="num">Inside</th><th class="num">Staff</th></tr></thead><tbody>` +
    rows
      .map(
        ({ v, occ, staff, fill }) =>
          `<tr><td>${v.name}</td><td><div class="meter"><i style="width:${Math.min(100, fill * 100)}%;background:${stressColor(renderer.pal, fill)}"></i></div></td><td class="num">${fmt(occ)}</td><td class="num">${staff}</td></tr>`,
      )
      .join("") +
    "</tbody>";
  tl.set([{ label: "Staff needed", color: css("--accent"), data: staffSeries }], world.minuteIndex + 1);
}
setInterval(refresh, 400);
refresh();
