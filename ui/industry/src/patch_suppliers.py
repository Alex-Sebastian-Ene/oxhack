# Runs after patch_panel.py on hormuz-flow.html.
# "Your suppliers" card in the World view: a company drops in its supplier list or bill of materials, the reader
# service (ui/industry/extract_server.py) asks Gemini to turn it into rows of product and supplier country, and the
# page rates each row with its own sourced numbers. Gemini never supplies a number. Uploading appears only with
# ?suppliers=1 (or ?suppliers=<service url>); the made-up sample list works everywhere, with no AI at all.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


SUP_JS = r'''  // ------------------------------------------------------------ your suppliers: rate a company's own list
  const SUPSVC = (() => { try { const b = new URLSearchParams(location.search).get("suppliers"); return b ? (b === "1" ? "http://127.0.0.1:8789" : b) : null; } catch (e) { return null; } })();
  // a made-up list for trying the card; it is labelled as such wherever it shows
  const SAMPLE_ROWS = [
    { item: "Urea, granular 46% N", material: "fertiliser", country_iso3: "OMN", supplier: "Sample supplier A", quantity: "2,000 t" },
    { item: "Ammonia, anhydrous", material: "fertiliser", country_iso3: "QAT", supplier: "Sample supplier B", quantity: "800 t" },
    { item: "PE film for bags", material: "polyethylene", country_iso3: "SAU", supplier: "Sample supplier C", quantity: "120 t" },
    { item: "Aluminium foil lids", material: "aluminium", country_iso3: "CHN", supplier: "Sample supplier D", quantity: "40 t" },
    { item: "Tinplate steel cans", material: "steel", country_iso3: "IND", supplier: "Sample supplier E", quantity: "300,000 units" },
    { item: "Diesel for delivery trucks", material: "crude_oil", country_iso3: "IND", supplier: "Sample supplier F", quantity: "90,000 L" },
    { item: "Corrugated boxes", material: "other", country_iso3: "DEU", supplier: "Sample supplier G", quantity: "50,000 units" },
  ];
  let supRows = null, supMeta = null;
  const MIME_BY_EXT = { pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", csv: "text/csv", txt: "text/plain", tsv: "text/tab-separated-values" };
  (function buildSuppliers() {
    const before = $("prod-card");   // after "The shock", before the product card
    if (!before || $("sup-card")) return;
    const c = document.createElement("section");
    c.className = "card"; c.id = "sup-card";
    c.innerHTML = `<div class="row between"><span class="label">Your suppliers</span></div>
      <p class="sub">See which of your purchases the Hormuz shock reaches: each item is rated with this page's own price links and trade tables.</p>
      <div class="sup-actions">${SUPSVC ? '<label class="sup-up" tabindex="0"><input type="file" id="sup-file" accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.txt,.tsv" hidden>Upload a supplier list</label>' : ""}<button type="button" id="sup-sample">Try a sample list</button><button type="button" id="sup-clear" hidden>Clear</button></div>
      <p class="fine" id="sup-hint">${SUPSVC ? "PDF, image, CSV or text, up to 8 MB. Gemini reads the file into items and countries; you can also drop a file here." : "Uploading your own list needs the Gemini reader service, which runs with the deployed version."}</p>
      <div id="sup-out" aria-live="polite"></div>`;
    before.before(c);
    $("sup-sample").addEventListener("click", () => { supRows = SAMPLE_ROWS; supMeta = { sample: true }; renderSuppliers(); });
    $("sup-clear").addEventListener("click", () => { supRows = null; supMeta = null; renderSuppliers(); });
    if (!SUPSVC) return;
    const fi = $("sup-file"), up = c.querySelector(".sup-up");
    fi.addEventListener("change", () => fi.files[0] && readFile(fi.files[0]));
    up.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fi.click(); } });
    c.addEventListener("dragover", (e) => { e.preventDefault(); c.classList.add("drop"); });
    c.addEventListener("dragleave", () => c.classList.remove("drop"));
    c.addEventListener("drop", (e) => { e.preventDefault(); c.classList.remove("drop"); const f = e.dataTransfer.files[0]; if (f) readFile(f); });
  })();
  function readFile(f) {
    const ext = (f.name.split(".").pop() || "").toLowerCase(), mime = MIME_BY_EXT[ext] || f.type;
    const out = $("sup-out");
    if (!MIME_BY_EXT[ext]) { out.innerHTML = `<p class="fine warn">${escH(f.name)}: use a PDF, image (PNG, JPG, WEBP), CSV or text file.</p>`; return; }
    if (f.size > 8e6) { out.innerHTML = `<p class="fine warn">${escH(f.name)} is over 8 MB.</p>`; return; }
    out.innerHTML = `<p class="fine">Reading ${escH(f.name)} with Gemini…</p>`;
    const r = new FileReader();
    r.onload = async () => {
      try {
        const res = await fetch(`${SUPSVC}/extract`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: f.name, mime, data: String(r.result).split(",")[1] || "" }) });
        const b = await res.json();
        if (!res.ok) throw new Error(b.error || res.statusText);
        supRows = b.rows; supMeta = { model: b.model, at: b.generated_at, cached: b.cached, file: b.file || f.name };
        renderSuppliers();
      } catch (e) {
        out.innerHTML = `<p class="fine warn">Could not read ${escH(f.name)}: ${escH(String(e.message || e))}. Is <code>uv run ui/industry/extract_server.py</code> running with a GEMINI_API_KEY?</p>`;
      }
    };
    r.readAsDataURL(f);
  }
  // one row's rating, from our own numbers only
  function rateRow(r) {
    const name = r.country_iso3 && nameOfIso[r.country_iso3], m = mats[r.material], why = [];
    let price = null, level = 0;
    if (m) {
      const pm = priceMoveM(m);
      if (pm) { price = pm.mean; why.push(`price ${pctP(pm.mean, 0)} in 12 months (${m.oil.linear ? "Seb's linear link" : "Seb's model"})`); }
      else why.push("no fitted price link");
    } else if (r.material === "crude_oil") {
      const k = calc(name || "United States of America");
      price = k.price * 100; why.push(`pump price ${pct(k.price)} (validated Brent-to-fuel link)`);
    } else why.push("not a product in our tables");
    if (name) {
      if (VIA[name]) why.push(`supplier country: ${VIA[name]}`);
      if (m) {
        const rows = tableOf(m, "exports"), i = rows.findIndex((x) => x.iso3 === r.country_iso3), pr = tableOf(m, "production").findIndex((x) => x.iso3 === r.country_iso3);
        if (i >= 0) why.push(`#${i + 1} exporter (${shareTxt(rows[i])})`);
        else if (pr >= 0) why.push(`#${pr + 1} producer`);
      }
      const k = calc(name);
      if (k.score >= 25) why.push(`supplier country exposure ${fmtS(k.score)}`);
      level = VIA[name] || (price != null && price >= 20) ? 2 : (price != null && price >= 5) || k.score >= 25 ? 1 : 0;
    } else {
      why.push("supplier country not given");
      level = price != null && price >= 20 ? 2 : price != null && price >= 5 ? 1 : 0;
    }
    return { name, m, price, level, why };
  }
  function renderSuppliers() {
    const out = $("sup-out"), clr = $("sup-clear");
    if (!out) return;
    clr.hidden = !supRows;
    if (!supRows) { out.innerHTML = ""; return; }
    if (!supRows.length) { out.innerHTML = '<p class="fine warn">No purchases found in that file.</p>'; return; }
    const rated = supRows.map((r) => ({ r, k: rateRow(r) })).sort((a, b) => b.k.level - a.k.level || (b.k.price || 0) - (a.k.price || 0));
    const n = [0, 0, 0]; rated.forEach(({ k }) => n[k.level]++);
    const LV = ["Low", "Medium", "High"];
    const top = rated[0];
    out.innerHTML = `<div class="sup-sum"><b>${rated.length} items</b><span class="pill lv2">${n[2]} high</span><span class="pill lv1">${n[1]} medium</span><span class="pill lv0">${n[0]} low</span></div>
      ${top && top.k.level ? `<p class="sub">Most exposed: <b>${escH(top.r.item)}</b> from ${escH(top.k.name ? nmIso(top.r.country_iso3) : "an unnamed country")}, ${escH(top.k.why[0])}.</p>` : ""}
      <ul class="sup-list">${rated.map(({ r, k }, i) => `<li><button type="button" data-sup="${i}" ${k.name ? "" : "disabled"}>
        <span class="sup-top"><span class="sup-item">${escH(r.item)}</span><span class="pill lv${k.level}">${LV[k.level]}</span></span>
        <span class="sup-who">${r.country_iso3 && nameOfIso[r.country_iso3] ? `${flagImg(r.country_iso3)} ${escH(nmIso(r.country_iso3))}` : "Country not given"}${r.supplier ? ` · ${escH(r.supplier)}` : ""}${r.quantity ? ` · ${escH(r.quantity)}` : ""}</span>
        <span class="sup-why">${k.why.map(escH).join(" · ")}</span></button></li>`).join("")}</ul>
      <p class="fine">Risk: <b>High</b> if the supplier ships via Hormuz or the price link gives +20% or more; <b>Medium</b> if +5% or more, or the supplier country's exposure score is 25 or more; else <b>Low</b>. All at Brent $${st.brent}.</p>
      <p class="fine ${supMeta && supMeta.sample ? "" : "warn"}">${supMeta && supMeta.sample ? "Made-up sample list, for trying the card. No AI was used."
        : `Items read from ${escH(supMeta.file)} by ${escH(supMeta.model)}${supMeta.cached ? ", cached" : ""}, ${escH(new Date(supMeta.at).toLocaleString())}. Check them against your file: AI can misread. The numbers are from this page's sourced tables, not from Gemini.`}</p>`;
    out.querySelectorAll("[data-sup]").forEach((b) => b.addEventListener("click", () => {
      const { r, k } = rated[+b.dataset.sup];
      if (k.m && st.mat !== r.material) pickMat(r.material);
      if (k.m === undefined && st.mat) pickMat(null);
      if (k.name && st.sel !== k.name) select(k.name);
    }));
  }
'''
sub("  function renderCountry() {", SUP_JS + "  function renderCountry() {")
# the ratings follow the Brent setting and the scenario (renderMat runs on every change of either)
sub("    renderPop();\n    if (!m) return;", "    renderPop();\n    if (supRows) renderSuppliers();\n    if (!m) return;")

