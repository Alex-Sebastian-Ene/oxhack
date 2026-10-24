"""Colour roles (one colour, one meaning) and sea labels. Runs on the output of patch_world2.py."""
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- exposure = harm (red ramp) / gain (teal), never amber
sub('const STOPS = [[-40, "#2a9d8f"], [-15, "#8fcfc3"], [0, "#d3dae3"], [10, "#f1d9a8"], [25, "#efad55"], [40, "#e8833a"], [65, "#d9472f"]];',
    'const STOPS = [[-40, "#2a9d8f"], [-15, "#8fcfc3"], [0, "#d3dae3"], [10, "#f3d3ca"], [25, "#e8a493"], [40, "#d8705c"], [65, "#b23a2e"]];')
sub(':root { --hurt: #e2553d; --gain: #2a9d8f; --gain-soft: #1f7a6f; --neutral: #d3dae3; }',
    ':root { --hurt: #e2553d; --gain: #2a9d8f; --gain-soft: #1f7a6f; --neutral: #d3dae3; --harm: #b23a2e; --ink-sel: #e7ecf2; --violet: #6d4fc2; --sea-ink: #5d7c97; }')
sub('.hurt { color: var(--oil-soft); }', '.hurt { color: var(--harm); }')
# a Gulf producer's tag is about oil through the strait, so amber
sub('.tag.gulf { border-color: var(--hurt); color: #c4402a; }', '.tag.gulf { border-color: var(--oil); color: var(--oil-soft); }')

# ---------------------------------------------------------------- UI selection = ink, never a data colour
sub('.seg button[aria-pressed="true"] { border-color: var(--oil); color: var(--oil-soft); background: #fbecd6; }',
    '.seg button[aria-pressed="true"] { border-color: var(--text); color: var(--text); background: var(--ink-sel); font-weight: 600; }')
sub('button:focus-visible, select:focus-visible, canvas:focus-visible { outline: 2px solid var(--oil); outline-offset: 2px; }',
    'button:focus-visible, select:focus-visible, canvas:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }')
sub('.label svg { color: var(--oil); }', '.label svg { color: var(--muted); }')
sub('.pill.sim { background: transparent; border-color: var(--oil); color: var(--oil-soft); }',
    '.pill.sim { background: transparent; border-color: var(--muted); border-style: dashed; color: var(--muted); }')

ROLES = """
/* Colour roles: amber = oil and Hormuz · red = harm (exposure, cost rises) · teal = gain · blue = supply of the chosen
   material (producers, exporters, trade flows) · violet = ingredient routes · ink = what you selected · grey = no data.
   The Strait view keeps its ship colours: blue = seen on AIS, amber = dark tanker (oil moving unseen). */
.viewseg button[aria-pressed="true"], .mrail button[aria-pressed="true"], .mseg button[aria-pressed="true"], #pw-replay[aria-pressed="true"] { border-color: var(--text); color: var(--text); background: var(--ink-sel); }
.mrail button[aria-pressed="true"] svg, .mrail button svg { color: var(--text); }
.mrail button[aria-pressed="true"] span:not(.d) { font-weight: 600; }
.mhead .mi { background: var(--ink-sel); color: var(--text); }
.tmat .th svg { color: var(--text); }
.pbars button[aria-current="true"], .rank button[aria-current="true"] { background: var(--ink-sel); box-shadow: inset 2px 0 0 var(--text); }
.timebar input, #pw-day { accent-color: var(--text); }
.psearch input:focus-visible { outline-color: var(--text); }
#world .sea { fill: var(--sea-ink); font-family: var(--sans); font-style: italic; letter-spacing: .4px; paint-order: stroke; stroke: var(--sea); stroke-width: 3px; pointer-events: none; text-anchor: middle; }
#world .sea.ocean { letter-spacing: 2.5px; text-transform: uppercase; font-style: normal; font-weight: 500; opacity: .8; }
.ichip .dot.ing { background: var(--violet); }
#world .cont { fill: var(--text); opacity: .5; font-family: var(--sans); font-weight: 600; letter-spacing: 3px; text-anchor: middle; paint-order: stroke; stroke: rgba(255,255,255,.75); stroke-width: 3px; pointer-events: none; }
/* 3D hover labels: globe.gl wraps them in its own tooltip box with light text; use our card and dark text instead */
.wtip { color: var(--text); box-shadow: 0 4px 14px rgba(20,32,46,.12); }
.float-tooltip-kap { background: transparent !important; padding: 0 !important; color: var(--text) !important; border-radius: 0 !important; box-shadow: none !important; }
"""
sub('</style>\n<div class="app">', ROLES + '</style>\n<div class="app">')

