"""World view, round 2: Edward's materials globe inside Hormuz Flow.
Flat map and 3D globe from one state; sector icons; materials data from ui/globe (notes/materials/);
detail panes only after a click or a search. Input v8.html (live 1792872645-13ac) -> hormuz-flow.html."""
import pathlib, subprocess

here = pathlib.Path(__file__).parent
G = here.parents[1] / "globe"   # ui/globe (Edward's materials globe)
s = (here / "v8.html").read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- libraries and data (bundled, offline)
vendor = (G / "vendor" / "globe.gl.min.js").read_text(encoding="utf-8")
data = "\n".join((G / "data" / f).read_text(encoding="utf-8").strip() for f in ("countries.js", "materials.js", "flags.js"))
for blob in (vendor, data):
    assert "</script" not in blob.lower()
BUNDLE = ("<script>/* globe.gl 2.41.4, MIT licence (c) 2019 Vasco Asturiano, bundled from ui/globe/vendor */\n" + vendor + "\n</script>\n"
          "<script>/* Materials globe data from ui/globe/data: Natural Earth 1:110m (public domain), notes/materials/ via "
          "experiments/globe_data.py, flag-icons 7.6.0 (MIT) */\n" + data + "\n</script>\n")
sub("<script>\n// World view: where Hormuz oil goes", BUNDLE + "<script>\n// World view: where Hormuz oil goes")

