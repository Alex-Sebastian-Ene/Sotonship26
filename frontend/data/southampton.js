// Southampton city-centre walking graph for the passenger simulations.
//
// HAND-PLACED SCHEMATIC. Node coordinates are approximate WGS84 positions of real places (cruise
// terminals, dock gates, streets and dining/retail clusters), placed by hand on 16 Oct 2026 because
// OpenStreetMap was not reachable from the build environment. Edges follow the real street
// pattern but are straight segments, and footway widths are class defaults, not survey values.
// scripts/export_frontend_graph.py replaces this file with an osmnx export in the same schema.
//
// Venues are *clusters* of businesses (e.g. "Oxford Street dining"), not single businesses: the
// forecast is sold per cluster first and split to individual businesses later from OSM amenity
// tags and the business's own covers. Capacity is the seats or floor space left for cruise
// passengers after typical local trade. Capacities, dwell times and spend are calibration guesses.

export const META = {
  name: "Southampton city centre (schematic)",
  source: "Hand-placed from public knowledge of the street layout",
  collected: "2026-10-16",
  licence: "Own work; replace with OSM (ODbL) export before submission",
  synthetic: true,
  origin: { lat: 50.9005, lon: -1.405 },
};

// kind: terminal | gate | junction | venue | exit
// venue.category: food | drink | retail | culture | park
export const NODES = [
  // Cruise terminals (ships come alongside here)
  { id: "T_MAY", kind: "terminal", name: "Mayflower Cruise Terminal", lat: 50.9022, lon: -1.4268, berth: "106" },
  { id: "T_HOR", kind: "terminal", name: "Horizon Cruise Terminal", lat: 50.899, lon: -1.4212, berth: "102" },
  { id: "T_CITY", kind: "terminal", name: "City Cruise Terminal", lab: "below", lat: 50.8984, lon: -1.4176, berth: "101" },
  { id: "T_OCEAN", kind: "terminal", name: "Ocean Cruise Terminal", lat: 50.8946, lon: -1.3976, berth: "46" },
  { id: "T_QE2", kind: "terminal", name: "QEII Cruise Terminal", lat: 50.8897, lon: -1.3968, berth: "38/39" },

  // Dock gates: the pinch points between the port estate and the city
  { id: "G10", kind: "gate", name: "Dock Gate 10", lat: 50.906, lon: -1.4222, width: 4 },
  { id: "G8", kind: "gate", name: "Dock Gate 8", lat: 50.9004, lon: -1.415, width: 4 },
  { id: "G4", kind: "gate", name: "Dock Gate 4", lat: 50.8978, lon: -1.3979, width: 4 },

  // Street junctions
  { id: "J_WQR2", kind: "junction", name: "West Quay Rd (west)", lat: 50.9072, lon: -1.4205 },
  { id: "J_WQR", kind: "junction", name: "West Quay Rd", lat: 50.9049, lon: -1.4168 },
  { id: "J_MRB", kind: "junction", name: "Mayflower Roundabout", lat: 50.9005, lon: -1.4118 },
  { id: "J_HPN", kind: "junction", name: "Harbour Parade", lat: 50.9058, lon: -1.4112 },
  { id: "J_CEN", kind: "junction", name: "Commercial Rd", lat: 50.9086, lon: -1.4101 },
  { id: "J_ABN", kind: "junction", name: "Above Bar (Civic Centre)", lat: 50.9082, lon: -1.4045 },
  { id: "J_LON", kind: "junction", name: "London Rd", lat: 50.9116, lon: -1.4048 },
  { id: "J_ABM", kind: "junction", name: "Above Bar St", lat: 50.9055, lon: -1.4042 },
  { id: "J_BAR", kind: "junction", name: "Bargate", lat: 50.9026, lon: -1.4043 },
  { id: "J_ES", kind: "junction", name: "East St", lat: 50.903, lon: -1.4013 },
  { id: "J_EAST", kind: "junction", name: "St Mary St", lat: 50.9036, lon: -1.3972 },
  { id: "J_WALLS", kind: "junction", name: "Western Esplanade", lat: 50.903, lon: -1.4098 },
  { id: "J_WP", kind: "junction", name: "Town Quay Rd (west)", lat: 50.8974, lon: -1.4086 },
  { id: "J_HS2", kind: "junction", name: "High St (north)", lat: 50.901, lon: -1.4044 },
  { id: "J_HS1", kind: "junction", name: "High St / Bernard St", lat: 50.8995, lon: -1.4041 },
  { id: "J_BUG", kind: "junction", name: "Bugle St", lat: 50.8986, lon: -1.4066 },
  { id: "J_TQ", kind: "junction", name: "Town Quay", lat: 50.8966, lon: -1.4044 },
  { id: "J_GHT", kind: "junction", name: "Platform Rd", lat: 50.8969, lon: -1.4012 },
  { id: "J_OXW", kind: "junction", name: "Oxford St (west)", lat: 50.8993, lon: -1.4001 },
  { id: "J_OXE", kind: "junction", name: "Terminus Terrace", lat: 50.8991, lon: -1.3966 },
  { id: "J_CAN", kind: "junction", name: "Canute Rd", lat: 50.8968, lon: -1.3946 },
  { id: "J_OV", kind: "junction", name: "Ocean Village", lat: 50.8961, lon: -1.3923 },
  { id: "J_DOCK", kind: "junction", name: "Eastern Docks road", lat: 50.8925, lon: -1.3975 },

  // Venue clusters: where the business forecast lands
  { id: "V_OX", kind: "venue", category: "food", name: "Oxford Street dining", lat: 50.8997, lon: -1.3983, capacity: 340, dwell: 70, spend: 24, perStaff: 14 },
  { id: "V_OV", kind: "venue", category: "drink", name: "Ocean Village marina", lat: 50.8947, lon: -1.3898, capacity: 260, dwell: 60, spend: 16, perStaff: 18 },
  { id: "V_TQ", kind: "venue", category: "food", name: "Town Quay cafés", lab: "above", lat: 50.8958, lon: -1.4056, capacity: 120, dwell: 35, spend: 9, perStaff: 16 },
  { id: "V_HIGH", kind: "venue", category: "drink", name: "High Street pubs", lat: 50.9012, lon: -1.4033, capacity: 200, dwell: 50, spend: 14, perStaff: 22 },
  { id: "V_TUDOR", kind: "venue", category: "culture", name: "Tudor House", lat: 50.8999, lon: -1.4062, capacity: 110, dwell: 45, spend: 8, perStaff: 25 },
  { id: "V_GHT", kind: "venue", category: "culture", name: "God's House Tower", lat: 50.8975, lon: -1.4004, capacity: 90, dwell: 35, spend: 6, perStaff: 25 },
  { id: "V_WQ", kind: "venue", category: "retail", name: "WestQuay shopping", lat: 50.9048, lon: -1.4074, capacity: 1600, dwell: 85, spend: 38, perStaff: 40 },
  { id: "V_WMK", kind: "venue", category: "food", name: "WestQuay Watermark", lab: "left", lat: 50.9039, lon: -1.4093, capacity: 480, dwell: 75, spend: 22, perStaff: 14 },
  { id: "V_ABAR", kind: "venue", category: "food", name: "Above Bar cafés", lat: 50.9061, lon: -1.4031, capacity: 220, dwell: 30, spend: 8, perStaff: 16 },
  { id: "V_EAST", kind: "venue", category: "food", name: "East Street food", lat: 50.9025, lon: -1.3995, capacity: 140, dwell: 40, spend: 11, perStaff: 16 },
  { id: "V_GUILD", kind: "venue", category: "culture", name: "SeaCity Museum", lat: 50.9091, lon: -1.4068, capacity: 260, dwell: 70, spend: 10, perStaff: 30 },
  { id: "V_BED", kind: "venue", category: "drink", name: "Bedford Place bars", lat: 50.914, lon: -1.4072, capacity: 240, dwell: 55, spend: 15, perStaff: 20 },
  { id: "V_PARK", kind: "venue", category: "park", name: "Mayflower Park", lab: "above", lat: 50.8987, lon: -1.4106, capacity: 1500, dwell: 25, spend: 0, perStaff: 0 },
  { id: "V_QP", kind: "venue", category: "park", name: "Queen's Park", lat: 50.8982, lon: -1.399, capacity: 800, dwell: 15, spend: 0, perStaff: 0 },

  // Ways out of the city for disembarking passengers (and in, for embarking ones)
  { id: "X_RAIL", kind: "exit", name: "Southampton Central", mode: "rail", lat: 50.9077, lon: -1.4137 },
  { id: "X_RF", kind: "exit", name: "Red Funnel", lab: "below", mode: "ferry", lat: 50.8953, lon: -1.403 },
  { id: "X_HYTHE", kind: "exit", name: "Hythe Ferry", lab: "left", mode: "ferry", lat: 50.8954, lon: -1.4068 },
];

