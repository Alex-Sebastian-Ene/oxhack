# Runs last, after patch_iea.py, on hormuz-flow.html.
# The Industries tab lists five hand-picked industries per country. This adds "Add an industry" under them:
# 1. Any of the page's 16 industries, drawn the same way as the hand-picked rows (cost share x fuel price change,
#    or the industry's own prices, export earnings or "no data", whichever the page has for it).
# 2. Any of the 20 industries in Seb's sector model (notes/country-trends.json: producer prices for Europe and the
#    US): its own prices after 12 months at this Brent, its latest index and year-on-year change, and its forecast
#    skill. Where Eileen's notes/industry/industry_exposure.csv has an energy or materials share for it (cement,
#    chemicals, plastics, manufacturing), that share is shown beside it, read at build time.
# 3. Added industries stay as you click between countries, so one industry can be compared across them; each has
#    Remove, and rows with a sector series (added or hand-picked) link to its chart in the Trends tab.
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
# sector-model industry code <- CSV row with its energy or materials share
SEC_ROWS = {"C23": "cement_non_metallic_minerals", "C235": "cement_non_metallic_minerals", "C20": "chemicals",
            "C22": "packaging_resin", "C": "manufacturing_average"}
trends = json.loads((root / "notes" / "country-trends.json").read_text(encoding="utf-8"))
codes = {c for c, _ in trends["industries"]}
assert set(SEC_ROWS) <= codes, set(SEC_ROWS) - codes
SEC_SHARE = {}
for code, key in SEC_ROWS.items():
    r = rows[key]
    SEC_SHARE[code] = f'{r["oil_linked_cost"]} {r["share_pct"]}%: {r["measure"]} ({r["source"]}, {r["region"]}, {r["year"]})'

# 1. industries() takes an optional list of keys, so added industries get the same rows as the hand-picked ones
sub("  function industries(name) {\n    const k = calc(name);\n    return k.d.ind.map((key) => {",
    "  function industries(name, keys) {\n    const k = calc(name);\n    return (keys || k.d.ind).map((key) => {")

