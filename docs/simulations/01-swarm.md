# 01 · Swarm

**Page:** `frontend/swarm.html` · **Code:** `frontend/js/sims/swarm.js`

## Question it answers

What happens in the first few hours after one ship docks? Where do walkers go, and where do the
streets jam?

This is the demo opener. It is real time, it has one ship, and it reads in five seconds.

## What you see

- One turnaround ship berths at 08:00 at the chosen terminal. Walkers come off from about 08:45
  over roughly three and a half hours, so the page opens at 09:00 with the first ones already
  ashore.
- Each dot walks its shortest path. Its shape and colour give its persona. While a passenger is
  inside a venue, their dot circles that venue's hexagon, so a crowded place looks crowded.
- Edges glow with the number of people on them and change colour by Fruin level of service.
  Moving chevrons show which way people are walking.
- The side panel counts people on the streets, in venues, gone onward and turned away, and lists
  every venue with a fill meter, people inside, arrivals so far and staff needed now.
- The bottom chart shows people walking and people in venues, minute by minute.

## Design decisions

| Decision | Why |
| --- | --- |
| One ship, disembarkation only | The simplest story that still shows the whole mechanism. Embarking flows and crew are in Turnaround Day. |
| Opens at 09:00, already busy | An empty map shows nothing. The opening frame is what a judge or a thumbnail sees. |
| Default 2 people per dot, slider up to 8 | Two per dot keeps the swarm dense enough to read as a crowd at 5,400 passengers while staying smooth on a laptop. |
| Dwelling dots orbit the venue | Hiding people inside a venue makes busy places look empty. The orbit radius steps in three rings so a full venue looks crowded. |
| Lane offset by walking direction | People keep left or right of the walking direction, so two-way streams separate visibly and you can read direction without the arrows. |
| Short motion trails, not long ones | A tail of a few metres reads as motion at 90× speed without smearing into the street colour. |
| "Walk times" layer = isochrones from the chosen terminal, in 5-minute bands | The first question a business asks is "am I within walking distance of the ship?" Bands use one sequential blue ramp. |
| "Heat" layer off by default | It is beautiful but hides the individual agents, and the agents are the point of this page. |
| "Avoid crowds" toggle | Switches routing from shortest path to a crowd-weighted one (cost × (1 + 3 × density)). It shows how much of the jam is a routing problem rather than a demand problem. |
| Policy randomness slider | Temperature of the stand-in policy. At 0.2 everyone makes the same "best" choice and one venue floods; at 2 they spread out. Seeing that is the quickest way to explain why the RL policy matters. |

## Controls

Terminal, passengers aboard, share who walk, people per dot (restart to apply), speed, policy
randomness, layers (flow arrows, crowding, heat, walk times, labels), avoid crowds. Click a venue
or its table row to chart its occupancy against capacity.

## Backend hooks

- Walk share and disembarkation timing match `configs/default.yaml` and
  `demand/passengers.py`.
- Swap `HeuristicPolicy` for `ReplayPolicy(trace)` to show trained behaviour on the same ship.

## Next

- Use the real VTS schedule entry for the chosen day and terminal.
- Show the dock-gate queue before people reach the street.
