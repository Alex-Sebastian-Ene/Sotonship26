# 05 · Skyline

**Page:** `frontend/skyline.html` · **Code:** `frontend/js/sims/skyline.js`, `drawSkyline` in `frontend/js/core/render.js`

## Question it answers

Which venues are under pressure right now? It is the at-a-glance view for a pitch slide, a BID
dashboard on a screen in the office, or a restaurant owner who will not read a table.

## What you see

The same city tilted into an isometric view (rotated 32°, vertical squashed to 52%). Every venue
cluster becomes a hexagonal tower whose height is the people inside it, or the staff it needs. The
tower changes colour as the venue fills (green, amber, orange, red). A dashed glass outline above
each tower marks the height at which the venue is full. Passengers still walk on the ground plane.
The bottom chart shows total staff needed across the city through the day.

## Design decisions

| Decision | Why |
| --- | --- |
| Height = people inside, toggle to staff needed | People inside is the honest raw number; staff needed is what the owner acts on. One toggle switches the question without changing the picture. |
| Glass envelope for capacity | Height alone says "big"; height against an outline says "nearly full". The envelope is skipped when it would run off the top of the screen. |
| Same status colours as the hexagon fills elsewhere | One meaning per colour across all five pages. |
| Towers drawn back to front by screen depth | Correct overlap without a 3D engine. Three visible side faces get two shades of the ink colour for light and shade. |
| Only the five busiest towers (plus a selected one) are labelled | All 14 labels collide in isometric view. The busiest are the ones worth reading. |
| Canvas 2D, no WebGL or three.js | Fourteen prisms do not need a GPU, and the page stays dependency-free and works in the sandboxed preview. |
| Opens at 10:30 | The morning disembarkation peak, when the skyline is tallest. |

## Controls

Tower metric (people or staff), tower scale, speed, passengers on or off, heat, labels. Click a
tower to label it.

## Next

- Animate tower heights between frames for a smoother rise.
- A "tomorrow" mode that shows the forecast skyline at a chosen hour, without the walking agents.