# ---------------------------------------------------------------- ingredient arcs and chips = violet (shades by ingredient)
sub('  const icon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[k] || ""}</svg>`;',
    '  const icon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[k] || ""}</svg>`;\n'
    '  // ingredient routes are violet: one shade per ingredient of the chosen material (a material has at most three)\n'
    '  const VIOLET = ["#5b3fb5", "#8d6fd6", "#b9a6ec"];\n'
    '  const ingColor = (m, id) => VIOLET[Math.max(0, m.inputs.indexOf(id)) % VIOLET.length];')
sub('        add(l.from, l.to, inp ? inp.color : "#8a96a3", l.share, `${inp ? inp.name : l.input}: ${nmIso(l.from)} → ${nmIso(l.to)} ${Math.round(l.share * 100)}%`);',
    '        add(l.from, l.to, ingColor(m, l.input), l.share, `${inp ? inp.name : l.input}: ${nmIso(l.from)} → ${nmIso(l.to)} ${Math.round(l.share * 100)}%`);')
sub('<span class="dot" style="background:${inp ? inp.color : "#8a96a3"}"></span>${flagIm',
    '<span class="dot" style="background:${ingColor(m, l.input)}"></span>${flagIm')

# ---------------------------------------------------------------- 3D: selection is ink, Hormuz stays amber
# the selected country floats: it keeps its data colour, rises with dark sides, and carries a flag name tag
sub('    G3.polygonCapColor((f) => (f.properties.name === st.sel ? "#ffd89a" : fillFor(f.properties.name)))',
    '    G3.polygonCapColor((f) => { const c = fillFor(f.properties.name); return c === "#eceff3" ? "#56657a" : c; })\n'
    '      .polygonSideColor((f) => (f.properties.name === st.sel ? "rgba(20,32,46,0.62)" : "rgba(90,110,130,0.25)"))\n'
    '      .polygonStrokeColor((f) => (f.properties.name === st.sel ? "#14202e" : "rgba(255,255,255,0.85)"))')
# one height rule for every country: all sit flat, only the clicked one rises (share is shown by colour, not height)
sub("0.006 + (s3[f.properties.name] ? 0.1 * Math.sqrt(s3[f.properties.name] / max) : 0) + (f.properties.name === st.sel ? 0.02 : 0));",
    "(f.properties.name === st.sel ? 0.085 : 0.006));")
sub("alt: 0.02 + (s3[p.name] ? 0.1 * Math.sqrt(s3[p.name] / max) : 0),", "alt: p.name === st.sel ? 0.1 : 0.02,")
# re-place the pop-up once the globe or flat map has settled after a view switch
sub("if (G3 && G3.resumeAnimation) G3.resumeAnimation(); paint3d(); }",
    "if (G3 && G3.resumeAnimation) G3.resumeAnimation(); paint3d(); setTimeout(placePop, 60); setTimeout(placePop, 900); }")
sub("if (G3 && G3.pauseAnimation) G3.pauseAnimation(); layout(); }",
    "if (G3 && G3.pauseAnimation) G3.pauseAnimation(); layout(); setTimeout(placePop, 60); }")
