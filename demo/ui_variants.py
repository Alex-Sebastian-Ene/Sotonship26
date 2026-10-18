"""Four simplified UI variants of the forecast app, each a separate page built from the same template
and data: the variant's CSS goes before </style>, its init replaces the app's last line."""
import base64
import json
import re
import sys
from pathlib import Path

TEMPLATE, DATA, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
INIT = "  renderChip(); showView(location.hash.slice(1), true);"

COMMON_CSS = """
/* variant shell */
body[data-variant] .views { display: none !important; }
body[data-variant] .masthead, body[data-variant] .sec-head { display: none !important; }
.v-btn { border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); border-radius: 999px; padding: 8px 16px; min-height: 40px; font-weight: 700; cursor: pointer; transition: transform .15s, background .15s; }
.v-btn:hover { transform: translateY(-1px); }
.v-btn.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.v-btn:disabled { opacity: .35; cursor: default; transform: none; }
"""

COMMON_JS = r"""
  const VAR = __VARIANT__;
  document.body.dataset.variant = VAR;
  function showSet(name) {
    document.body.dataset.view = name;
    document.querySelectorAll('[data-views]').forEach(el => el.classList.toggle('off-view', !el.dataset.views.split(' ').includes(name)));
  }
  function tag(sel, views) { const el = typeof sel === 'string' ? $(sel) : sel; if (el) el.dataset.views = views; return el; }
  const calSec = $('#cal-h').closest('section'), methodSec = $('#method-h').closest('section');
  let liveDay = null;
  function mapLive(play) {
    requestAnimationFrame(() => { layout(); zoomTo('docks', false); drawAgents(); });
    if (!play || REDUCED || !agentDay()) return;
    if (liveDay !== state.date) { liveDay = state.date; setBin(7); }        // 06:45, before the morning build-up
    if (state.layer !== 'agents') $('#layer-agents').click();
    else if (!vehAnim) $('#veh-play').click();
  }
"""

VARIANTS = {}

# 1 ---------------------------------------------------------------- Focus: one screen, details in a drawer
VARIANTS["focus"] = ("""
body[data-variant="focus"] .wrap { max-width: 1600px; gap: 12px; padding-top: 12px; }
body[data-variant="focus"] .cal-dow, body[data-variant="focus"] #legend { display: none !important; }
body[data-variant="focus"] .cal { display: flex; overflow-x: auto; gap: 6px; padding-bottom: 4px; scrollbar-width: thin; }
body[data-variant="focus"] .cal .cell { flex: 0 0 76px; min-height: 60px; padding: 6px 8px; }
body[data-variant="focus"] .cal .cell-off, body[data-variant="focus"] .cal .cell-beyond, body[data-variant="focus"] .cal .cell-tags, body[data-variant="focus"] .cal .cell-lv, body[data-variant="focus"] .cal .mon { display: none; }
body[data-variant="focus"] #day { grid-template-columns: minmax(0, 1fr) !important; }
body[data-variant="focus"] #day > * { grid-column: 1 !important; grid-row: auto !important; }
body[data-variant="focus"] .map-box { height: max(420px, calc(100vh - 360px)) !important; }
.drawer { position: fixed; top: 58px; right: 0; bottom: 0; z-index: 45; width: min(440px, 94vw); overflow: auto; display: grid; gap: 18px; align-content: start;
  padding: 18px; background: var(--surface); border-left: 1px solid var(--line); box-shadow: -18px 0 40px rgba(0,0,0,.25); transform: translateX(105%); transition: transform .3s cubic-bezier(.2,.7,.2,1); }
.drawer.open { transform: none; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
""", r"""
  const drawer = document.createElement('aside'); drawer.className = 'drawer'; drawer.setAttribute('aria-label', 'Actions and ships');
  drawer.innerHTML = '<div class="drawer-head"><h2>Today\'s plan</h2><button class="v-btn" id="drawer-x" aria-label="Close">✕</button></div>';
  ['#row-actions', '#ppo-card', '#ships-block'].forEach(s => { const el = $(s); delete el.dataset.views; drawer.append(el); });
  document.body.append(drawer);
  const db = document.createElement('button'); db.className = 'v-btn primary'; db.id = 'drawer-btn'; db.textContent = 'Plan';
  $('.stepper').before(db);
  const toggle = () => drawer.classList.toggle('open');
  db.addEventListener('click', toggle); $('#drawer-x').addEventListener('click', toggle);
  tag(calSec, 'focus'); tag('#day-head', 'focus'); tag('#day-body', 'focus');
  [methodSec, '#notices', '#row-vehicles', '#heat-card', '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live'].forEach(s => tag(s, 'none'));
  const _sel = selectDay;
  showSet('focus'); renderChip(); mapLive(true);
  $('#cal').addEventListener('click', () => setTimeout(() => mapLive(true), 50));
""")

