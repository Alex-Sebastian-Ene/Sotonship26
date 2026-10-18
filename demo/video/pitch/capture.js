// Real-time screen capture of the live Story page (saved copy of sotonyard.keanuc.net), driven by a
// click script whose phases are timed to the narration. Writes frames/ + capture.json (frame times, phase starts).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const D = JSON.parse(fs.readFileSync('vot/durations.json', 'utf8'));
const PAD = 0.5;
const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  fs.rmSync('frames', { recursive: true, force: true }); fs.mkdirSync('frames');
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
    args: ['--window-size=1920,1080', '--autoplay-policy=no-user-gesture-required', '--mute-audio', '--hide-scrollbars'],
    defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
  });
  const page = await browser.newPage();
  page.on('pageerror', e => console.log('pageerror', e.message));
  await page.goto('file:///' + __dirname.replace(/\\/g, '/') + '/live.html', { waitUntil: 'load', timeout: 120000 });
  await wait(2500);
  const cdp = await page.target().createCDPSession();
  const frames = []; let t0 = null;
  cdp.on('Page.screencastFrame', async f => {
    const t = f.metadata.timestamp; if (t0 === null) t0 = t;
    const name = `frames/${String(frames.length).padStart(5, '0')}.jpg`;
    fs.writeFileSync(name, Buffer.from(f.data, 'base64')); frames.push([name, t - t0]);
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 82, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  const start = Date.now(), phases = {};
  const mark = k => { phases[k] = (Date.now() - start) / 1000; console.log(k, phases[k].toFixed(2)); };
  const click = sel => page.evaluate(s => { const el = document.querySelector(s); if (!el) return 'missing ' + s; el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.click(); return 'ok'; }, sel).then(r => r !== 'ok' && console.log(r));
  const hold = k => wait((D[k] + PAD) * 1000);

  await wait(2200);                               // the landing page, animated
  await click('#l-go'); await wait(1200);         // Set sail -> step 1, the calendar
  mark('demo1');
  await wait(2600); await click('button.cell[data-date="2026-10-24"]');
  await wait((D.demo1 + PAD) * 1000 - 2600);
  mark('demo2'); await click('.voy-port[data-step="1"]'); await hold('demo2');
  mark('demo3'); await click('.voy-port[data-step="2"]'); await wait((D.demo3 + PAD + 3) * 1000);
  mark('demo4'); await click('.voy-port[data-step="3"]');
  await wait(1800);
  await page.evaluate(() => { const y = [...document.querySelectorAll('.dec-yes')].filter(b => b.offsetParent); y[0] && y[0].click(); });
  await wait(1500);
  await page.evaluate(() => { const y = [...document.querySelectorAll('.dec-yes')].filter(b => b.offsetParent); y[1] && y[1].click(); });
  await wait(1300);
  await page.evaluate(() => { const n = [...document.querySelectorAll('.dec-no')].filter(b => b.offsetParent); n[2] && n[2].click(); });
  await wait((D.demo4 + PAD) * 1000 - 4600 + 1500);
  mark('demo5'); await click('.voy-port[data-step="4"]'); await hold('demo5');
  mark('fail'); await click('.voy-port[data-step="0"]'); await wait(1300);
  await click('button.cell-beyond'); await wait(900);
  await click('.voy-port[data-step="1"]'); await wait((D.fail + PAD) * 1000 - 2200 + 1200);
  mark('end');
  await cdp.send('Page.stopScreencast'); await wait(300);
  fs.writeFileSync('capture.json', JSON.stringify({ frames, phases }));
  console.log('frames', frames.length, 'span', frames.at(-1)[1].toFixed(1), 's');
  await browser.close();
})();
