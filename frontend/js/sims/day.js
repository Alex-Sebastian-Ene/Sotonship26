// Turnaround Day: a whole cruise day from the schedule, ending in an hourly staffing plan.

import { Graph } from "../core/graph.js";
import { World } from "../core/world.js";
import { HeuristicPolicy } from "../core/policy.js";
import { Renderer } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { SAMPLE_DAY, planDay, clock, hhmm, TERMINAL_NAMES } from "../core/schedule.js";
import { hourlyStaff, compareRosters, WAGE_GBP } from "../core/staffing.js";
import { $, loop, legend, TimeChart, css, fmt, gbp, lineKeys, drawStaffChart } from "../core/ui.js";
import { mountBar, mapTooltips, bindRange } from "../core/page.js";

mountBar("day.html");
legend($("#legend"));

const START = hhmm("05:00");
const END = hhmm("20:00");
const graph = new Graph();
const renderer = new Renderer($("#map"), graph, { heat: false });
let world;
let seed = 26;
let speed = 360;
let venueId = "V_OX";

bindRange("speed", (v) => `${v}× · 1 h in ${Math.round(3600 / v)} s`, (v) => (speed = v));
const walkshare = bindRange("walkshare", (v) => `${Math.round(v * 100)}%`, (v, final) => final && build());
$("#weather").addEventListener("change", build);

const venueSel = $("#venue");
venueSel.innerHTML = graph.venues
  .filter((v) => v.perStaff)
  .map((v) => `<option value="${v.id}"${v.id === venueId ? " selected" : ""}>${v.name}</option>`)
  .join("");
venueSel.addEventListener("change", () => {
  venueId = venueSel.value;
  refresh();
});

const tl = new TimeChart($("#tl"), { start: START, minutes: (END - START) / 60 + 1 });
const occ = new TimeChart($("#occ"), { start: START, minutes: (END - START) / 60 + 1 });

function build() {
  const ppa = 3;
  const plan = planDay(SAMPLE_DAY.ships, new Rng(seed), { walkShare: +walkshare.value, peoplePerAgent: ppa });
  world = new World({
    graph,
    plan,
    seed,
    start: START,
    end: END,
    peoplePerAgent: ppa,
    weather: $("#weather").value,
    policy: new HeuristicPolicy(),
    meta: { schedule: SAMPLE_DAY.label },
  });
}
build();
world.advance(hhmm("08:15") - START); // open with the first ships already disembarking

function jumpTo(t) {
  if (t < world.t) build();
  while (world.t < t) world.advance(Math.min(600, t - world.t));
  refresh();
}
for (const b of document.querySelectorAll("[data-jump]")) {
  b.addEventListener("click", () => jumpTo(hhmm(b.dataset.jump)));
}
$("#restart").addEventListener("click", () => {
  seed++;
  build();
  refresh();
});

// Ship bars on the timeline, aligned with the chart's plot area (34px left gutter, 10px right).
function drawShips() {
  const el = $("#ships");
  const span = END - START;
  const pct = (t) => ((t - START) / span) * 100;
  const rows = SAMPLE_DAY.ships
    .map((s, i) => {
      const a = Math.max(START, hhmm(s.arrive));
      const d = Math.min(END, hhmm(s.depart));
      const top = i * 21 + 2;
      return `<div class="ship" style="left:calc(34px + (100% - 44px) * ${pct(a) / 100});width:calc((100% - 44px) * ${(pct(d) - pct(a)) / 100});top:${top}px" title="${s.name}: ${s.arrive} to ${s.depart}, ${s.pax.toLocaleString("en-GB")} passengers">${TERMINAL_NAMES[s.terminal]} · ${s.name} · ${s.type === "transit" ? "port call" : "turnaround"} · ${s.pax.toLocaleString("en-GB")}</div>`;
    })
    .join("");
  el.style.height = `${SAMPLE_DAY.ships.length * 21 + 4}px`;
  el.innerHTML = rows + `<div class="now" id="now"></div>`;
}
drawShips();

