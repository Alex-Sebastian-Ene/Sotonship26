// Where an ashore passenger goes next.
//
// The RL policy lives in the Python backend (src/sotonship26/rl). The frontend only needs the
// decision interface, so every simulation talks to a Policy:
//
//   decide(agent, ctx) -> { choice: nodeId, probs: [[nodeId, p], ...], utilities: {...} }
//
// HeuristicPolicy is a multinomial-logit gravity model that stands in until the trained policy is
// exported; ReplayPolicy plays back decisions recorded in a trace file (see docs/simulations).

export const PERSONAS = {
  rail: {
    label: "Rail transfer",
    shape: "circle",
    prefs: { food: 0.7, drink: 0.1, retail: 0.25, culture: 0.05, park: 0.05 },
    maxVisits: 1,
    leave: 1.6,
    speed: 1.15, // luggage
    dwellMul: 0.6,
  },
  diner: {
    label: "Diner",
    shape: "square",
    prefs: { food: 1.6, drink: 0.9, retail: 0.3, culture: 0.3, park: 0.3 },
    maxVisits: 3,
    leave: 0.1,
    speed: 1.3,
    dwellMul: 1.1,
  },
  shopper: {
    label: "Shopper",
    shape: "diamond",
    prefs: { food: 0.6, drink: 0.3, retail: 1.8, culture: 0.2, park: 0.2 },
    maxVisits: 3,
    leave: 0.1,
    speed: 1.3,
    dwellMul: 1,
  },
  explorer: {
    label: "Sightseer",
    shape: "triangle",
    prefs: { food: 0.6, drink: 0.4, retail: 0.3, culture: 1.7, park: 1.2 },
    maxVisits: 4,
    leave: 0,
    speed: 1.35,
    dwellMul: 0.9,
  },
  crew: {
    label: "Crew shore leave",
    shape: "cross",
    prefs: { food: 0.8, drink: 1.5, retail: 1.0, culture: 0, park: 0.4 },
    maxVisits: 2,
    leave: 0.2,
    speed: 1.45,
    dwellMul: 0.9,
  },
  embark: {
    label: "Boarding passenger",
    shape: "ring",
    prefs: { food: 0.9, drink: 0.4, retail: 0.2, culture: 0.1, park: 0.1 },
    maxVisits: 1,
    leave: 1.2,
    speed: 1.15,
    dwellMul: 0.6,
  },
};

export const PERSONA_ORDER = ["rail", "diner", "shopper", "explorer", "crew", "embark"];

export const DEFAULT_WEIGHTS = {
  walk: 0.09, // utility lost per walking minute
  crowd: 2.4, // penalty once a venue passes 75% full
  size: 0.6, // gravity: bigger clusters draw more people
  meal: 0.8, // food bonus 11:30-14:00
  evening: 0.6, // drink bonus after 16:00
  temperature: 0.7,
};

export class HeuristicPolicy {
  constructor(weights = {}) {
    this.name = "Gravity model (placeholder for the RL policy)";
    this.w = { ...DEFAULT_WEIGHTS, ...weights };
  }

  decide(agent, ctx) {
    const { graph, now, occupancy, rng } = ctx;
    const p = PERSONAS[agent.persona];
    const w = this.w;
    const here = agent.at;
    const hour = now / 3600;
    const options = [];

    const toSink = graph.walkMinutes(here, agent.sink, agent.speed);
    const left = (agent.deadline - now) / 60;
    const used = 1 - Math.max(0, left) / Math.max(1, agent.budget / 60);
    const sinkOption = {
      id: agent.sink,
      u: p.leave + 0.5 * agent.visits.length + 2.2 * used * used - w.walk * 0.25 * toSink,
    };
    // Someone still on their own ship only "goes back" once they have been somewhere.
    const onBoard = here === agent.sink && agent.visits.length === 0;
    if (!onBoard) options.push(sinkOption);

    if (agent.visits.length < p.maxVisits) {
      for (const v of graph.venues) {
        if (agent.visits.includes(v.id) || agent.avoid?.has(v.id)) continue;
        const walk = graph.walkMinutes(here, v.id, agent.speed);
        const back = graph.walkMinutes(v.id, agent.sink, agent.speed);
        if (walk + v.dwell * p.dwellMul * 0.6 + back > left) continue; // can't make the ship/train
        const fill = (occupancy.get(v.id) ?? 0) / v.capacity;
        let u = p.prefs[v.category] * (1 + w.size * Math.log10(v.capacity / 100));
        u -= w.walk * walk;
        u -= w.crowd * Math.max(0, fill - 0.75) * 4;
        if (v.category === "food" && hour >= 11.5 && hour <= 14) u += w.meal;
        if (v.category === "drink" && hour >= 16) u += w.evening;
        if (ctx.weather === "rain" && (v.category === "park")) u -= 1.5;
        if (ctx.weather === "rain" && (v.category === "retail" || v.category === "culture")) u += 0.5;
        options.push({ id: v.id, u });
      }
    }

    if (!options.length) options.push(sinkOption);
    const t = w.temperature;
    const max = Math.max(...options.map((o) => o.u));
    const ex = options.map((o) => Math.exp((o.u - max) / t));
    const z = ex.reduce((a, b) => a + b, 0);
    const probs = options.map((o, i) => [o.id, ex[i] / z]);
    const choice = probs[rng.weighted(probs.map((q) => q[1]))][0];
    return { choice, probs, utilities: Object.fromEntries(options.map((o) => [o.id, o.u])) };
  }
}

// Plays back decisions from a trace (the backend's output, or one this frontend exported). Falls
// back to `fallback` once an agent runs past its recorded decisions.
export class ReplayPolicy {
  constructor(trace, fallback = new HeuristicPolicy()) {
    this.name = `Replay: ${trace.meta?.policy ?? "trace"}`;
    this.byAgent = new Map(trace.agents.map((a) => [a.id, a.decisions ?? []]));
    this.fallback = fallback;
  }

  decide(agent, ctx) {
    const rec = this.byAgent.get(agent.traceId ?? agent.id)?.[agent.decisionCount];
    if (!rec) return this.fallback.decide(agent, ctx);
    const probs = rec.probs ? Object.entries(rec.probs) : [[rec.choice, 1]];
    return { choice: rec.choice, probs, utilities: {} };
  }
}
