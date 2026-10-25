# Runs after patch_vivid.py on hormuz-flow.html.
# Where each line ends now blinks (oil routes: the buyer's port; arcs: the receiving country),
# and the 3D globe draws the same Hormuz oil routes as the flat map.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- flat map
sub('  const gFl = root.append("g").attr("aria-hidden", "true");',
    '  const gFl = root.append("g").attr("aria-hidden", "true");\n'
    '  const gPulse = root.append("g").attr("aria-hidden", "true").style("pointer-events", "none");')
sub("gH.raise(); gFl.raise();", "gH.raise(); gPulse.raise(); gFl.raise();")
sub('    gLift.selectAll("path").attr("stroke-width", 1.6);',
    '    gLift.selectAll("path").attr("stroke-width", 1.6);\n'
    '    gPulse.selectAll("circle").attr("r", (d) => d.r / k);')
PULSE_JS = r'''  // the end of every line blinks: oil routes at the buyer's port, arcs at the receiving country
  function endsOf() {
    if (st.mat) {
      const seen = new Map();
      for (const a of arcsFor()) if (!seen.has(a.to)) seen.set(a.to, { lng: where[a.to].lng, lat: where[a.to].lat, color: a.color });
      return [...seen.values()];
    }
    const own = st.sel && C[st.sel] && C[st.sel].r;
    return Object.entries(C).filter(([n, d]) => d.r && d.h && (!own || n === st.sel))
      .map(([, d]) => { const e = d.r[d.r.length - 1]; return { lng: e[0], lat: e[1], color: "#e06a00" }; });
  }
  function drawPulses() {
    const ends = endsOf(), k = (svgEl.node().__zoom || { k: 1 }).k;
    const g = gPulse.selectAll("g.blink").data(ends).join((en) => {
      const e = en.append("g").attr("class", "blink");
      e.append("circle").attr("class", "blink-ring");
      e.append("circle").attr("class", "blink-core");
      return e;
    });
    g.each(function (d, i) {
      const [x, y] = proj([d.lng, d.lat]), n = d3.select(this);
      n.select(".blink-ring").datum({ r: 3.2 }).attr("cx", x).attr("cy", y).attr("r", 3.2 / k).attr("stroke", d.color).style("animation-delay", `${(i % 5) * 0.28}s`);
      n.select(".blink-core").datum({ r: 2.6 }).attr("cx", x).attr("cy", y).attr("r", 2.6 / k).attr("fill", d.color);
    });
  }
'''
sub("  function drawLift() {", PULSE_JS + "  function drawLift() {")
sub("    drawFlatArcs();\n    drawLift();\n    paint3d();\n  }", "    drawFlatArcs();\n    drawLift();\n    drawPulses();\n    paint3d();\n  }")
sub("    drawFlatArcs();\n    drawLift();\n    rescale();\n  }", "    drawFlatArcs();\n    drawLift();\n    drawPulses();\n    rescale();\n  }")

# ---------------------------------------------------------------- 3D globe: same routes, same blinking ends
sub('''    G3.ringsData(w ? [w] : [{ lat: 26.5, lng: 56.4 }]).ringColor(() => (t) => (w ? `rgba(20,32,46,${1 - t})` : `rgba(194,111,18,${1 - t})`)).ringMaxRadius(w ? 5 : 3).ringPropagationSpeed(2).ringRepeatPeriod(1200);''',
'''    const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)).join(",");
    const rings = [w ? { lat: w.lat, lng: w.lng, color: "#14202e", max: 5 } : { lat: 26.5, lng: 56.4, color: "#c26f12", max: 3 },
      ...endsOf().map((e) => ({ ...e, max: 2.4 }))];
    G3.ringsData(rings).ringColor((d) => (t) => `rgba(${rgb(d.color)},${1 - t})`).ringMaxRadius((d) => d.max).ringPropagationSpeed(2.2).ringRepeatPeriod(1100);
    const own = st.sel && C[st.sel] && C[st.sel].r;
    G3.pathsData(st.mat ? [] : Object.entries(C).filter(([, d]) => d.r && d.h).map(([n, d]) => ({ n, pts: d.r.map(([lng, lat]) => [lat, lng]), on: !own || n === st.sel })))
      .pathPoints("pts").pathPointAlt(0.004).pathStroke((d) => (d.on ? 1.6 : 0.6))
      .pathColor((d) => (d.on ? ["rgba(224,106,0,0.35)", "#e06a00"] : ["rgba(224,106,0,0.12)", "rgba(224,106,0,0.25)"]))
      .pathDashLength(0.06).pathDashGap(0.02).pathDashAnimateTime(9000).pathTransitionDuration(0);''')