sub('ctryPaths.attr("fill", (c) => fillFor(c.properties.name))', 'ctryPaths.attr("fill", (c) => (c.properties.name === st.sel ? "#aab5c2" : fillFor(c.properties.name)))')
LIFT_JS = r'''  // Flat map: the selected country lifts off the map (its place turns slate) and a flag name tag floats over it
  function drawLift() {
    const f = st.sel && countries.find((c) => c.properties.name === st.sel);
    gLift.selectAll("path").data(f ? [f] : [], (d) => d.properties.name)
      .join((en) => en.append("path").attr("class", "lift"))
      .attr("d", gpath).attr("fill", fillFor(st.sel || ""))
      .on("click", () => select(st.sel)).style("cursor", "pointer");
    const iso = st.sel && isoOf[st.sel], w = iso && where[iso];
    let at = null;
    if (f) { const b = gpath.bounds(f), c = gpath.centroid(f); at = { x: c[0], y: Math.max(b[0][1] - 8, 14) }; }
    else if (w) { const p = proj([w.lng, w.lat]); at = { x: p[0], y: p[1] - 10 }; }
    const label = st.sel === "United States of America" ? "United States" : st.sel;
    const g = gFl.selectAll("g.flabel").data(at ? [{ ...at, label, iso }] : [], (d) => d.label).join((en) => {
      const e = en.append("g").attr("class", "flabel");
      e.append("rect").attr("class", "fl-bg");
      e.append("image").attr("class", "fl-flag");
      e.append("text").attr("class", "fl-name");
      e.append("path").attr("class", "fl-tip");
      return e;
    });
    g.each(function (d) {
      const n = d3.select(this), hasFlag = !!FLAGS[d.iso], tw = d.label.length * 7.4, wd = tw + (hasFlag ? 44 : 22);
      n.select(".fl-bg").attr("x", -wd / 2).attr("y", -36).attr("width", wd).attr("height", 26).attr("rx", 13);
      n.select(".fl-flag").attr("href", hasFlag ? FLAGS[d.iso] : null).attr("x", -wd / 2 + 10).attr("y", -30).attr("width", 20).attr("height", 14).attr("preserveAspectRatio", "xMidYMid slice").style("display", hasFlag ? null : "none");
      n.select(".fl-name").attr("x", -wd / 2 + (hasFlag ? 36 : 11)).attr("y", -18.5).text(d.label);
      n.select(".fl-tip").attr("d", "M-6 -10.5 L0 -4 L6 -10.5 Z");
    });
    rescale();
  }
'''
sub("  function drawFlatArcs() {", LIFT_JS + "  function drawFlatArcs() {")
LIFT_CSS = """
#world .lift { stroke: #14202e; vector-effect: non-scaling-stroke; filter: drop-shadow(0 7px 6px rgba(20,32,46,.38)); transform: translate(0, -4px); animation: liftup .35s cubic-bezier(.2,.8,.2,1) both; }
@keyframes liftup { from { transform: translate(0, 0); filter: drop-shadow(0 0 0 rgba(20,32,46,0)); } to { transform: translate(0, -4px); filter: drop-shadow(0 7px 6px rgba(20,32,46,.38)); } }
#world .flabel { pointer-events: none; animation: tagin .3s ease-out both; }
@keyframes tagin { from { opacity: 0; } to { opacity: 1; } }
#world .fl-bg, #world .fl-tip { fill: #14202e; }
#world .fl-name { fill: #ffffff; font: 600 12px var(--sans); }
#world .fl-flag { clip-path: inset(0 round 2px); }
.glabel { display: flex; align-items: center; gap: 6px; padding: 4px 11px 4px 8px; border-radius: 999px; background: #14202e; color: #ffffff; font: 600 12px var(--sans); white-space: nowrap; box-shadow: 0 6px 16px rgba(20,32,46,.32); transform: translate(-50%, -140%); pointer-events: none; }
.glabel .flag { width: 20px; height: 14px; box-shadow: none; }
@media (prefers-reduced-motion: reduce) { #world .lift, #world .flabel { animation: none; } }
"""
sub('</style>\n<div class="app">', LIFT_CSS + '</style>\n<div class="app">')
sub("    G3.ringsData(w ? [w] : [{ lat: 26.5, lng: 56.4 }]).ringColor(() => (t) => `rgba(194,111,18,${1 - t})`).ringMaxRadius(w ? 5 : 3).ringPropagationSpeed(2).ringRepeatPeriod(1200);",
    "    G3.ringsData(w ? [w] : [{ lat: 26.5, lng: 56.4 }]).ringColor(() => (t) => (w ? `rgba(20,32,46,${1 - t})` : `rgba(194,111,18,${1 - t})`)).ringMaxRadius(w ? 5 : 3).ringPropagationSpeed(2).ringRepeatPeriod(1200);\n"
    "    const tagIso = st.sel && isoOf[st.sel];\n"
    "    G3.htmlElementsData(w ? [{ lat: w.lat, lng: w.lng, iso: tagIso, name: st.sel === \"United States of America\" ? \"United States\" : st.sel }] : [])\n"
    "      .htmlLat((d) => d.lat).htmlLng((d) => d.lng).htmlAltitude(0.1)\n"
    "      .htmlElement((d) => { const el = document.createElement(\"div\"); el.className = \"glabel\"; el.innerHTML = `${d.iso ? flagImg(d.iso) : \"\"}<span>${escH(d.name)}</span>`; return el; });")

