# Runs after patch_tradestats.py, on hormuz-flow.html.
# Every country's own numbers in the World view, from notes/country-oil.json (experiments/country_oil.py) and Seb's
# cost-of-living model (notes/cost-of-living-fans.csv), read at build time:
# 1. Import dependence and the Gulf share of oil imports from UN Comtrade (HS 2709 + 2710, by value). The hand-entered
#    table (EIA, Energy Institute) fills in where Comtrade has nothing (Taiwan, Iran); a country in neither says
#    "not in our data" and is grey on the map.
# 2. Fuel cost from the country's own Brent -> pump-price pass-through, fitted on its monthly motor-fuel consumer
#    prices (Eurostat, the BLS, the OECD's national CPIs, Statistics Canada, SingStat), with the series, its months
#    and when it was collected. Other countries show no fuel estimate: a pooled median would be the same number for
#    all of them. The Industries tab and the fuel-cost path use the same pass-through.
# 3. The hand-set exposure score is gone. The map, the ranking and the cards show how much oil the shock cuts off:
#    an importer's Gulf share of oil imports × the share of Hormuz flow lost, a Gulf producer's exports trapped,
#    another exporter's change in oil earnings.
# 4. A Cost of living tab, first in the country panel: prices and food prices now and before the closure (FAOSTAT),
#    and what 100 spent today costs after 1, 2, 3, 6 and 12 months, with a chart. Groceries and all prices for
#    every country (the naive rule plus oil's known moves; a fitted time-series model lost to it in backtests), and
#    the item basket from Seb's cost-of-living model for the US, the UK and the euro area.
# 5. The pop-up leads with groceries, fuel and oil cut off, then prices now and our models' 12-month what-ifs.
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


src = json.loads((root / "notes" / "country-oil.json").read_text(encoding="utf-8"))
fuel, trade, prices = src["fuel"], src.get("trade") or {"countries": {}}, src["prices"]
H = [str(h) for h in prices["horizons"]]


def price_entry(v):
    o = v.get("outlook")
    return {"now": v["now"], "before": v["before"], "from": o["from"] if o else None, "out": o["q"] if o else None,
            "b": {h: v["link"][h]["b"] for h in H} if v.get("link") else None,
            "own": {h: v["link"][h]["own"] for h in H} if v.get("link") else None,
            "src": v.get("src"), "why": v.get("why_none"), "unc": v.get("uncertain", False), "rule": o.get("rule") if o else None}


# Seb's cost-of-living model: the outlook from its latest origin, by item, for the US, the UK and the euro area
COL_KINDS = ["bread", "dairy", "meat", "fruit_veg", "oils_fats", "sugar", "electricity", "gas", "fuel", "restaurants", "composite"]
fans = [r for r in csv.DictReader((root / "notes" / "cost-of-living-fans.csv").open(encoding="utf-8")) if r["scenario"] == "outlook"]
col_from = max(r["origin"] for r in fans)
COL = {}
for r in fans:
    if r["origin"] != col_from or r["kind"] not in COL_KINDS or r["months_ahead"] not in H or r["region"] not in ("us", "uk", "ea"):
        continue
    if r["series"] != f'{r["region"]}_{r["kind"]}' and f'{r["region"]}_{r["kind"]}' in {x["series"] for x in fans}:
        continue  # the item's main series, not a variant
    COL.setdefault(r["region"], {}).setdefault(r["kind"], {})[r["months_ahead"]] = [float(r["q05"]), float(r["q50"]), float(r["q95"])]
assert COL and all(len(v) == len(H) for reg in COL.values() for v in reg.values()), COL

COIL = {
    "generated": src["generated"],
    "fuel": {iso: {k: v[k] for k in ("e", "lo", "hi", "series", "from", "to", "collected")} for iso, v in fuel["countries"].items()},
    "trade": {iso: {"m": v["m"], "gs": v["gulf_share"], "year": v["year"], "top": next(iter(v["by"]), None), "mirror": bool(v.get("mirror"))}
              for iso, v in trade["countries"].items()},
    "tradeSrc": f'{trade["source"]}, collected {trade["collected"]}' if trade.get("source") else "",
    "prices": {iso: {k: price_entry(v) for k, v in c.items()} for iso, c in prices["countries"].items()},
    "pricesSrc": prices["source"], "weights": prices.get("weights", {}), "skill": prices.get("model", {}).get("skill", {}),
    # the link each country's own is ridge-updated towards: our cost-of-living model for all prices and food, the
    # cross-country average for housing and energy, and transport
    "prior": {k: prices["prior"].get(k) or {h: v[h]["b"] for h in H} for k, v in prices["pooled"].items()},
    "priorSrc": {k: "our cost-of-living model" if k in prices["prior"] else "the cross-country average" for k in prices["pooled"]},
    "col": COL, "colFrom": col_from, "colGen": fans[0]["generated"],
}
# who publishes the motor-fuel prices behind the pass-through, for the "no estimate" text
FUEL_BY = {"Eurostat": "Eurostat", "BLS": "the BLS", "OECD": "the OECD", "Statistics Canada": "Statistics Canada", "SingStat": "SingStat"}
unnamed = {v["source"] for v in fuel["countries"].values() if not any(v["source"].startswith(k) for k in FUEL_BY)}
assert not unnamed, f"add these fuel sources to FUEL_BY: {unnamed}"
fuel_by = [name for k, name in FUEL_BY.items() if any(v["source"].startswith(k) for v in fuel["countries"].values())]
NOFUEL = (f"No fuel price estimate: we only estimate pump prices for the {len(fuel['countries'])} countries whose monthly "
          f"motor-fuel consumer prices we have ({', '.join(fuel_by[:-1])} and {fuel_by[-1]}), and this is not one of them.")

