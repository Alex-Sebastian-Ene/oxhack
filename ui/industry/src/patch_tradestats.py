# Runs after patch_iea.py on hormuz-flow.html.
# Exports and imports for every country on the map, at the top of the country card's Trade tab (below the
# product's own block when a product is picked):
# - exports and imports of goods and services in US$ and as % of GDP, and the balance when both are the same year
# - goods exports and imports, and fuel's share of each
# - the five largest partners for goods exports and imports; a partner on the map opens its own card
# Every number shows its year, its indicator code on hover, and the source line says when it was collected.
# Countries the sources don't cover say so. Numbers: notes/trade-stats.json (experiments/trade_stats.py: World
# Bank WDI and UN Comtrade), read at build time.
import json, pathlib, re, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- data: compacted, every map country present
data = json.loads((root / "notes" / "trade-stats.json").read_text(encoding="utf-8"))
geo = s[s.index("window.COUNTRIES = "):]
on_map = set(re.findall(r'"iso3":"([^"]+)"', geo[:geo.index("\n")]))
assert on_map == set(data["countries"]), f"map and notes/trade-stats.json differ: {sorted(on_map ^ set(data['countries']))}"
IND = data["indicators"]
C = {}
for iso, c in data["countries"].items():
    for k, v in c["stats"].items():  # one collection date per indicator, so the source line can give it once
        assert v["indicator"] == IND[k]["code"] and v["collected"] == IND[k]["collected"], (iso, k)
    e = {"s": {k: [round(v["value"]) if abs(v["value"]) > 1e5 else round(v["value"], 2), v["year"]] for k, v in c["stats"].items()}} if c["stats"] else {}
    if c["partners"]:
        e["p"] = {f: [x["year"], round(x["total"]), x["collected"],
                         [[t["iso3"] or "", t["name"], t["share"], round(t["value"]), int(t["on_map"])] for t in x["top"]]]
                  for f, x in c["partners"].items()}
    if c.get("too_old"):
        e["o"] = c["too_old"]
    if "note" in c:
        e["note"] = c["note"]
    C[iso] = e
TRADE = {"ind": {k: {f: v[f] for f in ("code", "name", "collected")} for k, v in IND.items()},
         "wdi": {f: data["sources"]["wdi"][f] for f in ("name", "updated")}, "c": C}
TRADE_JS = (
    "  // Exports and imports for every map country (notes/trade-stats.json, experiments/trade_stats.py). c[iso3]:\n"
    "  //  s: World Bank WDI figures by indicator, [value, year] (each country's latest year)\n"
    "  //  o: indicators whose latest figure is more than 10 years old (not shown), by year\n"
    "  //  p: UN Comtrade goods partners by flow, [year, total with the world, collected, [[iso3, name, share, value, on map]]]\n"
    "  //  note: why there are no figures\n"
    f"  const TRADE = {json.dumps(TRADE, ensure_ascii=False, separators=(',', ':')).replace('</', '<' + chr(92) + '/')};\n"
)

# ---------------------------------------------------------------- markup: its own block in the Trade tab
sub('        <div id="t-sec" hidden>',
    '        <div id="x-sec"><span class="label">Exports and imports <i class="x-cached" id="x-cached" hidden></i></span><div id="x-body"></div></div>\n'
    '        <div id="t-sec" hidden>')
sub('pane("trade", [$("t-sec")])', 'pane("trade", [$("x-sec"), $("t-sec")])')

