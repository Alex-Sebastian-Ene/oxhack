# Runs last, after patch_reserves.py, on hormuz-flow.html.
# The Industries tab and "What it costs buyers" from one source each, so they agree and stay current:
# 1. Cost shares come from Eileen's notes/industry/industry_exposure.csv, read at build time (no retyped numbers).
#    Cost change = that share x the modelled price change, as before.
# 2. Where Seb's sector model has the industry (notes/country-trends.json: producer prices for Europe and the US),
#    the row also shows how much the industry's own prices rise after 12 months at this Brent. A row with no sourced
#    cost share shows that instead of "no data".
# 3. Oil exporters' "Oil exports" and "Government revenue" rows show oil export earnings: price change x the oil that
#    still gets out (Gulf producers lose the share trapped behind the strait). Inputs are the country table's cited
#    volumes and the Brent from the flow-premium curve.
# 4. The tab says that which industries are listed for a country is a hand-picked, illustrative choice.
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


rows = {r["industry"]: r for r in csv.DictReader((root / "notes" / "industry" / "industry_exposure.csv").open(encoding="utf-8"))}


def cite(r):
    return {"s": float(r["share_pct"]), "src": f'{r["oil_linked_cost"]} {r["share_pct"]}%: {r["measure"]} ({r["source"]}, {r["region"]}, {r["year"]})',
            "url": r["source_url"], "year": r["year"]}


# page industry key <- CSV row
IND_ROWS = {"aviation": "airlines", "shipping": "container_shipping", "freight": "trucking", "petchem": "chemicals",
            "manuf": "manufacturing_average", "fishing": "fishing", "agri": "farming_fuel"}
# product card buyers: (material, buyer label) <- CSV row
BUYER_ROWS = {("jet_fuel", "Airlines"): "airlines", ("fertiliser", "Farming"): "farming",
              ("steel", "Construction"): "construction_steel", ("aluminium", "Packaging (cans)"): "can_aluminium",
              ("polyethylene", "Packaging"): "packaging_resin"}
POWER_TEXT = rows["textiles_power"]
for k in list(IND_ROWS.values()) + list(BUYER_ROWS.values()):
    assert k in rows, f"{k} missing from industry_exposure.csv"
CSV_IND = {key: cite(rows[r]) for key, r in IND_ROWS.items()}
CSV_BUY = {f"{m}|{b}": cite(rows[r]) for (m, b), r in BUYER_ROWS.items()}
# page industry key -> Seb's sector-model industry code
SECTOR = {"refining": "C19", "power": "D35", "upstream": "B06", "petchem": "C20", "manuf": "C", "agri": "C2015"}
trends = json.loads((root / "notes" / "country-trends.json").read_text(encoding="utf-8"))
codes = {c for c, _ in trends["industries"]}
assert set(SECTOR.values()) <= codes, set(SECTOR.values()) - codes

