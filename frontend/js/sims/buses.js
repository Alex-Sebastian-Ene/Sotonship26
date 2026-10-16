// Buses: timetabled lines, lateness, stop queues and what late buses do to passengers.

import { Graph } from "../core/graph.js";
import { World } from "../core/world.js";
import { Renderer, stressColor } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { BUS_META } from "../core/transit.js";
import { SAMPLE_DAY, planDay, clock, hhmm } from "../core/schedule.js";
import { $, loop, legend, TimeChart, css, fmt } from "../core/ui.js";
import { mountBar, mapTooltips, bindRange, pill } from "../core/page.js";

mountBar("buses.html");
legend($("#legend"));

const START = hhmm("05:30");
const END = hhmm("20:00");
const graph = new Graph();
const renderer = new Renderer($("#map"), graph, { flows: false });
let world;
let seed = 26;
let speed = 240;
let stop = "X_RAIL";
let selectedLine = null;
let selectedBus = null;

const extra = bindRange("extra", (v) => (v ? `+${v} min` : "as profiled"), (v, final) => final && build(true));
bindRange("speed", (v) => `${v}×`, (v) => (speed = v));

function build(keepTime = false) {
  const t = keepTime && world ? world.t : hhmm("09:00");
  const off = $("#buses-off").getAttribute("aria-pressed") === "true";
  const plan = planDay(SAMPLE_DAY.ships, new Rng(seed), { peoplePerAgent: 3 });
  world = new World({
    graph,
    plan,
    seed,
    start: START,
    end: END,
    peoplePerAgent: 3,
    buses: off ? null : { extraDelayMin: +extra.value },
  });
  world.advance(t - START); // re-run the same seeded day up to now, so changes compare like with like
  fillStops();
  refresh();
}

function fillStops() {
  const sel = $("#stop");
  if (!world.transit) {
    sel.innerHTML = "";
    return;
  }
  if (sel.options.length) return;
  sel.innerHTML = [...world.transit.stops]
    .map((id) => `<option value="${id}"${id === stop ? " selected" : ""}>${graph.node(id).name}</option>`)
    .join("");
}
$("#stop").addEventListener("change", (e) => {
  stop = e.target.value;
  refresh();
});
$("#restart").addEventListener("click", () => {
  seed++;
  build();
});
$("#buses-off").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  build(true);
});

$("#late-key").innerHTML = [
  ["On time (≤1 min)", renderer.pal.good],
  ["1–3 min late", renderer.pal.warning],
  ["3–5 min", renderer.pal.serious],
  ["Over 5 min", renderer.pal.critical],
]
  .map(([t, c]) => pill(t, c))
  .join("");

mapTooltips(renderer, () => world);
renderer.on("pick", (hit) => {
  selectedBus = hit?.type === "bus" ? hit.bus : null;
  if (hit?.type === "bus") selectedLine = hit.bus.line.id;
  if (hit?.type === "node" && world.transit?.stops.has(hit.node.id)) {
    stop = hit.node.id;
    $("#stop").value = stop;
  }
  refresh();
});

const playBtn = $("#play");
const l = loop((dt) => {
  if (!world.done) world.advance(dt * speed);
  if (selectedBus?.state === "done") selectedBus = null;
  renderer.draw(world, { selectedStop: stop, selectedLine, selectedBus });
  $("#clock").textContent = clock(world.t);
});
playBtn.addEventListener("click", () => {
  l.running = !l.running;
  playBtn.textContent = l.running ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(l.running));
});
$("#reset-view").addEventListener("click", () => renderer.resetView());

const tl = new TimeChart($("#tl"), { start: START, minutes: (END - START) / 60 + 1 });
const waitChart = new TimeChart($("#wait-chart"), { start: START, minutes: (END - START) / 60 + 1 });