# 1. one profile per country: hand-entered table for routes and volumes, data for dependence, Gulf share, pass-through
sub('''  function info(name) {
    const d = C[name] || (DEFAULT_EXP.has(name) ? { c: 50, h: 0, m: -3, ind: EXP } : { c: 0, h: 0, m: .8, ind: IMP, generic: true });
    return d;
  }''', '''  // Country profiles from notes/country-oil.json (experiments/country_oil.py) and the cost-of-living outlook
  // (notes/cost-of-living-fans.csv), read at build time
  const COIL = ''' + json.dumps(COIL, ensure_ascii=False, separators=(",", ":")) + ''';
  const NODATA = "#eceff3";
  const NOFUEL = ''' + json.dumps(NOFUEL, ensure_ascii=False) + ''';
  function info(name) {
    const iso = isoOf[name], t = COIL.trade[iso], f = COIL.fuel[iso], hand = C[name];
    const d = Object.assign({ c: 0, h: 0, m: null }, hand || {});
    // partners' records (for countries that don't report) understate the Gulf share: the hand-entered table wins
    if (t && !(t.mirror && hand)) Object.assign(d, { dep: t.m, gs: t.gs, top: t.top, depSrc: t.mirror ? `UN Comtrade, partners' records for ${t.year}; a lower bound for the Gulf share` : `UN Comtrade, ${t.year}` });
    else if (hand) Object.assign(d, { dep: hand.m, gs: hand.c && hand.m > 0 ? Math.min(1, hand.h / (hand.c * hand.m)) : null, depSrc: "this page's country table (EIA, Energy Institute)" });
    else Object.assign(d, { dep: null, gs: null, nodata: true });
    if (!hand) d.ind = d.dep != null && d.dep <= 0 ? EXP : IMP;
    d.pt = f ? Object.assign({ own: true }, f) : null;   // only where it has its own motor-fuel prices: no pooled stand-in
    return d;
  }''')
sub("    const hz = d.c ? Math.min(1, d.h / d.c) : 0;",
    "    const hz = d.gs;                                  // share of its oil imports from the Gulf producers (null: not in our data)")
sub("    const price = fuelFrac(dlog);                     // validated: Brent -> retail fuel",
    "    const price = d.pt ? d.pt.e * dlog : null;        // its own Brent -> pump-price pass-through (null: no estimate)")
sub("    const fuel = price * (1 + (inDisruption(s) ? DISRUPT.mid : 0));   // the normal link, times 1.49 in a disruption",
    "    const fuel = price == null ? null : price * (1 + (inDisruption(s) ? DISRUPT.mid : 0));   // the normal link, times 1.49 in a disruption")
sub('''    let score, kind;
    if (d.gulf) { kind = "gulf"; score = d.gulf * s * 100; }
    else if (d.m <= 0) { kind = "exp"; score = -Math.min(1, -d.m / 3 + 0.15) * Math.max(dB, 0) * 60; }
    else { kind = "imp"; score = fuel * (0.4 + 0.6 * d.m) * 100; }
    return { d, hz, fuel, price, dlog, score, kind, s, dB };''',
    '''    // how much oil the shock cuts off: an importer's Gulf share x flow lost, a Gulf producer's exports trapped,
    // another exporter's oil earnings (shown as a gain); the map, ranking and cards all read this
    let score, kind, cut = null;
    if (d.gulf) { kind = "gulf"; score = d.gulf * s * 100; cut = { txt: `${Math.round(score)}%`, lab: "of its oil exports trapped" }; }
    else if (d.dep == null) { kind = "none"; score = null; }
    else if (d.dep <= 0) { kind = "exp"; const e = Math.max(dB, 0) * 100; score = -Math.min(40, e); cut = { txt: `+${Math.round(e)}%`, lab: "oil export earnings" }; }
    else { kind = "imp"; score = hz == null ? null : 100 * hz * s; cut = score == null ? null : { txt: `${Math.round(score)}%`, lab: "of its oil imports cut off" }; }
    return { d, hz, fuel, price, dlog, score, kind, s, dB, cut };''')