# 2. sector-model rows, the picker and its list
PICK_JS = (
    "  // Add an industry: any of the page's industries or Seb's sector-model industries, kept across countries\n"
    "  // Energy or materials shares for sector-model industries, from notes/industry/industry_exposure.csv (build time)\n"
    f"  const SEC_SHARE = {json.dumps(SEC_SHARE, ensure_ascii=False)};\n"
) + r'''  const indAdd = [];
  let indAddAt = null;
  const trHas = (name, code) => { const c = TRENDS.countries[TR_GEO[name]]; return !!(c && ((c.price && c.price[code]) || (c.output && c.output[code]))); };
  const indActs = (name, code, rm) => {
    const tr = code && trHas(name, code) ? `<button type="button" data-indtr="${code}">Its chart in Trends</button>` : "";
    const x = rm ? `<button type="button" data-indrm="${rm}" aria-label="Remove ${escH(rm in IND ? IND[rm][0] : TR_IND[rm])}">Remove</button>` : "";
    return tr || x ? `<span class="ind-act">${tr}${x}</span>` : "";
  };
  const withActs = (html, acts) => (acts ? html.replace(/<\/li>\s*$/, `${acts}</li>`) : html);
  function sectorItem(name, code) {
    const geo = TR_GEO[name], c = geo && TRENDS.countries[geo], label = TR_IND[code];
    const where = geo === "US" ? "the US" : geo === "UK" ? "the UK" : c ? c.name : name;
    const share = SEC_SHARE[code] ? ` Cost share: ${escH(SEC_SHARE[code])}.` : "";
    const pr = c && c.price && c.price[code], out = c && c.output && c.output[code];
    if (!pr || !pr.resp || pr.resp[pr.resp.length - 1] == null) {
      const why = !c ? `Seb's sector model covers Europe, Türkiye and the US, not ${escH(name)}`
        : `No producer price series for ${escH(label.toLowerCase())} in ${escH(where)}${out ? "; its output is in the Trends tab" : ""}`;
      return `<li><span class="nm">${escH(label)}</span><span class="lv">no data</span><span class="why">${why}.${share}</span></li>`;
    }
    const x = st.brent / BRENT0 - 1, v = x > 0.005 ? pr.resp[pr.resp.length - 1] * Math.log(1 + x) / Math.log(1.1) : 0;
    const cls = v > 0.05 ? "hurt" : v < -0.05 ? "gain" : "";
    const [km, lv, i] = trLast(pr), yr = i >= 12 && pr.v[i - 12] != null ? (lv / pr.v[i - 12] - 1) * 100 : null;
    const now = `Latest: ${lv.toFixed(1)} in ${trMonth(km)} (2021 = 100)${yr == null ? "" : `, ${trNum(yr)}% on a year earlier`}.`;
    const fx = x > 0.005 ? `Its producer prices in ${escH(where)} end up about ${Math.abs(v).toFixed(1)}% ${v >= 0 ? "higher" : "lower"} after 12 months at $${st.brent} a barrel than with no oil move`
      : `At $${st.brent} a barrel oil is at its pre-war price, so there is no knock-on to its prices`;
    return `<li><span class="nm">${escH(label)}</span><span class="lv mono ${cls}">${pct(v / 100, 1)} its prices</span>
        <span class="why">${fx} (Seb's sector model, average effect; ${trSkill(pr.skill)} than a naive forecast). ${now}${share}</span></li>`;
  }
  function renderIndAdd(name, indItem) {
    indAddAt = { name, indItem };
    const box = $("c-ind-add");
    if (!box) return;
    const own = calc(name).d.ind;
    const keys = indAdd.filter((k) => k in IND && !own.includes(k));
    const rowsOf = Object.fromEntries(industries(name, keys).map((i) => [i.key, i]));
    $("c-inds-add").innerHTML = indAdd.filter((k) => !(k in IND && own.includes(k))).map((k) => (k in IND
      ? withActs(indItem(rowsOf[k]), indActs(name, SECTOR[k], k))
      : withActs(sectorItem(name, k), indActs(name, k, k)))).join("");
    const opt = (k, t) => `<option value="${k}">${escH(t)}</option>`;
    const page = Object.keys(IND).filter((k) => !own.includes(k) && !indAdd.includes(k));
    const secs = TRENDS.industries.filter(([k]) => !indAdd.includes(k));
    $("c-ind-pick").innerHTML = `<option value="">Pick an industry…</option>` +
      (page.length ? `<optgroup label="Oil-exposed industries">${page.map((k) => opt(k, IND[k][0])).join("")}</optgroup>` : "") +
      (secs.length ? `<optgroup label="Producer prices (Europe and the US)">${secs.map(([k, t]) => opt(k, trHas(name, k) ? t : `${t} (no data here)`)).join("")}</optgroup>` : "");
    $("c-ind-note").hidden = !indAdd.length;
  }
  $("c-ind-pick") && $("c-ind-pick").addEventListener("change", (e) => {
    const k = e.target.value;
    if (!k || !indAddAt) return;
    if (!indAdd.includes(k)) indAdd.push(k);
    renderIndAdd(indAddAt.name, indAddAt.indItem);
    $("c-ind-pick").focus();
  });
  $("cpane-inds") && $("cpane-inds").addEventListener("click", (e) => {
    const rm = e.target.closest("[data-indrm]"), tr = e.target.closest("[data-indtr]");
    if (rm && indAddAt) {
      indAdd.splice(indAdd.indexOf(rm.dataset.indrm), 1);
      renderIndAdd(indAddAt.name, indAddAt.indItem);
      $("c-ind-pick").focus();
    } else if (tr) {
      trInd = tr.dataset.indtr; setCTab("trends"); renderTrends();
      $("tr-ind-block").scrollIntoView({ block: "nearest" });
    }
  });
'''
sub("  function renderCountry() {", PICK_JS + "  function renderCountry() {")

# 3. one function draws a row, for the hand-picked list and the added one; hand-picked rows get the Trends link too
sub('    $("c-inds").innerHTML = inds.map((i) => {', "    const indItem = (i) => {")
sub('    }).join("");\n    renderTrade();',
    '    };\n'
    '    $("c-inds").innerHTML = inds.map((i) => withActs(indItem(i), indActs(name, SECTOR[i.key]))).join("");\n'
    '    renderIndAdd(name, indItem);\n'
    '    renderTrade();')

# 4. the picker sits under the hand-picked list and its note
sub('Cost shares: notes/industry/industry_exposure.csv.</p>',
    'Cost shares: notes/industry/industry_exposure.csv.</p>\n'
    '          <div class="ind-add" id="c-ind-add">\n'
    '            <label class="label" for="c-ind-pick">Add an industry</label>\n'
    '            <select id="c-ind-pick"></select>\n'
    '            <ul class="inds" id="c-inds-add"></ul>\n'
    '            <p class="faint" id="c-ind-note" hidden>Industries you add stay as you click other countries.</p>\n'
    '          </div>')
sub(".inds .why { grid-column: 1 / -1; font-size: 11.5px; color: var(--faint); }",
    ".inds .why { grid-column: 1 / -1; font-size: 11.5px; color: var(--faint); }\n"
    ".inds .ind-act { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; }\n"
    ".inds .ind-act button { font-size: 12px; min-height: 28px; padding: 0 10px; }\n"
    ".ind-add { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }\n"
    "#c-ind-pick { width: 100%; }")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