const playBtn = $("#play");
const l = loop((dt) => {
  if (!world.done) world.advance(dt * speed);
  renderer.draw(world, { selectedNode: venueId });
  $("#clock").textContent = clock(world.t);
  const now = $("#now");
  if (now) now.style.left = `calc(34px + (100% - 44px) * ${(world.t - START) / (END - START)})`;
});
playBtn.addEventListener("click", () => {
  l.running = !l.running;
  playBtn.textContent = l.running ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(l.running));
});
$("#reset-view").addEventListener("click", () => renderer.resetView());
mapTooltips(renderer, () => world);
renderer.on("pick", (hit) => {
  if (hit?.type === "node" && hit.node.kind === "venue" && hit.node.perStaff) {
    venueId = hit.node.id;
    venueSel.value = venueId;
    refresh();
  }
});

function rosterFor(v, upTo) {
  const hours = hourlyStaff(v, world.venueStats.get(v.id).series, START, upTo);
  return { hours, cmp: compareRosters(hours) };
}

function refresh() {
  const m = world.minuteIndex + 1;
  let walking = 0;
  for (const a of world.agents) if (a.state === "walk") walking++;
  const alongside = SAMPLE_DAY.ships.filter((s) => hhmm(s.arrive) <= world.t && world.t < hhmm(s.depart)).length;
  $("#sub").textContent = `${alongside} ship${alongside === 1 ? "" : "s"} alongside · ${fmt(world.agents.length * world.ppa)} ashore · ${fmt(walking * world.ppa)} walking`;

  const v = graph.node(venueId);
  const { hours, cmp } = rosterFor(v, m);
  drawStaffChart($("#staff"), hours, cmp.flat, Math.floor(world.t / 3600));
  $("#st-fc").textContent = fmt(cmp.forecastHours);
  $("#st-flat").textContent = fmt(cmp.flatHours);
  $("#st-save").textContent = gbp(Math.max(0, cmp.savedGBP));
  const s = world.venueStats.get(venueId);
  $("#st-away").textContent = fmt(s.turnedAway);
  $("#st-note").textContent =
    `Columns: staff the forecast says ${v.name} needs each hour (90th-percentile occupancy ÷ ${v.perStaff} customers per staff, minimum 2). Dashed line: staffing for the peak all day, which is what businesses do without a forecast. Wage £${WAGE_GBP}/h.`;
  occ.capacity = v.capacity;
  occ.set([{ label: v.name, color: css("--accent"), data: s.series }], m);

  const lines = [
    { label: "Walking", color: css("--p-rail"), data: world.series.walking },
    { label: "In venues", color: css("--p-diner"), data: world.series.dwelling },
  ];
  tl.set(lines, m);
  $("#tl-legend").innerHTML = lineKeys(lines);

  const rows = graph.venues
    .filter((x) => x.perStaff)
    .map((x) => {
      const st = world.venueStats.get(x.id);
      const r = rosterFor(x, m);
      return { x, st, r };
    })
    .sort((a, b) => b.st.peak / b.x.capacity - a.st.peak / a.x.capacity);
  $("#table").innerHTML =
    `<thead><tr><th>Venue</th><th class="num">Peak</th><th class="num">Peak staff</th><th class="num">Spend</th><th class="num">Saved</th></tr></thead><tbody>` +
    rows
      .map(
        ({ x, st, r }) =>
          `<tr data-id="${x.id}" class="${x.id === venueId ? "sel" : ""}"><td>${x.name}</td><td class="num">${fmt(st.peak)}/${fmt(x.capacity)}</td><td class="num">${r.cmp.flat}</td><td class="num">${gbp(st.revenue)}</td><td class="num">${gbp(Math.max(0, r.cmp.savedGBP))}</td></tr>`,
      )
      .join("") +
    "</tbody>";
}
$("#table").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (!tr) return;
  venueId = tr.dataset.id;
  venueSel.value = venueId;
  refresh();
});
setInterval(refresh, 400);
refresh();

$("#csv").addEventListener("click", () => {
  const lines = ["venue,hour,p90_occupancy,peak_occupancy,staff_needed"];
  for (const v of graph.venues.filter((x) => x.perStaff)) {
    for (const h of rosterFor(v, world.minuteIndex + 1).hours) {
      if (h.staff === null) continue;
      lines.push(`"${v.name}",${String(h.hour).padStart(2, "0")}:00,${h.p90},${h.peak},${h.staff}`);
    }
  }
  const blob = new Blob([`# Gangway forecast, SYNTHETIC schedule, seed ${seed}\n` + lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `gangway-staffing-seed${seed}.csv`;
  a.click();
});