JS = TRADE_JS + r'''  const xUsd = (v) => { const a = Math.abs(v);
    return `$${a >= 1e12 ? (a / 1e12).toFixed(2) + " trillion" : a >= 1e9 ? (a / 1e9).toFixed(a >= 1e11 ? 0 : 1) + " billion" : (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + " million"}`; };
  const xPct = (v) => (v > 0 && v < 1 ? "&lt;1%" : `${Math.round(v)}%`);  // HTML
  const xDay = (d) => new Date(d + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const X_FLOW = { exports: ["Main buyers of its goods", "exports to"], imports: ["Main suppliers of its goods", "imports from"] };
  function renderTradeStats(iso) {
    if (!$("x-body")) return;
    if (st.mat) $("t-sec").after($("x-sec")); else $("t-sec").before($("x-sec"));  // the picked product comes first
    const c = TRADE.c[iso], nm = iso ? nmIso(iso) : st.sel, badge = $("x-cached");
    if (!c || c.note) {
      badge.hidden = true;
      $("x-body").innerHTML = `<p class="sub">${escH(c ? c.note : `No export or import figures for ${nm} in the World Bank or UN Comtrade data.`)}</p>`;
      return;
    }
    const s = c.s || {}, o = c.o || {}, I = TRADE.ind, p = c.p || {};
    const tip = (k) => `${I[k].name}: World Bank WDI, ${I[k].code}, ${s[k][1]}`;
    const tile = (k, g, lab) => `<div class="x-tile" title="${escH([k, g].filter((x) => s[x]).map(tip).join("\n"))}"><span>${lab}</span>
      <b>${s[k] ? xUsd(s[k][0]) : "–"}</b><small>${[s[k] ? `in ${s[k][1]}` : o[k] ? `no figure since ${o[k]}` : "no US$ figure",
        s[g] ? `${xPct(s[g][0])} of GDP${s[k] && s[g][1] === s[k][1] ? "" : ` (${s[g][1]})`}` : ""].filter(Boolean).join(" · ")}</small></div>`;
    let h = "";
    if (s.exp || s.imp || s.exp_gdp || s.imp_gdp || o.exp || o.imp) {
      h += `<div class="x-tiles">${tile("exp", "exp_gdp", "Exports")}${tile("imp", "imp_gdp", "Imports")}</div>`;
      if (s.exp && s.imp && s.exp[1] === s.imp[1]) {
        const b = s.exp[0] - s.imp[0];
        h += `<p class="eco-head">${Math.abs(b) < 0.005 * s.imp[0] ? `<b>About balanced</b> in ${s.exp[1]}: it sold about as much abroad as it bought.`
          : `<b>Trade ${b > 0 ? "surplus" : "deficit"} of ${xUsd(b)}</b> in ${s.exp[1]}: it ${b > 0 ? "sold more abroad than it bought" : "bought more from abroad than it sold"}.`}</p>`;
      }
      h += `<p class="faint x-what">Goods and services, current US$.</p>`;
    } else h += `<p class="sub">The World Bank has no total for ${escH(nm)}'s exports and imports of goods and services.</p>`;
    const rows = [["goods_exp", "Goods exports", xUsd], ["goods_imp", "Goods imports", xUsd],
      ["fuel_exp", "Fuel's share of goods exports", xPct], ["fuel_imp", "Fuel's share of goods imports", xPct]].filter(([k]) => s[k] || o[k]);
    if (rows.length) h += `<dl class="x-rows">${rows.map(([k, lab, f]) => s[k] ? `<div title="${escH(tip(k))}"><dt>${lab}</dt><dd>${f(s[k][0])}<i>${s[k][1]}</i></dd></div>`
      : `<div title="${escH(`${I[k].name}: the World Bank's latest figure is from ${o[k]}, too old to show`)}"><dt>${lab}</dt><dd>–<i>since ${o[k]}</i></dd></div>`).join("")}</dl>`;
    for (const [f, [lab, verb]] of Object.entries(X_FLOW)) {
      const x = p[f];
      if (!x) continue;
      const [yr, tot, , top] = x;
      h += `<div class="x-tl"><span>${lab}, ${yr}</span><div class="ichips">${top.map(([pi, pn, sh, v, onMap]) => {
        const t = escH(`${xUsd(v)} of ${xUsd(tot)} in goods ${verb} the world in ${yr}, as ${nm} reports it (UN Comtrade)` +
          (pn === "Other Asia, nes" ? `. "Other Asia, nes" is how most countries record trade with Taiwan.` : ""));
        const show = pn === "United States of America" ? "United States" : pn, inner = `${pi ? flagImg(pi) : ""}${escH(show)} <b>${xPct(sh * 100)}</b>`;
        return onMap ? `<button type="button" class="ichip x-p" data-xsel="${escH(pn)}" title="${t}. Click to open ${escH(show)}.">${inner}</button>`
          : `<span class="ichip" title="${t}">${inner}</span>`;
      }).join("")}</div></div>`;
    }
    const codes = Object.keys(s).map((k) => I[k].code), days = [...new Set(Object.keys(s).map((k) => I[k].collected))];
    const pdays = [...new Set(Object.values(p).map((x) => x[2]))];
    h += `<p class="faint">${codes.length ? `${escH(TRADE.wdi.name)} (${codes.join(", ")}; updated ${xDay(TRADE.wdi.updated)}), collected ${days.map(xDay).join(" and ")}. ` : ""}` +
      (pdays.length ? `Partners: UN Comtrade, all goods, as ${escH(nm)} reports them, collected ${pdays.map(xDay).join(" and ")}. ` : `No partner figures from UN Comtrade for ${escH(nm)}. `) +
      `Each figure is the latest year published, so years differ; none of it is live.</p>`;
    $("x-body").innerHTML = h;
    const all = days.concat(pdays).sort();
    badge.hidden = false;
    badge.textContent = `cached ${xDay(all[all.length - 1])}`;
    badge.title = "Published annual statistics, collected on the date shown. Not live.";
    $("x-body").querySelectorAll("[data-xsel]").forEach((b) => b.addEventListener("click", () => { select(b.dataset.xsel); if (st.sel) setCTab("trade"); }));
  }
'''
sub("  function renderTrade() {\n    const iso = isoOf[st.sel];\n", JS + "  function renderTrade() {\n    const iso = isoOf[st.sel];\n    renderTradeStats(iso);\n")