# ---------------------------------------------------------------- sea and ocean labels (tier 1 always; higher tiers as you zoom)
SEAS = '''  const SEAS = [
    { name: "Pacific Ocean", lng: -128, lat: 12, tier: 1 }, { name: "Pacific Ocean", lng: 165, lat: 18, tier: 1, flatOnly: true },
    { name: "Atlantic Ocean", lng: -38, lat: 24, tier: 1 }, { name: "Indian Ocean", lng: 78, lat: -20, tier: 1 },
    { name: "Southern Ocean", lng: 60, lat: -60, tier: 1 }, { name: "Arctic Ocean", lng: 20, lat: 80, tier: 1, globeOnly: true },
    { name: "Arabian Sea", lng: 64.5, lat: 15.5, tier: 2 }, { name: "Mediterranean Sea", lng: 18, lat: 34.2, tier: 2 },
    { name: "Bay of Bengal", lng: 88.5, lat: 14.5, tier: 2 }, { name: "South China Sea", lng: 114, lat: 13, tier: 2 },
    { name: "Red Sea", lng: 38.3, lat: 20.5, tier: 3 }, { name: "Black Sea", lng: 34.5, lat: 43.3, tier: 3 },
    { name: "North Sea", lng: 3.5, lat: 56.3, tier: 3 }, { name: "Gulf of Aden", lng: 48.5, lat: 12.4, tier: 3 },
    { name: "Persian Gulf", lng: 51.2, lat: 27.3, tier: 4 }, { name: "Gulf of Oman", lng: 58.8, lat: 24.3, tier: 4 },
  ];
  // Continents: upright spaced capitals in ink, so they never read as water (seas are italic blue-grey)
  const CONTS = [
    { name: "North America", lng: -100, lat: 47 }, { name: "South America", lng: -60, lat: -14 },
    { name: "Europe", lng: 15, lat: 52 }, { name: "Africa", lng: 19, lat: 6 }, { name: "Asia", lng: 92, lat: 50 },
    { name: "Oceania", lng: 134, lat: -25 }, { name: "Antarctica", lng: 0, lat: -80, globeOnly: true },
  ];
'''
sub('  const gRB = root.append("g"), gR = root.append("g"), gArc = root.append("g"), gP = root.append("g"), gH = root.append("g");',
    SEAS + '  const gLift = root.append("g").attr("aria-hidden", "true");\n'
    '  const gSea = root.append("g").attr("aria-hidden", "true"), gCont = root.append("g").attr("aria-hidden", "true");\n'
    '  const gRB = root.append("g"), gR = root.append("g"), gArc = root.append("g"), gP = root.append("g"), gH = root.append("g");\n'
    '  const gFl = root.append("g").attr("aria-hidden", "true");')
