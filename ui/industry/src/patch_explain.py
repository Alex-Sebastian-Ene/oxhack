# Runs after patch_economy.py on hormuz-flow.html.
# Optional "Why these numbers?" box in the country card (Overview tab) and in the product card. It sends the numbers
# the page shows, each with its source, to ui/industry/explain_server.py, which asks Gemini for a few plain bullets
# that each cite the facts they use, and flags any number in a bullet that is not in those facts. Gemini only
# explains: it never changes a number, a colour or a table. Off by default: the box appears only with ?explain=1
# (or ?explain=<service url>) in the URL, so the published page is unchanged.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


EXPLAIN_JS = r'''  // ------------------------------------------------------------ optional "Why these numbers?" (Gemini explains)
  // Off unless the URL has ?explain=1 (service on http://127.0.0.1:8789) or ?explain=<service url>.
  const EXPSVC = (() => { try { const b = new URLSearchParams(location.search).get("explain"); return b ? (b === "1" ? "http://127.0.0.1:8789" : b) : null; } catch (e) { return null; } })();
  const expFor = { country: "", product: "" };
  (function buildExplain() {
    if (!EXPSVC) return;
    const box = (kind) => {
      const d = document.createElement("div");
      d.className = "gexp"; d.id = `exp-${kind}`;
      d.innerHTML = `<div class="bh"><span class="label">Why these numbers?</span><span class="fine">Gemini explains the numbers above, using only them</span></div>
        <button type="button" class="go-exp" id="exp-${kind}-go">Explain with Gemini</button><div id="exp-${kind}-out" aria-live="polite"></div>`;
      d.querySelector("button").addEventListener("click", () => runExplain(kind));
      return d;
    };
    const ov = $("cpane-overview"), md = $("mdetail");
    if (ov) ov.appendChild(box("country"));
    if (md) md.appendChild(box("product"));
  })();
  const expKey = (kind) => `${kind === "country" ? st.sel || "" : st.mat || ""}|${kind === "country" ? st.mat || "" : ""}|${st.brent}|${st.key}`;
  function resetExplain() {
    if (!EXPSVC) return;
    for (const kind of ["country", "product"]) {
      const out = $(`exp-${kind}-out`), btn = $(`exp-${kind}-go`);
      if (!out || expFor[kind] === expKey(kind)) continue;
      expFor[kind] = expKey(kind);
      out.innerHTML = ""; btn.disabled = false;
    }
  }
  const scenFact = () => `Scenario: ${st.lost} points of normal Hormuz flow lost as AIS sees it (the reader's choice; the price curve was fitted on AIS-visible flow), so ${st.flow.toFixed(1)} of about ${PREWAR} mb/d get through. Brent averages about $${st.brent} over the next 12 months vs $${BRENT0} pre-war (Seb's flow-premium curve, fitted to the 2026 closure)`;
  // what the page shows for a country, each with where it comes from
  function countryFacts(name) {
    const iso = isoOf[name], k = calc(name), out = [scenFact()];
    out.push(`${nmIso(iso)} exposure score ${fmtS(k.score)} on a -40 (gains) to +65 (hurt) scale (an illustrative index: its weights are hand-set, not from a model; inputs from the scenario)`);
    out.push(`Fuel cost ${pct(k.fuel)} vs pre-war: Brent to retail fuel link validated on FRED (fitted 1991-2008, tested 2009-2026) times 1.49 in a supply disruption (Seb's cost-of-living model: 90% range 1.08 to 1.89, fitted on the US, UK and euro area, an assumption elsewhere)`);
    if (k.d.c) out.push(`About ${(k.hz * 100).toFixed(0)}% of ${nmIso(iso)}'s oil use comes through Hormuz (this page's country table)`);
    if (VIA[name]) out.push(`${nmIso(iso)} exports oil: ${VIA[name]}`);
    for (const r of industries(name).slice(0, 4)) out.push(`${r.label}: ${r.v == null ? "no sourced cost share" : `costs ${pct(r.lo / 100, 1)} to ${pct(r.hi / 100, 1)} (${r.src || "sourced share"})`}; ${String(r.why || "").slice(0, 120)}`);
    const m = mats[st.mat];
    if (m) for (const mode of ["production", "exports"]) {
      const rows = tableOf(m, mode), i = rows.findIndex((r) => r.iso3 === iso);
      if (i >= 0) out.push(`${m.name} ${mode === "exports" ? "exports" : "production"}: ${shareTxt(rows[i])}${rows[i].share != null ? " of world" : ""}, rank ${i + 1} (${(mode === "exports" ? (m.exports || {}).year : m.year) || ""})`);
    }
    return out;
  }
  // what the page shows for a product
  function productFacts(m) {
    const out = [scenFact()], pm = priceMoveM(m), d = shockRangeM(m);
    out.push(pm && pm.chain ? `${m.name} price ${pctP(pm.mean)} after 12 months against no disruption; 90% range of outcomes ${pctP(pm.lo)} to ${pctP(pm.hi)} (Seb's recommended chain, notes/chain-scenarios-3m-margins.csv)`
      : pm ? `${m.name} price ${pctP(pm.mean)} in 12 months at this Brent; average-effect band ${pctP(pm.lo)} to ${pctP(pm.hi)}, single moves vary more (${m.oil.series}; ${String(m.oil.source).slice(0, 120)})`
      : `${m.name}: no fitted oil price link yet`);
    if (d) out.push(`Past supply shocks moved it ${pctP(d.lo)} to ${pctP(d.hi)}`);
    if (m.oil && m.oil.extra) out.push(m.oil.extra);
    if (HORMUZ[m.id]) out.push(`Hormuz: ${HORMUZ[m.id]}`);
    tableOf(m, "production").slice(0, 4).forEach((r, i) => out.push(`#${i + 1} producer ${nmIso(r.iso3)} ${shareTxt(r)}${VIA[nameOfIso[r.iso3]] ? `, ${VIA[nameOfIso[r.iso3]]}` : ""} (${m.year})`));
    for (const [ind, share, src] of BUYERS[m.id] || []) out.push(share == null || !pm ? `${ind}: no sourced cost share (${src})` : `${ind}: ${m.short || m.name} is ${share}% of costs (${src}), so costs ${pctP(share * pm.mean / 100)}`);
    return out;
  }
  async function runExplain(kind) {
    const out = $(`exp-${kind}-out`), btn = $(`exp-${kind}-go`), ask = expKey(kind);
    const m = mats[st.mat], subject = kind === "country" ? st.sel : m && m.name;
    if (!subject) return;
    const facts = kind === "country" ? countryFacts(st.sel) : productFacts(m);
    btn.disabled = true;
    out.innerHTML = '<p class="fine">Explaining…</p>';
    try {
      const res = await fetch(`${EXPSVC}/explain`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, subject, facts }) });
      const b = await res.json();
      if (!res.ok) throw new Error(b.error || res.statusText);
      if (ask !== expKey(kind)) return;   // the reader moved on
      const fx = b.facts || facts, when = new Date(b.generated_at).toLocaleString();
      const flagged = b.bullets.filter((x) => x.unsupported && x.unsupported.length).length;
      out.innerHTML = `<ul class="exp-list">${b.bullets.map((x) => `<li><span>${escH(x.text)}</span>${x.facts.length ? ` <span class="exp-ref">${x.facts.map((i) => `[${i}]`).join("")}</span>` : ""}${x.unsupported && x.unsupported.length ? `<span class="exp-warn">Not in our data: ${x.unsupported.map(escH).join(", ")}</span>` : ""}</li>`).join("")}</ul>
        <details class="exp-facts"><summary>The ${fx.length} facts Gemini was given</summary><ol>${fx.map((f) => `<li>${escH(f)}</li>`).join("")}</ol></details>
        <p class="fine warn">AI-written by ${escH(b.model)}${b.cached ? `, cached, written ${escH(when)}` : `, ${escH(when)}`}. It explains this page's numbers and adds none of its own${flagged ? `; ${flagged} bullet${flagged > 1 ? "s" : ""} mention${flagged > 1 ? "" : "s"} a number not in them, flagged above` : ""}. Not checked by the team.</p>`;
    } catch (e) {
      out.innerHTML = `<p class="fine warn">No explanation: ${escH(String(e.message || e))}. Is <code>uv run ui/industry/explain_server.py</code> running with a GEMINI_API_KEY?</p>`;
      btn.disabled = false;
    }
  }
'''
sub("  function renderCountry() {", EXPLAIN_JS + "  function renderCountry() {")
# a new country, product, Brent price or scenario clears an old explanation (renderMat runs on every change)
sub("    renderPop();\n", "    renderPop();\n    resetExplain();\n")

CSS = """
.gexp { display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 12px; border: 1px dashed #b9a6ec; background: #f6f2ff; }
.gexp .bh { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.gexp .go-exp { align-self: flex-start; min-height: 36px; }
.exp-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; }
.exp-list li { font-size: 14px; line-height: 1.6; color: var(--text); }
.exp-ref { font: 11.5px var(--mono); color: #6d28d9; white-space: nowrap; }
.exp-warn { display: block; margin-top: 2px; font-size: 12.5px; font-weight: 600; color: #a3140d; }
.exp-facts summary { cursor: pointer; font-size: 13px; color: var(--muted); }
.exp-facts ol { margin: 6px 0 0; padding-left: 22px; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; line-height: 1.5; color: var(--muted); }
.gexp .warn { color: #8a4b00 !important; font-size: 12.5px; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')
sub("      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)",
    "      <li><b>Why these numbers? (off by default):</b> with <code>?explain=1</code> and <code>ui/industry/explain_server.py</code> running, Gemini explains a country's or a product's numbers in a few bullets. It gets only the numbers shown here, with their sources; each bullet cites the facts it uses, and any number not in them is flagged. It is labelled AI-written and not checked by the team.</li>\n"
    "      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
