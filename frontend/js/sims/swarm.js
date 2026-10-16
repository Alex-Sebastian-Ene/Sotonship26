// Swarm: one turnaround ship disembarks and its walkers spread through the city in real time.

import { Graph } from "../core/graph.js";
import { World } from "../core/world.js";
import { HeuristicPolicy } from "../core/policy.js";
import { Renderer } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { planShip, clock, hhmm } from "../core/schedule.js";
import { $, loop, legend, TimeChart, css, fmt, lineKeys } from "../core/ui.js";
import { mountBar, venueRows, venueTableHead, mapTooltips, bindRange } from "../core/page.js";

mountBar("swarm.html");
legend($("#legend"));

const graph = new Graph();
const renderer = new Renderer($("#map"), graph);
let world;
let selected = null;
let speed = 90;
let seed = 26;

const S = {
  pax: bindRange("pax", (v) => v.toLocaleString("en-GB")),
  walk: bindRange("walk", (v) => `${Math.round(v * 100)}%`),
  ppa: bindRange("ppa", (v) => `${v}`),
  temp: bindRange("temp", (v) => v.toFixed(1)),
};
bindRange("speed", (v) => `${v}× real time`, (v) => (speed = v));

function build() {
  const terminal = $("#terminal").value;
  const ship = { id: "s1", name: "Ship", terminal, arrive: "08:00", depart: "18:00", pax: +S.pax.value, crew: 0, type: "turnaround" };
  const ppa = +S.ppa.value;
  const plan = planShip(ship, new Rng(seed), { walkShare: +S.walk.value, peoplePerAgent: ppa }, { disembarkOnly: true });
  world = new World({
    graph,
    plan,
    seed,
    peoplePerAgent: ppa,
    start: hhmm("08:30"),
    end: hhmm("15:00"),
    policy: new HeuristicPolicy({ temperature: +S.temp.value }),
    congestionRouting: $("#congestion").getAttribute("aria-pressed") === "true",
  });
  world.advance(hhmm("09:00") - world.start); // open with the first walkers already ashore
  if (renderer.opts.isochrone) renderer.set({ isochrone: terminal });
  renderer.staticDirty = true;
  chart.start = world.start;
  chart.minutes = world.minutes;
  if (selected) vdChart.minutes = world.minutes;
}

const chart = new TimeChart($("#tl"), { start: hhmm("08:30"), minutes: 391 });
const vdChart = new TimeChart($("#vd-chart"), { start: hhmm("08:30"), minutes: 391 });
build();

$("#restart").addEventListener("click", () => {
  seed++;
  build();
});
$("#terminal").addEventListener("change", build);

for (const b of document.querySelectorAll("[data-layer]")) {
  b.addEventListener("click", () => {
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(on));
    const layer = b.dataset.layer;
    renderer.set({ [layer]: layer === "isochrone" ? (on ? $("#terminal").value : null) : on });
  });
}
$("#congestion").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  world.congestionRouting = on;
});

const playBtn = $("#play");
const clockLoop = loop((dt) => {
  if (!world.done) world.advance(dt * speed);
  renderer.draw(world, { selectedNode: selected });
  $("#clock").textContent = clock(world.t);
});
playBtn.addEventListener("click", () => {
  clockLoop.running = !clockLoop.running;
  playBtn.textContent = clockLoop.running ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(clockLoop.running));
});
$("#reset-view").addEventListener("click", () => renderer.resetView());

mapTooltips(renderer, () => world);
renderer.on("pick", (hit) => {
  if (hit?.type === "node" && hit.node.kind === "venue") select(hit.node.id);
});

function select(id) {
  selected = selected === id ? null : id;
  $("#venue-detail").hidden = !selected;
  if (selected) $("#vd-title").textContent = graph.node(selected).name;
  refreshPanel();
}

$("#venues").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) select(tr.dataset.id);
});

function refreshPanel() {
  let walking = 0;
  let dwelling = 0;
  for (const a of world.agents) a.state === "walk" ? walking++ : dwelling++;
  const ppa = world.ppa;
  $("#s-walk").textContent = fmt(walking * ppa);
  $("#s-dwell").textContent = fmt(dwelling * ppa);
  $("#s-done").textContent = fmt(world.totals.arrived * ppa);
  let away = 0;
  for (const s of world.venueStats.values()) away += s.turnedAway;
  $("#s-away").textContent = fmt(away);
  const remaining = world.plan.length - world.pi;
  $("#sub").textContent = world.done
    ? "Day complete"
    : remaining > 0
      ? `Disembarking · ${fmt(remaining * ppa)} still aboard to walk`
      : "Everyone ashore";
  $("#venues").innerHTML = venueTableHead() + `<tbody>${venueRows(world, renderer.pal, { selected })}</tbody>`;

  const m = world.minuteIndex + 1;
  const lines = [
    { label: "Walking", color: css("--p-rail"), data: world.series.walking },
    { label: "In venues", color: css("--p-diner"), data: world.series.dwelling },
  ];
  chart.set(lines, m);
  $("#tl-legend").innerHTML = lineKeys(lines);
  if (selected) {
    const v = graph.node(selected);
    vdChart.capacity = v.capacity;
    vdChart.set([{ label: "Inside", color: css("--accent"), data: world.venueStats.get(selected).series }], m);
  }
}
setInterval(refreshPanel, 300);
refreshPanel();
