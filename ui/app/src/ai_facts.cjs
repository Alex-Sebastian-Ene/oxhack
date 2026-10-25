// Node script, not part of the page. Reads the facts each Gemini panel sends ("What is it?" for every resource,
// "Summarise with Gemini" for every country) from the built app at the 2026-closure setting, so that
// `uv run experiments/country_brief.py bake` can write the answers ahead of time (ui/app/data/ai-panels.json).
//
//   python3 ui/app/src/build.py && node ui/app/src/ai_facts.cjs   # -> data/raw/briefs/facts-2026-closure.json
//
// Needs Node and Playwright with Chromium (npm i -g playwright && npx playwright install chromium).
// A country's profile facts include its exposure tiles, so each country is selected on the World map first,
// the way a viewer would, by sending a click to its shape (or its dot, for the small ones).
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const ROOT = path.resolve(__dirname, "..", "..", "..");
const PAGE = path.join(ROOT, "ui", "app", "index.html");
const OUT = path.join(ROOT, "data", "raw", "briefs", "facts-2026-closure.json");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("file://" + PAGE + "#app");
  await page.waitForFunction(() => window.HZAI && window.HZAI.facts);
  await page.click('[data-mode="world"]');
  // the preset sits in "The shock" card, which may be folded, so press it from the page rather than by pointer
  const setting = await page.evaluate(() => {
    const b = document.querySelector('[data-path="iea2026"]');
    b.click();
    return { pressed: b.getAttribute("aria-pressed") === "true", detail: `${b.dataset.txt} (${b.dataset.avg} on average), as the IEA counts it` };
  });
  if (!setting.pressed) throw new Error("the 2026 closure preset did not switch on");
  await page.waitForTimeout(500);
  const got = await page.evaluate(() => {
    const CN = window.COUNTRIES, els = new Map(), raw = {}, countries = [], skipped = [];
    document.querySelectorAll("#world .ctry").forEach((el) => el.__data__ && els.set(el.__data__.properties.name, el));
    document.querySelectorAll("#world circle.dot").forEach((el) => el.__data__ && !els.has(el.__data__[0]) && els.set(el.__data__[0], el));
    for (const f of CN.features) raw[f.properties.iso3] = f.properties.name;
    for (const [k, p] of Object.entries(CN.points)) if (!raw[k]) raw[k] = p.name;
    const shown = () => document.getElementById("c-name").textContent;
    for (const iso of window.HZAI.facts.countries()) {
      const name = raw[iso], el = els.get(name);
      if (!/^[A-Z]{3}$/.test(iso) || !el) { skipped.push(`${iso} ${name || ""}`.trim()); continue; }
      const r = el.getBoundingClientRect();
      const click = () => el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
      click();
      if (shown() !== name) click();   // a second click on the selected country clears it, so try once more
      if (shown() !== name) { skipped.push(`${iso} ${name}`); continue; }
      countries.push(window.HZAI.facts.country(iso));
    }
    return { resources: window.HZAI.facts.resources(), countries, skipped, readout: (document.getElementById("hz-read") || {}).textContent || "" };
  });
  await browser.close();
  if (errors.length) throw new Error(`page errors: ${errors.slice(0, 3).join("; ")}`);
  const out = { page: "ui/app/index.html", read_at: new Date().toISOString().slice(0, 19) + "Z", setting: "2026-closure",
    setting_detail: setting.detail, readout: got.readout.trim(), resources: got.resources, countries: got.countries, skipped: got.skipped };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
  console.log(`wrote ${path.relative(ROOT, OUT)}: ${out.resources.length} resources, ${out.countries.length} countries`
    + (got.skipped.length ? `; skipped (no shape to click): ${got.skipped.join(", ")}` : ""));
})().catch((e) => { console.error(e.message); process.exit(1); });