sub('    gP.raise(); dotEls.raise(); gH.raise();\n    drawFlatArcs();\n    rescale();',
    '    gSea.selectAll("text").data(SEAS.filter((x) => !x.globeOnly)).join("text").attr("class", (x) => `sea${x.tier === 1 ? " ocean" : ""}`)\n'
    '      .attr("x", (x) => proj([x.lng, x.lat])[0]).attr("y", (x) => proj([x.lng, x.lat])[1]).text((x) => x.name);\n'
    '    gCont.selectAll("text").data(CONTS.filter((x) => !x.globeOnly)).join("text").attr("class", "cont")\n'
    '      .attr("x", (x) => proj([x.lng, x.lat])[0]).attr("y", (x) => proj([x.lng, x.lat])[1]).text((x) => x.name.toUpperCase());\n'
    '    gP.raise(); dotEls.raise(); gH.raise(); gFl.raise();\n    drawFlatArcs();\n    drawLift();\n    rescale();')
sub('    gH.select("text").attr("font-size", 12 / k).attr("transform", null);',
    '    gH.select("text").attr("font-size", 12 / k).attr("transform", null);\n'
    '    const showAt = { 1: 1, 2: 1.6, 3: 2.4, 4: 3.2 };\n'
    '    gSea.selectAll("text").attr("font-size", (x) => (x.tier === 1 ? 11 : 10.5) / k).attr("stroke-width", 3 / k)\n'
    '      .attr("display", (x) => (k >= showAt[x.tier] ? null : "none"));\n'
    '    gCont.selectAll("text").attr("font-size", 11.5 / k).attr("stroke-width", 3 / k).attr("display", k > 3.5 ? "none" : null);\n'
    '    gFl.selectAll("g.flabel").attr("transform", (d) => `translate(${d.x},${d.y}) scale(${1 / k})`);\n'
    '    gLift.selectAll("path").attr("stroke-width", 1.6);')
sub('    G3.globeMaterial().color.set("#cfe0ee");',
    '    G3.globeMaterial().color.set("#cfe0ee");\n'
    '    G3.labelsData([...SEAS.filter((x) => !x.flatOnly), ...CONTS.map((x) => ({ ...x, cont: true }))]).labelLat((x) => x.lat).labelLng((x) => x.lng)\n'
    '      .labelText((x) => (x.cont || x.tier === 1 ? x.name.toUpperCase() : x.name))\n'
    '      .labelSize((x) => (x.cont ? 2.6 : { 1: 1.5, 2: 0.9, 3: 0.65, 4: 0.5 }[x.tier])).labelDotRadius(0).labelAltitude((x) => (x.cont ? 0.03 : 0.003)).labelResolution(3)\n'
    '      .labelColor((x) => (x.cont ? "rgba(20,32,46,0.62)" : x.tier === 1 ? "rgba(93,124,151,0.7)" : "rgba(93,124,151,0.9)")).labelIncludeDot(false);')

# the legend's line sample takes the colour of the lines on the map: amber oil routes, violet ingredients, blue trade
sub('    drawFlatArcs();\n    paint3d();\n  }',
    '    const fk = $("wflowkey").previousElementSibling;\n'
    '    if (fk) fk.style.borderTopColor = st.mat ? (st.mode === "exports" ? "#1f7fc0" : "#5b3fb5") : "";\n'
    '    drawFlatArcs();\n    drawLift();\n    paint3d();\n  }')

# ---------------------------------------------------------------- the colour key, in the info sheet
sub('      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT), flag-icons 7.6.0 (MIT), Natural Earth 1:110m (public domain). Nothing here is live.</li></ul>` },',
    '      <li><b>Colours, one job each:</b> amber = oil and Hormuz (routes, the strait, Gulf producers that ship through it) · red = harm (exposure, cost rises) · teal = gain · blue = supply of the chosen material (producers, exporters, trade flows) · violet = where a country\'s ingredients come from · dark outline = what you selected · grey = no data.</li>\n'
    '      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT), flag-icons 7.6.0 (MIT), Natural Earth 1:110m (public domain). Nothing here is live.</li></ul>` },')

