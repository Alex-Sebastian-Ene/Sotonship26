// Compare: two worlds on the same seed, one lever changed, differences tallied as they happen.

import { Graph } from "../core/graph.js";
import { World } from "../core/world.js";
import { HeuristicPolicy } from "../core/policy.js";
import { Renderer } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { SAMPLE_DAY, planDay, clock, hhmm } from "../core/schedule.js";
import { $, loop, legend, TimeChart, css, fmt, gbp, lineKeys } from "../core/ui.js";
import { mountBar, mapTooltips, bindRange } from "../core/page.js";

mountBar("compare.html");
legend($("#legend"));

const BASE_SHIPS = SAMPLE_DAY.ships.filter((s) => s.id !== "s3");
const EXTRA_SHIP = SAMPLE_DAY.ships.find((s) => s.id === "s3");

// Each lever maps to something the backend env can also do: edge cost scaling and closures are
// its steering action, a longer disembarkation is its metering action.
export const SCENARIOS = {
  baseline: { label: "Baseline", desc: "Three ships, dry day, everyone takes the shortest path." },
  rain: { label: "Rain", weather: "rain", desc: "Parks lose their pull; shops and SeaCity Museum gain it." },
  stagger: {
    label: "Staggered disembarkation",
    params: { disembarkDurationMin: 330 },
    desc: "Ships release walkers over 5.5 hours instead of 3.5. This is the metering lever in the RL environment.",
  },
  canute: {
    label: "Canute Road closed",
    close: [["G4", "J_CAN"]],
    desc: "Event closure between Dock Gate 4 and Ocean Village. Walkers from Ocean and QEII must go round.",
  },
  steer: {
    label: "Stewards at Dock Gate 4",
    scale: [["G4", "J_OXE", 4], ["G4", "J_GHT", 0.6]],
    desc: "Stewards push walkers from Ocean and QEII along Platform Road rather than Terminus Terrace. This is the steering lever.",
  },
  avoid: {
    label: "Crowd-aware wayfinding",
    congestionRouting: true,
    desc: "Every walker routes around crowded footways, as if following a live wayfinding app.",
  },
  extra: { label: "Fourth ship at Mayflower", ships: [EXTRA_SHIP], desc: "Adds a 5,200-passenger turnaround at Mayflower." },
  walkmore: {
    label: "Rail disruption (45% walk)",
    params: { walkShare: 0.45 },
    desc: "Fewer coach transfers, so more passengers walk to the station and the ferries.",
  },
};

const START = hhmm("06:30");
const END = hhmm("17:30");
let seed = 26;
let speed = 240;
const sides = {
  a: { key: "baseline", graph: new Graph() },
  b: { key: "canute", graph: new Graph() },
};
sides.a.renderer = new Renderer($("#map-a"), sides.a.graph);
sides.b.renderer = new Renderer($("#map-b"), sides.b.graph);

for (const id of ["a", "b"]) {
  const sel = $(`#sc-${id}`);
  sel.innerHTML = Object.entries(SCENARIOS)
    .map(([k, s]) => `<option value="${k}"${k === sides[id].key ? " selected" : ""}>${s.label}</option>`)
    .join("");
  sel.addEventListener("change", () => {
    sides[id].key = sel.value;
    build();
  });
  mapTooltips(sides[id].renderer, () => sides[id].world);
}
bindRange("speed", (v) => `${v}×`, (v) => (speed = v));

function edgeBetween(graph, a, b) {
  return graph.edges.find((e) => (e.a === a && e.b === b) || (e.a === b && e.b === a));
}

function buildSide(side) {
  const sc = SCENARIOS[side.key];
  const g = side.graph;
  for (const e of g.edges) e.cost = 1;
  for (const [a, b] of sc.close ?? []) edgeBetween(g, a, b).cost = 1e6;
  for (const [a, b, k] of sc.scale ?? []) edgeBetween(g, a, b).cost = k;
  g.invalidatePaths();
  const ships = [...BASE_SHIPS, ...(sc.ships ?? [])];
  const plan = planDay(ships, new Rng(seed), { peoplePerAgent: 3, ...(sc.params ?? {}) });
  side.world = new World({
    graph: g,
    plan,
    seed,
    start: START,
    end: END,
    peoplePerAgent: 3,
    weather: sc.weather ?? "dry",
    congestionRouting: !!sc.congestionRouting,
    policy: new HeuristicPolicy(),
  });
  side.peakEdge = 0;
  side.renderer.staticDirty = true;
}

