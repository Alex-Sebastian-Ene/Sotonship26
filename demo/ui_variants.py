"""Four simplified UI variants of the forecast app, each a separate page built from the same template
and data: the variant's CSS goes before </style>, its init replaces the app's last line."""
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

# 2 ---------------------------------------------------------------- Story: five guided steps
VARIANTS["story"] = ("""
.storybar { position: sticky; top: 58px; z-index: 35; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding: 12px max(16px, env(safe-area-inset-left, 0px));
  background: color-mix(in srgb, var(--bg) 90%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
.story-q { font-family: var(--font-display); font-size: clamp(1.3rem, 2.6vw, 2rem); font-weight: 750; margin-right: auto; }
.story-n { font-family: var(--font-data); color: var(--accent); margin-right: 10px; }
.dots { display: flex; gap: 6px; }
.dots button { width: 12px; height: 12px; padding: 0; border-radius: 50%; border: 0; background: var(--line-strong); cursor: pointer; transition: width .25s, background .25s; }
.dots button[aria-current="step"] { width: 30px; border-radius: 6px; background: var(--accent); }
body[data-variant="story"] .wrap { max-width: 1400px; padding-top: 18px; }
body[data-variant="story"] #day { grid-template-columns: minmax(0, 1fr) !important; }
body[data-variant="story"] #day > * { grid-column: 1 !important; grid-row: auto !important; }
body[data-variant="story"] .map-box { height: max(440px, calc(100vh - 300px)) !important; }
""", r"""
  const STEPS = [
    { q: 'When are the hard days?', show: [calSec] },
    { q: 'How bad is it?', show: ['#day-head', '#notices'] },
    { q: 'Watch the day', show: ['#day-head', '#day-body'], map: true },
    { q: 'What to do', show: ['#row-actions', '#ppo-card'] },
    { q: 'Does the AI help?', show: [methodSec, '#ppo-viz', '#bus-live'] },
  ];
  // everything starts hidden; each step lists what it shows
  [calSec, methodSec, '#day-head', '#notices', '#row-actions', '#ppo-card', '#day-body', '#row-vehicles', '#heat-card', '#ships-block',
   '#tl-card', '#sure-card', '#gates-card', '#row-model', '#bus-card', '#bus-live', '#ppo-viz', '#ppo-test', '#freight-card'].forEach(s => tag(s, 'none'));
  methodSec.querySelectorAll(':scope > .sec-head, :scope > .grid2, :scope > .folds > details').forEach(el => { if (el.id !== 'ppo-viz') tag(el, 'none'); });
  STEPS.forEach((st, i) => st.show.forEach(s => { const el = typeof s === 'string' ? $(s) : s; el.dataset.views = (el.dataset.views === 'none' ? '' : el.dataset.views + ' ') + 'step' + i; }));
  const bar = document.createElement('div'); bar.className = 'storybar';
  bar.innerHTML = `<span class="story-q"><span class="story-n" id="story-n"></span><span id="story-q"></span></span>
    <div class="dots" role="tablist" aria-label="Steps">${STEPS.map((s, i) => `<button role="tab" data-step="${i}" aria-label="Step ${i + 1}: ${esc(s.q)}"></button>`).join('')}</div>
    <button class="v-btn" id="story-back">Back</button><button class="v-btn primary" id="story-next">Next</button>`;
  $('.appbar').after(bar);
  let step = 0;
  function showStep(i) {
    step = Math.max(0, Math.min(STEPS.length - 1, i));
    showSet('step' + step);
    $('#story-n').textContent = `${step + 1}/${STEPS.length}`; $('#story-q').textContent = STEPS[step].q;
    bar.querySelectorAll('[data-step]').forEach(b => b.setAttribute('aria-current', +b.dataset.step === step ? 'step' : 'false'));
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

tpl = TEMPLATE.read_text(encoding="utf-8")
data = DATA.read_text(encoding="utf-8")
for tag_ in ("demo-data", "extra-data"):
    m = re.search(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', data, re.S)
    tpl = re.sub(rf'(<script id="{tag_}" type="application/json">)(.*?)(</script>)', lambda k: k[1] + m[2] + k[3], tpl, count=1, flags=re.S)
assert tpl.count(INIT) == 1 and tpl.count("</style>") == 1
TITLES = {"focus": "Forecast · Focus", "story": "Forecast · Story", "officer": "Forecast · Officer", "wall": "Forecast · Wallboard"}
for name, (css, js) in VARIANTS.items():
    page = tpl.replace("</style>", COMMON_CSS + css + "</style>", 1)
    page = page.replace(INIT, COMMON_JS.replace("__VARIANT__", repr(name)) + js, 1)
    page = page.replace("<title>Cruise-day traffic forecast</title>", f"<title>{TITLES[name]}</title>", 1)
    (OUT / f"ui-{name}.html").write_text(page, encoding="utf-8")
    print(name, round(len(page.encode()) / 1e6, 1), "MB")
