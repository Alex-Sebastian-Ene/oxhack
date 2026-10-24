# Runs after patch_metals.py on hormuz-flow.html.
# The World view's right panel: wider, larger type with more line spacing, and the country card split into
# three tabs (Overview, Industries, Trade) instead of one long column.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- tabs in the country card
# The existing sections keep their ids, so the render code fills them as before; this only moves them into panels.
TABS_JS = r'''  // country card: three tabs instead of one long column (the sections keep their ids; render code is unchanged)
  const CTABS = [["overview", "Overview"], ["inds", "Industries"], ["trade", "Trade"]];
  let ctab = "overview";
  (function buildCTabs() {
    const cc = $("country-card"), sub = $("c-sub");
    if (!cc || !sub || $("ctabs")) return;
    const bar = document.createElement("div");
    bar.className = "seg ctabs"; bar.id = "ctabs"; bar.setAttribute("role", "tablist"); bar.setAttribute("aria-label", "Country detail");
    bar.innerHTML = CTABS.map(([k, t]) => `<button type="button" role="tab" id="ctab-${k}" data-ctab="${k}" aria-controls="cpane-${k}">${t}</button>`).join("");
    sub.after(bar);
    const pane = (k, nodes) => {
      const d = document.createElement("div");
      d.className = "cpane"; d.id = `cpane-${k}`; d.setAttribute("role", "tabpanel"); d.setAttribute("aria-labelledby", `ctab-${k}`);
      nodes.filter(Boolean).forEach((n) => d.appendChild(n));
      return d;
    };
    const kpis = cc.querySelector(".kpis"), chart = $("c-chartbox") && $("c-chartbox").parentElement, inds = $("c-inds") && $("c-inds").parentElement;
    const panes = [pane("overview", [kpis, chart]), pane("inds", [inds]), pane("trade", [$("t-sec")])];
    let at = bar;
    for (const d of panes) { at.after(d); at = d; }
    bar.addEventListener("click", (e) => { const b = e.target.closest("[data-ctab]"); if (b) setCTab(b.dataset.ctab); });
    bar.addEventListener("keydown", (e) => {
      const i = CTABS.findIndex(([k]) => k === ctab), d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      e.preventDefault(); setCTab(CTABS[(i + d + CTABS.length) % CTABS.length][0]); $(`ctab-${ctab}`).focus();
    });
    setCTab("overview");
  })();
  function setCTab(k) {
    ctab = k;
    for (const [id] of CTABS) {
      const on = id === k, b = $(`ctab-${id}`), pn = $(`cpane-${id}`);
      if (b) { b.setAttribute("aria-selected", String(on)); b.setAttribute("aria-pressed", String(on)); b.tabIndex = on ? 0 : -1; }
      if (pn) pn.hidden = !on;
    }
  }
'''
sub("  function renderCountry() {", TABS_JS + "  function renderCountry() {")
# a new country opens on Overview, or on Trade when a product is picked
sub("    st.sel = name && name === st.sel ? null : name;",
    '    st.sel = name && name === st.sel ? null : name;\n    if (st.sel && typeof setCTab === "function" && $("ctabs")) setCTab(st.mat ? "trade" : "overview");')
# the pop-up's "Full analysis" button lands on the matching tab
sub('$("cp-more").addEventListener("click", () => { const c = $("country-card");',
    '$("cp-more").addEventListener("click", () => { if ($("ctabs")) setCTab(st.mat ? "trade" : "overview"); const c = $("country-card");')

# ---------------------------------------------------------------- room and type
CSS = """
@media (min-width: 861px) { #world-stage .hud { flex: 0 0 430px; width: 430px; max-width: 430px; } }
#world-stage .hud { gap: 14px; }
#world-stage .hud .card { padding: 18px 20px; gap: 12px; }
#world-stage .hud .label { font: 600 11.5px var(--sans); letter-spacing: .7px; text-transform: uppercase; color: var(--muted); }
#world-stage .hud .sub { font-size: 14px; line-height: 1.6; color: var(--muted); }
#world-stage .hud .faint { font-size: 13px; line-height: 1.55; }
#world-stage .ctitle h2 { font-size: 21px; }
/* tabs */
.ctabs { display: flex; width: 100%; margin-top: 2px; }
.ctabs button { flex: 1 1 0; min-height: 38px; font-size: 13px; padding: 0 6px; white-space: nowrap; }
.cpane { display: flex; flex-direction: column; gap: 16px; padding-top: 4px; }
/* overview numbers */
#world-stage .kpis { gap: 8px; }
#world-stage .kpis div { padding: 12px 10px; gap: 4px; }
#world-stage .kpis b { font-size: 24px; }
#world-stage .kpis span { font-size: 12.5px; line-height: 1.4; color: var(--muted); }
/* industries and buyers: one row each, the reason on its own line */
#world-stage .inds { gap: 0; }
#world-stage .inds li { padding: 12px 0; border-top: 1px solid var(--line); gap: 6px 12px; }
#world-stage .inds li:first-child { border-top: 0; padding-top: 4px; }
#world-stage .inds .nm { font-size: 14.5px; font-weight: 600; }
#world-stage .inds .lv { font-size: 12.5px; }
#world-stage .inds .tr { height: 8px; border-radius: 4px; }
#world-stage .inds .why { font-size: 13px; line-height: 1.55; color: var(--muted); }
/* products and trade */
#world-stage .tmat { padding: 14px 0; gap: 10px; }
#world-stage .tmat:first-child { border-top: 0; padding-top: 4px; }
#world-stage .tmat .th { font-size: 15px; font-weight: 600; }
#world-stage .tmat .th .rl { font-size: 12.5px; font-weight: 400; }
#world-stage .tmat .tl { gap: 6px; font-size: 13px; }
#world-stage .tmat .tl > span { font: 600 11px var(--sans); letter-spacing: .7px; }
#world-stage .ichips { gap: 6px; }
#world-stage .ichip { font: 12.5px var(--sans); padding: 4px 9px; gap: 5px; }
#world-stage .ichip .dot { box-shadow: 0 0 0 1px rgba(20,32,46,.35); }
/* product card */
#world-stage .pbars button { min-height: 36px; font-size: 13.5px; }
#world-stage #m-band { font-size: 13px; line-height: 1.6; }
#world-stage #m-hormuz { font-size: 14px; line-height: 1.6; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
