// node capture.js [slug...]: 1920x1080 PNG of each still
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const DIR = __dirname, only = process.argv.slice(2);
(async () => {
  const b = await chromium.launch();
  const files = fs.readdirSync(DIR).filter((f) => /^still-\d-.*\.html$/.test(f)).filter((f) => !only.length || only.some((s) => f.includes(`-${s}.html`))).sort();
  for (const f of files) {
    const p = await b.newPage({ viewport: { width: 1920, height: 1080 } }); const errs = [];
    p.on('pageerror', (e) => errs.push(e.message)); p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    const t0 = Date.now();
    await p.goto('file://' + path.join(DIR, f)); await p.waitForFunction(() => window.READY === true, null, { timeout: 60000 });
    const png = await p.evaluate(() => document.getElementById('c').toDataURL('image/png'));
    fs.writeFileSync(path.join(DIR, f.replace('.html', '.png')), Buffer.from(png.split(',')[1], 'base64'));
    console.log(f, 'ok', (Date.now() - t0) + 'ms', errs.length ? 'ERRORS: ' + errs.join(' | ') : '');
    await p.close();
  }
  await b.close();
})();