sub("    if (!k.d || k.d.m > 0) return null;", "    if (!k.d || !(k.d.dep <= 0)) return null;")
sub("      const lo = sh.s * fuelFrac(k.dlog, 1) * (1 + (dz ? DISRUPT.lo : 0)), hi = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.hi : 0));\n"
    "      const mid = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.mid : 0));",
    "      if (!k.d.pt) return { key, label, why, v: null, sec, earn, chn, ports, power, nofuel: true, src: sh.src };\n"
    "      const lo = sh.s * k.d.pt.lo * k.dlog * (1 + (dz ? DISRUPT.lo : 0)), hi = sh.s * k.d.pt.hi * k.dlog * (1 + (dz ? DISRUPT.hi : 0));\n"
    "      const mid = sh.s * k.d.pt.e * k.dlog * (1 + (dz ? DISRUPT.mid : 0));")
sub("      return 100 * (1 + fuelFrac(Math.log(1 + dB)) * (1 + DISRUPT.mid",
    "      return 100 * (1 + k.d.pt.e * Math.log(1 + dB) * (1 + DISRUPT.mid")

# no pump-price estimate: no fuel-cost path, and industry rows say why instead of showing a cost change
sub("  function renderChart(name) {\n", r'''  function renderChart(name) {
    const leg = $("c-chartbox").nextElementSibling;
    if (leg) leg.hidden = !calc(name).d.pt;
    if (!calc(name).d.pt) { $("c-chartbox").innerHTML = `<p class="faint">${NOFUEL}</p>`; return; }
''')
sub("      if (i.v == null && i.sec) {", r'''      if (i.v == null && i.nofuel) return `<li><span class="nm">${i.label}</span>`
        + (i.sec ? `<span class="lv mono ${i.sec.v > 0.05 ? "hurt" : i.sec.v < -0.05 ? "gain" : ""}">${pct(i.sec.v / 100, 1)} its prices</span>` : `<span class="lv">no estimate</span>`)
        + `<span class="why">${i.why}. Cost share: ${escH(i.src)}. No cost change is shown because there is no pump-price estimate for this country (we have no monthly motor-fuel consumer prices for it).${i.sec ? ` ${secLine(i.sec)}` : ""}</span></li>`;
      if (i.v == null && i.sec) {''')

# 2. map, legend, ranking, tooltips: oil cut off, grey for no data
sub("  function fillFor(name) { return st.mat ? matShade(name) : color(calc(name).score); }",
    "  function fillFor(name) { if (st.mat) return matShade(name); const v = calc(name).score; return v == null ? NODATA : color(v); }")
sub('  const fmtS = (v) => (v > 0.5 ? "+" : v < -0.5 ? "−" : "") + Math.abs(v).toFixed(0);',
    '  const fmtS = (v) => (v == null ? "–" : (v > 0.5 ? "+" : v < -0.5 ? "−" : "") + Math.abs(v).toFixed(0));\n'
    '  const cutTxt = (k) => (k.cut ? `${k.cut.txt} ${k.cut.lab}` : "oil cut off: not in our data");')
sub('<span id="wttl">Exposure score (illustrative)</span>', '<span id="wttl">Oil cut off by the shock</span>')
sub(': "Exposure score (illustrative)";', ': "Oil cut off by the shock";')
sub('[[-40, "−40 gains"], [0, "0"], [25, "25"], [65, "65 hurt"]]', '[[-40, "gains"], [0, "0%"], [25, "25%"], [65, "65%"]]')
sub('Most exposed</span> <i class="illus" title="Illustrative: the score\'s weights are hand-set, not from a model (asked on OXH-3)">illustrative</i>',
    'Most oil cut off</span>')
sub("    const list = [...names].filter((n) => C[n]).map((n) => [n, calc(n).score]).sort((a, b) => b[1] - a[1]).slice(0, 10);",
    "    const list = [...names].map((n) => [n, calc(n).score]).filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]).slice(0, 10);")
sub('<span class="v">${fmtS(v)}</span></button>', '<span class="v">${Math.round(v)}%</span></button>')
sub('''    t.innerHTML = `<b>${name}</b><span>Exposure <span class="mono ${k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : ""}">${fmtS(k.score)}</span></span>
      <span>Fuel cost <span class="mono">${pct(k.fuel)}</span></span>${k.d.h ? `<span>Via Hormuz <span class="mono">${(k.hz * 100).toFixed(0)}% of use</span></span>` : ""}`;''',
    '''    const pr = COIL.prices[isoOf[name]], al = pr && pr.all && pr.all.now, fd = pr && pr.food && pr.food.now;
    t.innerHTML = `<b>${name}</b><span class="mono ${k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : ""}">${cutTxt(k)}</span>
      ${k.fuel == null ? "" : `<span>Fuel <span class="mono">${pct(k.fuel)}</span></span>`}${al ? `<span>Prices <span class="mono">${pctP(al.v)}</span>, food <span class="mono">${fd ? pctP(fd.v) : "–"}</span> (${ymLabel(al.month)})</span>` : ""}`;''')
