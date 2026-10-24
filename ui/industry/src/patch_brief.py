# Runs after patch_panel.py on hormuz-flow.html.
# Optional AI brief in the country card, from Edward's local Gemini proxy (experiments/country_brief.py,
# docs/country-briefs.md). Off by default: it appears only with ?brief=1 (or ?brief=<proxy url>) in the URL,
# so the published artifact is unchanged. Same rules as Edward's globe: the key stays with the proxy, the page
# sends only the numbers it already shows (with their sources) as facts, and the answer is labelled AI-written,
# with its model, its date, "cached" when it is, and "Not checked by the team".
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


BRIEF_JS = r'''  // ------------------------------------------------------------ optional AI brief (Edward's Gemini proxy)
  // Off unless the URL has ?brief=1 (proxy on http://127.0.0.1:8787) or ?brief=<proxy url>.
  const BRIEF = (() => { try { const b = new URLSearchParams(location.search).get("brief"); return b ? (b === "1" ? "http://127.0.0.1:8787" : b) : null; } catch (e) { return null; } })();
  let briefFor = "";
  (function buildBrief() {
    const cc = $("country-card");
    if (!BRIEF || !cc || $("brief")) return;
    const d = document.createElement("div");
    d.className = "brief"; d.id = "brief";
    d.innerHTML = `<div class="bh"><span class="label">AI brief</span><span class="fine">Gemini with Google Search, written on request</span></div>
      <button type="button" class="go-brief" id="brief-go"></button><div id="brief-out" aria-live="polite"></div>`;
    cc.appendChild(d);
    $("brief-go").addEventListener("click", () => writeBrief());
  })();
  function resetBrief() {
    if (!BRIEF || !$("brief")) return;
    const key = `${st.sel || ""}|${st.mat || ""}`;
    if (key === briefFor) return;
    briefFor = key;
    $("brief-out").innerHTML = "";
    const b = $("brief-go"); b.disabled = false;
    const nm = st.sel === "United States of America" ? "United States" : st.sel || "";
    b.textContent = st.mat ? `Write a brief on ${nm} and ${mats[st.mat].short || mats[st.mat].name}` : `Write a brief on ${nm} and the oil shock`;
  }
  // the facts are the numbers this page shows for the country, each with where it comes from
  function briefFacts(name) {
    const iso = isoOf[name], k = calc(name), out = [];
    const scen = `this page's ${st.key} scenario, simulated: Brent $${st.brent} vs $${BRENT0} pre-war, Hormuz flow ${st.flow.toFixed(1)} mb/d`;
    out.push(`Exposure score ${fmtS(k.score)} on a -40 to +65 scale (${scen})`);
    out.push(`Fuel cost ${pct(k.fuel)} vs pre-war (Brent to retail fuel link validated on FRED 1991-2008, tested 2009-2026, plus an assumed shortage premium)`);
    if (k.d.c) out.push(`About ${(k.hz * 100).toFixed(0)}% of its oil use comes through Hormuz (this page's country table)`);
    const m = mats[st.mat];
    if (m) {
      const pm = priceMoveM(m);
      if (pm) out.push(`${m.name} price ${pctP(pm.mean)} in 12 months at that Brent (${m.oil.series}; ${m.oil.source})`);
      for (const mode of ["production", "exports"]) {
        const rows = tableOf(m, mode), i = rows.findIndex((r) => r.iso3 === iso), src = mode === "exports" ? m.exports || {} : m;
        if (i >= 0) out.push(`${m.name} ${mode === "exports" ? "exports" : "production"}: ${shareTxt(rows[i])}${rows[i].share != null ? " of world" : ""}, rank ${i + 1} (${src.year || m.year}; ${String(src.source || m.source || "").slice(0, 160)})`);
      }
      for (const l of m.links.filter((x) => x.to === iso)) {
        const inp = MAT.inputs[l.input];
        out.push(`${m.name}: ${Math.round(l.share * 100)}% of ${nmIso(iso)}'s ${inp ? inp.name : l.input} from ${nmIso(l.from)} (${l.basis || ""}; ${l.year || ""}; ${String(l.source || "").slice(0, 120)})`);
      }
    }
    return out;
  }
  async function writeBrief() {
    const name = st.sel, iso = isoOf[name], out = $("brief-out"), btn = $("brief-go");
    if (!name || !iso) return;
    const ask = `${st.sel || ""}|${st.mat || ""}`;
    btn.disabled = true;
    out.innerHTML = '<p class="fine">Writing…</p>';
    try {
      const res = await fetch(`${BRIEF}/brief`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ iso3: iso, country: name, material: st.mat ? mats[st.mat].name : "crude oil and oil products", facts: briefFacts(name) }) });
      const b = await res.json();
      if (!res.ok) throw new Error(b.error || res.statusText);
      if (ask !== `${st.sel || ""}|${st.mat || ""}`) return;   // the reader moved on
      const when = new Date(b.generated_at).toLocaleString();
      const host = (u) => { try { return new URL(u).hostname; } catch (e) { return u; } };
      out.innerHTML = `<div class="btext">${escH(b.text).replace(/^\s*[*-]\s+/gm, "• ").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")}</div>
        ${b.sources && b.sources.length ? `<div class="srcs">${b.sources.map((x) => `<a class="srcl" href="${escH(x.uri)}" target="_blank" rel="noopener" title="${escH(x.uri)}">${escH(x.title || host(x.uri))}</a>`).join("")}</div>` : ""}
        <p class="fine warn">AI-written by ${escH(b.model)}${b.cached ? `, cached, written ${escH(when)}` : `, ${escH(when)}`}. Not checked by the team: verify before quoting.</p>`;
    } catch (e) {
      out.innerHTML = `<p class="fine warn">No brief: ${escH(String(e.message || e))}. Is <code>uv run experiments/country_brief.py</code> running with a GEMINI_API_KEY?</p>`;
      btn.disabled = false;
    }
  }
'''
sub("  function renderCountry() {", BRIEF_JS + "  function renderCountry() {")
# a new country or product clears the old brief
sub('    if (st.sel && typeof setCTab === "function" && $("ctabs")) setCTab(st.mat ? "trade" : "overview");',
    '    if (st.sel && typeof setCTab === "function" && $("ctabs")) setCTab(st.mat ? "trade" : "overview");\n    resetBrief();')
sub("  function pickMat(id) {\n    st.mat = id;", "  function pickMat(id) {\n    st.mat = id;\n    resetBrief();")

CSS = """
.brief { display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 12px; border: 1px dashed #b9a6ec; background: #f6f2ff; }
.brief .bh { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.brief .go-brief { align-self: flex-start; min-height: 36px; }
.brief .btext { font-size: 14px; line-height: 1.6; color: var(--text); }
.brief .srcs { display: flex; flex-wrap: wrap; gap: 6px; }
.brief .srcl { font-size: 12px; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--line2); color: var(--seen); text-decoration: none; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brief .warn { color: #8a4b00 !important; font-size: 12.5px; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')
# the info sheet says the brief exists and is off by default
sub("      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)",
    "      <li><b>AI brief (off by default):</b> with <code>?brief=1</code> and Edward's local proxy (<code>experiments/country_brief.py</code>) running, the country card can ask Gemini for a short brief. It gets only the numbers shown here, with their sources, and is labelled AI-written and not checked by the team.</li>\n"
    "      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
