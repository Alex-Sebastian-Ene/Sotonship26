# 03 · Policy Lens

**Page:** `frontend/policy.html` · **Code:** `frontend/js/sims/policy.js`, `frontend/js/core/policy.js`

## Question it answers

Why did the policy send this passenger there? This page is for the RL teammate, the judges'
"AI at the core" criterion, and anyone who needs to trust a forecast built on a learned policy.

## What you see

- Two ships (a port call at QEII and a turnaround at City) at 5 people per dot. The page opens at
  09:40, already following one passenger who has made at least one decision.
- Every other dot is dimmed. From the followed passenger's last decision point, a **fan** of curved
  spokes runs to every option the policy weighed. Spoke thickness and opacity are the probability;
  the chosen option is magenta with its percentage. The rest of their path is a moving dashed line;
  the places they have already been are a dotted line.
- The panel shows their persona, sink, deadline, the probabilities of the latest decision as made,
  the same options **re-scored live** with the current weights, and a log of every decision.
- Sliders for the stand-in model's weights: walking-time aversion, crowd aversion, pull of big
  venues, temperature.
- Episode counters: decisions, covers served, turned away, late for ship or train.
- Trace import and export.

## Design decisions

| Decision | Why |
| --- | --- |
| `probs` are part of the policy interface, not a debug extra | An RL policy that only returns an action cannot be explained. Asking the backend for the action distribution costs nothing (PPO has it) and makes this page possible. |
| Fan from the decision point, not from the agent's current position | The decision was made at a place, with the options available there. Drawing from the moving dot would suggest it is re-deciding all the time. |
| Pause at each decision, on by default | Decisions are instantaneous. Without a pause there is nothing to read. |
| "As decided" and "If they chose again now" shown together | Moving a weight slider changes only future decisions. Re-scoring the same options live shows what each term does without waiting for the next decision. |
| Persona filter dims rather than hides | Hidden agents still occupy venues and footways; dimming keeps the crowding honest. |
| Followed camera eases (4% per frame) rather than snapping | Snapping is disorienting at 60× speed. Easing keeps the street context while tracking. |
| Trace replay falls back to the gravity model when a trace runs out | A partial trace (say, the first decision only) is still useful, and the page never stalls. |
| Validation on load names the problem | A bad trace says which agent names which unknown node or persona, rather than failing silently. |

## Trace contract

`sotonship26.trace/1`, specified in [README.md](README.md#trace-format-sotonship26trace1). The
"Export this run as a trace" button writes a valid example from the live model. Replaying a trace
uses its own spawn plan, so the backend controls who appears, where and when, as well as where
they go.

## Backend hooks

- Simplest: the backend runs an episode and writes a trace; drop it on this page.
- Next: a small HTTP endpoint that takes the same `ctx` fields and returns `{choice, probs}`, so a
  `RemotePolicy` can call the live model. Decisions would need batching per frame to keep up.

## Next

- Show the observation vector the policy saw next to the probabilities.
- An aggregate view: for one venue, the distribution of where people go next.