# (the app's world.py swaps make the flat map and the globe share tipHtml, with the flag)
sub('''    return `<b>${escH(name)}</b><span>Exposure <span class="mono">${fmtS(k.score)}</span></span><span>Fuel cost <span class="mono">${pct(k.fuel)}</span></span>`;''',
    '''    return `<b>${escH(name)}</b><span class="mono">${cutTxt(k)}</span>${k.fuel == null ? "" : `<span>Fuel <span class="mono">${pct(k.fuel)}</span></span>`}`;''')
# one run from cyan (gains) through pale yellow (none) and orange to red (the worst)
sub('const STOPS = [[-40, "#00a88f"], [-15, "#4fd1b6"], [0, "#dfe5ec"], [10, "#ffb59c"], [25, "#ff7b55"], [40, "#ee3b2b"], [65, "#b8100c"]];',
    'const STOPS = [[-40, "#00a88f"], [-15, "#4fd1b6"], [0, "#eee6a6"], [8, "#f5d547"], [25, "#ff9a2e"], [45, "#ee3b2b"], [65, "#b8100c"]];')

# 3. country card: tag, line under the name, oil cut off, Gulf share
sub('    tag.textContent = k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : "Net importer";',
    '    tag.textContent = k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : k.kind === "none" ? "No oil trade data" : "Net importer";')
sub('''    else sub = d.generic ? "No direct Hormuz cargoes in this model, so the shock arrives through the world oil price. Figures use a typical importer profile." : "Feels the shock through the world oil price.";''',
    '''    else if (d.nodata) sub = "Not in our data: it doesn't report oil trade to UN Comtrade, so there is no import dependence or Gulf share for it.";
    else if (k.hz != null) sub = `Before the war about ${Math.round(k.hz * 100)}% of its oil imports came from the Gulf producers${d.top ? `, most from ${d.top}` : ""} (${d.depSrc}), so the shock reaches it through supply as well as price.`;
    else sub = "Feels the shock through the world oil price.";''')
sub('''    sc.textContent = fmtS(k.score);''', '''    sc.textContent = k.cut ? k.cut.txt : "–";
    $("c-score-l").textContent = k.cut ? k.cut.lab : "oil cut off: not in our data";''')
sub('''<div><b id="c-score">–</b><span>Exposure score <i class="illus" title="Illustrative: the score's weights are hand-set, not from a model (asked on OXH-3)">illustrative</i></span></div>''',
    '''<div><b id="c-score">–</b><span id="c-score-l">of its oil imports cut off</span></div>''')
sub('    $("c-dep").textContent = k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–";',
    '    $("c-dep").textContent = k.kind === "imp" && k.hz != null ? `${(k.hz * 100).toFixed(0)}%` : "–";\n'
    '    if (k.fuel == null) $("c-fuel").textContent = "–";\n'
    '    $("c-fuel").title = k.d.pt ? `Pass-through ${k.d.pt.e.toFixed(2)} (${k.d.pt.series}, ${k.d.pt.from} to ${k.d.pt.to}, collected ${k.d.pt.collected}) × 1.49 in a disruption` : NOFUEL;')
sub('<div><b id="c-dep">–</b><span>Oil use sourced via Hormuz</span></div>', '<div><b id="c-dep">–</b><span>Oil imports from the Gulf</span></div>')

# 4. Cost of living tab, first in the panel
sub('const CTABS = [["overview", "Overview"],', 'const CTABS = [["col", "Cost of living"], ["overview", "Overview"],')
sub('const panes = [pane("overview", [kpis, chart]),', 'const panes = [pane("col", [$("col-sec")]), pane("overview", [kpis, chart]),')
sub('setCTab("overview");', 'setCTab("col");')
sub('setCTab(st.mat ? "trade" : "overview")', 'setCTab(st.mat ? "trade" : "col")', count=2)
sub('<div id="e-sec">', '''<div id="col-sec">
          <p class="col-now" id="col-now"></p>
          <span class="label">What 100 spent today will cost</span>
          <div class="seg eseg" role="group" aria-label="Months ahead" id="col-h"></div>
          <ul class="inds col-list" id="col-list"></ul>
          <p class="eco-head" id="col-chart-h"></p>
          <div class="chartbox" id="col-chart"></div>
          <p class="faint" id="col-src"></p>
        </div>
        <div id="e-sec">''')
