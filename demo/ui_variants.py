"""Four simplified UI variants of the forecast app, each a separate page built from the same template
and data: the variant's CSS goes before </style>, its init replaces the app's last line."""
import base64
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
  function mapLive(play) {
    requestAnimationFrame(() => { layout(); zoomTo('docks', false); drawAgents(); });
    if (play && state.layer !== 'agents' && agentDay() && !REDUCED) $('#layer-agents').click();
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
.storybar { position: sticky; top: 58px; z-index: 35; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding: 10px max(16px, env(safe-area-inset-left, 0px));
  background: color-mix(in srgb, var(--bg) 90%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
.story-q { display: flex; align-items: center; gap: 12px; font-family: var(--font-display); font-size: clamp(1.3rem, 2.6vw, 2rem); font-weight: 750; margin-right: auto; }
.story-q .stk { width: 46px; height: 46px; flex: none; animation: stk-pop .45s cubic-bezier(.2, 1.6, .4, 1) both; }
.story-n { font-family: var(--font-data); color: var(--accent); }
@keyframes stk-pop { from { transform: scale(.3) rotate(-20deg); } to { transform: none; } }
/* voyage: the current step is a steamship sailing between buoys */
.voyage { position: relative; width: 260px; height: 52px; --k: 0; }
.voy-sea { position: absolute; left: 0; right: 0; bottom: 6px; height: 10px; opacity: .8;
  background: radial-gradient(circle at 5px -1px, transparent 5px, var(--accent) 5.5px 7px, transparent 7.5px) 0 0 / 10px 10px repeat-x; }
.voy-port { position: absolute; bottom: 4px; left: calc(var(--x) * (100% - 18px)); width: 18px; height: 18px; padding: 0; border-radius: 50%; cursor: pointer;
  border: 2px solid var(--ink); background: var(--surface); transition: transform .2s, background .2s; }
.voy-port:hover { transform: scale(1.2); }
.voy-port.done { background: var(--accent); }
.voy-ship { position: absolute; bottom: 14px; left: calc(var(--k) * (100% - 18px) - 15px); width: 48px; height: 38px; transition: left .7s cubic-bezier(.45, 0, .2, 1); pointer-events: none; }
.voy-ship .stk { position: absolute; inset: 0; animation: bob 1.6s ease-in-out infinite; }
.voyage.back .voy-ship .stk { animation-name: bob-back; }
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
.stk { display: inline-block; background-position: center; background-size: contain; background-repeat: no-repeat; }
:root[data-theme="steam"] .storybar { background: #FFF6E2; border-bottom: 2px dashed #1D2B45; }
:root[data-theme="steam"] .v-btn { border: 2px solid #1D2B45; box-shadow: 3px 3px 0 #1D2B45; }
:root[data-theme="steam"] .v-btn.primary { background: #D8473A; color: #fff; }
:root[data-theme="steam"] .brand-mark { background: none; width: 40px; height: 32px; }
:root[data-theme="steam"] .brand-mark svg { display: none; }
:root[data-theme="steam"] .brand-mark::after { content: ''; width: 40px; height: 32px; background: var(--ico-ship) center / contain no-repeat; }
.deco-gull { position: fixed; z-index: 1; top: 130px; left: -80px; width: 56px; height: 42px; pointer-events: none; display: none; animation: fly 26s linear infinite; }
:root[data-theme="steam"] .deco-gull { display: block; }
@keyframes fly { from { transform: translate(0, 0); } 50% { transform: translate(60vw, 40px); } to { transform: translate(calc(100vw + 160px), -10px); } }
/* landing page */
.landing { position: fixed; inset: 0; z-index: 100; overflow: hidden; display: grid; place-items: center; color: #1D2B45; font-family: "Fredoka", "Trebuchet MS", sans-serif;
  background: linear-gradient(#FFE9C7 0%, #FFD7B0 46%, #FFC9A8 62%, #A9D9D3 62.2%, #7CC3BE 100%); transition: transform .8s cubic-bezier(.6, 0, .3, 1); }
.landing.gone { transform: translateY(-104%); }
.l-sun { position: absolute; left: 50%; top: 62%; width: 34vmin; height: 34vmin; margin: -17vmin 0 0 -17vmin; border-radius: 50%; background: radial-gradient(#FFF3D6, #FFB27A 70%); opacity: .9; }
.l-cloud { position: absolute; left: 0; height: 26px; border-radius: 20px; background: #FFF8EC; border: 2.5px solid #1D2B45; animation: drift linear infinite; }
.l-cloud::before, .l-cloud::after { content: ''; position: absolute; bottom: 8px; border-radius: 50%; background: #FFF8EC; border: 2.5px solid #1D2B45; border-bottom-color: transparent; border-right-color: transparent; transform: rotate(45deg); }
.l-cloud::before { left: 14px; width: 34px; height: 34px; } .l-cloud::after { left: 40px; width: 26px; height: 26px; }
.l-cloud.c1 { top: 9%; width: 110px; animation-duration: 70s; animation-delay: -20s; } .l-cloud.c2 { top: 23%; width: 90px; animation-duration: 95s; animation-delay: -60s; } .l-cloud.c3 { top: 15%; width: 130px; animation-duration: 120s; animation-delay: -95s; }
@keyframes drift { from { transform: translateX(-20vw); } to { transform: translateX(120vw); } }
.l-gull { position: absolute; width: 64px; height: 48px; animation: glide 9s ease-in-out infinite; }
.l-gull.g1 { left: 12%; top: 26%; } .l-gull.g2 { right: 18%; top: 12%; width: 46px; height: 34px; animation-delay: -4s; }
@keyframes glide { 0%, 100% { transform: translate(0, 0) rotate(-4deg); } 50% { transform: translate(30px, -18px) rotate(4deg); } }
.l-light { position: absolute; right: 5vw; bottom: 31%; width: 13vmin; height: 17vmin; z-index: 1; }
.l-anchor { position: absolute; left: 4vw; bottom: 6%; width: 9vmin; height: 12vmin; transform: rotate(-12deg); z-index: 3; }
.l-wheel { position: absolute; right: 6vw; bottom: 5%; width: 12vmin; height: 12vmin; z-index: 3; animation: spin 18s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.l-ship { position: absolute; left: 50%; bottom: 19%; width: min(38vmin, 340px); aspect-ratio: 183 / 138; transform: translateX(-50%); z-index: 2; transition: transform 1.3s cubic-bezier(.5, 0, .7, .4); }
.l-ship .stk { position: absolute; inset: 0; animation: bob 2.4s ease-in-out infinite; }
.l-ship .puff { width: 18px; height: 18px; border-width: 2.5px; animation-duration: 3s; }
.l-ship .puff.p1 { left: 36%; top: 2%; } .l-ship .puff.p2 { left: 57%; top: 2%; animation-delay: 1s; } .l-ship .puff.p3 { left: 46%; top: 0; animation-delay: 2s; }
.landing.sail .l-ship { transform: translateX(80vw); }
.l-waves { position: absolute; left: 0; bottom: 0; width: 200%; height: 30%; z-index: 3; pointer-events: none; }
.l-waves path { animation: wave linear infinite; }
.l-waves .w1 { fill: #7CC3BE; animation-duration: 14s; } .l-waves .w2 { fill: #3E9E9C; animation-duration: 10s; } .l-waves .w3 { fill: #1D6F78; animation-duration: 7s; }
@keyframes wave { to { transform: translateX(-50%); } }
.l-card { position: relative; z-index: 4; display: grid; justify-items: center; gap: 14px; text-align: center; padding: 0 16px; align-self: start; margin-top: max(24px, 5vh); }
.l-kicker { font-weight: 600; letter-spacing: .12em; text-transform: uppercase; font-size: .85rem; }
.l-plate { position: relative; padding: 14px 38px 16px; border-radius: 18px; background: #1D2B45; color: #FFF6E2; box-shadow: 0 0 0 4px #FFF6E2, 0 0 0 7px #1D2B45, 8px 10px 0 7px rgba(29, 43, 69, .3); }
.l-plate::before, .l-plate::after { content: ''; position: absolute; top: 50%; width: 9px; height: 9px; margin-top: -4.5px; border-radius: 50%; background: #F2B84B; }
.l-plate::before { left: 13px; } .l-plate::after { right: 13px; }
.l-plate h1 { font-family: inherit; font-weight: 700; font-size: clamp(2rem, 6vw, 4rem); line-height: 1; letter-spacing: .01em; color: #FFF6E2; }
.l-plate h1 span { color: #FF8A73; }
.l-sub { font-size: clamp(1rem, 2.2vw, 1.3rem); font-weight: 500; max-width: 30ch; }
.l-tickets { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; }
.l-ticket { display: grid; padding: 6px 20px 8px; background: #FFF6E2; border: 2.5px solid #1D2B45; border-radius: 10px; box-shadow: 3px 3px 0 #1D2B45; }
.l-ticket b { font-size: 1.6rem; line-height: 1.1; color: #D8473A; }
.l-ticket span { font-size: .8rem; font-weight: 600; }
.l-go { display: inline-flex; align-items: center; gap: 12px; padding: 10px 28px 10px 12px; border-radius: 999px; border: 3px solid #1D2B45; background: #D8473A; color: #fff;
  font: 700 1.35rem "Fredoka", sans-serif; cursor: pointer; box-shadow: 4px 5px 0 #1D2B45; transition: transform .15s, box-shadow .15s; }
.l-go:hover { transform: translate(-1px, -2px); box-shadow: 5px 7px 0 #1D2B45; }
.l-go:active { transform: translate(3px, 4px); box-shadow: 1px 1px 0 #1D2B45; }
.l-go .stk { width: 40px; height: 40px; animation: spin 6s linear infinite; }
.l-src { font-size: .78rem; font-weight: 500; max-width: 60ch; padding: 3px 10px; border-radius: 999px; background: rgba(255, 246, 226, .7); }
@media (max-width: 640px) { .l-light { display: none; } .l-ship { bottom: 18%; }
  .storybar { gap: 8px 10px; } .story-q { flex-basis: 100%; } .voyage { flex: 1 1 150px; width: auto; } .storybar .v-btn { padding: 6px 12px; min-height: 36px; } }
@media (prefers-reduced-motion: reduce) { .landing *, .voy-ship, .voy-ship .stk, .deco-gull { animation: none !important; transition: none !important; } .landing { transition: none; } }
""", r"""
  const STEPS = [
    { q: 'When are the hard days?', ico: 'lighthouse', show: [calSec] },
    { q: 'How bad is it?', ico: 'ring', show: ['#day-head', '#notices'] },
    { q: 'Watch the day', ico: 'gull', show: ['#day-head', '#day-body'], map: true },
    { q: 'What to do', ico: 'wheel', show: ['#row-actions', '#ppo-card'] },
    { q: 'Does the AI help?', ico: 'hat', show: [methodSec, '#ppo-viz', '#bus-live'] },
  ];
  // everything starts hidden; each step lists what it shows
  [calSec, methodSec, '#day-head', '#notices', '#row-actions', '#ppo-card', '#day-body', '#row-vehicles', '#heat-card', '#ships-block',
   '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live', '#ppo-viz', '#ppo-test', '#freight-card'].forEach(s => tag(s, 'none'));
  methodSec.querySelectorAll(':scope > .sec-head, :scope > .grid2, :scope > .folds > details').forEach(el => { if (el.id !== 'ppo-viz') tag(el, 'none'); });
  STEPS.forEach((st, i) => st.show.forEach(s => { const el = typeof s === 'string' ? $(s) : s; el.dataset.views = (el.dataset.views === 'none' ? '' : el.dataset.views + ' ') + 'step' + i; }));
  const bar = document.createElement('div'); bar.className = 'storybar';
  bar.innerHTML = `<span class="story-q"><span class="stk" id="story-stk" aria-hidden="true"></span><span class="story-n" id="story-n"></span><span id="story-q"></span><span id="story-src"></span></span>
    <div class="voyage" id="voyage" role="tablist" aria-label="Steps"><span class="voy-sea"></span>
      ${STEPS.map((s, i) => `<button class="voy-port" role="tab" data-step="${i}" style="--x:${i / (STEPS.length - 1)}" aria-label="Step ${i + 1}: ${esc(s.q)}" title="${esc(s.q)}"></button>`).join('')}
      <span class="voy-ship" aria-hidden="true"><span class="stk stk-ship"></span><i class="puff"></i><i class="puff"></i></span></div>
    <button class="v-btn" id="story-back">Back</button><button class="v-btn primary" id="story-next">Next</button>`;
  $('.appbar').after(bar);
  const gull = document.createElement('span'); gull.className = 'stk stk-gull deco-gull'; gull.setAttribute('aria-hidden', 'true'); document.body.append(gull);
  let step = 0;
  function showStep(i) {
    const prev = step;
    step = Math.max(0, Math.min(STEPS.length - 1, i));
    showSet('step' + step);
    $('#story-n').textContent = `${step + 1}/${STEPS.length}`; $('#story-q').textContent = STEPS[step].q;
    const stk = $('#story-stk'); stk.className = 'stk stk-' + STEPS[step].ico; stk.style.animation = 'none'; void stk.offsetWidth; stk.style.animation = '';
    const voy = $('#voyage'); voy.style.setProperty('--k', step / (STEPS.length - 1)); voy.classList.toggle('back', step < prev);
    bar.querySelectorAll('[data-step]').forEach(b => { b.setAttribute('aria-selected', String(+b.dataset.step === step)); b.classList.toggle('done', +b.dataset.step <= step); });
    $('#story-back').disabled = step === 0; $('#story-next').disabled = step === STEPS.length - 1;
    if (STEPS[step].map) mapLive(true); else stopVehicles();
    if (step === 4) { const v = $('#ppo-viz'); if (v && !v.open) { v.open = true; v.dispatchEvent(new Event('toggle')); } }
    const w = $('.wrap'); w.classList.remove('view-enter'); void w.offsetWidth; w.classList.add('view-enter');
    window.scrollTo(0, 0);
  }
  $('#story-back').addEventListener('click', () => showStep(step - 1));
  $('#story-next').addEventListener('click', () => showStep(step + 1));
  bar.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => showStep(+b.dataset.step)));
  $('#cal').addEventListener('click', e => { if (e.target.closest('button[data-date]') && step === 0) setTimeout(() => showStep(1), 250); });
  // sources stay one ? away, beside the step question
  setTimeout(() => { const pw = $('.provenance') && $('.provenance').closest('.qwrap'); if (pw) $('#story-src').append(pw); }, 0);

  /* landing page */
  const live = DATA.days.filter(d => !d.beyond);
  const nCalls = live.reduce((n, d) => n + d.calls.length, 0), nHard = live.filter(d => ['high', 'severe'].includes(level(uplift(d)).key)).length;
  const prov = ($('.provenance') || {}).textContent || '', when = (prov.match(/VTS schedule \(collected ([^)]+)\)/) || [])[1];
  const land = document.createElement('div'); land.className = 'landing'; land.setAttribute('role', 'dialog'); land.setAttribute('aria-modal', 'true'); land.setAttribute('aria-labelledby', 'l-title');
  const wave = (y, a) => `M0 ${y} ` + Array.from({ length: 12 }, () => `q 50 ${-a} 100 0 t 100 0`).join(' ') + ' V300 H0Z';
  land.innerHTML = `<div class="l-sun"></div><div class="l-cloud c1"></div><div class="l-cloud c2"></div><div class="l-cloud c3"></div>
    <span class="stk stk-gull l-gull g1" aria-hidden="true"></span><span class="stk stk-gull l-gull g2" aria-hidden="true"></span>
    <span class="stk stk-lighthouse l-light" aria-hidden="true"></span>
    <div class="l-ship" aria-hidden="true"><span class="stk stk-ship"></span><i class="puff p1"></i><i class="puff p2"></i><i class="puff p3"></i></div>
    <svg class="l-waves" viewBox="0 0 2400 300" preserveAspectRatio="none" aria-hidden="true"><path class="w1" d="${wave(70, 30)}"/><path class="w2" d="${wave(140, 24)}"/><path class="w3" d="${wave(210, 18)}"/></svg>
    <span class="stk stk-anchor l-anchor" aria-hidden="true"></span><span class="stk stk-wheel l-wheel" aria-hidden="true"></span>
    <div class="l-card">
      <p class="l-kicker">Southampton docks · next six weeks</p>
      <div class="l-plate"><h1 id="l-title">Cruise-day <span>traffic</span></h1></div>
      <p class="l-sub">Which days the ships jam the roads, and what to do about it.</p>
      <div class="l-tickets"><span class="l-ticket"><b>${nCalls}</b><span>ship calls</span></span><span class="l-ticket"><b>${nHard}</b><span>heavy days</span></span><span class="l-ticket"><b>${live.length}</b><span>days forecast</span></span></div>
      <button class="l-go" id="l-go"><span class="stk stk-ring" aria-hidden="true"></span>Set sail</button>
      <p class="l-src">Ship calls: ABP Southampton VTS schedule${when ? `, collected ${esc(when)}` : ''}. Traffic is modelled, not measured.</p>
    </div>`;
  const sail = () => {
    if (land.classList.contains('sail')) return;
    land.classList.add('sail');
    setTimeout(() => land.classList.add('gone'), REDUCED ? 0 : 650);
    setTimeout(() => { land.remove(); $('#story-next').focus({ preventScroll: true }); }, REDUCED ? 0 : 1500);
  };
  if (location.hash !== '#app') {
    document.body.append(land);
    $('#l-go').addEventListener('click', sail);
    land.addEventListener('keydown', e => { if (e.key === 'Escape') sail(); });
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

tpl = TEMPLATE.read_text(encoding="utf-8")
data = DATA.read_text(encoding="utf-8")
for tag_ in ("demo-data", "extra-data"):
    m = re.search(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', data, re.S)
    tpl = re.sub(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', lambda k: k[1] + m[2] + k[3], tpl, count=1, flags=re.S)
assert tpl.count(INIT) == 1 and tpl.count("</style>") == 1
TITLES = {"focus": "Forecast · Focus", "story": "Cruise-day traffic", "officer": "Forecast · Officer", "wall": "Forecast · Wallboard"}
for name, (css, js) in VARIANTS.items():
    page = tpl.replace("</style>", COMMON_CSS + ICON_CSS + css + "</style>", 1)
    page = page.replace(INIT, COMMON_JS.replace("__VARIANT__", repr(name)) + js, 1)
    page = page.replace("<title>Cruise-day traffic forecast</title>", f"<title>{TITLES[name]}</title>", 1)
    (OUT / f"ui-{name}.html").write_text(page, encoding="utf-8")
    print(name, round(len(page.encode()) / 1e6, 1), "MB")