# ================================================================ stronger, distinct palette (same roles)
SUPPLY_LO, SUPPLY_HI = "#c4ddf6", "#0a5bb5"     # supply of the chosen material
GULF_LO, GULF_HI = "#fdd8a5", "#e06a00"         # Gulf producers whose exports pass Hormuz
sub('const STOPS = [[-40, "#2a9d8f"], [-15, "#8fcfc3"], [0, "#d3dae3"], [10, "#f3d3ca"], [25, "#e8a493"], [40, "#d8705c"], [65, "#b23a2e"]];',
    'const STOPS = [[-40, "#00a38c"], [-15, "#8fd9cb"], [0, "#dde3ea"], [10, "#fcd5c8"], [25, "#f59a7f"], [40, "#e45a3f"], [65, "#b3201a"]];')
sub('return VIA[name] ? d3.interpolateLab("#f6dcb6", "#c26f12")(f) : d3.interpolateLab("#cfe0ee", "#1f6aa3")(f);',
    f'return VIA[name] ? d3.interpolateLab("{GULF_LO}", "{GULF_HI}")(f) : d3.interpolateLab("{SUPPLY_LO}", "{SUPPLY_HI}")(f);')
sub('    if (!v) return "#e4e9ef";', '    if (!v) return "#eceff3";')
sub('"linear-gradient(90deg, #cfe0ee, #1f6aa3 55%, #f6dcb6 55%, #c26f12)"',
    f'"linear-gradient(90deg, {SUPPLY_LO}, {SUPPLY_HI} 55%, {GULF_LO} 55%, {GULF_HI})"')
sub('background:${VIA[n] ? "#c26f12" : "#1f6aa3"}', f'background:${{VIA[n] ? "{GULF_HI}" : "{SUPPLY_HI}"}}')
sub('add(f.from, f.to, "#1f7fc0",', 'add(f.from, f.to, "#0a6fd6",')
sub('(st.mode === "exports" ? "#1f7fc0" : "#5b3fb5")', '(st.mode === "exports" ? "#0a6fd6" : "#6d28d9")')
sub('  const VIOLET = ["#5b3fb5", "#8d6fd6", "#b9a6ec"];', '  const VIOLET = ["#6d28d9", "#9b6cf0", "#c4a8fb"];')
# sea: a clearer blue so land and producers stand out
sub('--sea: #dfeaf3;', '--sea: #d3e4f3;')
sub('    G3.globeMaterial().color.set("#cfe0ee");', '    G3.globeMaterial().color.set("#b9d3ea");')
sub('.atmosphereColor("#8fbde0")', '.atmosphereColor("#6fa8dc")')
sub(':root { --hurt: #e2553d; --gain: #2a9d8f; --gain-soft: #1f7a6f; --neutral: #d3dae3; --harm: #b23a2e;',
    ':root { --hurt: #e2553d; --gain: #00a38c; --gain-soft: #00806f; --neutral: #dde3ea; --harm: #c62a1e;')
sub('--violet: #6d4fc2;', '--violet: #6d28d9;')
# rail: price change coloured by direction
sub('<span class="d">${p ? pctP(p.mean, 0) : "?"}</span>', '<span class="d ${p ? (p.mean > 0.05 ? "up" : p.mean < -0.05 ? "dn" : "") : ""}">${p ? pctP(p.mean, 0) : "?"}</span>')
PAL = """
/* Stronger palette, same roles. Selected = solid ink with white text. */
.seg button[aria-pressed="true"], .viewseg button[aria-pressed="true"], .mrail button[aria-pressed="true"], .mseg button[aria-pressed="true"], #pw-replay[aria-pressed="true"] { background: var(--text); border-color: var(--text); color: #ffffff; }
.mrail button[aria-pressed="true"] svg { color: #ffffff; }
.mrail button[aria-pressed="true"] .d { color: #d6dde6; }
.mrail .d.up { color: var(--harm); font-weight: 500; } .mrail .d.dn { color: var(--gain-soft); font-weight: 500; }
.mhead .mi { background: #e6f0fb; color: #0a5bb5; }
.pbars button[aria-current="true"], .rank button[aria-current="true"] { background: #eef3f9; box-shadow: inset 3px 0 0 var(--text); }
#world .ctry.sel { stroke: #14202e; stroke-width: 2.2; }
#world .route { stroke: #e06a00; }
#world .route-base { stroke: rgba(224,106,0,0.28); }
#world .route-base.hi { stroke: rgba(224,106,0,0.7); }
#world .hz, #world .src, #world .port { fill: #e06a00; }
#world .hzlabel { fill: #b35400; }
.price input { accent-color: #e06a00; }
.price b { color: #b35400; }
"""
sub('</style>\n<div class="app">', PAL + '</style>\n<div class="app">')

