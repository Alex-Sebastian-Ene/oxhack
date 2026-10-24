# Runs after patch_shock.py on hormuz-flow.html.
# A fourth tab in the country card, "Economy": how consumer prices and unemployment respond to the chosen Brent
# price over 36 months, for the economy that country belongs to (United States, United Kingdom or euro area).
# Numbers: Seb's Bayesian responses, notes/macro-bayes-responses.csv (experiments/macro_bayes.py), read at build time.
# +10% rows for rises and -10% rows for falls, scaled by ln(1+x)/ln(1.1 or 0.9), the same rule as the product prices.
# Unemployment is shown but not used as a forecast: its historical link with oil has the demand sign (oil up,
# unemployment down), so docs/macro-ensemble.md keeps it out of the what-if. The tab says so.
import csv, json, pathlib, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- data from Seb's table
src = root / "notes" / "macro-bayes-responses.csv"
rows = [r for r in csv.DictReader(src.open(encoding="utf-8")) if r["series"] in
        {f"{e}_{t}" for e in ("us", "uk", "ea") for t in ("cpi", "unemp")}]
macro, meta = {}, {}
for r in rows:
    key = "up" if r["shock"] == "brent_up_10pct" else "down"
    d = macro.setdefault(r["series"], {}).setdefault(key, {})
    d[int(r["months_ahead"])] = [round(float(r["mean"]), 4), round(float(r["q05"]), 4), round(float(r["q95"]), 4)]
    meta = {"fitted_to": r["fitted_to"], "generated": r["generated"], "source": r["source"], "interval": r["interval"]}
for ser in macro.values():
    for key, d in ser.items():
        assert sorted(d) == list(range(1, 37)), "expected months 1 to 36"
        ser[key] = [d[m] for m in range(1, 37)]
assert len(macro) == 6
MACRO_JS = ("  // Seb's Bayesian responses to a 10% Brent move (notes/macro-bayes-responses.csv), months 1 to 36: [mean, q05, q95].\n"
            f"  const MACRO = {json.dumps(macro, separators=(',', ':'))};\n"
            f"  const MACRO_META = {json.dumps(meta)};\n")

# ---------------------------------------------------------------- markup: the tab's content, moved into its pane by the tab code
SEC = '''        <div id="e-sec">
          <div class="eco-who"><span class="sub" id="e-who"></span>
            <div class="seg eseg" role="group" aria-label="Which economy"><button type="button" data-eco="us">US</button><button type="button" data-eco="uk">UK</button><button type="button" data-eco="ea">Euro area</button></div>
          </div>
          <div class="eco-block">
            <span class="label">Prices (consumer price index)</span>
            <p class="eco-head" id="e-cpi-head"></p>
            <div class="chartbox" id="e-cpi-chart"></div>
          </div>
          <div class="eco-block">
            <span class="label">Unemployment</span>
            <p class="eco-head" id="e-un-head"></p>
            <div class="chartbox" id="e-un-chart"></div>
            <p class="sub" id="e-un-note"></p>
          </div>
          <div class="legend2"><span><i style="background:var(--oil)"></i>Average effect</span><span><i style="background:rgba(242,107,0,0.22)"></i>90% range</span><span><i class="eco-sc"></i>Months 13 to 36: scenario, not tested</span></div>
          <p class="faint" id="e-src"></p>
        </div>
'''
# put it at the end of the country card; the tab code moves it into its own pane
a = s.index('<section class="card" id="country-card"')
b = s.index("      </section>", a)
s = s[:b] + SEC + s[b:]

# ---------------------------------------------------------------- the tab
sub('const CTABS = [["overview", "Overview"], ["inds", "Industries"], ["trade", "Trade"]];',
    'const CTABS = [["overview", "Overview"], ["inds", "Industries"], ["trade", "Trade"], ["econ", "Economy"]];')
sub('const panes = [pane("overview", [kpis, chart]), pane("inds", [inds]), pane("trade", [$("t-sec")])];',
    'const panes = [pane("overview", [kpis, chart]), pane("inds", [inds]), pane("trade", [$("t-sec")]), pane("econ", [$("e-sec")])];')

