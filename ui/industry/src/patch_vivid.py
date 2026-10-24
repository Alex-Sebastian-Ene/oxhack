# Runs after patch_colors.py on hormuz-flow.html.
# Light-blue sea in both views; each product gets its own vivid colour tied to what it is,
# and Gulf producers that ship through Hormuz keep amber as an outline instead of a fill.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- sea: light blue, the same in both views
SEA = "#a8d8f8"
sub("--sea: #d3e4f3;", f"--sea: {SEA};")
sub("--sea-ink: #5d7c97;", "--sea-ink: #1f5f8f;")
# the globe's ocean glows a little so the lit sphere shows the same blue as the flat map
sub('    G3.globeMaterial().color.set("#12304d");',
    f'    G3.globeMaterial().color.set("{SEA}"); G3.globeMaterial().emissive.set("{SEA}"); G3.globeMaterial().emissiveIntensity = 0.08;')
# the flat map sits on the same starry space as the globe, outside the map's outline
sub("  function initGlobe() {",
    '  { const mw = document.querySelector("#world-stage .mapwrap"); if (mw) mw.style.background = `url(${starfield()}) center / cover, radial-gradient(ellipse at 50% 45%, #0f1d33 0%, #060b16 70%)`; }\n'
    "  function initGlobe() {")
sub('"rgba(255,255,255,0.72)" : x.tier === 1 ? "rgba(150,190,230,0.7)" : "rgba(150,190,230,0.85)"',
    '"rgba(20,32,46,0.75)" : x.tier === 1 ? "rgba(26,84,130,0.75)" : "rgba(26,84,130,0.9)"')
# on the light ocean the selection goes back to ink
sub('"rgba(255,255,255,0.42)" : "rgba(8,20,36,0.55)"', '"rgba(20,32,46,0.6)" : "rgba(50,80,110,0.3)"')
sub('.polygonStrokeColor((f) => (f.properties.name === st.sel ? "#ffffff" : "rgba(255,255,255,0.55)"))',
    '.polygonStrokeColor((f) => (f.properties.name === st.sel ? "#14202e" : st.mat && VIA[f.properties.name] ? "#e06a00" : "rgba(255,255,255,0.8)"))')
sub("`rgba(255,255,255,${1 - t})`", "`rgba(20,32,46,${1 - t})`")
sub('.polygonCapColor((f) => { const c = fillFor(f.properties.name); return c === "#eceff3" ? "#56657a" : c; })',
    '.polygonCapColor((f) => fillFor(f.properties.name))')

# ---------------------------------------------------------------- one vivid colour per product
HUE_JS = '''  // each product has its own colour, picked to match the thing: steel blue, jet-fuel flame, aluminium can,
  // fertiliser green, plastic magenta. Light = small producer, deep = large.
  const HUE = { steel: "#3f5bd8", jet_fuel: "#ff6a13", aluminium: "#0aa5c8", fertiliser: "#27ae3f", polyethylene: "#e0279a" };
  const hueOf = (id) => HUE[id] || "#3f5bd8";
  function rampOf(id) {
    const h = hueOf(id);
    return d3.scaleLinear().domain([0, 0.55, 1]).range([d3.interpolateLab("#ffffff", h)(0.32), h, d3.hsl(h).darker(0.9).formatHex()]).interpolate(d3.interpolateLab);
  }
'''
sub("  function matShade(name) {", HUE_JS + "  function matShade(name) {")
sub('    return VIA[name] ? d3.interpolateLab("#fdd8a5", "#e06a00")(f) : d3.interpolateLab("#c4ddf6", "#0a5bb5")(f);',
    "    return rampOf(st.mat)(f);")
sub('background:${VIA[n] ? "#e06a00" : "#0a5bb5"}', 'background:${hueOf(st.mat)};${VIA[n] ? "box-shadow:inset 0 0 0 2px #e06a00" : ""}')
sub('      $("wgrad").style.background = "linear-gradient(90deg, #c4ddf6, #0a5bb5 55%, #fdd8a5 55%, #e06a00)";\n'
    '      $("wticks").innerHTML = \'<span style="left:0;transform:none">smaller</span><span style="left:30%">larger</span><span style="left:56%;transform:none">Gulf: via Hormuz</span>\';',
    '      const r = rampOf(st.mat);\n'
    '      $("wgrad").style.background = `linear-gradient(90deg, ${r(0)}, ${r(0.55)} 55%, ${r(1)})`;\n'
    '      $("wticks").innerHTML = \'<span style="left:0;transform:none">smaller</span><span style="left:100%;transform:translateX(-100%)">larger producer</span><span class="viarow"><i class="viakey"></i>amber edge: Gulf producer, ships via Hormuz</span>\';')