sub("    renderEcon();\n    renderTrends();\n", "    renderEcon();\n    renderTrends();\n    renderCol();\n")
COL_JS = r'''  // ------------------------------------------------------------ Cost of living: prices now, and what 100 spent today will cost
  const COL_ITEMS = [["bread", "Bread"], ["dairy", "Dairy"], ["meat", "Meat"], ["fruit_veg", "Fruit and vegetables"], ["oils_fats", "Oils and fats"],
    ["sugar", "Sugar"], ["electricity", "Electricity"], ["gas", "Gas"], ["fuel", "Motor fuel"], ["restaurants", "Eating out"], ["composite", "Whole basket"]];
  const COL_REGION = { us: "US", uk: "UK", ea: "euro area" };
  // each row's explanation sits behind a "Why" toggle, closed until opened; which ones are open survives a redraw
  const colOpen = new Set();
  const whyBox = (key, label, body) => `<details class="why"${colOpen.has(key) ? " open" : ""}><summary>${label}</summary>${body}</details>`;
  const COL_KINDS = [["food", "Groceries (food)"], ["energy", "Housing and energy"], ["transport", "Transport"], ["all", "All prices"]];
  // which forecast a row uses, and how the cross-country model scored at this horizon in its backtest
  const RULE_NAME = { gbm: "gradient-boosted trees", blend: "trees averaged with a median regression", lad: "a median regression", ridge: "a ridge regression" };
  function fcTxt(r) {
    const rule = r.rule && r.rule[colH], sk = COIL.skill[r.kind] && COIL.skill[r.kind][colH];
    if (!rule || rule === "naive" || !sk) return " Forecast: the latest 12 months' rate continues (the naive rule).";
    return ` Forecast: our cross-country model (${RULE_NAME[rule] || rule}, trained on about 200 countries). In backtests over 2015-2024 it had `
      + `<b>${Math.round(100 * sk.skill)}% less error</b> than "the latest rate continues" at ${colH} month${colH === "1" ? "" : "s"}, and its 90% range held what happened ${Math.round(100 * sk.coverage)}% of the time.`;
  }
  let colH = "12", colPick = "food";
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const ymAdd = (ym, h) => { const [y, m] = ym.split("-").map(Number), t = y * 12 + m - 1 + Number(h); return `${MON[t % 12]} ${Math.floor(t / 12)}`; };
  // {h: [lo, mid, hi]} at a few horizons -> 13 monthly points [mid, lo, hi] from 0 to 12, straight lines between
  function colPath(q) {
    const hs = [0].concat(Object.keys(q).map(Number).sort((a, b) => a - b)), at = (h) => (h === 0 ? [0, 0, 0] : q[h]);
    const out = [];
    for (let m = 0; m <= 12; m++) {
      const j = Math.max(1, hs.findIndex((h) => h >= m)), h0 = hs[j - 1], h1 = hs[j], a = at(h0), b = at(h1), w = m <= h0 ? 0 : (m - h0) / (h1 - h0);
      out.push([a[1] + (b[1] - a[1]) * w, a[0] + (b[0] - a[0]) * w, a[2] + (b[2] - a[2]) * w]);
    }
    return out;
  }
  function colRows(name) {
    const P = COIL.prices[isoOf[name]] || {}, reg = ecoOf(name), rows = [];
    const W = COIL.weights[isoOf[name]] || {};
    for (const [kind, label] of COL_KINDS) {
      const v = P[kind], share = W[kind] != null ? `${W[kind].toFixed(0)}% of a household budget here` : "";
      rows.push(v && v.out ? { key: kind, kind, name: label, from: v.from, q: v.out, b: v.b, own: v.own, src: v.src, share, unc: v.unc, rule: v.rule }
        : { key: kind, name: label, none: v ? (v.why || "no forecast") : "not in our data", now: v && v.now, src: v && v.src, share });
    }
    if (reg && COIL.col[reg]) for (const [kk, nm] of COL_ITEMS) if (COIL.col[reg][kk]) rows.push({ key: `col_${kk}`, name: nm, from: COIL.colFrom, q: COIL.col[reg][kk], model: reg });
    return rows;
  }
  function renderCol() {
    if (!st.sel || !$("col-sec")) return;
    const name = st.sel, P = COIL.prices[isoOf[name]] || {}, k = calc(name), nm = name === "United States of America" ? "the United States" : name;
    const f = P.food, a = P.all, yr = (v) => (v ? `<b>${pctP(v.v)}</b>` : "–"), at = (v) => (v && v.now ? ` (${ymLabel(v.now.month)}, ${v.src})` : "");
    $("col-now").innerHTML = a && a.now
      ? `Prices in ${escH(nm)} were ${yr(a.now)} on a year earlier${at(a)}, food ${yr(f && f.now)}${f && f.now && f.now.month !== a.now.month ? at(f) : ""}.`
        + (a.before ? ` Before the Hormuz closure, in Feb 2026: ${yr(a.before)}, food ${yr(f && f.before)}.` : "")
      : `Neither the IMF nor FAOSTAT has consumer prices for ${escH(nm)}: not in our data.`;
    $("col-h").innerHTML = ["1", "2", "3", "6", "12"].map((h) => `<button type="button" data-colh="${h}" aria-pressed="${h === colH}">${h} mo</button>`).join("");
    const rows = colRows(name), shock = 100 * Math.log(st.brent / BRENT0);
    if (!rows.some((r) => r.key === colPick && r.q)) colPick = (rows.find((r) => r.q) || {}).key;
    const fuelRow = k.fuel == null ? `<li data-colkey="fuel"><span class="nm">Fuel at the pump</span><span class="lv">no estimate</span>${whyBox("fuel", "Why no estimate", NOFUEL)}</li>`
      : `<li data-colkey="fuel"><span class="nm">Fuel at the pump</span><span class="lv mono ${k.fuel > 0.005 ? "hurt" : ""}">${pct(k.fuel)}</span>
        ${whyBox("fuel", k.fuel >= 0 ? "Why it rises" : "Why it falls", `Against pre-war, at Brent $${st.brent}: ${escH(nm)}'s own pass-through of ${k.d.pt.e.toFixed(2)} (${escH(k.d.pt.series)}, ${k.d.pt.from} to ${k.d.pt.to}, collected ${k.d.pt.collected})${inDisruption(k.s) ? ", times 1.49 in a supply disruption" : ""}. Pump prices follow oil within weeks.`)}</li>`;
    $("col-list").innerHTML = rows.map((r) => {
      if (!r.q) return `<li data-colkey="${r.key}"><span class="nm">${r.name}</span><span class="lv">${r.now ? `${pctP(r.now.v)} a year` : "–"}</span>
        ${whyBox(r.key, "Why no forecast", `No forecast: ${escH(r.none)}${r.now ? `. Latest: ${pctP(r.now.v)} on a year earlier in ${ymLabel(r.now.month)} (${r.src})` : ""}.${r.share ? ` ${r.share}.` : ""}`)}</li>`;
      const q = r.q[colH], cls = q[1] > 0.05 ? "hurt" : q[1] < -0.05 ? "gain" : "", w = Math.min(100, Math.abs(q[1]) / 20 * 100);
      const cost = `By ${ymAdd(r.from, colH)}, 100 spent today costs <b>${(100 + q[1]).toFixed(1)}</b> (90% range ${(100 + q[0]).toFixed(1)} to ${(100 + q[2]).toFixed(1)}).`;
      const why = r.model ? `${cost} Seb's cost-of-living model (${COL_REGION[r.model]}), with the disruption continuing.`
        : `${cost}${fcTxt(r)}${r.unc ? " <b>Very uncertain</b>: this country's prices have swung far from the rule before." : ""}${r.share ? ` ${r.share}.` : ""}${q[3] ? ` Oil's moves since ${ymLabel(r.from)} add ${pctP(q[3], 2)}.` : ""}${r.b && r.own && st.brent > BRENT0
          ? ` Brent at $${st.brent} instead of the pre-war $${BRENT0}, over ${colH} months by itself: ${COIL.priorSrc[r.kind]} ${pctP(COIL.prior[r.kind][colH] * shock, 2)}, `
            + `${escH(nm)}'s own data ${pctP(r.own[colH] * shock, 2)}, combined <b>${pctP(r.b[colH] * shock, 2)}</b> (a ridge update on ${escH(nm)}'s prices).` : ""} Prices to ${ymLabel(r.from)} (${r.src}).`;
      return `<li class="colrow" data-colitem="${r.key}" aria-current="${r.key === colPick}"><span class="nm">${r.name}${r.model ? ` <span class="faint">${COL_REGION[r.model]} model</span>` : ""}</span><span class="lv mono ${cls}">${pctP(q[1])}</span>
        <span class="tr"><div style="width:${Math.max(w, 2)}%;background:${q[1] < 0 ? "var(--gain)" : color(Math.min(65, Math.max(6, q[1] * 4)))}"></div></span>${whyBox(r.key, q[1] >= 0.05 ? "Why it rises" : q[1] <= -0.05 ? "Why it falls" : "Why it holds", why)}</li>`;
    }).join("") + fuelRow;
    const sel = rows.find((r) => r.key === colPick && r.q);
    $("col-chart-h").innerHTML = sel ? `<b>${sel.name}</b>: % change from ${ymLabel(sel.from)}, with its 90% range. Click a row to chart it.` : "";
    if (sel) ecoChart($("col-chart"), colPath(sel.q), { unit: "%" }); else $("col-chart").innerHTML = "";
    $("col-src").textContent = `Prices: ${COIL.pricesSrc}. Groceries and all prices: our cross-country model (experiments/country_outlook.py: gradient-boosted trees, and at 6-12 months their average with a median regression, on recent inflation, the country's longer-run rate, world inflation, the food-all gap, Brent and the season), `
      + `which beat the naive rule at every horizon in a rolling backtest 2015-2024; the six hyperinflation countries and rates above 50% keep the rule. Housing and energy, and transport: the rule. Every row adds Brent's known moves since its last price month through the country's oil link, `
      + `ridge-updated on the country's own prices (2009-2025) from our cost-of-living model (all prices, food) or the cross-country average (housing and energy, transport). `
      + `The range is how far that rule missed for this country, 2015-2024. A fitted time-series model lost to this rule in backtests, so it isn't used. Budget shares: IMF CPI weights. `
      + (ecoOf(name) ? `Item rows: Seb's cost-of-living model, outlook from ${ymLabel(COIL.colFrom)} (notes/cost-of-living-fans.csv, ${COIL.colGen}); how it compares with the Fed and the SPF is in the Models tab.` : "");
  }
  $("col-h") && $("col-h").addEventListener("click", (e) => { const b = e.target.closest("[data-colh]"); if (b) { colH = b.dataset.colh; renderCol(); } });
  $("col-list") && $("col-list").addEventListener("click", (e) => {
    const sm = e.target.closest("summary"), li = e.target.closest("li");
    if (sm && li) {   // the toggle opens or closes by itself; just remember it
      const key = li.dataset.colitem || li.dataset.colkey, box = sm.parentElement;
      setTimeout(() => (box.open ? colOpen.add(key) : colOpen.delete(key)), 0);
      return;
    }
    if (li && li.dataset.colitem) { colPick = li.dataset.colitem; renderCol(); }
  });
'''
sub("  function renderCountry() {", COL_JS + "  function renderCountry() {")
sub("#c-ind-pick { width: 100%; }",
    "#c-ind-pick { width: 100%; }\n"
    ".cpop .cp-pred { display: block; margin-top: 6px; font-size: 11.5px; color: var(--faint); }\n"
    ".ctabs { flex-wrap: wrap; }\n"
    "#col-sec { display: flex; flex-direction: column; gap: 10px; }\n"
    ".col-now { margin: 0; font-size: 13.5px; line-height: 1.5; }\n"
    ".col-list .colrow { cursor: pointer; }\n"
    ".col-list details.why > summary { cursor: pointer; width: fit-content; color: var(--muted); font-size: 12px; }\n"
    ".col-list details.why[open] > summary { margin-bottom: 4px; }\n"
    ".col-list .colrow[aria-current=\"true\"] .nm { text-decoration: underline; text-underline-offset: 3px; }")