CSS = """
/* Trade tab: exports and imports for every country (notes/trade-stats.json). */
#x-sec { display: flex; flex-direction: column; gap: 10px; }
#x-body { display: flex; flex-direction: column; gap: 12px; }
#x-body p { margin: 0; }
.x-tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.x-tile { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel2); min-width: 0; }
.x-tile span { font-size: 13px; color: var(--text); font-weight: 600; }
.x-tile b { font: 600 19px var(--mono); color: var(--text); }
.x-tile small { font-size: 12px; color: var(--muted); line-height: 1.4; }
.x-rows { display: grid; gap: 0; margin: 0; }
.x-rows div { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 7px 0; border-top: 1px solid var(--line); }
.x-rows div:first-child { border-top: 0; padding-top: 0; }
.x-rows dt { font-size: 13.5px; color: var(--muted); }
.x-rows dd { margin: 0; font: 500 14px var(--mono); color: var(--text); white-space: nowrap; }
.x-rows dd i { font: 12px var(--mono); font-style: normal; color: var(--faint); margin-left: 8px; }
.x-tl { display: flex; flex-direction: column; gap: 6px; }
.x-tl > span { font: 600 11px var(--sans); color: var(--faint); letter-spacing: .7px; text-transform: uppercase; }
.ichip.x-p { min-height: 0; cursor: pointer; color: var(--text); }
.ichip.x-p:hover { border-color: var(--text); }
.ichip b { font-weight: 600; }
.x-cached { display: inline-block; margin-left: 4px; padding: 0 6px; border-radius: 999px; border: 1px dashed var(--line2); font: 600 10.5px/1.6 var(--sans); font-style: normal; color: var(--muted); text-transform: none; letter-spacing: 0; white-space: nowrap; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
have = sum(1 for c in C.values() if "s" in c)
print("written", len(s.encode()), f"| {len(C)} map countries, {have} with WDI figures, {sum('p' in c for c in C.values())} with partners,",
      "none for:", ", ".join(data["countries"][i]["name"] for i, c in C.items() if "note" in c))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
