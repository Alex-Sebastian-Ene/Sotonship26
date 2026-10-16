// Bus lines and lateness for the simulations.
//
// SYNTHETIC PLACEHOLDER. These four lines are schematic corridors drawn on our own street graph,
// not real bustimes.org routes, and DELAY_PROFILE is a made-up shape (later in the peaks, worse on
// the dock road on cruise mornings), not measured lateness. bustimes.org was not reachable from the
// build environment. `scripts/bustimes.py export` writes data/buses.observed.js in this same
// schema from real collected data; switch the import in js/core/transit.js to use it.
//
// stops: graph node ids in running order (the reverse direction runs them backwards).
// headwayMin: minutes between departures from each end. first/last: departures from either end.

export const BUS_META = {
  source: "Synthetic placeholder lines and lateness",
  collected: "2026-10-16",
  licence: "Own work",
  synthetic: true,
};

export const BUS_LINES = [
  {
    id: "QL",
    name: "Quayside Link",
    from: "Central Station",
    to: "Ocean Village",
    stops: ["X_RAIL", "J_HPN", "J_MRB", "J_TQ", "J_GHT", "G4", "J_OV"],
    headwayMin: 12,
    first: "06:30",
    last: "19:30",
  },
  {
    id: "AB",
    name: "Above Bar",
    from: "London Road",
    to: "Town Quay",
    stops: ["J_LON", "J_ABN", "J_ABM", "J_BAR", "J_HS2", "J_HS1", "J_TQ"],
    headwayMin: 8,
    first: "06:00",
    last: "20:00",
  },
  {
    id: "WQ",
    name: "West Quay Road",
    from: "Dock Gate 10",
    to: "St Mary Street",
    stops: ["J_WQR2", "J_WQR", "X_RAIL", "J_ABN", "J_BAR", "J_ES", "J_EAST"],
    headwayMin: 15,
    first: "06:15",
    last: "19:45",
  },
  {
    id: "EC",
    name: "Eastern Docks",
    from: "Ocean Village",
    to: "Bargate",
    stops: ["J_OV", "J_CAN", "J_OXE", "J_EAST", "J_ES", "J_BAR"],
    headwayMin: 20,
    first: "07:00",
    last: "19:00",
  },
];

// Lateness in minutes by line and hour of day: { mean, p90 }. Missing hours use DEFAULT_DELAY.
export const DEFAULT_DELAY = { mean: 1, p90: 4 };

function shape({ base, am, pm, dock = 0 }) {
  const out = {};
  for (let h = 5; h <= 21; h++) {
    let mean = base;
    if (h >= 7 && h <= 9) mean += am;
    if (h >= 16 && h <= 18) mean += pm;
    if (h >= 9 && h <= 12) mean += dock; // turnaround traffic on the dock roads
    out[h] = { mean: +mean.toFixed(1), p90: +(mean * 2.2 + 2).toFixed(1) };
  }
  return out;
}

export const DELAY_PROFILE = {
  QL: shape({ base: 1, am: 2, pm: 3, dock: 2.5 }),
  AB: shape({ base: 1.5, am: 2.5, pm: 3.5 }),
  WQ: shape({ base: 1, am: 3, pm: 4, dock: 1.5 }),
  EC: shape({ base: 0.5, am: 1, pm: 2, dock: 3 }),
};
