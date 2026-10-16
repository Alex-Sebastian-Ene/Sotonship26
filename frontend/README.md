# Gangway frontend

Five browser simulations of cruise passengers walking from Southampton's terminals into the city,
built on one shared engine. Design notes: [docs/simulations](../docs/simulations/README.md).

```bash
python -m http.server -d frontend 8000
# open http://localhost:8000
```

No build step, no dependencies: plain ES modules and Canvas 2D. Fonts load from Google Fonts with
system fallbacks.

| Path | What it is |
| --- | --- |
| `index.html` | Landing page with a live preview and links to every simulation |
| `swarm.html`, `day.html`, `policy.html`, `compare.html`, `skyline.html` | The simulations |
| `data/southampton.js` | The walking graph: nodes, edges, footway widths, coastline (hand-placed, schematic) |
| `js/core/graph.js` | Projection, shortest paths, Weidmann walking speed, Fruin level of service |
| `js/core/world.js` | The simulation loop: spawn, walk, dwell, decide; trace export |
| `js/core/policy.js` | Personas, the `decide()` interface, the gravity-model stand-in, trace replay |
| `js/core/schedule.js` | Synthetic ship schedule and the passengers each ship puts ashore |
| `js/core/staffing.js` | Occupancy → staff per hour, compared with a flat roster |
| `js/core/render.js` | Canvas renderer: chart-style map, agents, flows, fans, isometric towers |
| `js/core/ui.js`, `js/core/page.js` | Charts, tooltips, theme toggle, shared page furniture |
| `js/sims/*.js` | One file per simulation |

To plug in the trained policy, implement `decide(agent, ctx)` returning `{ choice, probs }`, or
export a `sotonship26.trace/1` file from the backend and drop it on Policy Lens.

All ship schedules are synthetic and the map is schematic; every page says so on the map.
