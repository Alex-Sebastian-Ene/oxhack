# Runs after patch_labels.py on hormuz-flow.html.
# Yasmin's pass on the Strait view's side panel, so a judge reads the result first and can tell real from simulated:
# 1. The flow estimate leads: one line says what AIS shows, what we estimate and how much never appears on AIS.
# 2. Every number has words: the three chips, the true-value check and the tanker counters get labels.
# 3. Real and simulated are tagged where they appear: a "Simulated ships" tag on the map, "Real data" on PortWatch.
# 4. The published-estimates chart shows when each figure is from, and "Ours" is marked as the simulated scenario.
# 5. The estimate card says which scenario it is and how far the real counts run.
# 6. A "What this means" card links the lost flow to the World view, where it sets Brent and the knock-ons.
# Numbers are unchanged: same scenarios (window.STRAIT), same PortWatch cache, same chain in the World view.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


def cut(start_marker):
    """Remove the <section> that starts at start_marker (inside the Strait panel) and return it."""
    global s
    a = s.index(start_marker, s.index('id="strait-stage"'))
    b = s.index("      </section>\n", a) + len("      </section>\n")
    block = s[a:b]
    s = s[:a] + s[b:]
    return block


# ---------------------------------------------------------------- 2. labels on the chips, the check and the counters
sub('''<b id="est-seen" class="mono"></b></span>''', '''<b id="est-seen" class="mono"></b><span class="cl">seen on AIS</span></span>''')
sub('''<b id="est-bridged" class="mono"></b></span>''', '''<b id="est-bridged" class="mono"></b><span class="cl">AIS off mid-crossing</span></span>''')
sub('''<b id="est-hidden" class="mono"></b></span>''', '''<b id="est-hidden" class="mono"></b><span class="cl">never on AIS (radar)</span></span>''')
sub('''<path d="M5 12l5 5 9-10"/></svg> <span id="truth"></span></p>''',
    '''<path d="M5 12l5 5 9-10"/></svg> <span>True flow in this simulation:</span> <span id="truth"></span> <span>mb/d</span></p>''')
sub('''      <section class="card">
        <div class="counters">''', '''      <section class="card" id="count-card">
        <span class="label" id="count-head">Laden tankers out of the Gulf so far · simulated</span>
        <div class="counters">''')
sub('''<b class="mono" id="c-all">0</b></div>''', '''<b class="mono" id="c-all">0</b><span class="cl">out</span></div>''')
sub('''<b class="mono" id="c-ais">0</b></div>''', '''<b class="mono" id="c-ais">0</b><span class="cl">on AIS</span></div>''')
sub('''<b class="mono" id="c-dark">0</b></div>''', '''<b class="mono" id="c-dark">0</b><span class="cl">dark</span></div>''')

# ---------------------------------------------------------------- 1 and 5. the estimate leads, with one plain line and its scenario
sub('''        <p class="big"><span id="est-p50" class="mono">–</span><span class="unit">mb/d</span></p>''',
    '''        <p class="estline" id="est-line"></p>
        <p class="big"><span id="est-p50" class="mono">–</span><span class="unit">million barrels a day, our estimate</span></p>''')
sub('''        <p class="truth mono" title="True value in this simulation">''',
    '''        <p class="faint" id="est-when"></p>
        <p class="truth mono" title="True value in this simulation">''')
sub(''' Oil through the strait</span>''', ''' Oil through the strait <span class="tagc tag-sim">SIMULATED</span></span>''')

# ---------------------------------------------------------------- 3. tags: real data on PortWatch, simulated ships on the map
sub(''' Real transits · IMF PortWatch</span>''', ''' Real transits · IMF PortWatch <span class="tagc tag-real">REAL DATA</span></span>''')
sub(''' Tanker capacity · IMF PortWatch</span>''', ''' Tanker capacity · IMF PortWatch <span class="tagc tag-real">REAL DATA</span></span>''')
sub('''      <div class="real-flag" id="real-flag" hidden>''',
    '''      <div class="sim-flag" id="sim-flag">Simulated ships · illustrative positions</div>
      <div class="real-flag" id="real-flag" hidden>''')

# ---------------------------------------------------------------- 6. "What this means" card
LINK = '''      <section class="card" id="link-card">
        <span class="label"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg> What this means</span>
        <p class="estline" id="link-text"></p>
        <button type="button" id="link-go">See prices and countries <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg></button>
      </section>
'''

# ---------------------------------------------------------------- 4. the published-estimates chart: dates, and "Ours" marked simulated
sub('''        <div id="published" class="pub" aria-label="Published estimates compared with ours"></div>''',
    '''        <div id="published" class="pub" aria-label="Published estimates compared with ours"></div>
        <p class="faint">Published figures as reported, with when they refer to (sources: <code>docs/strait-live-data.md</code>; check before quoting). "Ours" is the estimate on the simulated scenario, not a measurement.</p>''')
sub('''    const rows = sc.published.map((p) => `<div class="r" title="${p.who}, ${p.when}"><span>${short[p.who] || p.who}</span>''',
    '''    const rows = sc.published.map((p) => `<div class="r" title="${p.who}, ${p.when}"><span>${short[p.who] || p.who}<i class="when">${p.when}</i></span>''')
