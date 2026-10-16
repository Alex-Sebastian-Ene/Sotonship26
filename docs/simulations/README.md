# Gangway simulations: shared design decisions

Gangway is the frontend for Sotonship26. It shows cruise passengers as agents walking from the
terminals into Southampton. The point is the business forecast: how many people each café, pub and
shop cluster gets each hour, and so how many staff it needs. The choice of where a passenger goes
next comes from the RL backend (`src/sotonship26/rl`); the frontend draws the result and offers a
stand-in until the trained policy is ready.

There are six simulations. Each has its own design note:

| Page | Note | Question it answers |
| --- | --- | --- |
| `swarm.html` | [01-swarm.md](01-swarm.md) | What happens in the first hours after one ship docks? |
| `day.html` | [02-turnaround-day.md](02-turnaround-day.md) | How many staff does my venue need each hour today? |
| `policy.html` | [03-policy-lens.md](03-policy-lens.md) | Why did the policy send this passenger there? |
| `compare.html` | [04-compare.md](04-compare.md) | What changes if it rains, a road closes or disembarkation is staggered? |
| `skyline.html` | [05-skyline.md](05-skyline.md) | Which venues are under pressure right now, at a glance? |
| `buses.html` | [06-buses.md](06-buses.md) | What do late buses do to passengers and to the venues waiting for them? |

Run them with any static file server from the repo root:

```bash
python -m http.server -d frontend 8000   # then open http://localhost:8000
```

There is no build step and there are no dependencies. Plain ES modules and Canvas 2D mean anyone on
the team can open a file and change it, and the pages run on a judge's laptop with no install.

## The street graph

**Geometric nodes, not map tiles.** The city is a graph of nodes placed at real WGS84 positions and
projected to local metres (`js/core/graph.js`, an equirectangular projection centred on the Old Town
that is accurate to well under a metre over 4 km). Edges are straight segments between them. The
look is schematic on purpose: it is the same graph the backend routes over, so what you see is what
the model sees. A tiled street map would suggest more precision than the model has.

Node kinds:

| Kind | Examples | Role |
| --- | --- | --- |
| `terminal` | Ocean, QEII, City, Horizon, Mayflower | Where ships put passengers ashore |
| `gate` | Dock Gates 4, 8, 10 | The pinch points between the port estate and the city; narrow (3.2 m) on purpose |
| `junction` | Above Bar St, Bargate, Canute Rd | Street intersections |
| `venue` | Oxford Street dining, WestQuay, Tudor House | Where people spend time and money |
| `exit` | Southampton Central, Red Funnel, Hythe Ferry | Where disembarking passengers leave the city and embarking ones arrive |

**Venues are clusters, not single businesses.** "Oxford Street dining" stands for the dozen
restaurants on that street. A cluster forecast is more reliable than a per-business one with the
data we have, and it is what a BID or the council would buy first. A single restaurant's share is a
later step: split the cluster by covers, using OSM amenity tags and the business's own numbers.
Each venue carries `capacity` (seats or floor space left for cruise passengers after typical local
trade), `dwell` (mean minutes), `spend` (£ per head) and `perStaff` (customers one member of staff
can serve). All four are calibration guesses and are marked as such in `data/southampton.js`.

**Venues, terminals and exits are endpoints only.** Shortest paths never pass through a restaurant
to reach the station. Each venue joins the street graph by one or more short `door` edges.

**The current graph is hand-placed** because OpenStreetMap was not reachable from the build
environment. `scripts/export_frontend_graph.py` rebuilds it from OSM through the backend's
`load_streets`, keeping every named place and snapping it to the nearest footway. Shortest paths use
a binary-heap Dijkstra so the full OSM network (thousands of nodes) stays fast.

## Agents

One dot is one or more people (`peoplePerAgent`, shown in tooltips). Every agent has:

- a **persona**, which sets category preferences, walking speed, dwell length and how keen they are
  to leave. Personas: rail transfer (luggage, heads for the station), diner, shopper, sightseer,
  crew on shore leave, boarding passenger;
- a **sink**: where they must end up (station or ferry for disembarking passengers, their own ship
  for port-call passengers, crew and boarding passengers);
- a **deadline**: their train, or all-aboard. The policy never offers a venue they cannot visit and
  still make it.