ECON_JS = MACRO_JS + r'''  // Which economy a country's numbers come from. Others fall back to a choice of the three, labelled as such.
  const EURO = new Set(["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Estonia", "Finland", "France", "Germany", "Greece", "Ireland",
    "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Portugal", "Slovakia", "Slovenia", "Spain"]);
  const ECO_NAME = { us: "the United States", uk: "the United Kingdom", ea: "the euro area" };
  const ecoOf = (n) => (n === "United States of America" ? "us" : n === "United Kingdom" ? "uk" : EURO.has(n) ? "ea" : null);
  let ecoPick = "us";
  // path of [mean, lo, hi] for months 0..36 at the current Brent, scaled like the product prices
  function ecoPath(series) {
    const x = st.brent / BRENT0 - 1;
    if (Math.abs(x) < 1e-9) return Array.from({ length: 37 }, () => [0, 0, 0]);
    const [rowsM, base] = x >= 0 ? [MACRO[series].up, 1.1] : [MACRO[series].down, 0.9];
    const f = Math.log(1 + x) / Math.log(base);
    return [[0, 0, 0]].concat(rowsM.map(([m, a, b]) => { const p = a * f, q = b * f; return [m * f, Math.min(p, q), Math.max(p, q)]; }));
  }
  function ecoChart(box, pts, { unit, grey }) {
    const W = 340, H = 170, L = 40, Rr = 52, T = 12, B = 24;
    const all = pts.flatMap((p) => [p[1], p[2]]).concat([0]);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = Math.max((hi - lo) * 0.12, unit === "%" ? 0.1 : 0.02);
    lo -= pad; hi += pad;
    const x = (i) => L + i / 36 * (W - L - Rr), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
    const step = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5].find((st_) => (hi - lo) / st_ <= 5) || 10;
    const fmt = (v) => `${v > 0.0001 ? "+" : v < -0.0001 ? "−" : ""}${Math.abs(v).toFixed(step < 0.1 ? 2 : 1)}`;
    let g = "";
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) g += `<line class="gl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 6}" y="${y(v) + 3.5}" text-anchor="end">${fmt(v)}</text>`;
    [[0, "now"], [12, "12 mo"], [24, "24"], [36, "36"]].forEach(([i, t]) => (g += `<text class="ax" x="${x(i)}" y="${H - 6}" text-anchor="middle">${t}</text>`));
    const band = `M${pts.map((p, i) => `${x(i)},${y(p[2])}`).join("L")}L${pts.map((p, i) => [i, p[1]]).reverse().map(([i, v]) => `${x(i)},${y(v)}`).join("L")}Z`;
    const line = `M${pts.map((p, i) => `${x(i)},${y(p[0])}`).join("L")}`;
    const m12 = pts[12][0], m36 = pts[36][0];
    box.innerHTML = `<svg class="chart${grey ? " eco-grey" : ""}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${unit === "%" ? "Price level" : "Unemployment rate"} change: ${fmt(m12)}${unit} after 12 months, ${fmt(m36)}${unit} after 36 months">
      <rect class="eco-scen" x="${x(12)}" y="${T}" width="${x(36) - x(12)}" height="${H - T - B}"/>
      ${g}<line class="ref" x1="${L}" x2="${W - Rr}" y1="${y(0)}" y2="${y(0)}"/>
      <text class="reflab" x="${W - Rr + 6}" y="${y(0) + 3.5}">${grey ? "what-if: 0" : "no change"}</text>
      <path class="band" d="${band}"/><path class="base" d="${line}"/>
      <circle class="end" cx="${x(12)}" cy="${y(m12)}" r="3.5"/>
      <text class="endlab" x="${x(12)}" y="${y(m12) + (m12 >= 0 ? -8 : 15)}" text-anchor="middle">${fmt(m12)}${unit}</text>
      <circle class="end" cx="${x(36)}" cy="${y(m36)}" r="3.5"/>
      <text class="endlab" x="${x(36) + 7}" y="${y(m36) + 4}">${fmt(m36)}${unit}</text></svg>`;
  }
  function renderEcon() {
    if (!st.sel || !$("e-sec")) return;
    const own = ecoOf(st.sel), eco = own || ecoPick, nm = st.sel === "United States of America" ? "the United States" : st.sel;
    $("e-who").innerHTML = own
      ? (own === "ea" ? `${nm} uses the euro, so these are <b>euro-area</b> figures.` : `Figures for <b>${ECO_NAME[own]}</b>.`)
      : `The model covers only the US, the UK and the euro area, not ${nm}. Showing <b>${ECO_NAME[eco]}</b> for comparison.`;
    document.querySelectorAll("[data-eco]").forEach((b) => { const on = b.dataset.eco === eco; b.setAttribute("aria-pressed", String(on)); b.disabled = !!own && !on; });
    const cpi = ecoPath(`${eco}_cpi`), un = ecoPath(`${eco}_unemp`);
    const pct = (st.brent / BRENT0 - 1) * 100, sg = (v) => (v > 0.005 ? "+" : v < -0.005 ? "−" : ""), a = Math.abs;
    const c12 = cpi[12];
    $("e-cpi-head").innerHTML = a(pct) < 0.5
      ? `At $${st.brent}, oil is at its pre-war price, so there is no knock-on to prices.`
      : `At <b>$${st.brent}</b> a barrel, prices in ${ECO_NAME[eco]} end up about <b>${a(c12[0]).toFixed(1)}% ${c12[0] >= 0 ? "higher" : "lower"}</b> after 12 months than they would otherwise be (range ${sg(c12[1])}${a(c12[1]).toFixed(1)} to ${sg(c12[2])}${a(c12[2]).toFixed(1)}%). That adds roughly that much to the year's inflation rate.`;
    ecoChart($("e-cpi-chart"), cpi, { unit: "%" });
    const u12 = un[12];
    $("e-un-head").innerHTML = `<b>No reliable effect.</b> The team's what-if keeps unemployment unchanged.`;
    ecoChart($("e-un-chart"), un, { unit: " pts", grey: true });
    $("e-un-note").textContent = a(pct) < 0.5 ? "" :
      `In the historical data, unemployment in ${ECO_NAME[eco]} moved ${u12[0] < 0 ? "down" : "up"} by about ${a(u12[0]).toFixed(2)} points when oil ${pct > 0 ? "rose" : "fell"} this much (grey line). ` +
      `That's because oil usually rises in booms, when demand is strong: it is demand, not a supply shock like a Hormuz closure, so it isn't used as a forecast (docs/macro-ensemble.md).`;
    $("e-src").textContent = `Seb's Bayesian model, notes/macro-bayes-responses.csv (${MACRO_META.source}; data to ${MACRO_META.fitted_to}, generated ${MACRO_META.generated}). ` +
      `Changes against no oil move, at the slider's Brent price. The range is the ${MACRO_META.interval}. Tested up to 12 months; 13 to 36 months is a scenario.`;
  }
  document.querySelectorAll("[data-eco]").forEach((b) => b.addEventListener("click", () => { ecoPick = b.dataset.eco; renderEcon(); }));
'''
sub("  function renderCountry() {", ECON_JS + "  function renderCountry() {")
# the country card draws the tab whenever it redraws (new country, slider, scenario); the shock sentence follows the country too
sub("  function renderCountry() {\n", "  function renderCountry() {\n    renderShockExplain();\n")
sub("    renderTrade();\n  }", "    renderTrade();\n    renderEcon();\n  }")

CSS = """
/* Economy tab: prices and unemployment for the country's economy over 36 months. */
.eco-who { display: flex; flex-direction: column; gap: 8px; }
.eseg { display: flex; width: 100%; }
.eseg button { flex: 1 1 0; min-height: 34px; font-size: 13px; }
.eseg button:disabled { opacity: .45; cursor: default; }
.eco-block { display: flex; flex-direction: column; gap: 6px; }
.eco-head { margin: 0; font-size: 14px; line-height: 1.55; color: var(--text); }
.chart .eco-scen { fill: rgba(20,32,46,0.045); }
.chart.eco-grey .base { stroke: var(--faint); stroke-dasharray: 4 3; }
.chart.eco-grey .band { fill: rgba(104,118,138,0.16); }
.chart.eco-grey .end { fill: var(--faint); }
.chart.eco-grey .endlab { fill: var(--muted); font-weight: 500; }
.legend2 i.eco-sc { background: rgba(20,32,46,0.09); }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