$("#data-note").textContent = `${BUS_META.source} (${BUS_META.collected}). ${
  BUS_META.synthetic
    ? "The lines are schematic corridors on our own street graph and the lateness profile is made up: later in the peaks and on the dock roads on cruise mornings. bustimes.org was not reachable when this was built; scripts/bustimes.py collects real lateness and exports it in the same format."
    : `Licence: ${BUS_META.licence}.`
}`;
if (!BUS_META.synthetic) $("#data-chip").textContent = `bustimes.org lateness · collected ${BUS_META.collected}`;

function boardHtml() {
  const tr = world.transit;
  if (!tr) return `<div class="b-head"><span>No buses</span></div><div class="b-dim">Buses are switched off for this run.</div>`;
  const rows = tr.board(stop);
  const head = `<div class="b-head"><span>${graph.node(stop).name}</span><span>${clock(world.t)}</span></div>`;
  if (!rows.length) return head + `<div class="b-dim">No more departures in the next 45 minutes</div>`;
  return (
    head +
    rows
      .map((r) => {
        const mins = Math.round((r.expected - world.t) / 60);
        const when = mins <= 0 ? "Due" : `${mins} min`;
        const note = r.tracked && r.delay > 1 ? ` <span class="b-dim">exp ${clock(r.expected)}</span>` : "";
        return `<div class="b-row"><span>${r.line}</span><span>${r.dest}${note}</span><span>${r.tracked ? when : clock(r.due)}</span></div>`;
      })
      .join("")
  );
}

function lineRows() {
  const tr = world.transit;
  if (!tr) return "";
  const by = new Map(tr.lines.map((x) => [x.id, []]));
  for (const r of tr.records) by.get(r.line)?.push(r.delayMin);
  const onRoad = new Map();
  for (const b of tr.buses) onRoad.set(b.line.id, (onRoad.get(b.line.id) ?? 0) + 1);
  return (
    `<thead><tr><th>Line</th><th class="num">Buses out</th><th class="num">Mean late</th><th class="num">90% within</th><th class="num">&gt;5 min</th></tr></thead><tbody>` +
    tr.lines
      .map((line) => {
        const xs = by.get(line.id).sort((a, b) => a - b);
        const mean = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
        const p90 = xs.length ? xs[Math.floor(xs.length * 0.9)] : 0;
        const over = xs.length ? xs.filter((x) => x > 5).length / xs.length : 0;
        return `<tr data-line="${line.id}" class="${line.id === selectedLine ? "sel" : ""}"><td><b>${line.id}</b> ${line.name}</td><td class="num">${onRoad.get(line.id) ?? 0}</td><td class="num">${mean.toFixed(1)} min</td><td class="num">${p90.toFixed(1)} min</td><td class="num">${Math.round(over * 100)}%</td></tr>`;
      })
      .join("") +
    "</tbody>"
  );
}
$("#lines").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-line]");
  if (!tr) return;
  selectedLine = selectedLine === tr.dataset.line ? null : tr.dataset.line;
  refresh();
});

function refresh() {
  const tr = world.transit;
  $("#board").innerHTML = boardHtml();
  $("#lines").innerHTML = lineRows();
  $("#s-board").textContent = fmt((tr?.totals.boardings ?? 0) * world.ppa);
  $("#s-gave").textContent = fmt((tr?.totals.gaveUp ?? 0) * world.ppa);
  let waiting = 0;
  for (const a of world.agents) if (a.state === "wait") waiting++;
  $("#s-wait").textContent = fmt(waiting * world.ppa);
  $("#s-late").textContent = fmt(world.totals.late * world.ppa);
  let riding = 0;
  for (const a of world.agents) if (a.state === "ride") riding++;
  $("#sub").textContent = tr
    ? `${tr.buses.length} buses on the road · ${fmt(riding * world.ppa)} riding · ${fmt(waiting * world.ppa)} waiting`
    : "No buses: everyone walks";
  const m = world.minuteIndex + 1;
  if (tr) {
    tl.set([{ label: "Average lateness (min)", color: css("--accent"), data: tr.series.delay }], m);
    waitChart.set([{ label: "Waiting", color: css("--p-rail"), data: tr.series.waiting }], m);
  }
}
setInterval(refresh, 400);
build();
