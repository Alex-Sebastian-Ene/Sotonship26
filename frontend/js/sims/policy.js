// Policy Lens: follow one passenger and inspect every decision the policy made for them.

import { Graph } from "../core/graph.js";
import { World, planFromTrace } from "../core/world.js";
import { HeuristicPolicy, ReplayPolicy, PERSONAS, PERSONA_ORDER } from "../core/policy.js";
import { Renderer } from "../core/render.js";
import { Rng } from "../core/rng.js";
import { planDay, clock, hhmm } from "../core/schedule.js";
import { $, loop, legend, TimeChart, css, fmt, glyph } from "../core/ui.js";
import { mountBar, mapTooltips, bindRange } from "../core/page.js";

mountBar("policy.html");
legend($("#legend"));

const SHIPS = [
  { id: "p1", name: "Port call", terminal: "T_QE2", arrive: "07:30", depart: "17:30", pax: 2400, crew: 900, type: "transit" },
  { id: "p2", name: "Turnaround", terminal: "T_CITY", arrive: "07:00", depart: "16:30", pax: 3000, crew: 1100, type: "turnaround" },
];
const graph = new Graph();
const renderer = new Renderer($("#map"), graph, { flows: false });
const policy = new HeuristicPolicy();
let world;
let followed = null;
let decisionsPerMin;
let pauseAtDecision = true;
const hidden = new Set();
let source = "live";

const W = {
  walk: bindRange("w-walk", (v) => v.toFixed(2), (v) => setW("walk", v)),
  crowd: bindRange("w-crowd", (v) => v.toFixed(1), (v) => setW("crowd", v)),
  size: bindRange("w-size", (v) => v.toFixed(2), (v) => setW("size", v)),
  temperature: bindRange("w-temp", (v) => v.toFixed(2), (v) => setW("temperature", v)),
};
function setW(k, v) {
  policy.w[k] = v;
  refreshAgent();
}

function attach(w) {
  world = w;
  followed = null;
  decisionsPerMin = new Float32Array(world.minutes);
  world.on((type, payload) => {
    if (type !== "decision") return;
    decisionsPerMin[world.minuteIndex]++;
    if (payload.agent === followed && pauseAtDecision && payload.agent.history.length > 1) {
      setRunning(false);
    }
  });
  tl.start = world.start;
  tl.minutes = world.minutes;
  refreshAgent();
}

function buildLive() {
  source = "live";
  const plan = planDay(SHIPS, new Rng(26), { peoplePerAgent: 5 });
  attach(new World({ graph, plan, policy, seed: 26, start: hhmm("07:30"), end: hhmm("18:30"), peoplePerAgent: 5 }));
  $("#policy-chip").textContent = "Gravity model · placeholder policy";
}

const tl = new TimeChart($("#tl"), { start: hhmm("07:30"), minutes: 661 });
buildLive();
// Open mid-morning with someone already ashore, so the first view shows a real decision.
world.advance(hhmm("09:40") - world.t);

// Persona filter chips
$("#persona-filter").innerHTML = PERSONA_ORDER.map(
  (id) =>
    `<button class="btn" type="button" data-persona="${id}" aria-pressed="true"><svg width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">${glyph(PERSONAS[id].shape, `var(--p-${id})`)}</svg>${PERSONAS[id].label}</button>`,
).join("");
$("#persona-filter").addEventListener("click", (e) => {
  const b = e.target.closest("[data-persona]");
  if (!b) return;
  const id = b.dataset.persona;
  hidden.has(id) ? hidden.delete(id) : hidden.add(id);
  b.setAttribute("aria-pressed", String(!hidden.has(id)));
});

function follow(a) {
  followed = a;
  $("#agent-card").hidden = !a;
  refreshAgent();
}
$("#random").addEventListener("click", () => {
  const pool = world.agents.filter((a) => !hidden.has(a.persona));
  if (pool.length) follow(pool[Math.floor(Math.random() * pool.length)]);
});
$("#unfollow").addEventListener("click", () => follow(null));
$("#stop-at").addEventListener("click", (e) => {
  pauseAtDecision = !pauseAtDecision;
  e.currentTarget.setAttribute("aria-pressed", String(pauseAtDecision));
});
renderer.on("pick", (hit) => {
  if (hit?.type === "agent") follow(hit.agent);
});
mapTooltips(renderer, () => world);

const playBtn = $("#play");
let l;
function setRunning(v) {
  l.running = v;
  playBtn.textContent = v ? "Pause" : "Play";
  playBtn.setAttribute("aria-pressed", String(v));
}
playBtn.addEventListener("click", () => setRunning(!l.running));
$("#reset-view").addEventListener("click", () => {
  renderer.resetView();
});

{
  const pool = world.agents.filter((a) => a.state === "walk" && a.history.length > 1 && a.persona !== "rail");
  if (pool.length) follow(pool[Math.floor(pool.length / 2)]);
}

l = loop((dt) => {
  if (!world.done) world.advance(dt * 60);
  if (followed?.state === "done") {
    $("#sub").textContent = `Passenger #${followed.id} reached ${graph.node(followed.sink).name}`;
    followed = null;
  }
  const overlay = {};
  overlay.dim = (a) => hidden.has(a.persona) || (followed && a !== followed);
  if (followed) {
    const last = followed.history[followed.history.length - 1];
    const at = graph.node(last.at);
    overlay.fan = { from: renderer.toScreen(at.x, at.y), probs: last.probs, chosen: last.choice };
    overlay.selectedAgent = followed;
    overlay.history = [followed.origin, ...followed.visits, ...(followed.state === "walk" ? [] : [followed.at])];
    if (followed.state === "walk") overlay.path = followed.path.segs.slice(followed.si);
    renderer.centerOn(followed.x, followed.y, 0.04);
  }
  renderer.draw(world, overlay);
  $("#clock").textContent = clock(world.t);
});