# 2 ---------------------------------------------------------------- Story: a landing page, then five guided steps
VARIANTS["story"] = ("""
.storybar { position: sticky; top: 58px; z-index: 35; display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto auto; align-items: center; gap: 10px 14px; padding: 10px max(16px, env(safe-area-inset-left, 0px));
  background: color-mix(in srgb, var(--bg) 90%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
.story-q { display: flex; align-items: center; gap: 12px; min-width: 0; white-space: nowrap; font-family: var(--font-display); font-size: clamp(1.3rem, 2.6vw, 2rem); font-weight: 750; }
#story-q { overflow: hidden; text-overflow: ellipsis; }
.storybar .v-btn { min-width: 88px; }
/* time of day, on every step that shows a day: the same 15-minute slots as the map's slider */
.story-time { display: none; align-items: center; gap: 10px; padding: 4px 6px 4px 14px; border-radius: 999px; border: 1px solid var(--line-strong); background: var(--surface); }
body[data-view="step1"] .story-time, body[data-view="step2"] .story-time, body[data-view="step3"] .story-time { display: inline-flex; }
.story-time b { font-family: var(--font-data); font-size: 1rem; min-width: 5ch; }
.story-time input { width: 170px; accent-color: var(--accent); }
:root[data-theme="steam"] .story-time { border: 2px solid #1D2B45; box-shadow: 3px 3px 0 #1D2B45; }
/* medium screens: a shorter slider, and on the day steps the step track gives way so the question still fits */
@media (max-width: 1280px) { .story-time input { width: 120px; } }
@media (max-width: 1100px) { body[data-view="step1"] .voyage, body[data-view="step2"] .voyage, body[data-view="step3"] .voyage { display: none; } }
.story-q .spr { height: 46px; width: auto; flex: none; }
.story-ico { display: inline-flex; animation: stk-pop .45s cubic-bezier(.2, 1.6, .4, 1) both; }
.story-n { font-family: var(--font-data); color: var(--accent); }
@keyframes stk-pop { from { transform: scale(.3) rotate(-20deg); } to { transform: none; } }
/* voyage: the current step is a steamship sailing between buoys */
.voyage { position: relative; width: 260px; height: 56px; margin-right: 28px; flex: none; --k: 0; }
.voy-sea { position: absolute; left: 0; right: 0; bottom: 6px; height: 10px; opacity: .8;
  background: radial-gradient(circle at 5px -1px, transparent 5px, var(--accent) 5.5px 7px, transparent 7.5px) 0 0 / 10px 10px repeat-x; }
.voy-port { position: absolute; bottom: 4px; left: calc(var(--x) * (100% - 18px)); width: 18px; height: 18px; padding: 0; border-radius: 50%; cursor: pointer;
  border: 2px solid var(--ink); background: var(--surface); transition: transform .2s, background .2s; }
.voy-port:hover { transform: scale(1.2); }
.voy-port.done { background: var(--accent); }
.voy-port[aria-selected="true"] { opacity: 0; }
.voy-ship { position: absolute; bottom: 9px; left: calc(var(--k) * (100% - 18px) - 18px); width: 52px; transition: left .7s cubic-bezier(.45, 0, .2, 1); pointer-events: none; }
.voy-ship .ship-svg { width: 100%; }
/* the steamship is drawn as vector art (same palette and outline as the generated icons) so it stays sharp at any size */
.ship-svg { display: block; width: 100%; height: auto; overflow: visible; }
.ship-svg .rock { transform-box: view-box; transform-origin: 300px 400px; animation: rock 3s ease-in-out infinite; }
@keyframes rock { 0%, 100% { transform: rotate(-1.5deg) translateY(0); } 50% { transform: rotate(1.5deg) translateY(-7px); } }
.ship-svg .puff2 { transform-box: fill-box; transform-origin: center; opacity: 0; animation: steam 1.76s linear infinite; }
.ship-svg .pu-o { fill: #1D2B45; stroke: #1D2B45; stroke-width: 12; animation-name: steam-o; }
@keyframes steam-o { 0% { transform: translate(0, 10px) scale(.3); opacity: 0; } 8% { opacity: 1; } 50% { opacity: 1; } 78% { opacity: 0; } 100% { transform: translate(-120px, -160px) scale(1.8); opacity: 0; } }
.ship-svg .pu-i { fill: #FFF8EC; }
@keyframes steam { 0% { transform: translate(0, 10px) scale(.3); opacity: 0; } 8% { opacity: 1; } 65% { opacity: .95; } 100% { transform: translate(-120px, -160px) scale(1.8); opacity: 0; } }
.ship-svg .wv { animation: lap 1.6s ease-in-out infinite; }
@keyframes lap { 50% { transform: translateX(-12px); } }
.voyage.back .voy-ship { transform: scaleX(-1); }
.puff { position: absolute; width: 8px; height: 8px; border-radius: 50%; background: #fff; border: 1.5px solid #1D2B45; opacity: 0; animation: puff 2.4s ease-out infinite; }
.voy-ship .puff { left: 20px; top: -2px; }
.voy-ship .puff:nth-of-type(2) { animation-delay: 1.2s; left: 27px; }
@keyframes bob { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-3px) rotate(2deg); } }
@keyframes bob-back { 0%, 100% { transform: scaleX(-1) translateY(0) rotate(-2deg); } 50% { transform: scaleX(-1) translateY(-3px) rotate(2deg); } }
@keyframes puff { 0% { opacity: 0; transform: translate(0, 0) scale(.5); } 15% { opacity: .95; } 100% { opacity: 0; transform: translate(-14px, -22px) scale(1.6); } }
body[data-variant="story"] .wrap { max-width: 1400px; padding-top: 18px; }
body[data-variant="story"] #day { grid-template-columns: minmax(0, 1fr) !important; }
body[data-variant="story"] #day > * { grid-column: 1 !important; grid-row: auto !important; }
body[data-variant="story"] .map-box { height: max(440px, calc(100vh - 300px)) !important; }
/* What to do: the cards on the left, the docks map with what is arranged on the right */
@media (min-width: 1000px) {
  body[data-variant="story"][data-view="step3"] #day { grid-template-columns: minmax(0, 1fr) minmax(380px, .9fr) !important; align-items: start; }
  body[data-variant="story"][data-view="step3"] #day > #row-actions, body[data-variant="story"][data-view="step3"] #day > #ppo-card { grid-column: 1 !important; }
  body[data-variant="story"][data-view="step3"] #day > #day-body { grid-column: 2 !important; grid-row: 1 / span 2 !important; position: sticky; top: 150px; }
  body[data-variant="story"][data-view="step3"] .map-box { height: calc(100vh - 290px) !important; min-height: 380px; }
}
body[data-variant="story"][data-view="step3"] .map-bar .seg-ctl, body[data-variant="story"][data-view="step3"] .map-bar select,
body[data-variant="story"][data-view="step3"] .map-bar label, body[data-variant="story"][data-view="step3"] .map-legend,
body[data-variant="story"][data-view="step3"] .time-row { display: none !important; }
.scroll-next { position: fixed; left: 50%; bottom: 18px; z-index: 50; display: flex; align-items: center; gap: 10px; padding: 8px 16px; border-radius: 999px;
  background: var(--surface); color: var(--ink); border: 1px solid var(--line-strong); box-shadow: 0 10px 30px rgba(0, 0, 0, .3); font-weight: 700; font-size: .9rem;
  transform: translate(-50%, 140%); opacity: 0; transition: transform .3s cubic-bezier(.2, .8, .2, 1), opacity .3s; pointer-events: none; }
.scroll-next.on { transform: translate(-50%, 0); opacity: 1; }
.scroll-next.up { top: 150px; bottom: auto; transform: translate(-50%, -40%); }
.scroll-next.up.on { transform: translate(-50%, 0); }
.sn-arrow { font-size: 1.1rem; color: var(--accent); animation: sn-bob 1.2s ease-in-out infinite; }
@keyframes sn-bob { 50% { transform: translateY(3px); } }
.sn-bar { width: 70px; height: 6px; border-radius: 3px; background: var(--sunk); overflow: hidden; }
.sn-bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .12s; }
:root[data-theme="steam"] .scroll-next { border: 2px solid #1D2B45; box-shadow: 3px 3px 0 #1D2B45; }
.home-btn { width: 46px; height: 40px; padding: 2px 4px; border-radius: 12px; border: 1px solid var(--line-strong); background: var(--surface); cursor: pointer; transition: transform .15s; }
.home-btn:hover { transform: translateY(-2px) rotate(-3deg); }
.home-btn .ship-svg { width: 100%; }
.appbar .brand-mark { display: none; }
:root[data-theme="steam"] .home-btn { border: 2px solid #FFF8EA; background: #FFF8EA; }
.landing.enter { animation: land-in .7s cubic-bezier(.2, .7, .2, 1) both; }
@keyframes land-in { from { transform: translateY(-104%); } to { transform: none; } }
.stk { display: inline-block; background-position: center; background-size: contain; background-repeat: no-repeat; }
:root[data-theme="steam"] .storybar { background: #FFF6E2; border-bottom: 2px dashed #1D2B45; }
:root[data-theme="steam"] .v-btn { border: 2px solid #1D2B45; box-shadow: 3px 3px 0 #1D2B45; }
:root[data-theme="steam"] .v-btn.primary { background: #D8473A; color: #fff; }
:root[data-theme="steam"] .brand-mark { background: none; width: 40px; height: 32px; }
:root[data-theme="steam"] .brand-mark svg { display: none; }
:root[data-theme="steam"] .brand-mark::after { content: ''; width: 40px; height: 32px; background: var(--ico-ship) center / contain no-repeat; }
.deco-gull { position: fixed; z-index: 1; top: 150px; left: -80px; width: 56px; pointer-events: none; display: none; animation: fly 26s linear infinite; }
.deco-gull .spr { display: block; width: 100%; transform: scaleX(-1); }  /* the gull drawing faces left; this one flies right */
:root[data-theme="steam"] .deco-gull { display: block; }
@keyframes fly { from { transform: translateX(0); } to { transform: translateX(calc(100vw + 160px)); } }
/* gulls fly curves: a steady glide across, an eased swoop up and down on a separate wrapper, and a tilt into each turn */
.gl { display: block; animation: swoop 4.6s ease-in-out infinite alternate; }
.gl.b { animation-duration: 3.7s; animation-delay: -1.9s; }
@keyframes swoop { 0% { transform: translateY(-34px) rotate(6deg); } 50% { transform: translateY(6px) rotate(-7deg); } 100% { transform: translateY(40px) rotate(4deg); } }
.gl > .gl2 { display: block; animation: drift-y 9.5s ease-in-out infinite alternate; }
@keyframes drift-y { from { transform: translateY(-18px); } to { transform: translateY(22px); } }
/* landing page */
.landing { position: fixed; inset: 0; z-index: 100; overflow: hidden; display: grid; place-items: center; color: #1D2B45; font-family: "Fredoka", "Trebuchet MS", sans-serif;
  background: linear-gradient(#FFE9C7 0%, #FFD7B0 46%, #FFC9A8 62%, #A9D9D3 62.2%, #7CC3BE 100%); transition: transform .8s cubic-bezier(.6, 0, .3, 1); }
.landing.gone { transform: translateY(-104%); }
/* the sun sets on the horizon (62%): drawn as the half disc above the sea, so none of it can show below */
.l-sun { position: absolute; left: 50%; top: calc(62% - 17vmin); width: 34vmin; height: 17vmin; margin-left: -17vmin; border-radius: 17vmin 17vmin 0 0;
  background: radial-gradient(circle 24vmin at 50% 100%, #FFF3D6, #FFB27A 70%); opacity: .9; }
.l-cloud { position: absolute; left: 0; height: 26px; border-radius: 20px; background: #FFF8EC; border: 2.5px solid #1D2B45; animation: drift linear infinite; }
.l-cloud::before, .l-cloud::after { content: ''; position: absolute; bottom: 8px; border-radius: 50%; background: #FFF8EC; border: 2.5px solid #1D2B45; border-bottom-color: transparent; border-right-color: transparent; transform: rotate(45deg); }
.l-cloud::before { left: 14px; width: 34px; height: 34px; } .l-cloud::after { left: 40px; width: 26px; height: 26px; }
.l-cloud.c1 { top: 9%; width: 110px; animation-duration: 70s; animation-delay: -20s; } .l-cloud.c2 { top: 23%; width: 90px; animation-duration: 95s; animation-delay: -60s; } .l-cloud.c3 { top: 15%; width: 130px; animation-duration: 120s; animation-delay: -95s; }
@keyframes drift { from { transform: translateX(-20vw); } to { transform: translateX(120vw); } }
/* the landing is a grid that centres its children, so the gulls are pinned to its left edge; each flight starts and
   ends wholly off screen, so no gull appears or vanishes in the middle of the sky */
.l-gull { position: absolute; left: 0; width: 72px; z-index: 1; }
.l-gull .spr { display: block; width: 100%; }
.l-gull.g1 { top: 24%; animation: cross 28s linear infinite; animation-delay: -6s; }
.l-gull.g2 { top: 11%; width: 50px; animation: cross 36s linear infinite reverse; animation-delay: -20s; }
/* the gull drawing faces left: g1 flies right, so it is mirrored; g2 flies left as drawn */
.l-gull.g1 .spr { transform: scaleX(-1); }
.l-gull.g2 .spr { --dur: .85s; }
@keyframes cross { from { transform: translateX(-120px); } to { transform: translateX(calc(100vw + 40px)); } }
.l-light { position: absolute; right: 1vw; bottom: 31%; width: 32vmin; z-index: 1; }
.l-light .spr, .l-anchor .spr, .l-wheel .spr, .l-spray .spr { display: block; width: 100%; }
.l-anchor { position: absolute; left: 3vw; bottom: 4%; width: 11vmin; z-index: 4; }
.l-wheel { position: absolute; right: 5vw; bottom: 4%; width: 12vmin; z-index: 4; }
/* the ship scales with the screen height like the waves, so it floats at the same depth on every screen */
/* the ship is placed by its waterline, 22% up: in the first big wave (its crests reach 24.5%, its troughs
   21.5%), so the wave washes over the bottom of the hull on every screen */
.landing { --sw: 40vmin; --wl: 22%; }  /* the ship's width and its waterline's height */
.l-ship { position: absolute; left: 66%; bottom: calc(var(--wl) - var(--sw) * .1283); width: var(--sw); transform: translateX(-50%); z-index: 2; transition: transform 1.3s cubic-bezier(.5, 0, .7, .4); }
/* the ship sits in a sea that runs the whole width of the screen, in front of its hull and behind the big
   waves. Its surface is the waterline, y 363 of the ship's 600 by 440 drawing (77 / 600 of its width up), and it
   is the colour of the sea behind it (the landing's gradient from 78% down), so it only shows on the hull.
   The ship rolls less than the small ones in the story bar, so the bottom of its hull stays under the ripples. */
.l-sea { position: absolute; left: 0; bottom: 0; width: 200%; height: var(--wl); background: linear-gradient(#96D0CA, #7CC3BE); z-index: 2;
  pointer-events: none; animation: wave 18s linear infinite; }
.l-sea svg { position: absolute; left: 0; bottom: calc(100% - 1.2vmin); width: 100%; height: 2.4vmin; fill: #96D0CA; }
.l-ship .ship-svg .rock { animation-name: rock-calm; }
@keyframes rock-calm { 0%, 100% { transform: rotate(-1deg) translateY(0); } 50% { transform: rotate(1deg) translateY(-5px); } }
.l-spray { position: absolute; width: 30%; left: -14%; bottom: 14%; transform: scaleX(-1); }
.l-spray.s2 { width: 22%; left: auto; right: -6%; bottom: 13%; transform: none; }
.l-rock-spray { position: absolute; right: 30%; bottom: -12%; width: 38%; }
.l-rock-spray .spr { display: block; width: 100%; --dur: 1.3s; }
.landing.sail .l-ship { transform: translateX(70vw); }
.l-waves { position: absolute; left: 0; bottom: 0; width: 200%; height: 30%; z-index: 3; pointer-events: none; }
.l-waves path { animation: wave linear infinite; }
.l-waves .w1 { fill: #7CC3BE; animation-duration: 14s; } .l-waves .w2 { fill: #3E9E9C; animation-duration: 10s; } .l-waves .w3 { fill: #1D6F78; animation-duration: 7s; }
@keyframes wave { to { transform: translateX(-50%); } }
.l-sun { left: 66%; }
/* the words sit in the sky on the left; the ship sails the right half */
.l-card { position: relative; z-index: 5; display: grid; justify-items: start; gap: 14px; text-align: left; padding: 0 16px; place-self: center start; margin: -22vh 0 0 3.5vw; max-width: min(660px, 52vw); }
.l-kicker { font-weight: 600; letter-spacing: .12em; text-transform: uppercase; font-size: .85rem; }
.l-plate { position: relative; padding: 14px 38px 16px; border-radius: 18px; background: #1D2B45; color: #FFF6E2; box-shadow: 0 0 0 4px #FFF6E2, 0 0 0 7px #1D2B45, 8px 10px 0 7px rgba(29, 43, 69, .3); }
.l-plate::before, .l-plate::after { content: ''; position: absolute; top: 50%; width: 9px; height: 9px; margin-top: -4.5px; border-radius: 50%; background: #F2B84B; }
.l-plate::before { left: 13px; } .l-plate::after { right: 13px; }
.l-plate h1 { white-space: nowrap; font-family: inherit; font-weight: 700; font-size: clamp(1.7rem, 4.1vw, 3.6rem); line-height: 1; letter-spacing: .01em; color: #FFF6E2; }
.l-plate h1 span { color: #FF8A73; }
.l-sub { font-size: clamp(1rem, 2vw, 1.3rem); font-weight: 500; max-width: 30ch; }
.l-tickets { display: flex; flex-wrap: wrap; gap: 10px; }
.l-ticket { display: grid; padding: 6px 20px 8px; background: #FFF6E2; border: 2.5px solid #1D2B45; border-radius: 10px; box-shadow: 3px 3px 0 #1D2B45; }
.l-ticket b { font-size: 1.6rem; line-height: 1.1; color: #D8473A; }
.l-ticket span { font-size: .8rem; font-weight: 600; }
.l-go { display: inline-flex; align-items: center; gap: 12px; padding: 10px 28px 10px 12px; border-radius: 999px; border: 3px solid #1D2B45; background: #D8473A; color: #fff;
  font: 700 1.35rem "Fredoka", sans-serif; cursor: pointer; box-shadow: 4px 5px 0 #1D2B45; transition: transform .15s, box-shadow .15s; }
.l-go:hover { transform: translate(-1px, -2px); box-shadow: 5px 7px 0 #1D2B45; }
.l-go:active { transform: translate(3px, 4px); box-shadow: 1px 1px 0 #1D2B45; }
.l-go .spr { width: 40px; flex: none; }
.l-src { font-size: .78rem; font-weight: 500; max-width: min(60ch, 100%); padding: 3px 10px; border-radius: 999px; background: rgba(255, 246, 226, .7); }
.l-sound { position: absolute; top: 16px; right: 16px; z-index: 6; display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 999px; border: 2.5px solid #1D2B45;
  background: #FFF6E2; color: #1D2B45; font: 600 .95rem "Fredoka", sans-serif; cursor: pointer; box-shadow: 3px 3px 0 #1D2B45; }
.l-sound svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.l-sound[aria-pressed="false"] .on, .l-sound[aria-pressed="true"] .off { display: none; }
.l-sound.hint { animation: hint 1.6s ease-in-out infinite; }
@keyframes hint { 50% { transform: scale(1.08); } }
/* portrait and narrow screens: words on top, the ship below them on the horizon */
/* tall landscape screens (1440p and up): the words grow with the ship, which scales with the screen height */
@media (min-height: 950px) and (min-aspect-ratio: 1/1) { .l-card { zoom: 1.2; } }
@media (min-height: 1200px) and (min-aspect-ratio: 1/1) { .l-card { zoom: 1.4; } }
@media (max-width: 820px), (max-aspect-ratio: 1/1) {
  .l-card { place-self: start start; margin: 28px 0 0 4vw; max-width: 92vw; }
  .landing { --sw: 46vmin; } .l-ship { left: 46%; }
  .l-sun { left: 46%; }
  .l-light { width: 30vmin; right: 2vw; bottom: 33%; }
}
/* short landscape screens (a phone on its side): a compact card, the ship pushed right */
@media (max-height: 520px) and (min-aspect-ratio: 1/1) {
  .l-card { margin: -6vh 0 0 3vw; gap: 8px; place-self: center start; justify-items: start; text-align: left; max-width: 58vw; }
  .l-kicker, .l-sub { display: none; }
  .l-ticket { padding: 3px 12px 5px; } .l-ticket b { font-size: 1.2rem; }
  .l-go { font-size: 1.1rem; padding: 6px 20px 6px 8px; } .l-go .spr { width: 30px; }
  .landing { --sw: 30vmax; } .l-ship { left: 72%; } .l-sun { left: 72%; } .l-light { width: 24vmin; right: 1vw; }
}
@media (max-width: 640px) { .l-light { width: 34vmin; right: 0; bottom: 34%; } .l-ship { left: 42%; }
  .l-card { margin: 68px 0 0; max-width: 100%; gap: 12px; } .l-tickets { gap: 8px; flex-wrap: nowrap; }
  .l-ticket { padding: 4px 11px 6px; } .l-ticket b { font-size: 1.3rem; } .l-ticket span { font-size: .72rem; white-space: nowrap; }
  .storybar { grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px 10px; } .story-q { grid-column: 1 / -1; } .voyage { width: auto; margin-right: 22px; }
  .story-time { grid-column: 1; min-width: 0; } .story-time input { flex: 1; width: auto; min-width: 0; }
  body[data-view="step1"] .voyage, body[data-view="step2"] .voyage, body[data-view="step3"] .voyage { display: none; }
  .story-q { font-size: 1.15rem; gap: 8px; white-space: normal; } .story-q .spr { height: 34px; } #story-q { overflow: visible; text-overflow: clip; }
  .storybar .v-btn { padding: 6px 12px; min-height: 36px; min-width: 64px; } }
@media (prefers-reduced-motion: reduce) { .landing *, .voy-ship, .deco-gull { animation: none !important; transition: none !important; } .landing { transition: none; } }
""", r"""
  const NAVY = '#1D2B45', CREAM = '#FFF6E6', RED = '#E4573F';
  const HULL = 'M24 262 L576 262 L548 378 Q545 388 534 388 L92 388 Q80 388 74 378 Z';
  // steam: the same puffs drawn twice, a navy layer under a cream one, so they merge into one outlined cloud
  const puffSet = cls => [259, 381].map((x, f) => Array.from({ length: 8 }, (_, i) => `<circle class="puff2 ${cls}" cx="${x}" cy="62" r="26" style="animation-delay:${-(i * 0.22 + f * 0.11).toFixed(2)}s"/>`).join('')).join('');
  const puffs = puffSet('pu-o') + puffSet('pu-i');
  const range = (a, b, st) => Array.from({ length: Math.floor((b - a) / st) + 1 }, (_, i) => a + i * st);
  const SHIP_SVG = id => `<svg class="ship-svg" viewBox="0 0 600 440" aria-hidden="true"><defs><clipPath id="hc-${id}"><path d="${HULL}"/></clipPath></defs>
    <g class="rock" stroke="${NAVY}" stroke-width="7" stroke-linejoin="round" stroke-linecap="round">
      <g stroke="none">${puffs}</g>
      <line x1="160" y1="214" x2="160" y2="98"/><line x1="146" y1="118" x2="174" y2="118"/><circle cx="160" cy="92" r="7" fill="${NAVY}"/>
      <line x1="528" y1="262" x2="528" y2="150"/><path d="M528 152 L580 165 L528 180 Z" fill="${RED}"/>
      ${[228, 350].map(x => `<path d="M${x} 72 L${x + 62} 72 L${x + 56} 172 L${x + 6} 172 Z" fill="${RED}"/><path d="M${x} 72 L${x + 62} 72 L${x + 61} 92 L${x + 1} 92 Z" fill="${NAVY}"/><line x1="${x + 4}" y1="128" x2="${x + 58}" y2="128" stroke="${CREAM}" stroke-width="6"/>`).join('')}
      <rect x="170" y="168" width="290" height="50" rx="9" fill="${CREAM}"/>
      ${range(192, 436, 34).map(x => `<rect x="${x}" y="184" width="18" height="16" rx="4" fill="${NAVY}" stroke="none"/>`).join('')}
      <rect x="116" y="214" width="396" height="52" rx="9" fill="${CREAM}"/>
      ${range(140, 488, 34).map(x => `<rect x="${x}" y="232" width="18" height="16" rx="4" fill="${NAVY}" stroke="none"/>`).join('')}
      <g clip-path="url(#hc-${id})" stroke="none"><path d="${HULL}" fill="${CREAM}"/><rect x="0" y="328" width="600" height="22" fill="${NAVY}"/><rect x="0" y="350" width="600" height="50" fill="${RED}"/></g>
      <path d="${HULL}" fill="none"/>
      ${range(150, 530, 40).map(x => `<circle cx="${x}" cy="298" r="9" fill="${CREAM}" stroke-width="5"/>`).join('')}
      <g stroke-width="5" fill="none"><circle cx="96" cy="282" r="5"/><path d="M96 287 V318 M84 297 H108 M80 306 Q96 330 112 306"/></g>
      ${id === 'land' ? '' /* the landing ship sits in the full-width sea (.l-sea) */ : `<g class="wv"><path d="M30 404 ${range(0, 10, 1).map(() => 'q27 -20 54 0').join(' ')} V440 H30 Z" fill="#3E9E9C"/>
      <path d="M30 404 ${range(0, 10, 1).map(() => 'q27 -20 54 0').join(' ')}" fill="none" stroke="#FFF8EC" stroke-width="6"/></g>`}
    </g></svg>`;
  const STEPS = [
    { q: 'When are the hard days?', ico: 'lighthouse', show: [calSec] },
    { q: 'How bad is it?', ico: 'ring', show: ['#day-head', '#notices'] },
    { q: 'Watch the day', ico: 'gull', show: ['#day-head', '#day-body'], map: true },
    { q: 'What to do', ico: 'wheel', show: ['#row-actions', '#ppo-card', '#day-body'], map: true },
    { q: 'Does the AI help?', ico: 'hat', show: [methodSec, '#ppo-viz', '#bus-live'] },
  ];
  // everything starts hidden; each step lists what it shows
  [calSec, methodSec, '#day-head', '#notices', '#row-actions', '#ppo-card', '#day-body', '#row-vehicles', '#heat-card', '#ships-block',
   '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live', '#ppo-viz', '#ppo-test', '#freight-card'].forEach(s => tag(s, 'none'));
  methodSec.querySelectorAll(':scope > .sec-head, :scope > .grid2, :scope > .folds > details').forEach(el => { if (el.id !== 'ppo-viz') tag(el, 'none'); });
  STEPS.forEach((st, i) => st.show.forEach(s => { const el = typeof s === 'string' ? $(s) : s; el.dataset.views = (el.dataset.views === 'none' ? '' : el.dataset.views + ' ') + 'step' + i; }));
  const bar = document.createElement('div'); bar.className = 'storybar';
  bar.innerHTML = `<span class="story-q"><span class="story-ico" id="story-stk" aria-hidden="true"></span><span class="story-n" id="story-n"></span><span id="story-q"></span><span id="story-src"></span></span>
    <label class="story-time" title="Time of day: moves the map, the roads and the day line"><b id="st-clock"></b><input type="range" id="st-slider" min="0" max="${N_BINS - 1}" step="1" aria-label="Time of day"></label>
    <div class="voyage" id="voyage" role="tablist" aria-label="Steps"><span class="voy-sea"></span>
      ${STEPS.map((s, i) => `<button class="voy-port" role="tab" data-step="${i}" style="--x:${i / (STEPS.length - 1)}" aria-label="Step ${i + 1}: ${esc(s.q)}" title="${esc(s.q)}"></button>`).join('')}
      <span class="voy-ship" aria-hidden="true">${SHIP_SVG('bar')}</span></div>
    <button class="v-btn" id="story-back">Back</button><button class="v-btn primary" id="story-next">Next</button>`;
  $('.appbar').after(bar);
  const home = document.createElement('button'); home.type = 'button'; home.className = 'home-btn'; home.title = 'Back to the start'; home.setAttribute('aria-label', 'Back to the start');
  home.innerHTML = SHIP_SVG('home'); $('.brand').prepend(home);
  const gull = document.createElement('span'); gull.className = 'deco-gull'; gull.innerHTML = '<span class="gl"><span class="gl2"><span class="spr spr-gull"></span></span></span>'; gull.setAttribute('aria-hidden', 'true'); document.body.append(gull);
  let step = 0;
  function showStep(i, fromBelow) {
    const prev = step;
    step = Math.max(0, Math.min(STEPS.length - 1, i));
    showSet('step' + step);
    $('#story-n').textContent = `${step + 1}/${STEPS.length}`; $('#story-q').textContent = STEPS[step].q;
    const stk = $('#story-stk'); stk.innerHTML = `<span class="spr spr-${STEPS[step].ico}"></span>`; stk.style.animation = 'none'; void stk.offsetWidth; stk.style.animation = '';
    const voy = $('#voyage'); voy.style.setProperty('--k', step / (STEPS.length - 1)); voy.classList.toggle('back', step < prev);
    bar.querySelectorAll('[data-step]').forEach(b => { b.setAttribute('aria-selected', String(+b.dataset.step === step)); b.classList.toggle('done', +b.dataset.step <= step); });
    $('#story-back').disabled = step === 0; $('#story-next').disabled = step === STEPS.length - 1;
    if (STEPS[step].map) mapLive(true); else stopVehicles();
    if (step === 4) { const v = $('#ppo-viz'); if (v && !v.open) { v.open = true; v.dispatchEvent(new Event('toggle')); } }
    const w = $('.wrap'); w.classList.remove('view-enter'); void w.offsetWidth; w.classList.add('view-enter');
    window.scrollTo(0, fromBelow ? document.documentElement.scrollHeight : 0);
    scrollHint();
  }
  $('#story-back').addEventListener('click', () => showStep(step - 1));
  // the bar's time slider and every other way of changing the time (map slider, day line, Play) stay in step
  const stSlider = $('#st-slider'), stClock = $('#st-clock');
  const syncTime = () => { stSlider.value = state.bin; stClock.textContent = binTime(state.bin).slice(0, 5); };
  const setBin0 = setBin;
  setBin = (b, keepMinute) => { setBin0(b, keepMinute); syncTime(); };
  stSlider.addEventListener('input', () => setBin(+stSlider.value));
  new MutationObserver(syncTime).observe($('#clock'), { childList: true, characterData: true, subtree: true });   // a new day moves the time without setBin
  syncTime();

  /* scroll through: past the end of a step, keep scrolling (wheel, trackpad, swipe, Page Down) to reach the
     next one, and past the top to go back. A bar fills as you pull, so a stray flick never turns the page. */
  const hint = document.createElement('div'); hint.className = 'scroll-next'; hint.setAttribute('aria-hidden', 'true');
  hint.innerHTML = '<span class="sn-arrow"></span><span class="sn-t"></span><span class="sn-bar"><i></i></span>';
  document.body.append(hint);
  const NEED = 280, tgt = e => (e.target instanceof Element ? e.target : document.body);
  let pull = 0, lock = 0, relax = null;
  const atBottom = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 6;
  const atTop = () => scrollY <= 2;
  const blocked = () => performance.now() < lock || !!document.querySelector('.landing') || document.body.classList.contains('selecting');
  function scrollHint() {
    const down = pull >= 0, target = step + (down ? 1 : -1), show = !blocked() && STEPS[target] && (down ? atBottom() : pull < 0);
    hint.classList.toggle('on', !!show); hint.classList.toggle('up', !down);
    if (!show) return;
    hint.querySelector('.sn-arrow').textContent = down ? '↓' : '↑';
    hint.querySelector('.sn-t').textContent = `${down ? 'Keep scrolling' : 'Back to'}: ${STEPS[target].q}`;
    hint.querySelector('.sn-bar i').style.width = `${Math.min(100, Math.abs(pull) / NEED * 100)}%`;
  }
  function pullBy(d) {
    if (blocked()) { pull = 0; return scrollHint(); }
    if (d > 0 && atBottom() && step < STEPS.length - 1) pull = Math.max(0, pull) + d;
    else if (d < 0 && atTop() && step > 0) pull = Math.min(0, pull) + d;
    else pull = 0;
    if (Math.abs(pull) >= NEED) { const dir = Math.sign(pull); pull = 0; lock = performance.now() + 900; showStep(step + dir, dir < 0); return; }
    scrollHint();
    clearTimeout(relax); relax = setTimeout(() => { pull = 0; scrollHint(); }, 700);
  }
  addEventListener('wheel', e => { if (!e.ctrlKey && !tgt(e).closest('.dial')) pullBy(e.deltaY * (e.deltaMode === 1 ? 32 : e.deltaMode === 2 ? innerHeight : 1)); }, { passive: true });
  let touchY = null;
  addEventListener('touchstart', e => { touchY = e.touches[0].clientY; }, { passive: true });
  addEventListener('touchmove', e => { if (touchY == null || tgt(e).closest('.map-box')) return; const y = e.touches[0].clientY; pullBy((touchY - y) * 2); touchY = y; }, { passive: true });
  addEventListener('touchend', () => { touchY = null; });
  addEventListener('scroll', scrollHint, { passive: true });
  addEventListener('keydown', e => {
    if (blocked() || e.defaultPrevented || tgt(e).closest('input, select, textarea, [role="slider"]')) return;
    const fwd = e.key === 'PageDown' || (e.key === ' ' && !tgt(e).closest('button')) || e.key === 'ArrowDown', back = e.key === 'PageUp' || e.key === 'ArrowUp';
    if (fwd && atBottom() && step < STEPS.length - 1) { e.preventDefault(); lock = performance.now() + 400; showStep(step + 1); }
    else if (back && atTop() && step > 0) { e.preventDefault(); lock = performance.now() + 400; showStep(step - 1, true); }
  });
  $('#story-next').addEventListener('click', () => showStep(step + 1));
  bar.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => showStep(+b.dataset.step)));
  // a new day on a map step (stepper, calendar or the map's own day chips) starts its vehicles straight away
  new MutationObserver(() => { if (STEPS[step].map && !document.querySelector('.landing')) setTimeout(() => mapLive(true), 60); }).observe($('#day-chip'), { childList: true, characterData: true, subtree: true });
  // sources stay one ? away, beside the step question
  setTimeout(() => { const pw = $('.provenance') && $('.provenance').closest('.qwrap'); if (pw) $('#story-src').append(pw); }, 0);

  /* landing page */
  const live = DATA.days.filter(d => !d.beyond);
  const nCalls = live.reduce((n, d) => n + d.calls.length, 0), nHard = live.filter(d => ['high', 'severe'].includes(level(uplift(d)).key)).length;
  const prov = ($('.provenance') || {}).textContent || '', when = (prov.match(/VTS schedule \(collected ([^)]+)\)/) || [])[1];
  const land = document.createElement('div'); land.className = 'landing'; land.setAttribute('role', 'dialog'); land.setAttribute('aria-modal', 'true'); land.setAttribute('aria-labelledby', 'l-title');
  const wave = (y, a) => `M0 ${y} ` + Array.from({ length: 12 }, () => `q 50 ${-a} 100 0 t 100 0`).join(' ') + ' V300 H0Z';
  land.innerHTML = `<div class="l-sun"></div><div class="l-cloud c1"></div><div class="l-cloud c2"></div><div class="l-cloud c3"></div>
    <span class="l-gull g1" aria-hidden="true"><span class="gl"><span class="gl2"><span class="spr spr-gull"></span></span></span></span><span class="l-gull g2" aria-hidden="true"><span class="gl b"><span class="gl2"><span class="spr spr-gull"></span></span></span></span>
    <span class="l-light" aria-hidden="true"><span class="spr spr-lighthouse"></span><span class="l-rock-spray"><span class="spr spr-spray"></span></span></span>
    <div class="l-ship" aria-hidden="true">${SHIP_SVG('land')}<span class="l-spray"><span class="spr spr-spray"></span></span><span class="l-spray s2"><span class="spr spr-spray"></span></span></div>
    <div class="l-sea" aria-hidden="true"><svg viewBox="0 0 2400 40" preserveAspectRatio="none"><path d="${wave(20, 8)}"/></svg></div>
    <button type="button" class="l-sound hint" id="l-sound" aria-pressed="false" aria-label="Sound"><svg viewBox="0 0 24 24"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path class="on" d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/><path class="off" d="M16 9.5l5 5M21 9.5l-5 5"/></svg><span id="l-sound-t">Sound on</span></button>
    <svg class="l-waves" viewBox="0 0 2400 300" preserveAspectRatio="none" aria-hidden="true"><path class="w1" d="${wave(70, 30)}"/><path class="w2" d="${wave(140, 24)}"/><path class="w3" d="${wave(210, 18)}"/></svg>
    <span class="l-anchor" aria-hidden="true"><span class="spr spr-anchor"></span></span><span class="l-wheel" aria-hidden="true"><span class="spr spr-wheel"></span></span>
    <div class="l-card">
      <p class="l-kicker">Southampton docks · next six weeks</p>
      <div class="l-plate"><h1 id="l-title">Cruise-day <span>traffic</span></h1></div>
      <p class="l-sub">Which days the ships jam the roads, and what to do about it.</p>
      <div class="l-tickets"><span class="l-ticket"><b>${nCalls}</b><span>ship calls</span></span><span class="l-ticket"><b>${nHard}</b><span>heavy days</span></span><span class="l-ticket"><b>${live.length}</b><span>days forecast</span></span></div>
      <button class="l-go" id="l-go"><span class="spr spr-ring" aria-hidden="true"></span>Set sail</button>
      <p class="l-src">Ship calls: ABP Southampton VTS schedule${when ? `, collected ${esc(when)}` : ''}. Traffic is modelled, not measured.</p>
    </div>`;
  /* landing sound, made with the Web Audio API: waves (filtered noise), seagull cries (swept, warbled
     sawtooth), a horn, and "Drunken Sailor" (traditional, public domain) on a two-reed accordion with an
     oom-pah bass. Browsers only allow sound after a click or key press, so it starts on the first one. */
  const Sea = (() => {
    let ctx = null, out = null, music = null, on = false;
    const N = { D3: 146.83, C3: 130.81, A2: 110, G2: 98, F3: 174.61, A3: 220, C4: 261.63, D4: 293.66, E4: 329.63, F4: 349.23, G4: 392, A4: 440, B4: 493.88, C5: 523.25, D5: 587.33, E5: 659.25 };
    const TUNE = 'A4 A4 A4 A4 A4 D4 F4 A4 G4 G4 G4 G4 G4 C4 E4 G4 A4 A4 A4 A4 A4 B4 C5 D5 C5 A4 G4 E4 D4 - D4 -'.split(' ');
    const BASS = ['D3', 'D3', 'C3', 'C3', 'D3', 'D3', 'C3', 'D3'], CHORD = { D3: ['D4', 'F4', 'A4'], C3: ['C4', 'E4', 'G4'] };
    function voice(f, t, dur, vol, type, cut, detune = 0) {
      const o = ctx.createOscillator(), g = ctx.createGain(), lp = ctx.createBiquadFilter();
      o.type = type; o.frequency.value = f; o.detune.value = detune; lp.type = 'lowpass'; lp.frequency.value = cut;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.02); g.gain.setValueAtTime(vol, t + dur * 0.7); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(lp).connect(g).connect(music); o.start(t); o.stop(t + dur + 0.05);
    }
    function playLoop(t0) {
      const E = 0.2;                                           // one quaver
      TUNE.forEach((n, i) => { if (n === '-') return; const t = t0 + i * E; [-7, 7].forEach(dt => voice(N[n], t, E * 0.95, 0.05, 'sawtooth', 2200, dt)); });
      BASS.forEach((b, i) => {
        const t = t0 + i * 4 * E;
        voice(N[b] / 2, t, E * 1.6, 0.09, 'triangle', 800); voice(N[b] / 2 * 1.5, t + 2 * E, E * 1.4, 0.06, 'triangle', 800);
        [E, 3 * E].forEach(dt => CHORD[b].forEach(c => voice(N[c] / 2, t + dt, E * 0.8, 0.018, 'sawtooth', 1400)));
      });
      return TUNE.length * E;
    }
    function waves() {
      const len = ctx.sampleRate * 3, buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0);
      let last = 0; for (let i = 0; i < len; i++) { last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02; d[i] = last * 3.5; }
      const src = ctx.createBufferSource(), lp = ctx.createBiquadFilter(), g = ctx.createGain(), lfo = ctx.createOscillator(), lg = ctx.createGain();
      src.buffer = buf; src.loop = true; lp.type = 'lowpass'; lp.frequency.value = 700; g.gain.value = 0.22;
      lfo.frequency.value = 0.11; lg.gain.value = 0.16; lfo.connect(lg).connect(g.gain);
      src.connect(lp).connect(g).connect(out); src.start(); lfo.start();
    }
    function gull(pitch = 1) {
      const t0 = ctx.currentTime + 0.05, n = 2 + Math.floor(Math.random() * 3);
      for (let i = 0; i < n; i++) {
        const t = t0 + i * (0.2 + Math.random() * 0.06), o = ctx.createOscillator(), bp = ctx.createBiquadFilter(), g = ctx.createGain(), v = ctx.createOscillator(), vg = ctx.createGain();
        o.type = 'sawtooth'; bp.type = 'bandpass'; bp.frequency.value = 1700 * pitch; bp.Q.value = 2.5;
        o.frequency.setValueAtTime(1300 * pitch, t); o.frequency.exponentialRampToValueAtTime(2200 * pitch, t + 0.05); o.frequency.exponentialRampToValueAtTime(850 * pitch, t + 0.19);
        v.frequency.value = 32; vg.gain.value = 90 * pitch; v.connect(vg).connect(o.frequency);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.3, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.21);
        o.connect(bp).connect(g).connect(out); o.start(t); v.start(t); o.stop(t + 0.23); v.stop(t + 0.23);
      }
    }
    function horn() {
      const t = ctx.currentTime + 0.02;
      [[110, 0], [138.6, 0], [110, 0.75], [138.6, 0.75]].forEach(([f, dt]) => {
        const o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
        o.type = 'sawtooth'; o.frequency.value = f; lp.type = 'lowpass'; lp.frequency.value = 600;
        g.gain.setValueAtTime(0.0001, t + dt); g.gain.exponentialRampToValueAtTime(0.16, t + dt + 0.06); g.gain.setValueAtTime(0.16, t + dt + 0.55); g.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.7);
        o.connect(lp).connect(g).connect(out); o.start(t + dt); o.stop(t + dt + 0.75);
      });
    }
    // one track only: the music is scheduled once into a single context; sound off fades it and pauses
    // the context, sound on resumes the same track where it stopped, so toggling never stacks copies
    let next = 0, ticker = null, cryT = null, lastGull = -9, offT = null;
    const tick = () => { if (!on) return; if (next < ctx.currentTime) next = ctx.currentTime + 0.1; while (next < ctx.currentTime + 1) next += playLoop(next); };
    function start() {
      if (on) return; on = true;
      clearTimeout(offT);
      if (!ctx) {
        ctx = new (window.AudioContext || window.webkitAudioContext)(); out = ctx.createGain(); out.gain.value = 0.0001; out.connect(ctx.destination);
        music = ctx.createGain(); music.gain.value = 0.9; music.connect(out); waves(); next = ctx.currentTime + 0.6;
      }
      ctx.resume().then(() => {
        if (!on) return;
        out.gain.cancelScheduledValues(ctx.currentTime); out.gain.setTargetAtTime(0.8, ctx.currentTime, 0.3);
        if (ctx.currentTime - lastGull > 1.5) { gull(1); lastGull = ctx.currentTime; }
        tick(); if (!ticker) ticker = setInterval(tick, 250);
        const cry = () => { if (!on) return; gull(0.85 + Math.random() * 0.35); lastGull = ctx.currentTime; cryT = setTimeout(cry, 3500 + Math.random() * 5000); };
        clearTimeout(cryT); cryT = setTimeout(cry, 2600);
      });
    }
    function stop(fade = 0.25) {
      if (!on || !ctx) return; on = false;
      clearInterval(ticker); ticker = null; clearTimeout(cryT);
      out.gain.cancelScheduledValues(ctx.currentTime); out.gain.setTargetAtTime(0.0001, ctx.currentTime, fade);
      clearTimeout(offT); offT = setTimeout(() => { if (!on) ctx.suspend(); }, fade * 5000);
    }
    return { start, stop, horn: () => { if (on && ctx) horn(); }, get on() { return on; } };
  })();
  let wantSound = true;
  try { wantSound = localStorage.getItem('forecast-sound') !== 'off'; } catch (e) { /* no storage: sound allowed */ }
  const soundBtn = land.querySelector('#l-sound');
  function setSound(v, remember) {
    v ? Sea.start() : Sea.stop();
    soundBtn.setAttribute('aria-pressed', String(v)); soundBtn.classList.remove('hint'); $('#l-sound-t').textContent = v ? 'Sound off' : 'Sound on';
    if (remember) try { localStorage.setItem('forecast-sound', v ? 'on' : 'off'); } catch (e) { /* not remembered */ }
  }
  soundBtn.addEventListener('click', e => { e.stopPropagation(); setSound(!Sea.on, true); });
  // the first click or key press on the landing page brings in the gulls and the music
  const firstTouch = e => { if (wantSound && !Sea.on && !e.target.closest('#l-sound')) setSound(true); };
  land.addEventListener('pointerdown', firstTouch, { once: true });
  land.addEventListener('keydown', firstTouch, { once: true });
  // browsers that already allow sound here (the visitor has interacted with the site before) play it straight away
  setTimeout(() => { try { const t = new (window.AudioContext || window.webkitAudioContext)(), ok = t.state === 'running'; t.close(); if (ok && wantSound && document.body.contains(land)) setSound(true); } catch (e) { /* no audio */ } }, 400);
  function showLanding() {
    stopVehicles();
    land.classList.remove('sail', 'gone'); land.classList.add('enter');
    document.body.append(land);
    setTimeout(() => land.classList.remove('enter'), 800);
    if (wantSound) setSound(true);
    $('#l-go').focus({ preventScroll: true });
  }
  home.addEventListener('click', showLanding);
  const sail = () => {
    if (land.classList.contains('sail')) return;
    Sea.horn(); setTimeout(() => Sea.stop(1.2), 900);
    land.classList.add('sail');
    setTimeout(() => land.classList.add('gone'), REDUCED ? 0 : 650);
    setTimeout(() => { land.remove(); $('#story-next').focus({ preventScroll: true }); if (STEPS[step].map) mapLive(true); }, REDUCED ? 0 : 1500);
  };
  land.querySelector('#l-go').addEventListener('click', sail);
  if (location.hash !== '#app') {
    document.body.append(land);
    land.addEventListener('keydown', e => { if (e.key === 'Escape' || e.key === 'PageDown' || e.key === 'ArrowDown') sail(); });
    // scrolling down on the landing page sets sail too
    land.addEventListener('wheel', e => { if (e.deltaY > 20) sail(); }, { passive: true });
    let ly = null;
    land.addEventListener('touchstart', e => { ly = e.touches[0].clientY; }, { passive: true });
    land.addEventListener('touchmove', e => { if (ly != null && ly - e.touches[0].clientY > 60) { ly = null; sail(); } }, { passive: true });
    setTimeout(() => $('#l-go').focus({ preventScroll: true }), 50);
  }
  renderChip(); showStep(0);
""")

