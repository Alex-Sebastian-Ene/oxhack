# Runs last, after patch_pickind.py, on hormuz-flow.html.
# Every country's own numbers in the World view, from notes/country-oil.json (experiments/country_oil.py), read at
# build time, instead of a typical importer profile for the countries the hand-entered table leaves out:
# 1. Import dependence and the Gulf share of oil imports from UN Comtrade (HS 2709 + 2710, by value), for every
#    country that reports oil trade. The hand-entered table (EIA, Energy Institute) fills in where Comtrade has
#    nothing (Taiwan, Iran); a country in neither says "not in our data" and is grey on the map.
# 2. Fuel cost from the country's own Brent -> pump-price pass-through where the trends data has its motor-fuel
#    prices (Europe, Türkiye, the US), else the median of those, marked "pooled". Industries and the fuel-cost
#    path use the same pass-through, so the panel agrees with the pop-up.
# 3. The pop-up adds our models' 12-month what-ifs where they reach the country: consumer prices (Seb's Bayesian
#    model: US, UK, euro area) and factory prices (the sector model: Europe, Türkiye, the US).
# The hand-entered table keeps routes, volumes, industries and the Gulf producers' trapped export share.
import json, pathlib, subprocess

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
fuel, trade = src["fuel"], src.get("trade") or {"countries": {}}
COIL = {
    "generated": src["generated"],
    "fuelSrc": f'{fuel["method"]}. Brent: {fuel["brent"]}',
    "tradeSrc": f'{trade["source"]}, collected {trade["collected"]}' if trade.get("source") else "",
    "pooled": {k: fuel["pooled"][k] for k in ("e", "lo", "hi", "n")},
    "fuel": {iso: {k: v[k] for k in ("e", "lo", "hi", "series", "from", "to")} for iso, v in fuel["countries"].items()},
    "trade": {iso: {"m": v["m"], "gs": v["gulf_share"], "year": v["year"], "top": next(iter(v["by"]), None)}
              for iso, v in trade["countries"].items()},
}

# 1. one profile per country: hand-entered table for routes and volumes, data for dependence, Gulf share, pass-through
sub('''  function info(name) {
    const d = C[name] || (DEFAULT_EXP.has(name) ? { c: 50, h: 0, m: -3, ind: EXP } : { c: 0, h: 0, m: .8, ind: IMP, generic: true });
    return d;
  }''', '''  // Country oil profiles from notes/country-oil.json (experiments/country_oil.py, read at build time): import
  // dependence and the Gulf share of oil imports (UN Comtrade), and the Brent -> pump-price pass-through (own or pooled)
  const COIL = ''' + json.dumps(COIL, ensure_ascii=False) + ''';
  const NODATA = "#eceff3";
  function info(name) {
    const iso = isoOf[name], t = COIL.trade[iso], f = COIL.fuel[iso], hand = C[name];
    const d = Object.assign({ c: 0, h: 0, m: null }, hand || {});
    if (t) Object.assign(d, { dep: t.m, gs: t.gs, top: t.top, depSrc: `UN Comtrade, ${t.year}` });
    else if (hand) Object.assign(d, { dep: hand.m, gs: hand.c && hand.m > 0 ? Math.min(1, hand.h / (hand.c * hand.m)) : null, depSrc: "this page's country table (EIA, Energy Institute)" });
    else Object.assign(d, { dep: null, gs: null, nodata: true });
    if (!hand) d.ind = d.dep != null && d.dep <= 0 ? EXP : IMP;
    d.pt = f ? Object.assign({ own: true }, f) : Object.assign({ own: false, series: `pooled: the median of ${COIL.pooled.n} countries' pass-through` }, COIL.pooled);
    return d;
  }''')
sub("    const hz = d.c ? Math.min(1, d.h / d.c) : 0;",
    "    const hz = d.gs;                                  // share of its oil imports from the Gulf producers (null: not in our data)")
sub("    const price = fuelFrac(dlog);                     // validated: Brent -> retail fuel",
    "    const price = d.pt.e * dlog;                      // its own Brent -> pump-price pass-through, or the pooled one")
sub('''    else if (d.m <= 0) { kind = "exp"; score = -Math.min(1, -d.m / 3 + 0.15) * Math.max(dB, 0) * 60; }
    else { kind = "imp"; score = fuel * (0.4 + 0.6 * d.m) * 100; }''',
    '''    else if (d.dep == null) { kind = "none"; score = null; }
    else if (d.dep <= 0) { kind = "exp"; score = -Math.min(1, -d.dep / 3 + 0.15) * Math.max(dB, 0) * 60; }
    else { kind = "imp"; score = fuel * (0.4 + 0.6 * Math.min(1, d.dep)) * 100; }''')
