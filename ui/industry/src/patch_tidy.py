# Runs last, after patch_straitui.py, on hormuz-flow.html.
# Yasmin's tidy-up for viewers: the panels said too much about how the page was built.
# - Inline notes keep one plain source line each (the AGENTS.md rule: every number says where it came from and when),
#   without model member names, file paths, ticket numbers or people's names.
# - The info sheets (the ⓘ buttons) say what a viewer needs: what the thing shows, how to read it, and its sources.
#   Build notes, colour lists, refresh instructions and the optional AI box (off by default) move out; they stay in
#   ui/industry/README.md and docs/. The World sheet is brought up to date: the slider now sets lost Hormuz flow.
# Numbers are unchanged; the facts sent to the optional explain service are unchanged.
import pathlib, re, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


def entry(obj, key, new):
    """Replace one entry of a `const OBJ = {` block: from `    key:` to the next 4-space entry or the closing brace."""
    global s
    o = s.index(f"  const {obj} = {{")
    m = re.compile(rf"^    {key}: ", re.M).search(s, o)
    assert m, f"{obj}.{key} not found"
    nxt = re.compile(r"^(    [A-Za-z_]+: |  \};)", re.M).search(s, m.end())
    s = s[:m.start()] + new.rstrip("\n") + "\n" + s[nxt.start():]


# ---------------------------------------------------------------- inline notes: one plain source line
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
sub("  const chainSrc = () => `Seb's recommended chain (bayes_own + global_lin + global, with the margin member on fuels), "
    "notes/chain-scenarios-3m-margins.csv: fitted to ${CHAIN_META.fitted_to}, started ${CHAIN_META.origin}, generated ${CHAIN_META.generated}`;",
    "  const ymLabel = (ym) => { const [y, m] = String(ym).split(\"-\"); return `" + "${[" + ",".join(f'"{x}"' for x in MONTHS) + "][Number(m) - 1] || m} ${y}`; };\n"
    "  // plain source line for viewers; the full method is in docs/chain.md\n"
    "  const chainSrc = () => `Source: the team's oil-shock model, fitted to data up to ${ymLabel(CHAIN_META.fitted_to)}`;")
sub('<span class="hint">Seb\'s flow-premium curve</span>', '<span class="hint">follows from the lost flow</span>')
sub(". The curve is fitted to the 2026 closure; the Bab el-Mandeb disruption of 2023–24 checks it out of sample.` : \"No lost flow: Brent stays at its pre-war $70 in this curve.\";",
    ".` : \"No lost flow: Brent stays at its pre-war $70.\";")
sub("    $(\"w-src\").textContent = `Diesel and inflation (US): ${chainSrc()}. Extra change against no disruption, 12 months on. "
    "Energy bills: the linear Brent link in notes/oil-chain-links.md, at that Brent. Ranges are 90% of outcomes.`;",
    "    $(\"w-src\").textContent = `Change against no disruption, 12 months on (US). Ranges cover 90% of outcomes. ${chainSrc()}; energy bills from US price data (FRED).`;")
sub("      `The chain's unemployment path (grey) moves ${u12[0] < 0 ? \"down\" : \"up\"} about ${a(u12[0]).toFixed(2)} points against no disruption, "
    "but it has no causal oil link: Seb marks it \"forecast only\", so it isn't used as an effect (docs/chain.md).`;",
    "      `The grey line moves ${u12[0] < 0 ? \"down\" : \"up\"} about ${a(u12[0]).toFixed(2)} points, but the model finds no proven link from oil to jobs, so it's shown for reference only.`;")
sub("    $(\"e-src\").textContent = `${chainSrc()}. Change against no disruption at the chosen lost flow, months 1 to 12 "
    "(straight lines between its 1, 3, 6 and 12-month points). The range is 90% of outcomes.`;",
    "    $(\"e-src\").textContent = `Change against no disruption. The range covers 90% of outcomes. ${chainSrc()}.`;")
sub("`${st.lost} points of Hormuz flow lost (Brent about $${st.brent}). Extra change against no disruption after 12 months; "
    "90% range of outcomes ${pctP(p.lo)} to ${pctP(p.hi)}. ${chainSrc()}.`",
    "`With ${st.lost}% of Hormuz flow lost (Brent about $${st.brent}), 12 months on. 90% of outcomes: ${pctP(p.lo, 0)} to ${pctP(p.hi, 0)}. ${chainSrc()}.`")
sub("`Brent $${st.brent} vs $${BRENT0} pre-war. Average-effect band ${pctP(p.lo)} to ${pctP(p.hi)}; single moves vary more."
    "${d ? ` Past supply shocks: ${pctP(d.lo)} to ${pctP(d.hi)}.` : \"\"} ${m.oil.series}.${m.oil.extra ? ` ${m.oil.extra}` : \"\"}`",
    "`Brent $${st.brent} vs $${BRENT0} pre-war, 12 months on. Range ${pctP(p.lo)} to ${pctP(p.hi)}."
    "${d ? ` Past supply shocks: ${pctP(d.lo)} to ${pctP(d.hi)}.` : \"\"} Source: past US price moves (FRED, 2001–2026)."
    "${m.oil.extra ? \" In the 2026 closure, prices rose faster than this.\" : \"\"}`")