# 3 ---------------------------------------------------------------- Officer: decisions only
VARIANTS["officer"] = ("""
body[data-variant="officer"] .wrap { max-width: 1440px; grid-template-columns: minmax(300px, 400px) minmax(0, 1fr); align-items: start; gap: 24px; padding-top: 18px; }
body[data-variant="officer"] .wrap > section:first-of-type { position: sticky; top: 76px; }
body[data-variant="officer"] .cal .cell { min-height: 48px; padding: 4px 6px; }
body[data-variant="officer"] .cal .cell-tags, body[data-variant="officer"] .cal .cell-lv, body[data-variant="officer"] .cal .today { display: none; }
body[data-variant="officer"] .cal .dnum { font-size: 1rem; }
body[data-variant="officer"] #legend { font-size: .75rem; }
body[data-variant="officer"] #day { grid-template-columns: minmax(0, 1fr) !important; }
body[data-variant="officer"] #day > * { grid-column: 1 !important; grid-row: auto !important; }
body[data-variant="officer"] .tile:nth-child(1), body[data-variant="officer"] .tile:nth-child(4) { display: none; }
body[data-variant="officer"] .dayline { display: none; }
body[data-variant="officer"] .map-box { height: 300px !important; }
body[data-variant="officer"] .map-bar .seg-ctl, body[data-variant="officer"] .map-bar select, body[data-variant="officer"] .map-bar label, body[data-variant="officer"] .time-row, body[data-variant="officer"] .map-legend { display: none; }
@media (max-width: 900px) { body[data-variant="officer"] .wrap { grid-template-columns: minmax(0, 1fr); } body[data-variant="officer"] .wrap > section:first-of-type { position: static; } }
""", r"""
  tag(calSec, 'officer');
  ['#day-head', '#notices', '#row-actions', '#ppo-card', '#day-body'].forEach(s => tag(s, 'officer'));
  [methodSec, '#row-vehicles', '#heat-card', '#ships-block', '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live'].forEach(s => tag(s, 'none'));
  // order on the right: verdict, notices, decisions, then a small map for context
  const day_ = $('#day'); ['#day-head', '#notices', '#row-actions', '#ppo-card', '#day-body'].forEach(s => day_.append($(s)));
  showSet('officer'); renderChip(); mapLive(false);
""")