// [a, b, class, width?]. class sets the default footway width (metres) in WIDTHS; an optional
// fourth element overrides it (the OSM export fills it from width tags where they exist).
export const EDGES = [
  ["T_MAY", "G10", "dock"],
  ["G10", "J_WQR2", "gate"],
  ["J_WQR2", "J_WQR", "road"],
  ["J_WQR", "X_RAIL", "road"],
  ["J_WQR", "J_HPN", "road"],
  ["X_RAIL", "J_CEN", "street"],
  ["J_HPN", "J_CEN", "road"],
  ["J_HPN", "J_MRB", "road"],
  ["J_MRB", "G8", "gate"],
  ["G8", "T_CITY", "dock"],
  ["G8", "T_HOR", "dock"],
  ["J_MRB", "V_PARK", "door"],
  ["J_MRB", "J_WP", "road"],
  ["J_WP", "V_PARK", "door"],
  ["J_WP", "J_BUG", "street"],
  ["J_WP", "J_WALLS", "street"],
  ["J_WALLS", "J_HPN", "street"],
  ["J_WALLS", "V_WMK", "door"],
  ["J_WALLS", "V_WQ", "door"],
  ["J_HPN", "V_WQ", "door"],
  ["J_ABM", "V_WQ", "door"],
  ["J_CEN", "V_GUILD", "door"],
  ["J_ABN", "V_GUILD", "door"],
  ["J_CEN", "J_ABN", "precinct"],
  ["J_ABN", "J_ABM", "precinct"],
  ["J_ABM", "J_BAR", "precinct"],
  ["J_ABM", "V_ABAR", "door"],
  ["J_ABN", "J_LON", "street"],
  ["J_LON", "V_BED", "door"],
  ["J_BAR", "J_HS2", "street"],
  ["J_BAR", "J_ES", "street"],
  ["J_ES", "V_EAST", "door"],
  ["J_ES", "J_EAST", "street"],
  ["J_WALLS", "J_BAR", "street"],
  ["J_HS2", "V_HIGH", "door"],
  ["J_HS2", "J_HS1", "street"],
  ["J_HS2", "J_BUG", "street"],
  ["J_BUG", "V_TUDOR", "door"],
  ["J_BUG", "J_TQ", "street"],
  ["J_HS1", "J_TQ", "street"],
  ["J_HS1", "J_OXW", "street"],
  ["J_TQ", "V_TQ", "door"],
  ["J_TQ", "X_RF", "door"],
  ["J_TQ", "X_HYTHE", "door"],
  ["J_TQ", "J_WP", "road"],
  ["J_TQ", "J_GHT", "road"],
  ["J_GHT", "V_GHT", "door"],
  ["J_GHT", "V_QP", "door"],
  ["J_OXW", "V_QP", "door"],
  ["J_OXW", "J_GHT", "street"],
  ["J_OXW", "V_OX", "door"],
  ["J_OXW", "J_OXE", "street"],
  ["J_OXE", "V_OX", "door"],
  ["J_OXE", "G4", "street"],
  ["J_OXE", "J_EAST", "street"],
  ["J_GHT", "G4", "road"],
  ["G4", "J_CAN", "road"],
  ["J_CAN", "J_OV", "street"],
  ["J_OV", "V_OV", "door"],
  ["G4", "T_OCEAN", "dock"],
  ["G4", "J_DOCK", "dock"],
  ["J_DOCK", "T_QE2", "dock"],
];