function build() {
  buildSide(sides.a);
  buildSide(sides.b);
  $("#tag-a").textContent = `A · ${SCENARIOS[sides.a.key].label}`;
  $("#tag-b").textContent = `B · ${SCENARIOS[sides.b.key].label}`;
  $("#sc-desc").innerHTML = `<b>A:</b> ${SCENARIOS[sides.a.key].desc}<br><b>B:</b> ${SCENARIOS[sides.b.key].desc}`;
}
build();
// Start mid-morning so both maps open busy.
for (const s of Object.values(sides)) s.world.advance(hhmm("09:30") - START);

// Keep the two cameras locked together.
for (const [me, other] of [["a", "b"], ["b", "a"]]) {
  sides[me].renderer.on("pan", () => {
    const r = sides[other].renderer;
    r.cam = { ...sides[me].renderer.cam };
    r.staticDirty = true;
    r.heatClear = true;
  });
}
$("#fit").addEventListener("click", () => {
  sides.a.renderer.resetView();
  sides.b.renderer.resetView();
});
$("#rerun").addEventListener("click", () => {
  seed++;
  build();
});

const playBtn = $("#play");
const l = loop((dt) => {
  for (const s of Object.values(sides)) {
    if (!s.world.done) s.world.advance(dt * speed);
    let max = 0;
    for (const e of s.graph.edges) max = Math.max(max, e.count);
    s.peakEdge = Math.max(s.peakEdge, max * s.world.ppa);
    s.renderer.draw(s.world);
  }
  $("#clock").textContent = clock(sides.a.world.t);
});
playBtn.addEventListener("click", () => {
  l.running = !l.running;
  playBtn.textContent = l.running ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(l.running));
});

const tl = new TimeChart($("#tl"), { start: START, minutes: (END - START) / 60 + 1 });

function totals(w) {
  let away = 0;
  let spend = 0;
  for (const s of w.venueStats.values()) {
    away += s.turnedAway;
    spend += s.revenue;
  }
  return { away, spend, late: w.totals.late * w.ppa };
}

function signed(n, f = fmt) {
  if (Math.abs(n) < 0.5) return "±0";
  return `${n > 0 ? "+" : "−"}${f(Math.abs(n))}`;
}

function refresh() {
  const A = sides.a.world;
  const B = sides.b.world;
  for (const [id, s] of Object.entries(sides)) {
    let walking = 0;
    for (const a of s.world.agents) if (a.state === "walk") walking++;
    $(`#sub-${id}`).textContent = `${id.toUpperCase()}: ${fmt(walking * s.world.ppa)} walking · ${fmt((s.world.agents.length - walking) * s.world.ppa)} in venues`;
  }
  const ta = totals(A);
  const tb = totals(B);
  $("#d-foot").textContent = signed(sides.b.peakEdge - sides.a.peakEdge);
  $("#d-away").textContent = signed(tb.away - ta.away);
  $("#d-late").textContent = signed(tb.late - ta.late);
  $("#d-spend").textContent = signed(tb.spend - ta.spend, gbp);

  const rows = A.graph.venues
    .map((v) => ({ v, a: A.venueStats.get(v.id).peak, b: B.venueStats.get(v.id).peak }))
    .sort((x, y) => Math.abs(y.b - y.a) - Math.abs(x.b - x.a));
  $("#diff").innerHTML =
    `<thead><tr><th>Venue</th><th class="num">A peak</th><th class="num">B peak</th><th class="num">B − A</th></tr></thead><tbody>` +
    rows
      .map(
        ({ v, a, b }) =>
          `<tr><td>${v.name}</td><td class="num">${fmt(a)}</td><td class="num">${fmt(b)}</td><td class="num">${signed(b - a)}</td></tr>`,
      )
      .join("") +
    "</tbody>";

  const lines = [
    { label: `A · ${SCENARIOS[sides.a.key].label}`, color: css("--p-rail"), data: A.series.walking },
    { label: `B · ${SCENARIOS[sides.b.key].label}`, color: css("--p-diner"), data: B.series.walking },
  ];
  tl.set(lines, Math.min(A.minuteIndex, B.minuteIndex) + 1);
  $("#tl-legend").innerHTML = lineKeys(lines);
}
setInterval(refresh, 400);
refresh();