IND_JS = (
    "  // Cost shares from notes/industry/industry_exposure.csv (read at build time); sector codes for Seb's sector model\n"
    f"  const CSV_IND = {json.dumps(CSV_IND, ensure_ascii=False)};\n"
    f"  const CSV_BUY = {json.dumps(CSV_BUY, ensure_ascii=False)};\n"
    f"  const SECTOR = {json.dumps(SECTOR)};\n"
) + r'''  for (const [key, c] of Object.entries(CSV_IND)) SHARE[key] = { s: c.s, src: c.src, lag: (SHARE[key] && SHARE[key].lag) || "" };
  for (const [mat, list] of Object.entries(BUYERS)) for (const row of list) {
    const c = CSV_BUY[`${mat}|${row[0]}`];
    if (c) { row[1] = c.s; row[2] = c.src; }
  }
  // Seb's sector model: the industry's own producer prices, extra change after 12 months at this Brent (average effect)
  function sectorMove(name, key) {
    const code = SECTOR[key], geo = typeof TR_GEO !== "undefined" && TR_GEO[name], c = geo && TRENDS.countries[geo];
    const pr = code && c && c.price && c.price[code];
    if (!pr || !pr.resp || pr.resp[pr.resp.length - 1] == null) return null;
    const x = st.brent / BRENT0 - 1, v = x > 0.005 ? pr.resp[pr.resp.length - 1] * Math.log(1 + x) / Math.log(1.1) : 0;
    const label = (TRENDS.industries.find(([k]) => k === code) || [code, code])[1];
    return { v, skill: pr.skill, label, where: geo === "US" ? "the US" : geo === "UK" ? "the UK" : c.name };
  }
  // oil exporters: earnings = price change x the oil that still gets out
  function exportEarnings(name) {
    const k = calc(name);
    if (!k.d || k.d.m > 0) return null;
    const out = 1 - (k.d.gulf ? k.d.gulf * k.s : 0);
    return { v: ((1 + k.dB) * out - 1) * 100, trapped: k.d.gulf ? k.d.gulf * k.s : 0 };
  }
  // where Seb's sector model doesn't reach the country: the US price series in his chain, labelled as US
  const CHAIN_IND = { refining: ["ind_pcu324110324110", "Petroleum refinery"], tourism: ["ind_pcu481111481111", "Passenger air fare"] };
  function chainMove(key) {
    const c = CHAIN_IND[key];
    if (!c) return null;
    const e = chainEffect(c[0]);
    return { v: e.mean, lo: e.lo, hi: e.hi, label: c[1], where: "the US" };
  }
  const POWER_SHARE = ''' + json.dumps({"s": float(POWER_TEXT["share_pct"]), "src": f'{POWER_TEXT["measure"]} ({POWER_TEXT["source"]}, {POWER_TEXT["year"]})'}) + r''';
'''
sub("  function industries(name) {", IND_JS + "  function industries(name) {")
sub("      if (!sh) return { key, label, why, v: null };",
    "      const sec = sectorMove(name, key), earn = (key === \"exports\" || key === \"budget\" || (key === \"upstream\" && !sec)) ? exportEarnings(name) : null;\n"
    "      const chn = sec ? null : chainMove(key), ports = key === \"ports\" ? { v: -st.lost } : null, power = key === \"textiles\" ? POWER_SHARE : null;\n"
    "      if (!sh) return { key, label, why, v: null, sec, earn, chn, ports, power };")
# power generation was a guess in the default importer profile (countries without their own data): drop it there
sub('const IMP = ["freight", "aviation", "agri", "manuf", "power"];', 'const IMP = ["freight", "aviation", "agri", "manuf"];')
sub("      return { key, label, why, v: hi, lo: Math.min(lo, hi), hi: Math.max(lo, hi), src: sh.src, lag: sh.lag };",
    "      return { key, label, why, v: hi, lo: Math.min(lo, hi), hi: Math.max(lo, hi), src: sh.src, lag: sh.lag, sec };")

OLD_RENDER = '''      if (i.v == null) return `<li><span class="nm">${i.label}</span><span class="lv">no data</span>
        <span class="why">${i.why}. No sourced fuel cost share yet, so no number is shown.</span></li>`;'''
NEW_RENDER = '''      const secLine = (sec) => `${escH(sec.label)} prices in ${escH(sec.where)} ${pct(sec.v / 100, 1)} after 12 months at this Brent (Seb's sector model, average effect; ${trSkill(sec.skill)} than a naive forecast).`;
      if (i.v == null && i.earn) {
        const e = i.earn, cls = e.v > 0.05 ? "gain" : e.v < -0.05 ? "hurt" : "";
        return `<li><span class="nm">${i.label}</span><span class="lv mono ${cls}">${pct(e.v / 100, 1)} earnings</span>
        <span class="why">Oil export earnings: the price change at Brent $${st.brent} × the oil that still gets out${e.trapped ? ` (${Math.round(e.trapped * 100)}% trapped behind the strait)` : ""}. Inputs: this page's country table (EIA, Energy Institute) and the flow-premium curve.</span></li>`;
      }
      if (i.v == null && i.sec) {
        const cls = i.sec.v > 0.05 ? "hurt" : i.sec.v < -0.05 ? "gain" : "";
        return `<li><span class="nm">${i.label}</span><span class="lv mono ${cls}">${pct(i.sec.v / 100, 1)} its prices</span>
        <span class="why">${i.why}. No sourced cost share, so this is how much the industry's own prices rise: ${secLine(i.sec)}</span></li>`;
      }
      if (i.v == null && i.chn) {
        const c = i.chn, cls = c.v > 0.05 ? "hurt" : c.v < -0.05 ? "gain" : "";
        return `<li><span class="nm">${i.label}</span><span class="lv mono ${cls}">${pct(c.v / 100, 1)} ${i.key === "tourism" ? "air fares" : "its prices"}</span>
        <span class="why">${i.why}. No sourced cost share, and no sector model for this country, so this is ${c.label.toLowerCase()} prices in the US after 12 months (Seb's chain, 90% range ${pct(c.lo / 100, 0)} to ${pct(c.hi / 100, 0)}).${i.key === "tourism" ? " Flights are the main way oil reaches tourism." : ""}</span></li>`;
      }
      if (i.v == null && i.ports) return `<li><span class="nm">${i.label}</span><span class="lv mono hurt">−${st.lost}% traffic</span>
        <span class="why">${i.why}. Hormuz traffic is down ${st.lost}% of normal at the lost flow you set (the shock card).</span></li>`;
      if (i.v == null && i.power) return `<li><span class="nm">${i.label}</span><span class="lv mono">power ${i.power.s}% of costs</span>
        <span class="why">The big energy cost here is electricity, not oil: ${escH(i.power.src)}. There is no oil-to-power-price link for this country, so no change is shown.</span></li>`;
      if (i.v == null) return `<li><span class="nm">${i.label}</span><span class="lv">no data</span>
        <span class="why">${i.why}. No sourced cost share yet, and Seb's sector model doesn't cover this industry${TR_GEO && TR_GEO[name] ? "" : " or this country"}.</span></li>`;'''