# 5. pop-up: groceries, fuel, oil cut off; prices now; our models' 12-month what-ifs
sub('    const tag = VIA[name] ? VIA[name] : k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : "Net importer";',
    '    const tag = VIA[name] ? VIA[name] : k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : k.kind === "none" ? "No oil trade data" : "Net importer";')
sub('''        + kpi(fmtS(k.score), "exposure score, illustrative", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "");''',
    '''        + kpi(k.cut ? k.cut.txt : "–", k.cut ? k.cut.lab : "oil cut off: not in our data", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "");''')
sub('''      kpis = kpi(fmtS(k.score), "exposure score, illustrative", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "")
        + kpi(pct(k.fuel), "fuel cost, in a disruption", k.fuel > 0.005 ? "hurt" : k.fuel < -0.005 ? "gain" : "")
        + kpi(k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–", "of its oil via Hormuz");''',
    '''      const P = COIL.prices[iso] || {}, fd = P.food, al = P.all, g = fd && fd.out && fd.out["12"], ga = al && al.out && al.out["12"];
      kpis = kpi(g ? pctP(g[1]) : "–", g ? `groceries by ${ymAdd(fd.from, 12)}${fd.unc ? ", very uncertain" : ""}` : "groceries: not in our data", g && g[1] > 0.05 ? "hurt" : "")
        + kpi(ga ? pctP(ga[1]) : "–", ga ? `all prices by ${ymAdd(al.from, 12)}${al.unc ? ", very uncertain" : ""}` : "all prices: not in our data", ga && ga[1] > 0.05 ? "hurt" : "")
        + kpi(k.cut ? k.cut.txt : "–", k.cut ? k.cut.lab : "oil cut off: not in our data", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "");''')