// Usable footway width per edge class, metres (calibrate against footway surveys).
export const WIDTHS = { dock: 5, gate: 3.2, road: 3, street: 3.5, precinct: 10, door: 6 };

// Schematic land masses in [lat, lon]; water is everything else. Not survey grade.
export const LAND = [
  // City centre and both dock estates
  [
    [50.935, -1.4345], [50.9118, -1.4318], [50.9062, -1.4296], [50.9032, -1.4292], [50.9008, -1.4276],
    [50.8993, -1.4238], [50.8978, -1.4192], [50.8974, -1.4142], [50.8978, -1.4112], [50.8963, -1.4088],
    [50.8949, -1.4066], [50.8945, -1.4036], [50.8952, -1.4006], [50.8949, -1.3993], [50.8905, -1.3998],
    [50.8879, -1.3984], [50.8881, -1.3951], [50.8926, -1.3944], [50.8936, -1.3944], [50.8937, -1.3966],
    [50.896, -1.3966], [50.8961, -1.3942], [50.8936, -1.3927], [50.8933, -1.3906], [50.8937, -1.3884],
    [50.8962, -1.3876], [50.9004, -1.3886], [50.9062, -1.3897], [50.9118, -1.3912], [50.935, -1.3928],
  ],
  // Woolston / Itchen east bank
  [[50.935, -1.381], [50.905, -1.3832], [50.896, -1.3842], [50.888, -1.3825], [50.87, -1.3795], [50.87, -1.37], [50.935, -1.37]],
  // Marchwood / Totton shore across the Test
  [[50.91, -1.46], [50.902, -1.45], [50.8985, -1.437], [50.893, -1.4265], [50.886, -1.418], [50.87, -1.413], [50.87, -1.46]],
];

// Deep-water approach for large ships, drawn as a dashed chart line.
export const CHANNEL = [
  [50.881, -1.3905], [50.8868, -1.4005], [50.8918, -1.4128], [50.8952, -1.4232], [50.8992, -1.4325],
];

export const VIEW = { lat: [50.8875, 50.9165], lon: [-1.4305, -1.3865] };