The life of an agent: spawn at a terminal or exit → ask the policy where to go → walk the shortest
path, or walk to a stop and take a bus when that is clearly faster → dwell at the venue (or be
turned away if it is full and ask again) → ask again → … → reach the sink. The bus choice sits
below the policy: the policy picks where, the transit model picks how (see
[06-buses.md](06-buses.md)).

**Spawn timing matches the backend.** `js/core/schedule.js` uses the same shapes as
`src/sotonship26/demand/passengers.py`: disembarkation starts 45 minutes after the ship is
alongside and runs about 210 minutes (Beta(2, 3)); embarking passengers arrive between 6 and 1.5
hours before departure (Beta(2, 2)); 30% of passengers walk, as in `configs/default.yaml`.

**Walking speed falls with crowding.** Speed on each edge follows Weidmann's pedestrian
speed–density relation, using people per square metre of footway. Crowds slow down visibly at the
dock gates.

**Crowding is graded by Fruin level of service.** Edges are coloured by Fruin's walkway LOS bands
(A–F, by people per m²), so "busy" means the same thing on every page and matches the measure
planners already use.

## The policy interface

Every simulation calls one method:

```js
policy.decide(agent, { graph, now, occupancy, rng, weather }) // ->
  { choice: "V_OX", probs: [["V_OX", 0.41], ["X_RAIL", 0.33], ...], dwell?: minutes }
```

- `HeuristicPolicy` (`js/core/policy.js`) is the stand-in: a multinomial-logit gravity model.
  Utility = persona preference × venue size − walking minutes − a crowding penalty past 75% full,
  plus a lunchtime bonus for food and an evening bonus for drink. Options are sampled by softmax
  with a temperature. It exists so the visuals are worth looking at today, not as a forecast.
- `ReplayPolicy` plays back decisions from a trace file, so the trained RL policy can be shown
  without running Python in the browser.

`probs` is part of the interface on purpose. Policy Lens draws it, and it is what makes an RL
policy explainable to a café owner.

### Trace format (`sotonship26.trace/1`)

```json
{
  "meta": { "format": "sotonship26.trace/1", "policy": "PPO run 12", "seed": 26,
            "synthetic": true, "peoplePerAgent": 5, "start": 27000, "end": 66600 },
  "agents": [
    { "id": 0, "persona": "diner", "ship": "s1", "origin": "T_OCEAN", "sink": "X_RAIL",
      "spawn": 29340, "deadline": 38100,
      "decisions": [
        { "t": 29340, "at": "T_OCEAN", "choice": "V_OX",
          "probs": { "V_OX": 0.52, "V_TQ": 0.21, "X_RAIL": 0.17 } }
      ] }
  ]
}
```

Times are seconds since midnight. Node IDs are the IDs in `data/southampton.js`. A decision may
carry `dwell` (minutes) to fix the dwell time; otherwise the frontend samples it. Policy Lens
exports this format from any live run, so the backend has a worked example.

## Visual language

- **Admiralty chart by day, ECDIS night palette by dark.** Buff land, white deep water, a shallow
  band along the shore and a dashed dredged channel, as on a nautical chart, because the users are
  in a port city. Chart magenta, which charts use for things a navigator must notice, is the one
  accent.
- **Persona = colour and shape.** Six categorical colours from a palette checked for colour
  blindness, each paired with its own marker shape (circle, square, diamond, triangle, cross, ring),
  so identity never depends on colour alone.
- **Venue fill = status colour.** Hexagons fill like a pie with how full the venue is: green under
  60%, amber to 85%, orange to 100%, red when full. These four colours are never used for anything
  else.
- **Flow arrows** move along each edge in the direction people walk; their weight is the smoothed
  flow in people per minute. Opposite directions sit on opposite sides of the street.
- **Labels honest about data.** Every page with synthetic inputs carries a magenta "Synthetic …"
  chip on the map, as the event rules require.

## What this does not do yet

- The street graph is schematic, and venue capacities, dwell times, spend and staff ratios are
  guesses.
- The ship schedule is synthetic. The real one comes from Southampton VTS (`data/cruise.py`).
- The default policy is a hand-tuned gravity model, not a trained one.
- Local (non-cruise) trade appears only as reduced capacity, not as its own demand curve.
- Coach and taxi passengers are not drawn; they leave from the terminal forecourt.