# ---------------------------------------------------------------- info sheets (Strait view)
entry("INFO", "sim", r'''    sim: () => ({ title: "Simulated data", html: `<p>The ships, names and radar passes in the Strait view are <b>made up</b>. Each scenario is set so the true flow matches a published figure; the estimate then sees only what ship tracking (AIS) and two radar passes would show.</p>
      <p>Why not real ships: there are no free AIS receivers covering Hormuz, and free radar passes are days apart. The PortWatch cards are real.</p>
      <p class="mono">Scenarios generated ${sc.generated}</p>` }),''')
entry("INFO", "estimate", r'''    estimate: () => ({ title: "How the flow is estimated", html: `<ul>
        <li><b>Seen on AIS:</b> loaded tankers whose tracking crosses the dashed line. Impossible jumps (fake positions) are dropped.</li>
        <li><b>AIS off mid-crossing:</b> tracking stops on one side of the line and comes back on the other.</li>
        <li><b>Never on AIS:</b> ships radar sees with no tracking match, turned into a daily rate.</li></ul>
        <p>The range comes from thousands of runs over what we can't know exactly: how full ships are, how many ships radar misses, and their speed.</p>
        <p>The ✓ figure is the true value, known only because the ships are simulated.</p>` }),''')
entry("INFO", "global", r'''    global: () => ({ title: "Global figures", html: `<ul>
        <li>World oil demand 2026: 103.3 mb/d (IEA, Aug 2026)</li>
        <li>Pre-war Hormuz flow: 20 mb/d, about 20% of world use (EIA, 2024 average)</li></ul>
        <p>Published 2026 estimates, as reported (check before quoting):</p><ul>
        ${sc.published.map((p) => `<li>${p.who}, ${p.when}: ${fmt(p.mbd)} mb/d</li>`).join("")}</ul>` }),''')

# PortWatch: drop the refresh instruction aimed at developers
sub("This page can't reach PortWatch itself, so the numbers are a cached snapshot. To refresh, query <code>Daily_Chokepoints_Data</code> with <code>portid='chokepoint6'</code>.",
    "These numbers are a saved copy, not live.")

# ---------------------------------------------------------------- info sheets (World view)
entry("WINFO", "materials", r'''    materials: { title: "Products and who makes them", html: `<p>Pick a product from the icons or the search (try "urea", "kerosene" or "plastic"). The map shows who makes it, or who ships it. Gulf producers whose exports pass the strait are outlined in amber. Click a country to see what it makes, where its inputs come from and where it ships.</p>
      <ul><li><b>Price in 12 months:</b> jet fuel, fertiliser and plastics from the team's oil-shock model; steel and aluminium from past US price moves (FRED). Ranges are 90% bands.</li>
      <li><b>What it costs buyers:</b> the product's share of a buyer's costs × its price change. Shares are sourced for airlines (IATA) and farming (CIBC); others show "no data".</li>
      <li><b>Who makes and ships it:</b> worldsteel, USGS, IEA and others as cited for each product, collected 24 Oct 2026. Check at source before quoting.</li></ul>
      <p class="faint">Map: globe.gl and flag-icons (MIT licence), Natural Earth. Nothing here is live.</p>` },''')
entry("WINFO", "model", r'''    model: { title: "How the world view works", html: `<p>You choose how much of the normal Hormuz flow is lost. The oil price follows from a curve fitted to the 2026 closure and checked against the 2023–24 Red Sea disruption; the knock-ons come from the team's oil-shock model, fitted to data up to early 2026.</p>
      <ul><li><b>Lines:</b> tanker routes from the strait. Faint lines show pre-war volume, bright lines today's estimated flow.</li>
      <li><b>Fuel cost:</b> the US link from oil to pump prices (about 5–7% per 10% oil rise), plus an extra premium for countries that got their oil through Hormuz. That premium is set by hand, not fitted.</li>
      <li><b>Industries:</b> fuel's share of costs × the fuel price change. Airlines 25% (IATA), shipping 22% (Maersk), trucking 21% (ATRI).</li>
      <li><b>Forecast chart:</b> the base case closes the gap over the year; the band runs from a quick reopening to a year-long closure.</li></ul>
      <p>Country volumes: EIA 2024 and Energy Institute. A teaching model: check figures before quoting.</p>` },''')
entry("WINFO", "score", r'''    score: { title: "Exposure score", html: `<p>One number per country for how hard the shock hits it. Above zero means hurt; below zero means it gains.</p>
      <ul><li><b>Importers:</b> how much more fuel costs × how much of their oil they import.</li>
      <li><b>Exporters outside the Gulf</b> (Norway, Canada, Nigeria and others) gain from the higher price.</li>
      <li><b>Gulf producers</b> are hurt by the oil they can't ship out.</li></ul>
      <p class="illus-note"><b>Illustrative:</b> the weights are set by hand, not fitted to data. Inputs: EIA 2024 Hormuz volumes and Energy Institute consumption. Countries without their own data use a typical importer.</p>` },''')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