sub("    if (!k.d || k.d.m > 0) return null;", "    if (!k.d || !(k.d.dep <= 0)) return null;")
# the same pass-through in the Industries tab and the fuel-cost path
sub("      const lo = sh.s * fuelFrac(k.dlog, 1) * (1 + (dz ? DISRUPT.lo : 0)), hi = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.hi : 0));\n"
    "      const mid = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.mid : 0));",
    "      const lo = sh.s * k.d.pt.lo * k.dlog * (1 + (dz ? DISRUPT.lo : 0)), hi = sh.s * k.d.pt.hi * k.dlog * (1 + (dz ? DISRUPT.hi : 0));\n"
    "      const mid = sh.s * k.d.pt.e * k.dlog * (1 + (dz ? DISRUPT.mid : 0));")
sub("      return 100 * (1 + fuelFrac(Math.log(1 + dB)) * (1 + DISRUPT.mid",
    "      return 100 * (1 + k.d.pt.e * Math.log(1 + dB) * (1 + DISRUPT.mid")

# 2. no data: grey on the map, "–" in the numbers, "not in our data" in words
sub("  function fillFor(name) { return st.mat ? matShade(name) : color(calc(name).score); }",
    "  function fillFor(name) { if (st.mat) return matShade(name); const v = calc(name).score; return v == null ? NODATA : color(v); }")
sub('  const fmtS = (v) => (v > 0.5 ? "+" : v < -0.5 ? "−" : "") + Math.abs(v).toFixed(0);',
    '  const fmtS = (v) => (v == null ? "–" : (v > 0.5 ? "+" : v < -0.5 ? "−" : "") + Math.abs(v).toFixed(0));')
GULF_TIP = ('${k.kind === "imp" || k.kind === "none" ? `<span>From the Gulf <span class="mono">${k.hz == null ? "not in our data" : `${(k.hz * 100).toFixed(0)}% of oil imports`}</span></span>` : ""}'
            '${k.score == null ? `<span>Exposure: not in our data</span>` : ""}')
sub('''      <span>Fuel cost <span class="mono">${pct(k.fuel)}</span></span>${k.d.h ? `<span>Via Hormuz <span class="mono">${(k.hz * 100).toFixed(0)}% of use</span></span>` : ""}`;''',
    '''      <span>Fuel cost <span class="mono">${pct(k.fuel)}${k.d.pt.own ? "" : " (pooled)"}</span></span>''' + GULF_TIP + "`;")
sub('''    return `<b>${escH(name)}</b><span>Exposure <span class="mono">${fmtS(k.score)}</span></span><span>Fuel cost <span class="mono">${pct(k.fuel)}</span></span>`;''',
    '''    return `<b>${escH(name)}</b><span>Exposure <span class="mono">${k.score == null ? "not in our data" : fmtS(k.score)}</span></span><span>Fuel cost <span class="mono">${pct(k.fuel)}${k.d.pt.own ? "" : " (pooled)"}</span></span>`;''')

# 3. country card: tag, line under the name, Gulf share
sub('    tag.textContent = k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : "Net importer";',
    '    tag.textContent = k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : k.kind === "none" ? "No oil trade data" : "Net importer";')
sub('''    else sub = d.generic ? "No direct Hormuz cargoes in this model, so the shock arrives through the world oil price. Figures use a typical importer profile." : "Feels the shock through the world oil price.";''',
    '''    else if (d.nodata) sub = "Not in our data: it doesn't report oil trade to UN Comtrade, so there is no import dependence or Gulf share for it. Fuel cost uses the pooled pass-through.";
    else if (k.hz != null) sub = `Before the war about ${Math.round(k.hz * 100)}% of its oil imports came from the Gulf producers${d.top ? `, most from ${d.top}` : ""} (${d.depSrc}), so the shock reaches it through supply as well as price.`;
    else sub = "Feels the shock through the world oil price.";''')
sub('    $("c-dep").textContent = k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–";',
    '    $("c-dep").textContent = k.kind === "imp" && k.hz != null ? `${(k.hz * 100).toFixed(0)}%` : "–";\n'
    '    $("c-fuel").title = `Pass-through ${k.d.pt.e.toFixed(2)} (${k.d.pt.series}${k.d.pt.from ? `, ${k.d.pt.from} to ${k.d.pt.to}` : ""}) × 1.49 in a disruption`;')
sub('<div><b id="c-dep">–</b><span>Oil use sourced via Hormuz</span></div>', '<div><b id="c-dep">–</b><span>Oil imports from the Gulf</span></div>')

