"""Gas on the World view, applied after world.SWAPS in build.py. Data: window.GAS, from ui/app/data/gas.json
(written by `uv run experiments/gas_routes.py`). Without that file the page draws no gas and says so nowhere.

Gas is violet, oil stays yellow. LNG lanes are dashed and run just beside the oil lanes they share, thinning
with the Hormuz flow like the oil does (we assume LNG through the strait is lost in the same share). Pipelines
are solid violet in a dark casing; the ones that bypass the strait keep full width.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

GAS = "#b58cff"

SWAPS = [
    # a layer for gas, between the oil routes and the arcs
    ('const gRB = root.append("g"), gR = root.append("g"), gArc = root.append("g")',
     'const gRB = root.append("g"), gR = root.append("g"), gGas = root.append("g").attr("class", "gasl"), gArc = root.append("g")', 1),
    # draw on layout, resize and every repaint
    ('    gR.selectAll("path").data(routes).join("path").attr("class", "route").attr("d", ([, d]) => line(d.r.map((p) => proj(p))));\n',
     '    gR.selectAll("path").data(routes).join("path").attr("class", "route").attr("d", ([, d]) => line(d.r.map((p) => proj(p))));\n'
     '    layoutGas();\n', 1),
    ('  function drawFlatArcs() {\n',
     '  // ---- gas: window.GAS (ui/app/data/gas.json). LNG via the named sea-lane segments in R, pipelines by path\n'
     '  // function declarations only: layout can run before this point is reached\n'
     '  function gasD() { return window.GAS || null; }\n'
     '  function lngPts(f) { const term = { QAT: [51.6, 25.9], ARE: [52.87, 25.15] }; return [f.start || term[f.from], ...((f.route && f.route.segments) || []).flatMap((s) => R[s] || []), ...((f.route && f.route.end) || [])].filter(Boolean); }\n'
     '  function lngMax() { return Math.max(...((gasD() || {}).lng || []).map((f) => f.value || 0), 1); }\n'
     '  // move a projected line a few pixels to its right, so a gas lane sits beside the oil lane it shares\n'
     '  function beside(pts, px) {\n'
     '    return pts.map((p, i) => { const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], n = Math.hypot(dx, dy) || 1;\n'
     '      return [p[0] - (dy / n) * px, p[1] + (dx / n) * px]; });\n'
     '  }\n'
     '  function gasTip(f) { return `Gas: ${nmIso(f.from)} → ${nmIso(f.to)} · ${f.value} ${f.unit || "Mt"} LNG (${f.year}; ${f.source})`; }\n'
     '  function pipeTip(p) { return `Gas pipeline: ${p.name}${p.capacity != null ? ` · ${p.capacity} ${p.unit || ""}` : ""}${p.bypasses_hormuz ? " · avoids Hormuz" : ""} (${p.year || ""}; ${p.source || ""})`; }\n'
     '  function layoutGas() {\n'
     '    const GASD = gasD(); if (!GASD) return;\n'
     '    const lanes = (GASD.lng || []).filter((f) => lngPts(f).length > 1), pipes = (GASD.pipelines || []).filter((p) => (p.path || []).length > 1);\n'
     '    gGas.selectAll("path.gpipe-c").data(pipes).join("path").attr("class", "gpipe-c").attr("d", (p) => line(p.path.map((q) => proj(q))));\n'
     '    gGas.selectAll("path.gpipe").data(pipes).join("path").attr("class", "gpipe").attr("d", (p) => line(p.path.map((q) => proj(q))))\n'
     '      .selectAll("title").data((p) => [p]).join("title").text(pipeTip);\n'
     '    gGas.selectAll("path.glane").data(lanes).join("path").attr("class", "glane").attr("d", (f) => line(beside(lngPts(f).map((q) => proj(q)), 3.5)))\n'
     '      .selectAll("title").data((f) => [f]).join("title").text(gasTip);\n'
     '  }\n'
     '  function paintGas() {\n'
     '    const GASD = gasD(), key = document.getElementById("wgaskey");\n'
     '    if (key) key.hidden = !GASD || !!st.mat;\n'
     '    if (!GASD) return;\n'
     '    const f = Math.min(st.flow / PREWAR, 1.1), mx = lngMax(), own = st.sel && isoOf[st.sel];\n'
     '    gGas.style("display", st.mat ? "none" : null);\n'
     '    gGas.selectAll("path.glane").attr("stroke-width", (g) => 0.6 + Math.sqrt((g.value || 0) / mx * Math.max(f, 0.04)) * 4.5)\n'
     '      .classed("dim", (g) => !!own && g.to !== own && g.from !== own).style("animation-duration", `${(2.2 / Math.max(f, 0.15)).toFixed(2)}s`);\n'
     '    gGas.selectAll("path.gpipe").attr("stroke-width", (p) => (p.bypasses_hormuz ? 2.6 : 2.6 * Math.max(f, 0.15)));\n'
     '    gGas.selectAll("path.gpipe-c").attr("stroke-width", (p) => (p.bypasses_hormuz ? 5 : 2.4 + 2.6 * Math.max(f, 0.15)));\n'
     '  }\n'
     '  function gas3d() {\n'
     '    const GASD = gasD(); if (!GASD || st.mat) return [];\n'
     '    const mx = lngMax(), f = Math.min(st.flow / PREWAR, 1.1), out = [];\n'
     '    for (const g of GASD.lng || []) { const p = lngPts(g); if (p.length > 1) out.push({ gas: true, pts: p.map(([lng, lat]) => [lat, lng + 0.6]), w: 0.3 + 1.6 * Math.sqrt((g.value || 0) / mx * Math.max(f, 0.04)), label: gasTip(g) }); }\n'
     '    for (const q of GASD.pipelines || []) if ((q.path || []).length > 1) out.push({ gas: true, pipe: true, pts: q.path.map(([lng, lat]) => [lat, lng]), w: 1.2, label: pipeTip(q) });\n'
     '    return out;\n'
     '  }\n'
     '  function drawFlatArcs() {\n', 1),
    ('    drawFlatArcs();\n    drawLift();\n', '    drawFlatArcs();\n    paintGas();\n    drawLift();\n', 2),
    # 3D: gas paths next to the oil paths, in violet
    ('G3.pathsData(st.mat ? [] : Object.entries(C).filter(([, d]) => d.r && d.h).map(([n, d]) => ({ n, pts: d.r.map(([lng, lat]) => [lat, lng]), on: !own || n === st.sel })))\n'
     '      .pathPoints("pts").pathPointAlt(0.004).pathStroke((d) => (d.on ? 1.6 : 0.6))\n'
     '      .pathColor((d) => (d.on ? ["rgba(255,214,10,0.45)", "#ffd60a"] : ["rgba(255,214,10,0.15)", "rgba(255,214,10,0.3)"]))',
     'G3.pathsData(st.mat ? [] : [...Object.entries(C).filter(([, d]) => d.r && d.h).map(([n, d]) => ({ n, pts: d.r.map(([lng, lat]) => [lat, lng]), on: !own || n === st.sel })), ...gas3d()])\n'
     '      .pathPoints("pts").pathPointAlt((d) => (d.gas ? 0.006 : 0.004)).pathStroke((d) => (d.gas ? d.w : d.on ? 1.6 : 0.6)).pathLabel((d) => (d.label ? escH(d.label) : ""))\n'
     f'      .pathColor((d) => (d.gas ? (d.pipe ? ["{GAS}", "{GAS}"] : ["rgba(181,140,255,0.35)", "{GAS}"]) : d.on ? ["rgba(255,214,10,0.45)", "#ffd60a"] : ["rgba(255,214,10,0.15)", "rgba(255,214,10,0.3)"]))', 1),
    # the key under the map
    ('<div class="flowkey"><i></i><span id="wflowkey">Oil leaving Hormuz, width = volume</span></div>',
     '<div class="flowkey"><i></i><span id="wflowkey">Oil leaving Hormuz, width = volume</span></div>\n'
     '        <div class="flowkey gaskey" id="wgaskey"><i></i><span>Gas: LNG lanes, and pipelines (solid)</span></div>', 1),
]

CSS = f"""/* gas on the World view (gas.py): violet, beside the yellow oil */
#world .gasl path {{ fill: none; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; pointer-events: stroke; }}
#world .glane {{ stroke: {GAS}; stroke-dasharray: 5 6; opacity: .9; animation: oilflow 2.2s linear infinite; }}
#world .glane.dim {{ opacity: .25; }}
#world .gpipe-c {{ stroke: #04060c; }}
#world .gpipe {{ stroke: {GAS}; }}
.legendbar .gaskey i {{ border-top: 3px dashed {GAS} !important; filter: none !important; }}
@media (prefers-reduced-motion: reduce) {{ #world .glane {{ animation: none; }} }}
"""
