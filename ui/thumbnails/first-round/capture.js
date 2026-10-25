// node capture.js [slug...] [--gif]: PNG still per thumbnail, plus GIF frames with --gif
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const DIR = __dirname, args = process.argv.slice(2), gif = args.includes('--gif'), only = args.filter((a) => !a.startsWith('--'));
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
  const files = fs.readdirSync(DIR).filter((f) => /^thumb-\d-.*\.html$/.test(f)).filter((f) => !only.length || only.some((s) => f.includes(`-${s}.html`))).sort();
  for (const f of files) {
    const p = await b.newPage({ viewport: { width: 1280, height: 720 } }); const errs = [];
    p.on('pageerror', (e) => errs.push(e.message)); p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    await p.addInitScript(() => { window.__capture = true; });
    await p.goto('file://' + path.join(DIR, f)); await p.waitForFunction(() => window.READY === true, null, { timeout: 20000 });
    const base = f.replace('.html', '');
    const t0 = Date.now();
    const still = await p.evaluate(() => { renderAt(window.STILL_T); return document.getElementById('c').toDataURL('image/png'); });
    fs.writeFileSync(path.join(DIR, base + '.png'), Buffer.from(still.split(',')[1], 'base64'));
    if (gif) {
      const fd = path.join(DIR, 'frames', base); fs.mkdirSync(fd, { recursive: true });
      const frames = await p.evaluate(() => {
        const loop = window.LOOP_MS, n = Math.round(loop / 1000 * 15), out = [], s = document.createElement('canvas'); s.width = 640; s.height = 360;
        const sx = s.getContext('2d');
        for (let i = 0; i < n; i++) { renderAt(window.STILL_T + i * loop / n); sx.imageSmoothingEnabled = true; sx.drawImage(document.getElementById('c'), 0, 0, 640, 360); out.push(s.toDataURL('image/png')); }
        return { out, ms: loop / n };
      });
      frames.out.forEach((d, i) => fs.writeFileSync(path.join(fd, String(i).padStart(3, '0') + '.png'), Buffer.from(d.split(',')[1], 'base64')));
      fs.writeFileSync(path.join(fd, 'ms.txt'), String(frames.ms));
    }
    console.log(f, 'ok', (Date.now() - t0) + 'ms', errs.length ? 'ERRORS: ' + errs.join(' | ') : '');
    await p.close();
  }
  await b.close();
})();