# ================================================================ 3D: the globe sits in space
# A dark starfield behind it and a deep-navy ocean, so the blue supply ramp and the sea no longer blur.
# On the dark ground, selection is white (the ink outline would vanish).
sub('.backgroundColor("#eef3f8")', '.backgroundColor("rgba(0,0,0,0)")')
sub('    G3.globeMaterial().color.set("#b9d3ea");',
    '    G3.globeMaterial().color.set("#12304d");\n'
    '    $("globe3d").style.background = `url(${starfield()}) center / cover, radial-gradient(ellipse at 50% 45%, #0f1d33 0%, #060b16 70%)`;')
sub('.atmosphereColor("#6fa8dc")', '.atmosphereColor("#4f93e6")')
sub('.atmosphereAltitude(0.15)', '.atmosphereAltitude(0.2)')
sub('"rgba(20,32,46,0.62)" : x.tier === 1 ? "rgba(93,124,151,0.7)" : "rgba(93,124,151,0.9)"',
    '"rgba(255,255,255,0.72)" : x.tier === 1 ? "rgba(150,190,230,0.7)" : "rgba(150,190,230,0.85)"')
sub('"rgba(20,32,46,0.62)" : "rgba(90,110,130,0.25)"', '"rgba(255,255,255,0.42)" : "rgba(8,20,36,0.55)"')
sub('.polygonStrokeColor((f) => (f.properties.name === st.sel ? "#14202e" : "rgba(255,255,255,0.85)"))',
    '.polygonStrokeColor((f) => (f.properties.name === st.sel ? "#ffffff" : "rgba(255,255,255,0.55)"))')
sub("`rgba(20,32,46,${1 - t})`", "`rgba(255,255,255,${1 - t})`")
STARS_JS = r'''  // a fixed starfield (seeded, so it is the same on every load), drawn once
  let starUrl = null;
  function starfield() {
    if (starUrl) return starUrl;
    const c = document.createElement("canvas"); c.width = 1600; c.height = 1000;
    const x = c.getContext("2d"); let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 520; i++) {
      const r = rnd() < 0.92 ? 0.4 + rnd() * 0.7 : 1.1 + rnd() * 0.8;
      x.fillStyle = `rgba(${rnd() < 0.2 ? "190,210,255" : "255,255,255"},${0.25 + rnd() * 0.65})`;
      x.beginPath(); x.arc(rnd() * c.width, rnd() * c.height, r, 0, 6.283); x.fill();
    }
    try { starUrl = c.toDataURL("image/png"); } catch (e) { starUrl = ""; }
    return starUrl;
  }
'''
sub("  function initGlobe() {", STARS_JS + "  function initGlobe() {")

# the pop-up sits beside the floating country, clear of its name tag
sub('''    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = xy[0] + 16, top = xy[1] - ph / 2;
    if (left + pw > W - 56) left = xy[0] - pw - 16;''',
'''    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let x0 = xy[0] - 70, x1 = xy[0] + 70, yc = xy[1];
    const lp = st.wview === "flat" && document.querySelector("#world path.lift");
    if (lp) { const r = lp.getBoundingClientRect(), o = wrap.getBoundingClientRect(); if (r.width) { x0 = r.left - o.left; x1 = r.right - o.left; yc = r.top - o.top + r.height / 2; } }
    let left = x1 + 14, top = yc - ph / 2;
    if (left + pw > W - 56) left = x0 - pw - 14;''')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