# ---------------------------------------------------------------- the legend says what the lines are
sub(': `Hormuz oil flow now · ${(f * 100).toFixed(0)}% of pre-war (faint)`;',
    ': `Oil routes out of Hormuz, blinking where they land · flow now ${(f * 100).toFixed(0)}% of pre-war`;')
sub('"Arcs: where its ingredients come from"', '"Arcs: where its ingredients come from, blinking where they land"')
sub('"Trade flows to and from the chosen country"', '"Trade flows of this product, blinking at the buyer"')

CSS = """
#world .blink-ring { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; transform-box: fill-box; transform-origin: center; animation: blink 1.5s ease-out infinite; }
#world .blink-core { stroke: #ffffff; stroke-width: 1.2; vector-effect: non-scaling-stroke; }
@keyframes blink { 0% { transform: scale(1); opacity: .95; } 80%, 100% { transform: scale(3.6); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { #world .blink-ring { animation: none; opacity: .6; transform: scale(1.8); } }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

# ---------------------------------------------------------------- every line is yellow, a colour nothing else uses
# Only one kind of line shows at a time (oil routes, ingredient arcs or trade arcs), and the legend names it.
# A thin dark edge keeps yellow readable on the light sea and on orange or green countries.
Y, Y2, Y3 = "#ffd60a", "#ffe866", "#fff3a6"
sub('  const VIOLET = ["#6d28d9", "#9b6cf0", "#c4a8fb"];', f'  const VIOLET = ["{Y}", "{Y2}", "{Y3}"];')
sub('add(f.from, f.to, "#0a6fd6",', f'add(f.from, f.to, "{Y}",')
sub('["rgba(224,106,0,0.35)", "#e06a00"] : ["rgba(224,106,0,0.12)", "rgba(224,106,0,0.25)"]',
    f'["rgba(255,214,10,0.45)", "{Y}"] : ["rgba(255,214,10,0.15)", "rgba(255,214,10,0.3)"]')
sub('return { lng: e[0], lat: e[1], color: "#e06a00" };', f'return {{ lng: e[0], lat: e[1], color: "{Y}" }};')
sub('fk.style.borderTopColor = st.mat ? (st.mode === "exports" ? "#0a6fd6" : "#6d28d9") : "";', f'fk.style.borderTopColor = "{Y}";')
sub("blue = supply of the chosen material (producers, exporters, trade flows) · violet = where a country's ingredients come from",
    "each product its own colour (steel blue, jet-fuel orange, aluminium cyan, fertiliser green, plastic magenta) · yellow = every line: oil routes out of Hormuz, or where ingredients and trade go, blinking where they land")
CSS2 = f"""
#world .route {{ stroke: #fffbe6; opacity: 1; }}
#world .route-base {{ stroke: rgba(255,214,10,0.75); filter: drop-shadow(0 0 1px rgba(20,32,46,.85)); }}
#world .route-base.hi {{ stroke: {Y}; }}
#world .arc {{ filter: drop-shadow(0 0 1.2px rgba(20,32,46,.9)); }}
#world .route.dim {{ opacity: .3; }}
.legendbar .flowkey i {{ border-top-color: {Y} !important; filter: drop-shadow(0 0 1px rgba(20,32,46,.9)); }}
"""
sub('</style>\n<div class="app">', CSS2 + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