# 4 ---------------------------------------------------------------- Wallboard: big, cycling, glanceable
VARIANTS["wall"] = ("""
body[data-variant="wall"] .stepper, body[data-variant="wall"] .theme-pick { display: none !important; }
body[data-variant="wall"] .wrap { max-width: none; padding: 16px 24px; gap: 16px; }
.wall-clock { margin-left: auto; font-family: var(--font-data); font-size: 2rem; font-weight: 750; font-variant-numeric: tabular-nums; }
body[data-variant="wall"] .cal-dow, body[data-variant="wall"] #legend { display: none !important; }
body[data-variant="wall"] .cal { grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 10px; }
body[data-variant="wall"] .cal .wall-hide { display: none; }
body[data-variant="wall"] .cal .cell { min-height: 150px; padding: 14px; border-radius: 14px; }
body[data-variant="wall"] .cal .dnum { font-size: 2.6rem; }
body[data-variant="wall"] .cal .cell-ships .ico { width: 26px; height: 20px; }
body[data-variant="wall"] .cal .cell-lv { font-size: 1.3rem; }
body[data-variant="wall"] .cal .cell[aria-pressed="true"] { outline-width: 5px; transform: translateY(-4px); }
body[data-variant="wall"] #day { grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr) !important; align-items: start; }
body[data-variant="wall"] #day > #day-body { grid-column: 1 !important; grid-row: 1 / span 2 !important; }
body[data-variant="wall"] #day > #day-head { grid-column: 2 !important; grid-row: 1 !important; }
body[data-variant="wall"] .tiles { grid-template-columns: 1fr 1fr; }
body[data-variant="wall"] .tile .v { font-size: 2.6rem; }
body[data-variant="wall"] .map-box { height: calc(100vh - 380px) !important; min-height: 360px; }
body[data-variant="wall"] .map-bar, body[data-variant="wall"] .time-row, body[data-variant="wall"] .veh-row, body[data-variant="wall"] .map-legend { display: none !important; }
.wall-progress { height: 4px; background: var(--accent); width: 0; transition: width linear; }
""", r"""
  const clock = document.createElement('span'); clock.className = 'wall-clock'; $('.appbar').append(clock);
  const tick = () => { const n = new Date(); clock.textContent = `${pad(n.getHours())}:${pad(n.getMinutes())}`; };
  tick(); setInterval(tick, 10000);
  const prog = document.createElement('div'); prog.className = 'wall-progress'; $('.appbar').after(prog);
  tag(calSec, 'wall'); tag('#day-head', 'wall'); tag('#day-body', 'wall');
  [methodSec, '#notices', '#row-actions', '#ppo-card', '#row-vehicles', '#heat-card', '#ships-block', '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live'].forEach(s => tag(s, 'none'));
  const WEEK = DATES.filter(iso => !BY_DATE[iso].beyond && iso >= ISSUED_DAY).slice(0, 7);
  const trim = () => $('#cal').querySelectorAll('.cell').forEach(c => c.classList.toggle('wall-hide', !WEEK.includes(c.dataset.date)));
  new MutationObserver(trim).observe($('#cal'), { childList: true });
  let auto = true, k = Math.max(0, WEEK.indexOf(state.date));
  function cycle() {
    if (!auto) return;
    k = (k + 1) % WEEK.length; selectDay(WEEK[k], false); mapLive(true);
    prog.style.transition = 'none'; prog.style.width = '0'; void prog.offsetWidth; prog.style.transition = 'width 12s linear'; prog.style.width = '100%';
  }
  ['pointerdown', 'keydown', 'wheel'].forEach(ev => addEventListener(ev, () => { auto = false; prog.style.width = '0'; }, { once: true }));
  showSet('wall'); selectDay(WEEK[0], false); trim(); renderChip(); mapLive(true);
  prog.style.transition = 'width 12s linear'; requestAnimationFrame(() => { prog.style.width = '100%'; });
  setInterval(cycle, 12000);
""")