sub(OLD_RENDER, NEW_RENDER)
sub("        <span class=\"why\">Range ${pct(i.lo / 100, 1)} to ${pct(i.hi / 100, 1)}. Reaches costs ${i.lag}. Share: ${i.src}.</span></li>`;",
    "        <span class=\"why\">Range ${pct(i.lo / 100, 1)} to ${pct(i.hi / 100, 1)}.${i.lag ? ` Reaches costs ${i.lag}.` : \"\"} Share: ${i.src}.${i.sec ? ` Its own prices: ${secLine(i.sec)}` : \"\"}</span></li>`;")
# buyers without a cost share: air freight gets the chain's air-freight prices; food makers are marked indirect
sub('  for (const [mat, list] of Object.entries(BUYERS)) for (const row of list) {',
    '  for (const row of BUYERS.jet_fuel) if (row[0] === "Air freight and couriers") row[4] = { chain: "ind_pcu481112481112", text: "air freight prices in the US" };\n'
    '  for (const row of BUYERS.fertiliser) if (row[0] === "Food manufacturers") row[4] = { indirect: "Fertiliser is a farm cost: it reaches food makers through crop prices, and farmers get 11.8 cents of each US food dollar (USDA ERS Food Dollar Series, 2024), so its share in a food maker\'s costs is small and diluted" };\n'
    '  for (const [mat, list] of Object.entries(BUYERS)) for (const row of list) {')
sub('''    $("m-buyers").innerHTML = (BUYERS[m.id] || []).map(([ind, share, src, lag]) => {
      const c = share == null || !p ? null : share * p.mean / 100;''',
'''    $("m-buyers").innerHTML = (BUYERS[m.id] || []).map(([ind, share, src, lag, alt]) => {
      if (alt && alt.chain) {
        const e = chainEffect(alt.chain), cls = e.mean > 0.05 ? "hurt" : e.mean < -0.05 ? "gain" : "";
        return `<li><span class="nm">${escH(ind)}</span><span class="lv mono ${cls}">${pctP(e.mean)} prices</span>
        <span class="why">No sourced fuel share, so this is ${alt.text} after 12 months (Seb's chain, 90% range ${pctP(e.lo, 0)} to ${pctP(e.hi, 0)}). Reaches costs ${escH(lag)}.</span></li>`;
      }
      if (alt && alt.indirect) return `<li><span class="nm">${escH(ind)}</span><span class="lv">indirect</span>
        <span class="why">${escH(alt.indirect)}. Reaches costs ${escH(lag)}.</span></li>`;
      const c = share == null || !p ? null : share * p.mean / 100;''')
sub('<ul class="inds" id="c-inds"></ul>',
    '<ul class="inds" id="c-inds"></ul>\n          <p class="faint">Which industries are listed for a country is a hand-picked choice from the original page <i class="illus" title="Not from data: the list per country was chosen by hand">illustrative</i>. Cost shares: notes/industry/industry_exposure.csv.</p>')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