# ---------------------------------------------------------------- CSS
CSS = """
/* Materials layer: sector icons on the map, Flat or 3D, producers in blue and Gulf producers in amber. */
#globe3d { position: absolute; inset: 0; }
.viewseg { position: absolute; left: 10px; top: 10px; z-index: 2; }
.viewseg button { min-width: 52px; min-height: 36px; font-size: 13px; background: rgba(255,255,255,.94); }
.viewseg button[aria-pressed="true"] { border-color: var(--seen); color: var(--seen); background: #e3f0fa; }
.mrail { position: absolute; left: 128px; top: 10px; z-index: 2; display: flex; flex-wrap: wrap; gap: 6px; max-width: calc(100% - 190px); }
.mrail button { width: 64px; min-height: 58px; padding: 4px 2px; flex-direction: column; gap: 1px; background: rgba(255,255,255,.94); font-size: 11px; color: var(--muted); }
.mrail button svg { width: 20px; height: 20px; color: var(--text); }
.mrail button .d { font: 10.5px var(--mono); color: var(--faint); }
.mrail button[aria-pressed="true"] { border-color: var(--seen); background: #e3f0fa; color: var(--seen); }
.mrail button[aria-pressed="true"] svg { color: var(--seen); }
@media (max-width: 720px) { .mrail { left: 10px; top: 54px; max-width: calc(100% - 70px); } .mrail button { width: 56px; min-height: 52px; } }
#world .arc { fill: none; stroke-linecap: round; vector-effect: non-scaling-stroke; stroke-dasharray: 6 5; animation: oilflow 1.8s linear infinite; }
@media (prefers-reduced-motion: reduce) { #world .arc { animation: none; stroke-dasharray: none; } }
.flag { width: 18px; height: 13px; border-radius: 2px; object-fit: cover; box-shadow: 0 0 0 1px var(--line2); flex: none; vertical-align: -2px; }
.flag.none { display: inline-flex; align-items: center; justify-content: center; font: 8px var(--mono); background: var(--panel2); color: var(--faint); }
.psearch { display: flex; gap: 6px; }
.psearch input { flex: 1 1 auto; min-width: 0; font: inherit; min-height: 40px; padding: 0 12px; border: 1px solid var(--line2); border-radius: 8px; background: var(--panel2); color: var(--text); }
.psearch input:focus-visible { outline: 2px solid var(--oil); outline-offset: 2px; }
.mres { display: flex; flex-direction: column; gap: 4px; }
.mres button { justify-content: flex-start; gap: 8px; min-height: 40px; background: var(--panel); text-align: left; }
.mres button svg { color: var(--text); }
.mres .why { font-size: 11.5px; color: var(--faint); }
.mhead { display: flex; align-items: center; gap: 10px; }
.mhead .mi { width: 36px; height: 36px; border-radius: 9px; background: #e3f0fa; color: var(--seen); display: inline-flex; align-items: center; justify-content: center; flex: none; }
.mhead .mi svg { width: 20px; height: 20px; }
.mhead b { font-size: 16px; }
.mhead .grow { flex: 1 1 auto; min-width: 0; }
.pprice { font: 500 26px var(--mono); line-height: 1; }
.pbars { display: flex; flex-direction: column; gap: 2px; }
.pbars button { display: grid; grid-template-columns: minmax(0, 1fr) 90px 58px; gap: 8px; align-items: center; min-height: 32px; padding: 0 6px; background: transparent; border: 0; border-radius: 6px; font-size: 12.5px; text-align: left; }
.pbars button:hover, .pbars button[aria-current="true"] { background: var(--panel2); }
.pbars .cn { display: inline-flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.pbars .tk { height: 6px; border-radius: 3px; background: var(--panel2); position: relative; overflow: hidden; }
.pbars .tk span { position: absolute; inset: 0 auto 0 0; border-radius: 3px; }
.pbars .v { font: 12px var(--mono); text-align: right; }
.mseg button { min-width: 86px; min-height: 34px; font-size: 12.5px; }
.ichips { display: flex; flex-wrap: wrap; gap: 4px; }
.ichip { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border: 1px solid var(--line2); border-radius: 999px; font: 11.5px var(--mono); background: var(--panel); }
.ichip .dot { width: 8px; height: 8px; border-radius: 50%; }
.ichip.dom { border-style: dashed; }
.tmat { display: flex; flex-direction: column; gap: 6px; padding: 8px 0; border-top: 1px solid var(--line); }
.tmat .th { display: flex; align-items: center; gap: 8px; background: transparent; border: 0; min-height: 32px; padding: 0; justify-content: flex-start; text-align: left; }
.tmat .th svg { color: var(--seen); }
.tmat .th .rl { font: 11.5px var(--mono); color: var(--muted); }
.tmat .tl { display: flex; flex-direction: column; gap: 3px; }
.tmat .tl > span { font-size: 11px; color: var(--faint); letter-spacing: .4px; text-transform: uppercase; }
.ctitle .ib { width: 28px; min-height: 28px; }
.hsearch { position: relative; display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1 1 320px; max-width: 460px; padding: 0 10px; min-height: 40px; border: 1px solid var(--line2); border-radius: 10px; background: var(--panel); }
.hsearch > svg { color: var(--muted); }
.hsearch input { flex: 1 1 auto; min-width: 0; font: inherit; border: 0; background: transparent; color: var(--text); min-height: 38px; outline: none; }
.hsearch:focus-within { border-color: var(--text); box-shadow: 0 0 0 2px rgba(20,32,46,.12); }
.hsearch .mres { position: absolute; left: -1px; right: -1px; top: calc(100% + 6px); z-index: 6; padding: 6px; border: 1px solid var(--line2); border-radius: 10px; background: var(--panel); box-shadow: 0 12px 28px rgba(20,32,46,.16); }
.tools { flex: 1 1 auto; justify-content: flex-end; min-width: 0; flex-wrap: wrap; }
.cpop { position: absolute; z-index: 4; width: 260px; max-width: calc(100% - 20px); padding: 10px 12px; border-radius: 12px; background: rgba(255,255,255,.98); border: 1px solid var(--line2); box-shadow: 0 10px 28px rgba(20,32,46,.18); display: flex; flex-direction: column; gap: 8px; }
.cpop .ph { display: flex; align-items: center; gap: 8px; }
.cpop .ph b { font-size: 15px; flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cpop .ph .flag { width: 22px; height: 16px; }
.cpop .ph .ib { width: 28px; min-height: 28px; }
.cpop .pk { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.cpop .pk div { display: flex; flex-direction: column; gap: 2px; padding: 6px 8px; border-radius: 8px; background: var(--panel2); min-width: 0; }
.cpop .pk b { font: 500 16px var(--mono); }
.cpop .pk span { font-size: 10.5px; line-height: 1.25; color: var(--faint); }
.cpop .pl { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.4; }
.cpop .more { align-self: flex-start; min-height: 30px; padding: 0 10px; font-size: 12.5px; gap: 6px; background: transparent; }
.cpop .more svg { width: 14px; height: 14px; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

# ---------------------------------------------------------------- HTML: map overlays, product card, country card
SEARCH = '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>'
INFO_I = '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.5"/>'
X_I = '<path d="M6 6l12 12M18 6L6 18"/>'
sub('<svg id="world" role="img" aria-label="World map. Lines show oil leaving the Strait of Hormuz; country colour shows exposure to the oil shock. Click a country for detail."></svg>',
    '<svg id="world" role="img" aria-label="World map. Lines show oil leaving the Strait of Hormuz; country colour shows exposure to the oil shock. Click a country for detail."></svg>\n'
    '      <div id="globe3d" hidden aria-label="3D globe. Drag to turn, scroll to zoom, click a country for detail."></div>\n'
    '      <div class="seg viewseg" role="group" aria-label="Map style"><button type="button" data-wview="flat" aria-pressed="true">Flat</button><button type="button" data-wview="3d" aria-pressed="false">3D</button></div>\n'
    '      <nav class="mrail" id="mrail" aria-label="Materials"></nav>')
sub('<div class="ttl"><span>Exposure score</span>', '<div class="ttl"><span id="wttl">Exposure score</span>')

PCARD = f"""<section class="card" id="prod-card" hidden>
        <div class="row between">
          <span class="label"><svg viewBox="0 0 24 24" aria-hidden="true">{SEARCH}</svg> Product</span>
          <button type="button" class="ib" data-winfo="materials" aria-label="About the materials data"><svg viewBox="0 0 24 24" aria-hidden="true">{INFO_I}</svg></button>
        </div>
        <div id="mdetail" hidden>
          <div class="mhead"><span class="mi" id="m-icon"></span><span class="grow"><b id="m-name"></b><span class="sub" id="m-sub" style="display:block"></span></span>
            <button type="button" class="ib" id="m-close" aria-label="Close product details"><svg viewBox="0 0 24 24" aria-hidden="true">{X_I}</svg></button></div>
          <div class="row between" style="align-items:baseline;margin-top:8px"><b class="pprice" id="m-price">–</b><span class="sub">price in 12 months</span></div>
          <p class="faint" id="m-band"></p>
          <div class="seg mseg" role="group" aria-label="Who makes it or who ships it"><button type="button" data-mmode="production" aria-pressed="true">Made</button><button type="button" data-mmode="exports" aria-pressed="false">Shipped</button></div>
          <div class="pbars" id="m-bars"></div>
          <p class="sub" id="m-hormuz"></p>
          <span class="label" style="margin-top:4px">What it costs buyers</span>
          <ul class="inds" id="m-buyers"></ul>
        </div>
      </section>

      """
i = s.index("> The shock</span>")
a = s.rindex('<section class="card">', 0, i)
s = s[:a] + PCARD + s[a:]

# product search lives in the top bar, results drop down under it (World view only)
HSEARCH = f"""<div class="hsearch" id="hsearch" role="search">
        <svg viewBox="0 0 24 24" aria-hidden="true">{SEARCH}</svg>
        <label for="prod-q" class="sr">Search a product or material</label>
        <input id="prod-q" type="search" placeholder="Search a product: urea, kerosene, bauxite, plastic…" autocomplete="off" aria-controls="mres">
        <div class="mres" id="mres" hidden></div>
      </div>
      """
sub('      <label for="scenario" class="sr">Scenario</label>', '      ' + HSEARCH + '<label for="scenario" class="sr">Scenario</label>')

# a small pop-up on the map for the clicked country: the headline facts; the full analysis stays in the panel
CPOP = f"""<div class="cpop" id="cpop" role="dialog" aria-labelledby="cp-name" hidden>
        <div class="ph"><span id="cp-flag"></span><b id="cp-name"></b><span class="tag" id="cp-tag"></span>
          <button type="button" class="ib" id="cp-close" aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true">{X_I}</svg></button></div>
        <div class="pk" id="cp-kpis"></div>
        <p class="pl" id="cp-line"></p>
        <button type="button" class="more" id="cp-more">Full analysis in the panel <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
      </div>
      """
sub('      <div class="wtip" id="wtip" hidden></div>', '      ' + CPOP + '<div class="wtip" id="wtip" hidden></div>')

sub('<section class="card" id="country-card" aria-live="polite">', '<section class="card" id="country-card" aria-live="polite" hidden>')
sub('<div class="ctitle"><h2 id="c-name">–</h2><span class="tag" id="c-tag"></span></div>\n        <p class="sub" id="c-sub"></p>',
    f'<div class="ctitle"><h2 id="c-name">–</h2><span class="row"><span class="tag" id="c-tag"></span><button type="button" class="ib" id="c-close" aria-label="Close country details"><svg viewBox="0 0 24 24" aria-hidden="true">{X_I}</svg></button></span></div>\n'
    '        <p class="sub" id="c-sub"></p>\n'
    '        <div id="t-sec" hidden><span class="label">What it makes, where inputs come from, where it ships</span><div id="t-body"></div></div>')

# ---------------------------------------------------------------- JS: materials layer
sub('const st = { key: "aug2026", brent: 104, sel: "Japan", flow: 6.2 };',
    'const st = { key: "aug2026", brent: 104, sel: null, flow: 6.2, mat: null, mode: "production", wview: "flat", q: "", qOpen: false, pop: null };' + r'''

  // ------------------------------------------------------------ materials layer (Edward's materials globe)
  // Data: ui/globe/data (notes/materials/*.json via experiments/globe_data.py; search-result snippets, 24 Oct 2026).
  // Price lines: Seb's Bayesian pass-through (notes/macro-bayes-responses.csv), +10% row for rises, -10% for falls.
  const MAT = window.MATERIALS, CN = window.COUNTRIES, FLAGS = (window.FLAGS && window.FLAGS.flags) || {};
  const mats = Object.fromEntries(MAT.materials.map((m) => [m.id, m]));
  const isoOf = {}, nameOfIso = {}, where = {};
  for (const f of CN.features) { isoOf[f.properties.name] = f.properties.iso3; nameOfIso[f.properties.iso3] = f.properties.name; where[f.properties.iso3] = { lat: f.properties.lat, lng: f.properties.lng }; }
  for (const [k, p] of Object.entries(CN.points)) { if (!isoOf[p.name]) isoOf[p.name] = k; if (!nameOfIso[k]) nameOfIso[k] = p.name; where[k] = { lat: p.lat, lng: p.lng }; }
  if (!isoOf.Macedonia && isoOf["North Macedonia"]) isoOf.Macedonia = isoOf["North Macedonia"];
  const nmIso = (iso) => { const n = nameOfIso[iso] || iso; return n === "United States of America" ? "United States" : n; };
  const escH = (x) => String(x == null ? "" : x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const flagImg = (iso) => (FLAGS[iso] ? `<img class="flag" src="${FLAGS[iso]}" alt="">` : `<span class="flag none">${escH(iso)}</span>`);
  // Sector icons from Edward's globe
  const ICONS = {
    steel: '<path d="M5 4h14M5 20h14M12 4v16"/><path d="M8 4v2M16 4v2M8 18v2M16 18v2"/>',
    jet_fuel: '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/>',
    aluminium: '<path d="M7 4h10l-1 16H8z"/><path d="M7.4 8h9.2"/>',
    fertiliser: '<path d="M12 21v-8"/><path d="M12 13C12 8 8 6 4 6c0 4 3 7 8 7z"/><path d="M12 11c0-4 3-6 8-6 0 4-3 6-8 6z"/>',
    polyethylene: '<path d="M10 2h4v3l2 3v12a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8l2-3z"/><path d="M8 12h8"/>',
  };
  const icon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[k] || ""}</svg>`;
  const FIND = { steel: "steel iron ore coking coal scrap construction", jet_fuel: "jet fuel kerosene aviation atf jet a-1 crude airline",
    aluminium: "aluminium aluminum bauxite alumina can", fertiliser: "fertiliser fertilizer urea ammonia nitrogen natural gas farm",
    polyethylene: "plastic plastics polyethylene resin pe polymer packaging naphtha ethane" };
  const HORMUZ = { steel: "Indirect: bunker fuel for ore and coal freight, coal prices and gas-based ironmaking.",
    jet_fuel: "About 24% of seaborne jet fuel passed the strait in 2025 (Argus citing Kpler).",
    aluminium: "UAE and Bahrain smelters, about 8% of world output, were hit by strikes on 28 Mar 2026.",
    fertiliser: "The Gulf is 36% of world urea exports (IFPRI), and its shipments are largely halted.",
    polyethylene: "Gulf petrochemical exports, a large share of world polyethylene trade, pass the strait." };
  // Buyer industries: [industry, product's share of their costs (%), source, how fast it reaches costs]
  const BUYERS = {
    jet_fuel: [["Airlines", 31.4, "jet fuel 31.4% of airline costs (IATA 2026)", "within weeks, less hedges (about a third of 2026 fuel hedged)"],
               ["Air freight and couriers", null, "no sourced fuel share yet", "surcharges reset weekly to monthly"]],
    fertiliser: [["Farming", 40, "synthetic fertiliser 40% of variable farm costs (CIBC)", "next planting season; food prices over about 2 years"],
                 ["Food manufacturers", null, "no sourced share yet", "through crop prices, months to 2 years"]],
    polyethylene: [["Packaging", null, "no sourced resin share yet", "up to about 10 months; resin lags crude"]],
    aluminium: [["Packaging (cans)", null, "no sourced share yet", "months"], ["Automotive", null, "no sourced share yet", "months"]],
    steel: [["Construction", null, "no sourced share yet", "months, through freight and coal"], ["Automotive", null, "no sourced share yet", "months"]],
  };
  const VIA = { "Kuwait": "Ships via Hormuz", "Iraq": "Ships via Hormuz", "Qatar": "Ships via Hormuz", "Bahrain": "Ships via Hormuz", "Iran": "Mostly via Hormuz",
    "Saudi Arabia": "Partly via Hormuz", "United Arab Emirates": "Partly via Hormuz" };
  const tableOf = (item, mode) => (mode === "exports" ? (item.exports && item.exports.list) || [] : item.producers || []);
  const shareTxt = (r) => (r.share != null ? `${r.approx ? "≈" : ""}${(r.share * 100).toFixed(r.share < 0.1 ? 1 : 0)}%` : `${r.value}`);
  function weightsByName(mode = st.mode) {
    const out = {};
    if (st.mat) for (const r of tableOf(mats[st.mat], mode)) out[nameOfIso[r.iso3] || r.iso3] = r.w;
    return out;
  }
  function matShade(name) {
    const w = weightsByName(), v = w[name];
    if (!v) return "#e4e9ef";
    const max = Math.max(...Object.values(w), 0.01), f = 0.25 + 0.75 * Math.sqrt(v / max);
    return VIA[name] ? d3.interpolateLab("#f6dcb6", "#c26f12")(f) : d3.interpolateLab("#cfe0ee", "#1f6aa3")(f);
  }
  function fillFor(name) { return st.mat ? matShade(name) : color(calc(name).score); }
  // 12-month price change (%) for the current Brent vs pre-war, with the 90% interval of the average effect
  function priceMoveM(m) {
    const oil = m && m.oil;
    if (!oil || !oil.up) return null;
    const x = st.brent / BRENT0 - 1;
    const [row, base] = x >= 0 ? [oil.up, 1.1] : [oil.down, 0.9];
    const f = Math.log(1 + x) / Math.log(base), a = row[1] * f, b = row[2] * f;
    return { mean: row[0] * f, lo: Math.min(a, b), hi: Math.max(a, b) };
  }
  function shockRangeM(m) {
    const d = m && m.oil && m.oil.disruption, x = st.brent / BRENT0 - 1;
    if (!d || x <= 0) return null;
    const f = Math.log(1 + x) / Math.log(1.1);
    return { lo: d.lo * f, hi: d.hi * f };
  }
  const pctP = (v, dp = 1) => `${v > 0.05 ? "+" : v < -0.05 ? "−" : ""}${Math.abs(v).toFixed(dp)}%`;
  // Arcs: Made = ingredients into the chosen country; Shipped = sourced trade flows of the material and its ingredients
  function arcsFor() {
    const m = mats[st.mat], iso = st.sel ? isoOf[st.sel] : null, out = [];
    if (!m) return out;
    const add = (from, to, col, weight, label) => { if (from !== to && where[from] && where[to]) out.push({ from, to, color: col, weight, label }); };
    if (st.mode === "production") {
      if (iso) for (const l of m.links.filter((x) => x.to === iso)) {
        const inp = MAT.inputs[l.input];
        add(l.from, l.to, inp ? inp.color : "#8a96a3", l.share, `${inp ? inp.name : l.input}: ${nmIso(l.from)} → ${nmIso(l.to)} ${Math.round(l.share * 100)}%`);
      }
    } else {
      const flows = [...(m.flows || []), ...m.inputs.flatMap((id) => (MAT.inputs[id] && MAT.inputs[id].flows) || [])].filter((f) => !iso || f.from === iso || f.to === iso);
      const maxv = Math.max(...flows.map((f) => f.value || 0), 1);
      for (const f of flows.slice(0, 16)) add(f.from, f.to, "#1f7fc0", f.value != null ? f.value / maxv : f.share_of_importer || f.share_of_exporter || 0.1,
        `${nmIso(f.from)} → ${nmIso(f.to)}${f.value != null ? ` · ${f.value}` : ""}${f.share_of_importer != null ? ` · ${Math.round(f.share_of_importer * 100)}% of its imports` : ""}`);
    }
    return out;
  }
  function tipHtml(name) {
    if (st.mat) {
      const m = mats[st.mat], iso = isoOf[name], r = tableOf(m, st.mode).find((x) => x.iso3 === iso);
      return `<b>${iso ? flagImg(iso) + " " : ""}${escH(name === "United States of America" ? "United States" : name)}</b><span>${escH(m.short || m.name)} ${st.mode === "exports" ? "shipped" : "made"}: <span class="mono">${r ? shareTxt(r) : "not listed"}</span></span>${VIA[name] ? `<span>${VIA[name]}</span>` : ""}`;
    }
    const k = calc(name);
    return `<b>${escH(name)}</b><span>Exposure <span class="mono">${fmtS(k.score)}</span></span><span>Fuel cost <span class="mono">${pct(k.fuel)}</span></span>`;
  }

  // ------------------------------------------------------------ 3D globe (built the first time 3D is chosen)
  let G3 = null;
  function initGlobe() {
    if (G3 || typeof Globe === "undefined") return;
    G3 = Globe()($("globe3d"))
      .backgroundColor("#eef3f8").showAtmosphere(true).atmosphereColor("#8fbde0").atmosphereAltitude(0.15)
      .polygonsData(CN.features).polygonSideColor(() => "rgba(90,110,130,0.25)").polygonStrokeColor(() => "rgba(255,255,255,0.85)")
      .polygonsTransitionDuration(500).polygonLabel((f) => `<div class="wtip" style="position:static">${tipHtml(f.properties.name)}</div>`)
      .onPolygonClick((f) => select(f.properties.name))
      .pointLabel((p) => `<div class="wtip" style="position:static">${p.hz ? "<b>Strait of Hormuz</b>" : tipHtml(p.name)}</div>`)
      .onPointClick((p) => { if (!p.hz) select(p.name); })
      .arcDashLength(0.45).arcDashGap(0.25).arcAltitudeAutoScale(0.45).arcDashAnimateTime(2200);
    G3.globeMaterial().color.set("#cfe0ee");
    G3.controls().autoRotate = false;
    G3.pointOfView({ lat: 24, lng: 58, altitude: 2.2 });
    sizeGlobe();
  }
  function sizeGlobe() { if (!G3) return; const el = $("globe3d"); if (el.clientWidth) G3.width(el.clientWidth).height(el.clientHeight); }
  function paint3d() {
    if (!G3 || st.wview !== "3d") return;
    const s3 = st.mat ? weightsByName() : {}, max = Math.max(...Object.values(s3), 0.01);
    G3.polygonCapColor((f) => (f.properties.name === st.sel ? "#ffd89a" : fillFor(f.properties.name)))
      .polygonAltitude((f) => 0.006 + (s3[f.properties.name] ? 0.1 * Math.sqrt(s3[f.properties.name] / max) : 0) + (f.properties.name === st.sel ? 0.02 : 0));
    const pts = [{ hz: true, name: "Strait of Hormuz", lat: 26.5, lng: 56.4, alt: 0.02, r: 0.45, color: "#c26f12" }];
    for (const p of Object.values(CN.points)) if (C[p.name] || s3[p.name]) pts.push({ name: p.name, lat: p.lat, lng: p.lng, alt: 0.02 + (s3[p.name] ? 0.1 * Math.sqrt(s3[p.name] / max) : 0), r: 0.5, color: fillFor(p.name) });
    G3.pointsData(pts).pointColor((d) => d.color).pointAltitude((d) => d.alt).pointRadius((d) => d.r);
    G3.arcsData(arcsFor().map((a) => ({ startLat: where[a.from].lat, startLng: where[a.from].lng, endLat: where[a.to].lat, endLng: where[a.to].lng, color: a.color, weight: a.weight, label: a.label })))
      .arcColor((d) => [d.color + "55", d.color]).arcStroke((d) => 0.25 + 1.2 * Math.sqrt(d.weight || 0.1)).arcLabel((d) => escH(d.label));
    const w = st.sel && isoOf[st.sel] && where[isoOf[st.sel]];
    G3.ringsData(w ? [w] : [{ lat: 26.5, lng: 56.4 }]).ringColor(() => (t) => `rgba(194,111,18,${1 - t})`).ringMaxRadius(w ? 5 : 3).ringPropagationSpeed(2).ringRepeatPeriod(1200);
  }
  function setWView(v) {
    st.wview = v;
    document.querySelectorAll("[data-wview]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.wview === v)));
    $("world").style.display = v === "3d" ? "none" : "";
    $("globe3d").hidden = v !== "3d";
    if (v === "3d") { initGlobe(); sizeGlobe(); if (G3 && G3.resumeAnimation) G3.resumeAnimation(); paint3d(); }
    else { if (G3 && G3.pauseAnimation) G3.pauseAnimation(); layout(); }
    try { localStorage.setItem("hz-wview", v); } catch (e) {}
  }
  function zoom3d(f) { if (!G3) return; const p = G3.pointOfView(); G3.pointOfView({ altitude: Math.min(4.5, Math.max(0.6, p.altitude * f)) }, 300); }
''')

# map colour, legend, arcs, 3D in paint()
sub('    ctryPaths.attr("fill", (c) => color(calc(c.properties.name).score)).classed("sel", (c) => c.properties.name === st.sel);\n'
    '    dotEls.attr("fill", ([n]) => color(calc(n).score))',
    '    ctryPaths.attr("fill", (c) => fillFor(c.properties.name)).classed("sel", (c) => c.properties.name === st.sel);\n'
    '    dotEls.attr("fill", ([n]) => fillFor(n))')
sub('    $("wflowkey").textContent = `Hormuz oil flow now · ${(f * 100).toFixed(0)}% of pre-war (faint)`;\n  }',
    '''    $("wflowkey").textContent = st.mat ? (st.sel ? (st.mode === "exports" ? "Trade flows to and from the chosen country" : "Arcs: where its ingredients come from") : "Click a country for its supplier and trade arcs")
      : `Hormuz oil flow now · ${(f * 100).toFixed(0)}% of pre-war (faint)`;
    const m = mats[st.mat];
    $("wttl").textContent = m ? `${m.name}: ${st.mode === "exports" ? "who ships it" : "who makes it"}` : "Exposure score";
    if (m) {
      $("wgrad").style.background = "linear-gradient(90deg, #cfe0ee, #1f6aa3 55%, #f6dcb6 55%, #c26f12)";
      $("wticks").innerHTML = '<span style="left:0;transform:none">smaller</span><span style="left:30%">larger</span><span style="left:56%;transform:none">Gulf: via Hormuz</span>';
    } else { $("wgrad").style.background = GRAD0; $("wticks").innerHTML = TICKS0; }
    drawFlatArcs();
    paint3d();
  }
  function drawFlatArcs() {
    const arcs = st.mat ? arcsFor() : [];
    gArc.selectAll("path").data(arcs).join("path").attr("class", "arc")
      .attr("d", (a) => gpath({ type: "LineString", coordinates: [[where[a.from].lng, where[a.from].lat], [where[a.to].lng, where[a.to].lat]] }))
      .attr("stroke", (a) => a.color).attr("stroke-width", (a) => 1 + 2.6 * Math.sqrt(a.weight || 0.1)).attr("opacity", 0.9)
      .selectAll("title").data((a) => [a]).join("title").text((a) => a.label);
    gR.style("display", st.mat ? "none" : null);
    gRB.style("display", st.mat ? "none" : null);
  }''')
sub('  const gRB = root.append("g"), gR = root.append("g"), gP = root.append("g"), gH = root.append("g");',
    '  const gRB = root.append("g"), gR = root.append("g"), gArc = root.append("g"), gP = root.append("g"), gH = root.append("g");')
sub('  const LMIN = -40, LMAX = 65;', '  const LMIN = -40, LMAX = 65;\n  let GRAD0 = "", TICKS0 = "";')
sub('`<span style="left:${(v - LMIN) / (LMAX - LMIN) * 100}%;${i === 0 ? "transform:none" : i === a.length - 1 ? "transform:translateX(-100%)" : ""}">${t}</span>`).join("");',
    '`<span style="left:${(v - LMIN) / (LMAX - LMIN) * 100}%;${i === 0 ? "transform:none" : i === a.length - 1 ? "transform:translateX(-100%)" : ""}">${t}</span>`).join("");\n'
    '  GRAD0 = $("wgrad").style.background; TICKS0 = $("wticks").innerHTML;')
# layout redraws arcs; the globe follows the map's size
sub('  function layout() {\n    const box = svgEl.node().getBoundingClientRect();',
    '  function layout() {\n    sizeGlobe();\n    const box = svgEl.node().getBoundingClientRect();')
sub('    gP.raise(); dotEls.raise(); gH.raise();\n    rescale();', '    gP.raise(); dotEls.raise(); gH.raise();\n    drawFlatArcs();\n    rescale();')
# zoom buttons drive whichever view is showing
sub('  $("wzin").addEventListener("click", () => svgEl.transition().duration(300).call(zoom.scaleBy, 1.6));\n'
    '  $("wzout").addEventListener("click", () => svgEl.transition().duration(300).call(zoom.scaleBy, 1 / 1.6));\n'
    '  $("wzreset").addEventListener("click", () => svgEl.transition().duration(400).call(zoom.transform, d3.zoomIdentity));',
    '  $("wzin").addEventListener("click", () => (st.wview === "3d" ? zoom3d(0.7) : svgEl.transition().duration(300).call(zoom.scaleBy, 1.6)));\n'
    '  $("wzout").addEventListener("click", () => (st.wview === "3d" ? zoom3d(1.4) : svgEl.transition().duration(300).call(zoom.scaleBy, 1 / 1.6)));\n'
    '  $("wzreset").addEventListener("click", () => (st.wview === "3d" ? G3 && G3.pointOfView({ lat: 24, lng: 58, altitude: 2.2 }, 600) : svgEl.transition().duration(400).call(zoom.transform, d3.zoomIdentity)));')
# flat tooltip uses the same words as the globe
sub('  function tip(e, name) {\n    const k = calc(name), t = $("wtip");',
    '  function tip(e, name) {\n    const k = calc(name), t = $("wtip");\n'
    '    if (st.mat) {\n'
    '      t.innerHTML = tipHtml(name); t.hidden = false;\n'
    '      const r2 = svgEl.node().getBoundingClientRect();\n'
    '      let x = e.clientX - r2.left + 14, y = e.clientY - r2.top + 14;\n'
    '      if (x + t.offsetWidth > r2.width - 8) x = e.clientX - r2.left - t.offsetWidth - 14;\n'
    '      t.style.left = `${x}px`; t.style.top = `${y}px`;\n'
    '      return;\n'
    '    }')

# selecting: click a country to open its pane, click it again (or ×) to close
sub("  function select(name) {\n    st.sel = name;\n    paint();\n    renderCountry();\n    renderRank();\n  }",
    "  // anchor = [lng, lat] the pop-up points at: where you clicked, or the country's centre\n"
    "  function select(name, anchor) {\n"
    "    st.sel = name && name === st.sel ? null : name;\n"
    "    const w = st.sel && isoOf[st.sel] && where[isoOf[st.sel]];\n"
    "    st.pop = st.sel ? anchor || (w ? [w.lng, w.lat] : null) : null;\n"
    "    if (w && G3 && st.wview === \"3d\" && !anchor) G3.pointOfView({ lat: w.lat, lng: w.lng, altitude: 2 }, 800);\n"
    "    paint();\n    renderCountry();\n    renderRank();\n    renderMat();\n  }")
# clicks on the map pass where they landed, so the pop-up opens there
sub('.attr("tabindex", -1).on("click", (e, f) => select(f.properties.name))',
    '.attr("tabindex", -1).on("click", (e, f) => select(f.properties.name, flatGeo(e)))')
sub('.on("click", (e, [n]) => select(n))', '.on("click", (e, [n]) => select(n, flatGeo(e)))')
sub('      .onPolygonClick((f) => select(f.properties.name))', '      .onPolygonClick((f, ev, c) => select(f.properties.name, c ? [c.lng, c.lat] : null))')
sub('      .onPointClick((p) => { if (!p.hz) select(p.name); })', '      .onPointClick((p) => { if (!p.hz) select(p.name, [p.lng, p.lat]); })\n      .onZoom(() => placePop())')
sub('const zoom = d3.zoom().scaleExtent([1, 10]).on("zoom", (e) => { cur = e.transform; root.attr("transform", cur); rescale(); });',
    'const zoom = d3.zoom().scaleExtent([1, 10]).on("zoom", (e) => { cur = e.transform; root.attr("transform", cur); rescale(); placePop(); });')
sub('    $("view-seg").hidden = m !== "strait";', '    $("view-seg").hidden = m !== "strait";\n    $("hsearch").hidden = m !== "world";')
sub("  function renderCountry() {\n    const name = st.sel, k = calc(name), d = k.d;",
    "  function renderCountry() {\n    $(\"country-card\").hidden = !st.sel;\n    if (!st.sel) return;\n    const name = st.sel, k = calc(name), d = k.d;")
sub("\n  }\n\n  function renderChart(name) {", "\n    renderTrade();\n  }\n\n  function renderChart(name) {")
sub("  function update() { renderShock(); paint(); renderCountry(); renderRank(); }",
    "  function update() { renderShock(); paint(); renderCountry(); renderRank(); renderMat(); }")

RENDER = r'''
  // ------------------------------------------------------------ materials: rail, search, product pane, country trade
  // the clicked point on the flat map, as [lng, lat]
  function flatGeo(e) {
    const r = svgEl.node().getBoundingClientRect();
    const [x, y] = cur.invert([e.clientX - r.left, e.clientY - r.top]);
    return proj.invert([x, y]);
  }
  // pop-up for the selected country: headline facts only; the panel holds the full analysis
  function renderPop() {
    const pop = $("cpop");
    if (!st.sel) { pop.hidden = true; return; }
    const name = st.sel, iso = isoOf[name], k = calc(name), m = mats[st.mat];
    $("cp-flag").innerHTML = iso ? flagImg(iso) : "";
    $("cp-name").textContent = name === "United States of America" ? "United States" : name;
    const tag = VIA[name] ? VIA[name] : k.kind === "gulf" ? "Gulf producer" : k.kind === "exp" ? "Net exporter" : "Net importer";
    $("cp-tag").textContent = tag;
    $("cp-tag").className = "tag" + (VIA[name] || k.kind === "gulf" ? " gulf" : k.kind === "exp" ? " exp" : "");
    const kpi = (v, label, cls = "") => `<div><b class="${cls}">${v}</b><span>${label}</span></div>`;
    let kpis, line;
    if (m) {
      const made = tableOf(m, "production"), ship = tableOf(m, "exports");
      const mi = made.findIndex((r) => r.iso3 === iso), si = ship.findIndex((r) => r.iso3 === iso);
      const into = m.links.filter((l) => l.to === iso && l.from !== iso).sort((a, b) => b.share - a.share)[0];
      kpis = kpi(mi >= 0 ? shareTxt(made[mi]) : "–", mi >= 0 ? `made, #${mi + 1}` : "not a listed maker")
        + kpi(si >= 0 ? shareTxt(ship[si]) : "–", si >= 0 ? `shipped, #${si + 1}` : "not a listed exporter")
        + kpi(fmtS(k.score), "exposure score", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "");
      line = into ? `${escH(m.name)}: biggest outside input is ${escH((MAT.inputs[into.input] || {}).name || into.input)} from ${flagImg(into.from)} ${escH(nmIso(into.from))}, ${Math.round(into.share * 100)}%.`
        : `${escH(m.name)}: no sourced supplier split for ${escH(nmIso(iso) || name)}.`;
    } else {
      kpis = kpi(fmtS(k.score), "exposure score", k.score > 0.5 ? "hurt" : k.score < -0.5 ? "gain" : "")
        + kpi(pct(k.fuel), "fuel cost vs pre-war", k.fuel > 0.005 ? "hurt" : k.fuel < -0.005 ? "gain" : "")
        + kpi(k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–", "of its oil via Hormuz");
      line = k.kind === "gulf" ? `About ${Math.round(k.d.gulf * 100)}% of its exports must pass the strait.` : k.kind === "exp" ? "Sells oil abroad, so a higher price brings in revenue." : "Pick a product above to see what it makes and trades.";
    }
    $("cp-kpis").innerHTML = kpis;
    $("cp-line").innerHTML = line;
    pop.hidden = false;
    placePop();
  }
  function placePop() {
    const pop = $("cpop");
    if (pop.hidden || !st.pop) return;
    const wrap = pop.parentElement, W = wrap.clientWidth, H = wrap.clientHeight;
    let xy = null;
    if (st.wview === "3d") { if (G3) { const c = G3.getScreenCoords(st.pop[1], st.pop[0], 0.02); xy = c ? [c.x, c.y] : null; } }
    else { const p = proj(st.pop); if (p) xy = [cur.applyX(p[0]), cur.applyY(p[1])]; }
    if (!xy || !isFinite(xy[0])) xy = [W / 2, H / 2];
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = xy[0] + 16, top = xy[1] - ph / 2;
    if (left + pw > W - 56) left = xy[0] - pw - 16;
    left = Math.min(Math.max(8, left), W - pw - 8);
    top = Math.min(Math.max(64, top), H - ph - 8);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
  }
  $("cp-close").addEventListener("click", () => select(st.sel));
  $("cp-more").addEventListener("click", () => { const c = $("country-card"); c.scrollIntoView({ behavior: "smooth", block: "start" }); c.setAttribute("tabindex", "-1"); c.focus({ preventScroll: true }); });
  function pickMat(id) {
    st.mat = id;
    st.qOpen = false;
    if (id && G3 && st.wview === "3d" && !st.sel) {
      const top = tableOf(mats[id], st.mode)[0], w = top && where[top.iso3];
      if (w) G3.pointOfView({ lat: Math.max(-40, Math.min(55, w.lat)), lng: w.lng, altitude: 2.3 }, 900);
    }
    update();
  }
  function renderMat() {
    $("mrail").innerHTML = MAT.materials.map((m) => {
      const p = priceMoveM(m);
      return `<button type="button" data-mat="${m.id}" aria-pressed="${m.id === st.mat}" title="${escH(m.name)}">${icon(m.id)}<span>${escH(m.short || m.name)}</span><span class="d">${p ? pctP(p.mean, 0) : "?"}</span></button>`;
    }).join("");
    $("mrail").querySelectorAll("[data-mat]").forEach((b) => b.addEventListener("click", () => pickMat(b.dataset.mat === st.mat ? null : b.dataset.mat)));
    const q = st.q.trim().toLowerCase();
    const hits = q ? MAT.materials.filter((m) => FIND[m.id].includes(q) || m.name.toLowerCase().includes(q) || m.inputs.some((id) => MAT.inputs[id] && MAT.inputs[id].name.toLowerCase().includes(q))) : [];
    $("mres").hidden = !q || !st.qOpen || (hits.length === 1 && hits[0].id === st.mat);
    $("mres").innerHTML = hits.length ? hits.map((m) => {
      const via = m.inputs.map((id) => MAT.inputs[id]).find((i) => i && i.name.toLowerCase().includes(q));
      return `<button type="button" data-pick="${m.id}">${icon(m.id)}<span><b>${escH(m.name)}</b><span class="why" style="display:block">${via ? `ingredient: ${escH(via.name)}` : "material"}</span></span></button>`;
    }).join("") : '<p class="faint">No match. This version covers steel, jet fuel, aluminium, fertiliser and plastic, with their ingredients.</p>';
    $("mres").querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => pickMat(b.dataset.pick)));
    const m = mats[st.mat];
    $("mdetail").hidden = !m;
    $("prod-card").hidden = !m;
    renderPop();
    if (!m) return;
    $("m-icon").innerHTML = icon(m.id);
    $("m-name").textContent = m.name;
    $("m-sub").textContent = `${tableOf(m, "production").length} producers, ${tableOf(m, "exports").length} exporters listed · ${m.unit}, ${m.year}`;
    const p = priceMoveM(m), d = shockRangeM(m);
    $("m-price").textContent = p ? pctP(p.mean) : "?";
    $("m-price").className = "pprice " + (p ? (p.mean > 0.05 ? "hurt" : p.mean < -0.05 ? "gain" : "") : "");
    $("m-band").textContent = p ? `Brent $${st.brent} vs $${BRENT0} pre-war. Average-effect band ${pctP(p.lo)} to ${pctP(p.hi)}; single moves vary more.${d ? ` Past supply shocks: ${pctP(d.lo)} to ${pctP(d.hi)}.` : ""} ${m.oil.series}.`
      : `No fitted oil link yet${m.oil && m.oil.note ? ` (${m.oil.note})` : ""}.`;
    document.querySelectorAll("[data-mmode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mmode === st.mode)));
    const rows = tableOf(m, st.mode), max = Math.max(...rows.map((r) => r.w), 0.01);
    $("m-bars").innerHTML = rows.length ? rows.slice(0, 8).map((r) => {
      const n = nameOfIso[r.iso3] || r.iso3;
      return `<button type="button" data-c="${escH(n)}" aria-current="${n === st.sel}"><span class="cn">${flagImg(r.iso3)}${escH(nmIso(r.iso3))}</span>
        <span class="tk"><span style="width:${r.w / max * 100}%;background:${VIA[n] ? "#c26f12" : "#1f6aa3"}"></span></span><span class="v">${shareTxt(r)}</span></button>`;
    }).join("") : `<p class="faint">No ${st.mode === "exports" ? "export" : "production"} table yet.</p>`;
    $("m-bars").querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => select(b.dataset.c)));
    $("m-hormuz").textContent = `Hormuz: ${HORMUZ[m.id] || ""}`;
    $("m-buyers").innerHTML = (BUYERS[m.id] || []).map(([ind, share, src, lag]) => {
      const c = share == null || !p ? null : share * p.mean / 100;
      const cls = c == null ? "" : c > 0.05 ? "hurt" : c < -0.05 ? "gain" : "";
      return `<li><span class="nm">${escH(ind)}</span><span class="lv mono ${cls}">${c == null ? "no data" : pctP(c) + " costs"}</span>
        <span class="why">${c == null ? `${escH(src)}.` : `${escH(src)} × ${pctP(p.mean)} price.`} Reaches costs ${escH(lag)}.</span></li>`;
    }).join("");
  }
  // Everything the materials data holds on one country (Edward's country sheet, compacted)
  function renderTrade() {
    const iso = isoOf[st.sel];
    const blocks = [];
    if (iso) for (const m of MAT.materials) {
      const roles = ["production", "exports"].map((mode) => { const rows = tableOf(m, mode), i = rows.findIndex((r) => r.iso3 === iso); return i < 0 ? null : `${mode === "exports" ? "Shipped" : "Made"} ${shareTxt(rows[i])} (#${i + 1})`; }).filter(Boolean);
      const into = m.links.filter((l) => l.to === iso).sort((a, b) => b.share - a.share);
      const supplies = m.links.filter((l) => l.from === iso && l.to !== iso);
      const flows = [...(m.flows || []), ...m.inputs.flatMap((id) => (MAT.inputs[id] && MAT.inputs[id].flows) || [])].filter((f) => f.from === iso || f.to === iso);
      if (!roles.length && !into.length && !supplies.length && !flows.length) continue;
      const chip = (l, side) => { const inp = MAT.inputs[l.input], o = side === "from" ? l.from : l.to;
        return `<span class="ichip ${o === iso ? "dom" : ""}" title="${escH(l.basis || "")} · ${l.year || ""}"><span class="dot" style="background:${inp ? inp.color : "#8a96a3"}"></span>${flagImg(o)}${escH(inp ? inp.name : l.input)} ${Math.round(l.share * 100)}%</span>`; };
      blocks.push(`<div class="tmat"><button type="button" class="th" data-goto="${m.id}" title="Show ${escH(m.name)} on the map">${icon(m.id)}<b>${escH(m.name)}</b><span class="rl">${roles.join(" · ") || "not a listed producer"}</span></button>
        ${into.length ? `<div class="tl"><span>Inputs come from</span><div class="ichips">${into.slice(0, 8).map((l) => chip(l, "from")).join("")}</div></div>` : ""}
        ${supplies.length ? `<div class="tl"><span>Supplies inputs to</span><div class="ichips">${supplies.slice(0, 8).map((l) => chip(l, "to")).join("")}</div></div>` : ""}
        ${flows.length ? `<div class="tl"><span>Exports and imports</span><div class="ichips">${flows.slice(0, 8).map((f) => `<span class="ichip">${flagImg(f.from)}→${flagImg(f.to)}${f.value != null ? ` ${escH(f.value)}` : ""}</span>`).join("")}</div></div>` : ""}
      </div>`);
    }
    $("t-sec").hidden = false;
    $("t-body").innerHTML = blocks.length ? blocks.join("") : `<p class="faint">${escH(st.sel)} isn't in the sourced materials tables yet.</p>`;
    $("t-body").querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => pickMat(b.dataset.goto)));
  }
  $("prod-q").addEventListener("keydown", (e) => { if (e.key === "Escape") { st.qOpen = false; renderMat(); } });
  $("prod-q").addEventListener("focus", () => { if (st.q) { st.qOpen = true; renderMat(); } });
  document.addEventListener("pointerdown", (e) => { if (st.qOpen && !$("hsearch").contains(e.target)) { st.qOpen = false; renderMat(); } });
  $("prod-q").addEventListener("input", (e) => {
    st.qOpen = true;
    st.q = e.target.value;
    const q = st.q.trim().toLowerCase();
    const hits = q ? MAT.materials.filter((m) => FIND[m.id].includes(q) || m.name.toLowerCase().includes(q)) : [];
    if (hits.length === 1 && hits[0].id !== st.mat) pickMat(hits[0].id); else renderMat();
  });
  $("m-close").addEventListener("click", () => { st.q = ""; $("prod-q").value = ""; pickMat(null); });
  $("c-close").addEventListener("click", () => select(st.sel));
  document.querySelectorAll("[data-mmode]").forEach((b) => b.addEventListener("click", () => { st.mode = b.dataset.mmode; update(); }));
  document.querySelectorAll("[data-wview]").forEach((b) => b.addEventListener("click", () => setWView(b.dataset.wview)));
'''
sub("\n  // ------------------------------------------------------------ info sheets\n  const WINFO = {", RENDER + "\n  // ------------------------------------------------------------ info sheets\n  const WINFO = {")

WINFO_M = r'''    materials: { title: "Products, materials and who makes them", html: `<p>Pick a sector icon on the map or search (try "urea", "kerosene", "bauxite" or "plastic"). The map, Flat or 3D, then shows who makes it, or who ships it: blue for producers, darker for more, amber for Gulf producers whose exports pass the strait. Click a country for what it makes, where its inputs come from and where it ships; click it again to close.</p>
      <ul><li><b>Data:</b> Edward's materials globe (<code>ui/globe</code>, from <code>notes/materials/</code>), collected on ${MAT.generated} from search-result snippets of the cited pages. Check figures at source before quoting.</li>
      <li><b>Price, 12 months:</b> Seb's Bayesian pass-through model (<code>notes/macro-bayes-responses.csv</code>), using the +10% response for rises and the −10% one for falls, scaled to the Brent setting. The band is the 90% interval of the average effect only; single moves vary more. Steel and aluminium have no fitted link yet (OXH-5).</li>
      <li><b>What it costs buyers:</b> the product's share of a buyer industry's costs × its price change. Shares are sourced for airlines (IATA) and farming (CIBC); others show "no data".</li>
      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT), flag-icons 7.6.0 (MIT), Natural Earth 1:110m (public domain). Nothing here is live.</li></ul>` },
'''
sub("  const WINFO = {\n", "  const WINFO = {\n" + WINFO_M)

# remember the map style; open in 3D if that was the last choice
sub('  setMode(mode === "strait" ? "strait" : "world");\n  loadScenario($("scenario").value || "aug2026");\n  layout();',
    '  setMode(mode === "strait" ? "strait" : "world");\n  loadScenario($("scenario").value || "aug2026");\n  layout();\n'
    '  let wv = "flat";\n  try { wv = localStorage.getItem("hz-wview") || "flat"; } catch (e) {}\n  if (wv === "3d") setWView("3d");')

(here / "hormuz-flow.html").write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