# generated cruise icons (Canva image generation, backgrounds cut out), embedded as CSS classes
ICONS = Path(__file__).with_name("assets")
ICON_CSS = "".join(f".stk-{p.stem} {{ background-image: url(data:image/webp;base64,{base64.b64encode(p.read_bytes()).decode()}); }}\n"
                   for p in sorted(ICONS.glob("*.webp")))
ICON_CSS += ":root { --ico-ship: url(data:image/webp;base64," + base64.b64encode((ICONS / "ship.webp").read_bytes()).decode() + "); }\n"
# sprite sheets from demo/sprites.py: one row of frames, stepped through with CSS steps()
SPRITES = json.loads((ICONS / "sprites" / "sprites.json").read_text())
# (the strip slides under a window with transform, so a frame can never land half way)
ICON_CSS += (".spr { display: inline-block; overflow: hidden; }\n"
             ".spr::before { content: ''; display: block; width: calc(var(--n) * 100%); height: 100%; background: var(--img) 0 0 / 100% 100% no-repeat;"
             " animation: spr var(--dur) steps(var(--n)) infinite; }\n"
             "@keyframes spr { to { transform: translateX(-100%); } }\n"
             "@media (prefers-reduced-motion: reduce) { .spr::before { animation: none; } }\n")
ICON_CSS += "".join(
    f".spr-{k} {{ --img: url(data:image/webp;base64,{base64.b64encode((ICONS / 'sprites' / f'{k}.webp').read_bytes()).decode()});"
    f" --n: {m['n']}; --dur: {m['dur']}s; aspect-ratio: {m['w']} / {m['h']}; }}\n"
    for k, m in SPRITES.items())