sub('''"Pick a product above to see what it makes and trades.";
    }
    $("cp-kpis").innerHTML = kpis;''', '''"Pick a product above to see what it makes and trades.";
      line = (al && al.now ? `Prices now <b>${pctP(al.now.v)}</b>, food <b>${fd && fd.now ? pctP(fd.now.v) : "–"}</b> on a year earlier (${ymLabel(al.now.month)}, ${al.src}). ` : "")
        + (k.kind === "imp" && k.hz != null ? `${Math.round(k.hz * 100)}% of its oil imports came from the Gulf. ` : "")
        + (k.fuel == null ? "" : `Fuel at the pump ${pct(k.fuel)}. `) + line + predHtml(name);
    }
    $("cp-kpis").innerHTML = kpis;''')
sub("  // pop-up for the selected country: headline facts only; the panel holds the full analysis\n  function renderPop() {",
    '''  // our models' 12-month what-ifs for a country at the shock card's Brent, where they reach it
  function predHtml(name) {
    const own = ecoOf(name), out = [];
    if (own) out.push(`consumer prices <b>${pctP(ecoPath(`${own}_cpi`)[12][0])}</b> (${own === "ea" ? "euro area" : own === "us" ? "US" : "UK"}, Bayesian model)`);
    const sec = sectorMove(name, "manuf");
    if (sec) out.push(`factory prices <b>${pctP(sec.v)}</b> (sector model)`);
    return out.length ? `<span class="cp-pred">Our models, 12 months at $${st.brent}, against no disruption: ${out.join("; ")}.</span>` : "";
  }
  // pop-up for the selected country: headline facts only; the panel holds the full analysis
  function renderPop() {''')