# 4. pop-up: the three numbers say where they come from, then our models' 12-month what-ifs
sub('    const tag = VIA[name] ? VIA[name] : k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : "Net importer";',
    '    const tag = VIA[name] ? VIA[name] : k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : k.kind === "none" ? "No oil trade data" : "Net importer";')
sub('''      kpis = kpi(fmtS(k.score), "exposure score, illustrative", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "")
        + kpi(pct(k.fuel), "fuel cost, in a disruption", k.fuel > 0.005 ? "hurt" : k.fuel < -0.005 ? "gain" : "")
        + kpi(k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–", "of its oil via Hormuz");''',
    '''      kpis = kpi(fmtS(k.score), k.score == null ? "exposure: not in our data" : "exposure score, illustrative", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "")
        + kpi(pct(k.fuel), k.d.pt.own ? "fuel cost, in a disruption" : "fuel cost, pooled estimate", k.fuel > 0.005 ? "hurt" : k.fuel < -0.005 ? "gain" : "")
        + kpi(k.kind !== "imp" || k.hz == null ? "–" : `${(k.hz * 100).toFixed(0)}%`, k.kind !== "exp" && k.kind !== "gulf" && k.hz == null ? "Gulf share: not in our data" : "of its oil imports from the Gulf");''')
sub('''"Pick a product above to see what it makes and trades.";
    }
    $("cp-kpis").innerHTML = kpis;''', '''"Pick a product above to see what it makes and trades.";
      line += predHtml(name);
    }
    $("cp-kpis").innerHTML = kpis;''')
sub("  // pop-up for the selected country: headline facts only; the panel holds the full analysis\n  function renderPop() {",
    '''  // our models' 12-month what-ifs for a country at the shock card's Brent, where they reach it
  function predHtml(name) {
    const own = ecoOf(name), out = [];
    if (own) out.push(`consumer prices <b>${pctP(ecoPath(`${own}_cpi`)[12][0])}</b> (${own === "ea" ? "euro area" : own === "us" ? "US" : "UK"}, Bayesian model)`);
    const sec = sectorMove(name, "manuf");
    if (sec) out.push(`factory prices <b>${pctP(sec.v)}</b> (sector model)`);
    return `<span class="cp-pred">${out.length ? `Our models, 12 months at $${st.brent}: ${out.join("; ")}.` : "Model what-ifs for prices: not in our data."}</span>`;
  }
  // pop-up for the selected country: headline facts only; the panel holds the full analysis
  function renderPop() {''')
sub("#c-ind-pick { width: 100%; }",
    "#c-ind-pick { width: 100%; }\n.cpop .cp-pred { display: block; margin-top: 6px; font-size: 11.5px; color: var(--faint); }")

# 5. what the Gemini panels are told, and the score's info sheet
sub('''    out.push(`Fuel cost ${pct(k.fuel)} vs pre-war: Brent to retail fuel link validated on FRED (fitted 1991-2008, tested 2009-2026) times 1.49 in a supply disruption (Seb's cost-of-living model: 90% range 1.08 to 1.89, fitted on the US, UK and euro area, an assumption elsewhere)`);
    if (k.d.c) out.push(`About ${(k.hz * 100).toFixed(0)}% of ${nmIso(iso)}'s oil use comes through Hormuz (this page's country table)`);''',
    '''    out.push(`Fuel cost ${pct(k.fuel)} vs pre-war: ${k.d.pt.own ? `${nmIso(iso)}'s own` : "a pooled"} Brent to pump-price pass-through of ${k.d.pt.e.toFixed(2)} (${k.d.pt.series}; country_oil.py) times 1.49 in a supply disruption (Seb's cost-of-living model: 90% range 1.08 to 1.89, fitted on the US, UK and euro area, an assumption elsewhere)`);
    if (k.hz != null) out.push(`About ${(k.hz * 100).toFixed(0)}% of ${nmIso(iso)}'s oil imports came from the Gulf producers before the war (${k.d.depSrc}; an upper bound for oil through the strait)`);
    else if (k.d.nodata) out.push(`${nmIso(iso)} has no oil trade in our data, so its exposure score is not shown`);''')
sub('''Inputs: EIA 2024 Hormuz volumes and Energy Institute consumption. Countries without their own data use a typical importer.</p>` },''',
    '''Inputs: each country's oil imports, exports and imports from the Gulf (UN Comtrade), and its own Brent to pump-price pass-through where we have its fuel prices (else the median, marked pooled). Countries in neither are grey: not in our data.</p>` },''')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