tpl = TEMPLATE.read_text(encoding="utf-8")
data = DATA.read_text(encoding="utf-8")
for tag_ in ("demo-data", "extra-data"):
    m = re.search(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', data, re.S)
    tpl = re.sub(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', lambda k, m=m: k[1] + m[2] + k[3], tpl, count=1, flags=re.S)
assert tpl.count(INIT) == 1 and tpl.count("</style>") == 1
TITLES = {"focus": "Forecast · Focus", "story": "Cruise-day traffic", "officer": "Forecast · Officer", "wall": "Forecast · Wallboard"}

# Story with a friendly "Does the AI help?" overview: two embedded designs (one on the learned policy, one on the
# buses observed) and an Advanced view switch that brings back every statistic. The designs are standalone pages
# (optional 4th argument: a folder holding viz-ai/emb-*.html and viz-bus/emb-*.html), shown in srcdoc iframes.
AI_CSS = """
.ai-simple { display: grid; gap: 22px; }
.ai-frame { width: 100%; border: 0; display: block; min-height: 320px; background: transparent; color-scheme: normal; }
.ai-card { border-radius: 18px; overflow: hidden; border: 1px solid var(--line); background: var(--surface); }
:root[data-theme="steam"] .ai-card { border: 2px solid #1D2B45; box-shadow: 4px 4px 0 #1D2B45; }
.ai-mode { display: inline-flex; padding: 3px; border-radius: 999px; background: var(--sunk); border: 1px solid var(--line); }
.ai-mode button { border: 0; background: transparent; color: var(--muted); padding: 8px 18px; border-radius: 999px; font-weight: 750; cursor: pointer; }
.ai-mode button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
.ai-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.ai-bar h2 { font-size: var(--step-2); }
.value-card { padding: 16px 18px; }
.value-card .vc { display: grid; gap: 10px; }
.value-card h3 { margin: 0; }
.value-card th.num, .value-card td.num { text-align: right; }
.value-card tr.vc-whole th, .value-card tr.vc-whole td { font-weight: 700; }
.value-card .vc-take b { font-family: var(--font-data); }
.vc-total { display: grid; gap: 8px; padding: 12px 14px; border-radius: 12px; background: var(--sunk); }
.vc-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.vc-stat { display: grid; }
.vc-stat b { font: 750 2.4rem/1.05 var(--font-data); }
.vc-stat span { color: var(--muted); font-weight: 600; font-size: var(--step--1); }
.vc-big { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
.vc-big b { font: 750 2rem/1.05 var(--font-data); }
.vc-big span { color: var(--muted); font-weight: 600; }
.vc-bar { display: flex; height: 40px; border-radius: 10px; overflow: hidden; background: var(--surface); }
.vc-bar i { display: grid; place-items: center; color: #fff; font-style: normal; font: 700 .9rem var(--font-data); min-width: 3px; }
.vc-bar i + i { box-shadow: inset 2px 0 0 var(--surface); }
.vc-keys { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: var(--step--1); }
.vc-keys i { display: inline-block; width: 11px; height: 11px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
.vc-moves > summary { cursor: pointer; font-weight: 650; }
.vc-defs { display: grid; grid-template-columns: minmax(130px, max-content) minmax(0, 1fr); gap: 4px 14px; margin: 4px 0 0; font-size: var(--step--1); }
.vc-defs dt { font-weight: 700; }
.vc-defs dd { margin: 0; color: var(--muted); }
@media (max-width: 560px) { .vc-defs { grid-template-columns: minmax(0, 1fr); } .vc-defs dd { margin-bottom: 4px; } }
.vc-moves h4 { margin: 8px 0 4px; font-size: var(--step--1); }
.vc-moves li { font-size: var(--step--1); }
body:not(.ai-adv) .adv-only { display: none !important; }
body.ai-adv .simple-only { display: none !important; }
"""
AI_JS = r"""
  /* Does the AI help?: an overview of two designs, and an Advanced view with every statistic */
  const AI_EMBEDS = __EMBEDS__;
  const aiSec = document.createElement('section'); aiSec.className = 'sec ai-simple';
  aiSec.innerHTML = `<div class="ai-bar"><h2>The learned plan, and the buses on the day</h2>
    <div class="ai-mode" role="group" aria-label="View"><button type="button" data-ai="simple" aria-pressed="true">Overview</button><button type="button" data-ai="adv" aria-pressed="false">Advanced view</button></div></div>
    ${AI_EMBEDS.map((e, i) => `<div class="ai-card simple-only"><iframe class="ai-frame" title="${esc(e.title)}" id="ai-f${i}"></iframe></div>`).join('')}`;
  $('#day').before(aiSec);   // top of the step, above the observed buses fold that lives in the day section
  aiSec.dataset.views = 'step4';
  [methodSec, '#ppo-viz', '#bus-live'].forEach(x => { const el = typeof x === 'string' ? $(x) : x; if (el) el.classList.add('adv-only'); });
  // the switch also sits at the top of the advanced statistics, so it is always in reach
  const advBar = aiSec.querySelector('.ai-mode');
  function aiMode(adv) {
    document.body.classList.toggle('ai-adv', adv);
    advBar.querySelectorAll('[data-ai]').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.ai === 'adv') === adv)));
    aiSec.querySelector('h2').textContent = adv ? 'Every statistic behind the answer' : 'The learned plan, and the buses on the day';
    if (adv) { const v = $('#ppo-viz'); if (v && !v.open) { v.open = true; v.dispatchEvent(new Event('toggle')); } const b = $('#bus-live'); if (b && !b.open) b.open = true; }
    else sizeFrames();
  }
  advBar.addEventListener('click', e => { const b = e.target.closest('[data-ai]'); if (b) aiMode(b.dataset.ai === 'adv'); });
  aiSec.querySelector('.ai-bar').classList.remove('simple-only');
  const frames = AI_EMBEDS.map((e, i) => { const f = $('#ai-f' + i); f.srcdoc = e.html; return f; });
  // under the two designs: what each option is worth (from the page's own data)
  const valHTML = typeof leverValueHTML === 'function' ? leverValueHTML() : '';
  if (valHTML) { const vc = document.createElement('div'); vc.className = 'ai-card value-card'; vc.innerHTML = valHTML; aiSec.querySelector('.ai-bar').after(vc); }
  const themeOf = () => document.documentElement.dataset.theme || 'harbour';
  function sizeFrames() {
    frames.forEach(f => { try { const d = f.contentDocument; if (!d || !d.documentElement) return; d.documentElement.dataset.theme = themeOf(); const h = d.documentElement.scrollHeight; if (h > 40) f.style.height = h + 'px'; } catch (err) { /* not ready */ } });
  }
  frames.forEach(f => f.addEventListener('load', () => {
    sizeFrames();
    try { new ResizeObserver(sizeFrames).observe(f.contentDocument.body); } catch (err) { /* sized on messages instead */ }
  }));
  addEventListener('message', e => { const f = frames.find(x => x.contentWindow === e.source); if (f && e.data && e.data.embedH) f.style.height = e.data.embedH + 'px'; });
  new MutationObserver(sizeFrames).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  addEventListener('resize', () => setTimeout(sizeFrames, 50));
  showStep(step);
"""
AI_PAIRS = {"race": ("policy-race", "map"), "days": ("every-test-day", "ladder"), "saves": ("where-ppo-saves", "board"),
            "verdict": ("verdict", "clock"), "fleet": ("pictogram", "stops"), "logbook": ("logbook", "gauge")}
EMBEDS = Path(sys.argv[4]) if len(sys.argv) > 4 else None
if EMBEDS:
    for key, (ai, bus) in AI_PAIRS.items():
        pages = [(EMBEDS / "viz-ai" / f"emb-{ai}.html", "Does the AI help?"), (EMBEDS / "viz-bus" / f"emb-{bus}.html", "Buses observed on the day")]
        if all(f.exists() for f, _ in pages):
            emb = json.dumps([{"title": t, "html": f.read_text(encoding="utf-8")} for f, t in pages]).replace("<", r"\u003c")   # no "<" inside the app's script, so nothing in the designs can end it early
            VARIANTS["story-" + key] = (VARIANTS["story"][0] + AI_CSS, VARIANTS["story"][1] + AI_JS.replace("__EMBEDS__", emb))
            TITLES["story-" + key] = "Cruise-day traffic · " + key.capitalize()
# The Story pages open on a splash: the landing's sky and sea, drawn by the first bytes of the page (before the
# script, fonts and data have loaded) so the screen is never half built. When the app is ready a wall of water
# rises over the screen and drains away to show it. If the script never runs, the splash fades after 25 seconds.
def _wave(y, a):
    return f"M0 {y} " + " ".join(f"q 50 {-a} 100 0 t 100 0" for _ in range(12)) + " V300 H0Z"


_CREST = "M0 50 " + " ".join("q 75 -44 150 0 t 150 0" for _ in range(8))
_DROPS = "".join(f'<i class="sp-drop" style="--x:{x}%;--s:{sz}px;--dx:{dx}px;--d:{d}s"></i>'
                 for x, sz, dx, d in ((8, 14, -30, .05), (19, 10, 20, .12), (31, 16, -14, 0), (44, 11, 26, .09), (56, 15, -22, .03),
                                      (67, 10, 18, .14), (78, 16, -26, .06), (90, 12, 22, .1)))
# (x %, y %, size px, throw x px, throw y vmin, delay s, foam or teal)
_BURST = [(6, 34, 30, -40, -14, .02, 1), (14, 58, 20, -24, -10, .1, 0), (22, 26, 36, -18, -18, .05, 1), (30, 48, 24, 10, -12, .14, 1),
          (38, 18, 18, -12, -9, .08, 0), (44, 40, 40, 6, -20, 0, 1), (52, 62, 22, 22, -11, .12, 1), (58, 24, 28, 30, -16, .04, 1),
          (66, 46, 34, 18, -19, .09, 0), (73, 20, 22, 40, -12, .03, 1), (80, 54, 30, 26, -15, .13, 1), (87, 30, 38, 44, -18, .06, 1),
          (94, 50, 20, 30, -10, .11, 0), (10, 74, 26, -30, -13, .16, 1), (48, 80, 30, -8, -15, .18, 1), (84, 76, 24, 20, -12, .15, 1)]
_BURST_HTML = "".join(f'<i class="sp-foam{"" if foam else " t"}" style="left:{x}%;top:{y}%;--s:{sz}px;--dx:{dx}px;--dy:{dy}vmin;--d:{d}s"></i>'
                      for x, y, sz, dx, dy, d, foam in _BURST)
SPLASH = f"""<div id="splash" aria-hidden="true"><style>
#splash {{ position: fixed; inset: 0; z-index: 400; overflow: hidden; background: linear-gradient(#FFE9C7 0%, #FFD7B0 46%, #FFC9A8 62%, #A9D9D3 62.2%, #7CC3BE 100%);
  animation: sp-safety .6s 25s forwards; }}
@keyframes sp-safety {{ to {{ opacity: 0; visibility: hidden; }} }}
#splash .sp-sea {{ position: absolute; left: 0; bottom: 0; width: 200%; height: 30%; }}
#splash .sp-sea path {{ animation: sp-roll linear infinite; }}
#splash .sp-a {{ fill: #7CC3BE; animation-duration: 14s; }} #splash .sp-b {{ fill: #3E9E9C; animation-duration: 10s; }} #splash .sp-c {{ fill: #1D6F78; animation-duration: 7s; }}
@keyframes sp-roll {{ to {{ transform: translateX(-50%); }} }}
#splash .sp-word {{ position: absolute; left: 0; right: 0; top: 40%; margin: 0; text-align: center; color: #1D2B45; font: 600 1.05rem/1 "Fredoka", "Trebuchet MS", sans-serif;
  letter-spacing: .12em; text-transform: uppercase; }}
#splash .sp-word i {{ display: inline-block; width: .45em; height: .45em; margin-left: .3em; border-radius: 50%; background: #D8473A; animation: sp-bob .9s ease-in-out infinite alternate; }}
#splash .sp-word i:nth-child(2) {{ animation-delay: .3s; }} #splash .sp-word i:nth-child(3) {{ animation-delay: .6s; }}
@keyframes sp-bob {{ from {{ transform: translateY(3px); }} to {{ transform: translateY(-5px); }} }}
/* the wall of water starts below the screen; 72% of its 160% height lifts the crest clear of the top */
#splash .sp-wall {{ position: absolute; left: 0; top: 100%; width: 100%; height: 160%; background: linear-gradient(#3E9E9C, #1D6F78 40%, #16525A);
  transition: transform .62s cubic-bezier(.55, 0, .85, .45); }}
#splash .sp-crest {{ position: absolute; left: 0; bottom: calc(100% - 1px); width: 200%; height: 12vmin; animation: sp-roll 2.6s linear infinite; }}
#splash .sp-drop {{ position: absolute; bottom: calc(100% + 6vmin); left: var(--x); width: var(--s); height: var(--s); border-radius: 50%; background: #FFF8EC; border: 2px solid #1D2B45; opacity: 0; }}
#splash.crash .sp-wall {{ transform: translateY(-72%); }}
#splash.crash .sp-drop {{ animation: sp-spray .7s var(--d) cubic-bezier(.2, .6, .4, 1) both; }}
@keyframes sp-spray {{ 0% {{ opacity: 0; transform: translate(0, 0) scale(.4); }} 25% {{ opacity: 1; }} 100% {{ opacity: 0; transform: translate(var(--dx), -16vmin) scale(1); }} }}
/* as the wave covers the screen it bursts into foam, which flies up and falls away while the water drains */
#splash .sp-burst {{ position: absolute; inset: 0; pointer-events: none; }}
#splash .sp-foam {{ position: absolute; width: var(--s); height: var(--s); margin: calc(var(--s) / -2) 0 0 calc(var(--s) / -2); border-radius: 50%;
  background: #FFF8EC; border: 3px solid #1D2B45; opacity: 0; }}
#splash .sp-foam.t {{ background: #7CC3BE; }}
#splash.crash .sp-foam {{ animation: sp-burst 1.25s calc(.42s + var(--d)) cubic-bezier(.15, .7, .45, 1) both; }}
@keyframes sp-burst {{ 0% {{ opacity: 0; transform: translate(0, 4vmin) scale(.2); }} 12% {{ opacity: 1; }}
  45% {{ opacity: 1; transform: translate(calc(var(--dx) * .7), var(--dy)) scale(1); }}
  100% {{ opacity: 0; transform: translate(var(--dx), calc(var(--dy) + 30vmin)) scale(.7); }} }}
#splash.drain {{ background: transparent; pointer-events: none; }}
#splash.drain .sp-sea, #splash.drain .sp-word {{ visibility: hidden; }}
#splash.drain .sp-wall {{ transform: translateY(8%); transition: transform .9s cubic-bezier(.35, .1, .55, 1); }}
@media (prefers-reduced-motion: reduce) {{ #splash *, #splash {{ animation: none !important; transition: none !important; }} }}
</style>
<svg class="sp-sea" viewBox="0 0 2400 300" preserveAspectRatio="none"><path class="sp-a" d="{_wave(70, 30)}"/><path class="sp-b" d="{_wave(140, 24)}"/><path class="sp-c" d="{_wave(210, 18)}"/></svg>
<p class="sp-word">Setting sail<i></i><i></i><i></i></p>
<div class="sp-wall">{_DROPS}<svg class="sp-crest" viewBox="0 0 2400 100" preserveAspectRatio="none"><path d="{_CREST} V100 H0Z" fill="#3E9E9C"/><path d="{_CREST}" fill="none" stroke="#FFF8EC" stroke-width="7" vector-effect="non-scaling-stroke"/></svg></div>
<div class="sp-burst">{_BURST_HTML}</div>
</div>
"""
SPLASH_JS = r"""
  // the opening: once the app (and its fonts) are ready, the splash's wave crashes over the screen and drains away
  (() => {
    const sp = document.getElementById('splash');
    if (!sp) return;
    const out = () => {
      if (REDUCED) { sp.remove(); return; }
      sp.classList.add('crash');
      setTimeout(() => sp.classList.add('drain'), 680);
      setTimeout(() => sp.remove(), 1950);
    };
    const fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    Promise.race([fonts, new Promise(r => setTimeout(r, 1500))]).then(() => setTimeout(out, 60));
  })();
"""
D3_TAG = '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>'
assert tpl.count(D3_TAG) == 1

for name, (css, js) in VARIANTS.items():
    base = "story" if name.startswith("story") else name
    if base == "story":
        js += SPLASH_JS
    page = tpl.replace("</style>", COMMON_CSS + (ICON_CSS if base == "story" else "") + css + "</style>", 1)
    page = page.replace(INIT, COMMON_JS.replace("__VARIANT__", repr(base)) + js, 1)
    page = page.replace("<title>Cruise-day traffic forecast</title>", f"<title>{TITLES[name]}</title>", 1)
    if base == "story":
        page = page.replace(D3_TAG, SPLASH + D3_TAG, 1)   # before the first thing that waits on the network
    (OUT / f"ui-{name}.html").write_text(page, encoding="utf-8")
    print(name, round(len(page.encode()) / 1e6, 1), "MB")