# 6. what the Gemini panels are told, and the info sheet that replaces the score's
sub('''    out.push(`${nmIso(iso)} exposure score ${fmtS(k.score)} on a -40 (gains) to +65 (hurt) scale (an illustrative index: its weights are hand-set, not from a model; inputs from the scenario)`);''',
    '''    out.push(k.cut ? `${nmIso(iso)}: ${k.cut.txt} ${k.cut.lab} at ${Math.round(k.s * 100)}% of Hormuz flow lost (${k.d.depSrc || "this page's country table"})` : `${nmIso(iso)} has no oil trade in our data`);''')
sub('''    out.push(`Fuel cost ${pct(k.fuel)} vs pre-war: Brent to retail fuel link validated on FRED (fitted 1991-2008, tested 2009-2026) times 1.49 in a supply disruption (Seb's cost-of-living model: 90% range 1.08 to 1.89, fitted on the US, UK and euro area, an assumption elsewhere)`);
    if (k.d.c) out.push(`About ${(k.hz * 100).toFixed(0)}% of ${nmIso(iso)}'s oil use comes through Hormuz (this page's country table)`);''',
    '''    out.push(k.fuel == null ? `No fuel price estimate for ${nmIso(iso)}: pump-price pass-through is only estimated for the ${Object.keys(COIL.fuel).length} countries whose monthly motor-fuel consumer prices we have`
      : `Fuel cost ${pct(k.fuel)} vs pre-war: ${nmIso(iso)}'s own Brent to pump-price pass-through of ${k.d.pt.e.toFixed(2)} (${k.d.pt.series}, ${k.d.pt.from} to ${k.d.pt.to}, collected ${k.d.pt.collected}; country_oil.py) times 1.49 in a supply disruption (Seb's cost-of-living model: 90% range 1.08 to 1.89, fitted on the US, UK and euro area, an assumption elsewhere)`);
    if (k.hz != null) out.push(`About ${(k.hz * 100).toFixed(0)}% of ${nmIso(iso)}'s oil imports came from the Gulf producers before the war (${k.d.depSrc}; an upper bound for oil through the strait)`);
    { const pr = COIL.prices[iso], al = pr && pr.all, fd = pr && pr.food;
      if (al && al.now) out.push(`Consumer prices in ${nmIso(iso)} ${pctP(al.now.v)} on a year earlier, food ${fd && fd.now ? pctP(fd.now.v) : "n/a"}, in ${ymLabel(al.now.month)} (${al.src})`);
      if (fd && fd.out) out.push(`Groceries forecast ${pctP(fd.out["12"][1])} by ${ymAdd(fd.from, 12)} (90% range ${pctP(fd.out["12"][0])} to ${pctP(fd.out["12"][2])}): the latest 12 months' rate continues plus oil's known moves (country_oil.py)`); }''')
sub('''    score: { title: "Exposure score", html: `<p>One number per country for how hard the shock hits it. Above zero means hurt; below zero means it gains.</p>
      <ul><li><b>Importers:</b> how much more fuel costs × how much of their oil they import.</li>
      <li><b>Exporters outside the Gulf</b> (Norway, Canada, Nigeria and others) gain from the higher price.</li>
      <li><b>Gulf producers</b> are hurt by the oil they can't ship out.</li></ul>
      <p class="illus-note"><b>Illustrative:</b> the weights are set by hand, not fitted to data. Inputs: EIA 2024 Hormuz volumes and Energy Institute consumption. Countries without their own data use a typical importer.</p>` },''',
    '''    score: { title: "Oil cut off by the shock", html: `<p>How much oil the shock takes from each country, from trade data and the lost flow you set.</p>
      <ul><li><b>Importers:</b> the share of their oil imports that came from the Gulf producers (UN Comtrade, 2024 or 2023, by value) × the share of Hormuz flow lost. An upper bound: some Saudi and UAE oil leaves by pipeline to Yanbu and Fujairah.</li>
      <li><b>Gulf producers:</b> the share of their exports trapped behind the strait.</li>
      <li><b>Other exporters</b> (Norway, Canada, Nigeria and others) gain: the map shows their oil earnings rising with the price, in teal.</li></ul>
      <p>Grey: not in our data (no oil trade reported to UN Comtrade). What it does to prices is in each country's Cost of living tab.</p>` },''')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
