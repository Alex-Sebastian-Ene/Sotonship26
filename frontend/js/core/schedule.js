// Ship calls and the passengers they put ashore.
//
// SAMPLE_DAY is SYNTHETIC: realistic-looking ship sizes and times, not a real VTS schedule. The
// timing shapes mirror src/sotonship26/demand/passengers.py (disembark 45 min after alongside over
// ~210 min, embark from 6 h to 1.5 h before departure) so the backend and the visuals agree.

export const SAMPLE_DAY = {
  label: "Sample turnaround Saturday (synthetic)",
  synthetic: true,
  ships: [
    { id: "s1", name: "Ventura-class", terminal: "T_OCEAN", arrive: "06:15", depart: "16:30", pax: 3100, crew: 1200, type: "turnaround" },
    { id: "s2", name: "Oasis-class", terminal: "T_HOR", arrive: "06:45", depart: "17:00", pax: 5400, crew: 2100, type: "turnaround" },
    { id: "s3", name: "Iona-class", terminal: "T_MAY", arrive: "07:00", depart: "17:30", pax: 5200, crew: 1800, type: "turnaround" },
    { id: "s4", name: "Explorer-class (port call)", terminal: "T_QE2", arrive: "08:00", depart: "18:00", pax: 1900, crew: 900, type: "transit" },
  ],
};

export const TERMINAL_NAMES = {
  T_MAY: "Mayflower",
  T_HOR: "Horizon",
  T_CITY: "City",
  T_OCEAN: "Ocean",
  T_QE2: "QEII",
};

export function hhmm(s) {
  const [h, m] = s.split(":").map(Number);
  return (h * 60 + m) * 60;
}

export function clock(seconds) {
  const m = Math.floor(seconds / 60);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export const DEFAULT_PARAMS = {
  walkShare: 0.3, // matches configs/default.yaml streets.walk_share
  loadFactor: 0.9,
  peoplePerAgent: 4,
  crewAshore: 0.2,
  transitAshore: 0.75,
  disembarkStartMin: 45,
  disembarkDurationMin: 210,
  embarkOpenMin: 360,
  embarkCloseMin: 90,
};

const DISEMBARK_MIX = [
  ["rail", 0.42],
  ["diner", 0.2],
  ["shopper", 0.2],
  ["explorer", 0.18],
];
const TRANSIT_MIX = [
  ["diner", 0.3],
  ["shopper", 0.3],
  ["explorer", 0.4],
];
const ONWARD = [
  ["X_RAIL", 0.78],
  ["X_RF", 0.14],
  ["X_HYTHE", 0.08],
];

function draw(rng, mix) {
  return mix[rng.weighted(mix.map((m) => m[1]))][0];
}

// Every agent a ship will put on the streets today: when, where from, who, heading where, and by
// when they must be there. Sorted by spawn time.
export function planShip(ship, rng, params = DEFAULT_PARAMS, opts = {}) {
  const P = { ...DEFAULT_PARAMS, ...params };
  const out = [];
  const arrive = hhmm(ship.arrive);
  const depart = hhmm(ship.depart);
  const ppa = P.peoplePerAgent;
  const agentsFor = (people) => Math.round(people / ppa);
  const delay = rng.normal(0, 20) * 60;

  if (ship.type === "turnaround") {
    const walkers = ship.pax * P.loadFactor * P.walkShare;
    const n = agentsFor(walkers);
    for (let i = 0; i < n; i++) {
      const t = arrive + delay + (P.disembarkStartMin + P.disembarkDurationMin * rng.beta(2, 3)) * 60;
      const persona = draw(rng, DISEMBARK_MIX);
      const sink = persona === "rail" ? "X_RAIL" : draw(rng, ONWARD);
      const budget = persona === "rail" ? rng.uniform(30, 70) * 60 : rng.lognormal(160, 0.35) * 60;
      out.push({ t, origin: ship.terminal, persona, sink, deadline: t + budget, ship: ship.id });
    }
    if (!opts.disembarkOnly) {
      const m = agentsFor(ship.pax * P.loadFactor * P.walkShare * 0.8);
      const lo = depart - P.embarkOpenMin * 60;
      const hi = depart - P.embarkCloseMin * 60;
      for (let i = 0; i < m; i++) {
        const arriveAtTerminal = lo + (hi - lo) * rng.beta(2, 2);
        const origin = draw(rng, ONWARD);
        const t = arriveAtTerminal - rng.uniform(20, 90) * 60;
        out.push({ t, origin, persona: "embark", sink: ship.terminal, deadline: hi, ship: ship.id });
      }
    }
  } else {
    const n = agentsFor(ship.pax * P.loadFactor * P.transitAshore * 0.55);
    for (let i = 0; i < n; i++) {
      const t = arrive + delay + (30 + 120 * rng.beta(2, 4)) * 60;
      out.push({
        t,
        origin: ship.terminal,
        persona: draw(rng, TRANSIT_MIX),
        sink: ship.terminal,
        deadline: depart - 45 * 60,
        ship: ship.id,
      });
    }
  }

  if (!opts.disembarkOnly) {
    const c = agentsFor(ship.crew * P.crewAshore);
    for (let i = 0; i < c; i++) {
      const t = arrive + rng.uniform(150, 330) * 60;
      const deadline = Math.min(t + rng.uniform(120, 220) * 60, depart - 60 * 60);
      if (deadline - t < 45 * 60) continue;
      out.push({ t, origin: ship.terminal, persona: "crew", sink: ship.terminal, deadline, ship: ship.id });
    }
  }
  return out;
}

export function planDay(ships, rng, params, opts) {
  return ships.flatMap((s) => planShip(s, rng, params, opts)).sort((a, b) => a.t - b.t);
}
