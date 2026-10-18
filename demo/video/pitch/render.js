// Render pitch.html frame by frame (deterministic seek(t)) to out/ JPEGs at 25 fps.
const puppeteer = require('puppeteer-core'); const fs = require('fs');
const FPS = 25, ONLY = process.argv[2] ? process.argv[2].split(',').map(Number) : null;
(async () => {
  const tl = fs.readFileSync('timeline.json', 'utf8');
  fs.writeFileSync('pitch-run.html', fs.readFileSync('pitch.html', 'utf8').replace('__TL__', tl));
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
    args: ['--window-size=1920,1080', '--hide-scrollbars'], defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 } });
  const page = await browser.newPage(); page.on('pageerror', e => console.log('pageerror', e.message));
  await page.goto('file:///' + __dirname.split(String.fromCharCode(92)).join('/') + '/pitch-run.html', { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  const total = await page.evaluate(() => window.TOTAL), N = Math.ceil(total * FPS);
  const outDir = ONLY ? 'stills' : 'out'; fs.mkdirSync(outDir, { recursive: true });
  const START = +(process.argv[3] || 0); const list = ONLY ? ONLY.map(t => Math.round(t * FPS)) : [...Array(N).keys()].filter(i => i >= START * FPS);
  const t0 = Date.now();
  for (const i of list) {
    await page.evaluate(t => window.seek(t), i / FPS);
    await page.screenshot({ path: `${outDir}/${ONLY ? 't' + (i / FPS).toFixed(1) : String(i).padStart(5, '0')}.jpg`, type: 'jpeg', quality: 90 });
    if (!ONLY && i % 250 === 0) console.log(i, '/', N, ((Date.now() - t0) / 1000).toFixed(0) + 's');
  }
  console.log('done', list.length, 'frames', ((Date.now() - t0) / 1000).toFixed(0) + 's'); await browser.close();
})();