# flat map: Gulf producers carry the amber outline while a product is chosen
sub('ctryPaths.attr("fill", (c) => (c.properties.name === st.sel ? "#aab5c2" : fillFor(c.properties.name))).classed("sel", (c) => c.properties.name === st.sel);',
    'ctryPaths.attr("fill", (c) => (c.properties.name === st.sel ? "#aab5c2" : fillFor(c.properties.name))).classed("sel", (c) => c.properties.name === st.sel)\n'
    '      .classed("via", (c) => !!(st.mat && VIA[c.properties.name]));')
# the rail button of the chosen product takes its colour (a deeper shade so white text stays readable)
sub('    $("mrail").querySelectorAll("[data-mat]").forEach((b) => b.addEventListener(',
    '    $("mrail").querySelectorAll("[data-mat]").forEach((b) => b.style.setProperty("--hue", d3.hsl(hueOf(b.dataset.mat)).darker(0.45).formatHex()));\n'
    '    $("mrail").querySelectorAll("[data-mat]").forEach((b) => b.addEventListener(')

# ---------------------------------------------------------------- exposure: stronger red and teal
sub('const STOPS = [[-40, "#00a38c"], [-15, "#8fd9cb"], [0, "#dde3ea"], [10, "#fcd5c8"], [25, "#f59a7f"], [40, "#e45a3f"], [65, "#b3201a"]];',
    'const STOPS = [[-40, "#00a88f"], [-15, "#4fd1b6"], [0, "#dfe5ec"], [10, "#ffb59c"], [25, "#ff7b55"], [40, "#ee3b2b"], [65, "#b8100c"]];')

# ---------------------------------------------------------------- pop-up docks in a corner instead of over the map
sub('''    let x0 = xy[0] - 70, x1 = xy[0] + 70, yc = xy[1];
    const lp = st.wview === "flat" && document.querySelector("#world path.lift");
    if (lp) { const r = lp.getBoundingClientRect(), o = wrap.getBoundingClientRect(); if (r.width) { x0 = r.left - o.left; x1 = r.right - o.left; yc = r.top - o.top + r.height / 2; } }
    let left = x1 + 14, top = yc - ph / 2;
    if (left + pw > W - 56) left = x0 - pw - 14;''',
'''    // the selected country's box on screen (flat: the lifted shape; 3D: around its centre and tag)
    const o = wrap.getBoundingClientRect();
    let box = { l: xy[0] - 80, r: xy[0] + 80, t: xy[1] - 60, b: xy[1] + 40 };
    const lp = st.wview === "flat" && document.querySelector("#world path.lift");
    if (lp) { const r = lp.getBoundingClientRect(); if (r.width) box = { l: r.left - o.left, r: r.right - o.left, t: r.top - o.top - 40, b: r.bottom - o.top }; }
    // things the pop-up must not cover: the legend, the zoom buttons, the product rail
    const avoid = [box];
    for (const sel of [".legendbar", ".zoomw", "#mrail", ".viewseg"]) {
      const el = wrap.querySelector(sel); if (!el || el.hidden) continue;
      const r = el.getBoundingClientRect(); if (r.width) avoid.push({ l: r.left - o.left, r: r.right - o.left, t: r.top - o.top, b: r.bottom - o.top });
    }
    const hits = (l, t) => avoid.reduce((n, a) => n + Math.max(0, Math.min(l + pw, a.r) - Math.max(l, a.l)) * Math.max(0, Math.min(t + ph, a.b) - Math.max(t, a.t)), 0);
    const spots = [[W - pw - 10, H - ph - 10], [W - pw - 10, 120], [10, 120], [(W - pw) / 2, H - ph - 10], [10, H - ph - 10]];
    let [left, top] = spots[0], best = Infinity;
    for (const [l, t] of spots) { const h = hits(l, t); if (h < best) { best = h; left = l; top = t; } if (!h) break; }''')
sub('''    left = Math.min(Math.max(8, left), W - pw - 8);
    top = Math.min(Math.max(64, top), H - ph - 8);''',
'''    left = Math.min(Math.max(8, left), W - pw - 8);
    top = Math.min(Math.max(8, top), H - ph - 8);''')

CSS = """
#world .ctry.via { stroke: #e06a00; stroke-width: 1.8; }
.legendbar .ticks .viarow { position: static; display: block; transform: none; margin-top: 16px; font-family: var(--sans); color: var(--muted); }
.legendbar .ticks:has(.viarow) { height: auto; min-height: 30px; }
.viakey { display: inline-block; width: 9px; height: 9px; margin-right: 4px; vertical-align: -1px; border: 2px solid #e06a00; border-radius: 2px; }
.mrail button[aria-pressed="true"] { background: var(--hue, var(--text)); border-color: var(--hue, var(--text)); }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