function probRows(probs, chosen) {
  return [...probs]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(
      ([id, p]) =>
        `<div class="p${id === chosen ? " chosen" : ""}"><span>${graph.node(id)?.name ?? id}</span><div class="meter"><i style="width:${p * 100}%;background:${id === chosen ? "var(--accent)" : "var(--seq-4)"}"></i></div><span class="num">${Math.round(p * 100)}%</span></div>`,
    )
    .join("");
}

function refreshAgent() {
  const a = followed;
  if (!a) return;
  const p = PERSONAS[a.persona];
  $("#ag-title").textContent = `Passenger #${a.id} · ${p.label}`;
  $("#ag-sink").textContent = graph.node(a.sink).name;
  $("#ag-deadline").textContent = clock(a.deadline);
  $("#ag-visits").textContent = a.visits.length;
  $("#ag-dec").textContent = a.history.length;
  const last = a.history[a.history.length - 1];
  let html = `<div class="note">${clock(last.t)} at ${graph.node(last.at).name}, as decided</div>` + probRows(last.probs, last.choice);
  if (source === "live" && a.state !== "done") {
    const now = policy.decide(a, {
      graph,
      now: world.t,
      occupancy: world.occupancy,
      rng: new Rng(1),
      weather: world.weather,
    });
    const here = a.state === "walk" ? `walking from ${graph.node(a.at).name}` : `at ${graph.node(a.at).name}`;
    html += `<div class="note" style="margin-top:8px">If they chose again now (${here}) with the weights below</div>` + probRows(now.probs, null);
  }
  $("#ag-probs").innerHTML = html;
  $("#ag-log").innerHTML = a.history
    .map((h) => {
      const p = h.probs.find(([id]) => id === h.choice)?.[1] ?? 1;
      return `<div class="p"><span>${clock(h.t)} ${graph.node(h.at).name} → ${graph.node(h.choice).name}</span><span></span><span class="num">${Math.round(p * 100)}%</span></div>`;
    })
    .join("");
}

function refresh() {
  refreshAgent();
  const m = world.minuteIndex + 1;
  tl.set([{ label: "Decisions", color: css("--accent"), data: decisionsPerMin }], m);
  let served = 0;
  let away = 0;
  for (const s of world.venueStats.values()) {
    served += s.arrivals;
    away += s.turnedAway;
  }
  $("#ep-dec").textContent = fmt(world.totals.decisions);
  $("#ep-served").textContent = fmt(served);
  $("#ep-away").textContent = fmt(away);
  $("#ep-late").textContent = fmt(world.totals.late * world.ppa);
  if (followed) {
    const doing =
      followed.state === "walk" ? `walking to ${graph.node(followed.target).name}` : `at ${graph.node(followed.at).name}`;
    $("#sub").textContent = `Following #${followed.id} · ${doing}${l.running ? "" : " · paused"}`;
  }
}
setInterval(refresh, 300);

// ---- traces ------------------------------------------------------------------------------------

function loadTrace(text, name) {
  let trace;
  try {
    trace = JSON.parse(text);
  } catch {
    $("#trace-status").textContent = `${name} is not valid JSON.`;
    return;
  }
  if (!trace?.meta || !Array.isArray(trace.agents)) {
    $("#trace-status").textContent = `${name} has no "meta" and "agents"; see docs/simulations/03-policy-lens.md for the format.`;
    return;
  }
  const unknown = trace.agents.find((a) => !graph.node(a.origin) || !graph.node(a.sink) || !PERSONAS[a.persona]);
  if (unknown) {
    $("#trace-status").textContent = `Agent ${unknown.id} names a node or persona this map does not have (${unknown.origin} → ${unknown.sink}, ${unknown.persona}).`;
    return;
  }
  source = "trace";
  const m = trace.meta;
  attach(
    new World({
      graph,
      plan: planFromTrace(trace),
      policy: new ReplayPolicy(trace, policy),
      seed: m.seed ?? 26,
      start: m.start ?? hhmm("07:30"),
      end: m.end ?? hhmm("18:30"),
      peoplePerAgent: m.peoplePerAgent ?? 5,
      meta: { replayOf: name },
    }),
  );
  $("#policy-chip").textContent = `Replay · ${m.policy ?? name}${m.synthetic ? " · synthetic" : ""}`;
  $("#trace-status").textContent = `Replaying ${trace.agents.length} agents from ${name}.`;
}

$("#file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (f) loadTrace(await f.text(), f.name);
});
const drop = $("#drop");
drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("over");
});
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", async (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  const f = e.dataTransfer.files[0];
  if (f) loadTrace(await f.text(), f.name);
});
$("#live").addEventListener("click", () => {
  buildLive();
  $("#trace-status").textContent = "Back on the live gravity model.";
});
$("#export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(world.exportTrace())], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `gangway-trace-${clock(world.t).replace(":", "")}.json`;
  a.click();
  $("#trace-status").textContent = "Trace exported. Downloads are blocked when this page runs inside a sandboxed preview.";
});