sub('''    rows.push(`<div class="r" title="Our estimate, 90% range"><span class="ours">Ours</span>''',
    '''    rows.push(`<div class="r" title="Our estimate on the simulated scenario, 90% range"><span class="ours">Ours<i class="when">simulated</i></span>''')

# ---------------------------------------------------------------- new order: estimate, counters, what it means, then the real data
est = cut('      <section class="card" id="est-card">')
cnt = cut('      <section class="card" id="count-card">')
first = s.index('      <section class="card" id="pw-card">', s.index('id="strait-stage"'))
s = s[:first] + est + "\n" + cnt + "\n" + LINK + "\n" + s[first:]

# ---------------------------------------------------------------- behaviour
sub('''    document.querySelector(".counters div").title = isReal ? "Ships through the gate so far (real daily count, both directions)" : "Laden tankers out of the Gulf so far";''',
    '''    document.querySelector(".counters div").title = isReal ? "Ships through the gate so far (real daily count, both directions)" : "Laden tankers out of the Gulf so far";
    $("count-head").textContent = isReal ? "Ships through the gate so far · real daily count, both directions" : "Laden tankers out of the Gulf so far · simulated";
    $("sim-flag").hidden = isReal;
    $("link-card").hidden = isReal;''')
sub('''    $("truth").textContent = fmt(sc.truth_mbd);''',
    '''    $("truth").textContent = fmt(sc.truth_mbd);
    // one line a judge can read first, and which scenario this is
    const lastReal = (window.PORTWATCH && window.PORTWATCH.dates) ? window.PORTWATCH.dates[window.PORTWATCH.dates.length - 1] : null;
    $("est-line").innerHTML = `AIS shows <b>${fmt(e.seen.p50)}</b> · we estimate <b>${fmt(e.total.p50)}</b> (${fmt(e.total.p5)}–${fmt(e.total.p95)}) · <b>${fmt(e.hidden.p50)}</b> of it never appears on AIS`;
    $("est-when").textContent = `Scenario: ${sc.label}. Simulated ships, calibrated to that published figure.${lastReal ? ` Real PortWatch counts run to ${new Date(lastReal + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}.` : ""}`;
    renderLink();''')
sub('''  function renderCounters(t) {''', '''  // "What this means": the lost flow, and the Brent price the World view's chain sets from it
  function renderLink() {
    if (!sc || sc.real || !sc.estimate) return;
    const flow = Math.min(sc.estimate.total.p50, 20), lost = Math.round(Math.max(0, Math.min(100, (1 - flow / 20) * 100)));
    const brent = ($("brent-v") && $("brent-v").textContent.trim()) || "";
    $("link-text").innerHTML = `About <b>${fmt(flow)}</b> of the pre-war 20 million barrels a day get through, so <b>${lost}%</b> of the flow is lost. ` +
      (brent ? `In the World view, that sets Brent at about <b>${brent}</b> a barrel and drives fuel, food and product prices and each country's exposure.` : `The World view turns that into a Brent price and its knock-ons.`);
  }
  // the replay button changed the scenario without telling the World view, so the two could disagree; tell it now
  if ($("brent-v")) new MutationObserver(() => renderLink()).observe($("brent-v"), { childList: true, characterData: true, subtree: true });
  $("link-go").addEventListener("click", () => { const b = document.querySelector('[data-mode="world"]'); if (b) b.click(); window.scrollTo({ top: 0 }); });
  function renderCounters(t) {''')

sub('''  $("pw-replay").addEventListener("click", () => { const k = state.key === "real" ? "aug2026" : "real"; sel.value = k; load(k); });''',
    '''  $("pw-replay").addEventListener("click", () => { const k = state.key === "real" ? "aug2026" : "real"; sel.value = k; sel.dispatchEvent(new Event("change")); });''')

CSS = """
/* Strait panel: result first, every number labelled, real vs simulated tagged. */
.tagc.tag-real { color: var(--ok); border-color: var(--ok); margin-left: 6px; }
.tagc.tag-sim { color: var(--muted); border-style: dashed; margin-left: 6px; }
.estline { margin: 0; font-size: 14px; line-height: 1.55; color: var(--text); }
.estline b { font-family: var(--mono); font-weight: 600; }
#strait-stage .chips .chip { flex-wrap: wrap; row-gap: 2px; }
#strait-stage .chip .cl, #strait-stage .counters .cl { flex-basis: 100%; font-size: 11.5px; line-height: 1.3; color: var(--muted); }
#strait-stage .counters div { flex-wrap: wrap; row-gap: 2px; }
#count-card .label { margin-bottom: 2px; }
.sim-flag { position: absolute; top: 58px; left: 10px; padding: 5px 10px; border-radius: 999px; background: rgba(255,255,255,.94); border: 1px dashed var(--muted); font-size: 12px; color: var(--muted); z-index: 1; }
#link-go { align-self: flex-start; min-height: 38px; font-size: 13.5px; }
#link-go svg { width: 16px; height: 16px; }
.pub .r { grid-template-columns: 96px minmax(0, 1fr) 36px; }
.pub .r > span:first-child { display: flex; flex-direction: column; line-height: 1.2; }
.pub .when { font-style: normal; font: 10.5px var(--mono); color: var(--faint); }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