CSS = """
#sup-card.drop { outline: 2px dashed var(--seen); outline-offset: -6px; }
.sup-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.sup-actions button, .sup-up { min-height: 38px; }
.sup-up { display: inline-flex; align-items: center; padding: 0 14px; border-radius: 8px; background: var(--text); color: #ffffff; font-weight: 600; cursor: pointer; }
.sup-up:focus-visible { outline: 2px solid var(--seen); outline-offset: 2px; }
.sup-sum { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font: 600 12px var(--sans); white-space: nowrap; }
.pill.lv2 { background: #fde2dc; color: #a3140d; }
.pill.lv1 { background: #ffefd2; color: #8a4b00; }
.pill.lv0 { background: #e3f4ec; color: #0f6b45; }
.sup-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.sup-list li + li { border-top: 1px solid var(--line); }
.sup-list button { width: 100%; display: flex; flex-direction: column; align-items: stretch; gap: 3px; padding: 11px 2px; background: transparent; border: 0; border-radius: 0; text-align: left; min-height: 0; }
.sup-list button:hover:not(:disabled) { background: var(--panel2); }
.sup-list button:disabled { cursor: default; opacity: 1; }
.sup-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.sup-item { font-size: 14.5px; font-weight: 600; color: var(--text); }
.sup-who { font-size: 13px; color: var(--muted); display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.sup-who .flag { width: 18px; height: 13px; }
.sup-why { font-size: 13px; line-height: 1.5; color: var(--muted); }
#sup-card .warn { color: #8a4b00 !important; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')
# the info sheet says what the card does and where its numbers come from
sub("      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)",
    "      <li><b>Your suppliers:</b> a company's supplier list is read into items and supplier countries, by Gemini when the reader service runs (<code>ui/industry/extract_server.py</code>), or from the made-up sample. Each item is then rated only with this page's own numbers: the product's price link, whether the supplier country ships via Hormuz, its trade rank and its exposure score.</li>\n"
    "      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
