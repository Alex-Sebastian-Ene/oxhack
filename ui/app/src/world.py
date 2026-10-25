"""Behaviour patches for the app's World view, applied after the colour swaps in build.py.

Made and Shipped are drawn together, as in ui/globe: the layer in front fills the countries (raised land on
the 3D globe) and its arcs are solid; the other stands on each country as a see-through column and its arcs
are faint. The Made / Shipped buttons pick which one is in front. Shipped arcs are sky blue, so they never
read as the yellow ingredient arcs. Tooltips name both layers and every tooltip carries the country's flag.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

SHIP = "#8fd0f5"

SWAPS = [
    # arcs of both kinds; the one not in front is marked faded
    ('    const add = (from, to, col, weight, label) => { if (from !== to && where[from] && where[to]) out.push({ from, to, color: col, weight, label }); };\n'
     '    if (st.mode === "production") {\n',
     '    const add = (from, to, col, weight, label, kind) => { if (from !== to && where[from] && where[to]) out.push({ from, to, color: col, weight, label, kind, faded: kind !== st.mode }); };\n'
     '    {\n', 1),
    ('${nmIso(l.from)} → ${nmIso(l.to)} ${Math.round(l.share * 100)}%`);',
     '${nmIso(l.from)} → ${nmIso(l.to)} ${Math.round(l.share * 100)}%`, "production");', 1),
    ('    } else {\n      const flows = [...(m.flows || [])',
     '    }\n    {\n      const flows = [...(m.flows || [])', 1),
    ('for (const f of flows.slice(0, 16)) add(f.from, f.to, "#ffd60a",',
     f'for (const f of flows.slice(0, 16)) add(f.from, f.to, "{SHIP}",', 1),
    ('${f.share_of_importer != null ? ` · ${Math.round(f.share_of_importer * 100)}% of its imports` : ""}`);',
     '${f.share_of_importer != null ? ` · ${Math.round(f.share_of_importer * 100)}% of its imports` : ""}`, "exports");', 1),
    # only the front layer's arcs blink where they land
    ('for (const a of arcsFor()) if (!seen.has(a.to))', 'for (const a of arcsFor()) if (!a.faded && !seen.has(a.to))', 1),

    # flat map: faint arcs under bright ones, then the back layer's columns
    ('const arcs = st.mat ? arcsFor() : [];\n    gArc.selectAll("path").data(arcs).join("path").attr("class", "arc")',
     'const arcs = st.mat ? arcsFor().sort((a, b) => b.faded - a.faded) : [];\n'
     '    gArc.selectAll("path").data(arcs).join("path").attr("class", (a) => (a.faded ? "arc faded" : "arc"))', 1),
    ('.attr("stroke-width", (a) => 1 + 2.6 * Math.sqrt(a.weight || 0.1)).attr("opacity", 0.9)',
     '.attr("stroke-width", (a) => (a.faded ? 0.5 : 1) * (1 + 2.6 * Math.sqrt(a.weight || 0.1))).attr("opacity", (a) => (a.faded ? 0.32 : 0.95))', 1),
    ('    gR.style("display", st.mat ? "none" : null);\n    gRB.style("display", st.mat ? "none" : null);\n  }\n',
     '    gR.style("display", st.mat ? "none" : null);\n    gRB.style("display", st.mat ? "none" : null);\n'
     '    let gCol = gArc.select("g.cols");\n'
     '    if (gCol.empty()) gCol = gArc.insert("g", ":first-child").attr("class", "cols");\n'
     '    gCol.selectAll("rect").data(backCols(), (d) => d.n).join("rect").attr("fill", (d) => d.color);\n'
     '    placeCols(cur.k);\n'
     '  }\n'
     '  // the layer not in front: one see-through column per country, height by its share\n'
     '  function backCols() {\n'
     '    if (!st.mat) return [];\n'
     '    const w = weightsByName(st.mode === "exports" ? "production" : "exports"), max = Math.max(...Object.values(w), 0.01);\n'
     '    const c = d3.color(st.mode === "exports" ? hueOf(st.mat) : "' + SHIP + '").brighter(0.4);\n'
     '    return Object.entries(w).map(([n, v]) => { const p = where[isoOf[n]]; return p && { n, v: v / max, lng: p.lng, lat: p.lat, color: c.formatHex() }; }).filter(Boolean);\n'
     '  }\n'
     '  function placeCols(k) {\n'
     '    gArc.select("g.cols").selectAll("rect").each(function (d) {\n'
     '      const [x, y] = proj([d.lng, d.lat]), h = (6 + 28 * Math.sqrt(d.v)) / k, w = 6 / k;\n'
     '      d3.select(this).attr("x", x - w / 2).attr("y", y - h).attr("width", w).attr("height", h);\n'
     '    });\n'
     '  }\n', 1),
    ('    gPulse.selectAll("circle").attr("r", (d) => d.r / k);\n',
     '    gPulse.selectAll("circle").attr("r", (d) => d.r / k);\n    placeCols(k);\n', 1),

    # 3D globe: front layer raised by its share, back layer as see-through columns, faint arcs
    ('.polygonAltitude((f) => (f.properties.name === st.sel ? 0.085 : 0.006));',
     '.polygonAltitude((f) => (f.properties.name === st.sel ? 0.085 : 0.006 + (s3[f.properties.name] ? 0.06 * Math.sqrt(s3[f.properties.name] / max) : 0)));', 1),
    ('    G3.pointsData(pts).pointColor((d) => d.color)',
     '    for (const d of backCols()) { const c = d3.color(d.color); c.opacity = 0.45; pts.push({ name: d.n, lat: d.lat, lng: d.lng, alt: 0.02 + 0.16 * Math.sqrt(d.v), r: 0.7, color: c.formatRgb() }); }\n'
     '    G3.pointsData(pts).pointColor((d) => d.color)', 1),
    ('weight: a.weight, label: a.label })))', 'weight: a.weight, label: a.label, faded: a.faded })))', 1),
    ('.arcColor((d) => [d.color + "55", d.color]).arcStroke((d) => 0.25 + 1.2 * Math.sqrt(d.weight || 0.1))',
     '.arcColor((d) => (d.faded ? [d.color + "0a", d.color + "55"] : [d.color + "55", d.color])).arcStroke((d) => (d.faded ? 0.45 : 1) * (0.25 + 1.2 * Math.sqrt(d.weight || 0.1)))', 1),

    # titles and keys say what each form means
    ('$("wttl").textContent = m ? `${m.name}: ${st.mode === "exports" ? "who ships it" : "who makes it"}` : "Exposure score (illustrative)";',
     '$("wttl").textContent = m ? `${m.short || m.name}: ${st.mode === "exports" ? "shipped (fill) · made (columns)" : "made (fill) · shipped (columns)"}` : "Exposure score (illustrative)";', 1),
    ('aria-label="Who makes it or who ships it"', 'aria-label="Which layer is in front"', 1),

    ("$(\"wticks\").innerHTML = '<span style=\"left:0;transform:none\">smaller</span><span style=\"left:100%;transform:translateX(-100%)\">larger producer</span><span class=\"viarow\"><i class=\"viakey\"></i>amber edge: Gulf producer, ships via Hormuz</span>';",
     '$("wticks").innerHTML = `<span style="left:0;transform:none">smaller</span><span style="left:100%;transform:translateX(-100%)">larger ${st.mode === "exports" ? "exporter" : "producer"}</span>'
     '<span class="viarow"><i class="colkey" style="background:${st.mode === "exports" ? hueOf(st.mat) : "#8fd0f5"}"></i>columns: ${st.mode === "exports" ? "made" : "shipped"}</span><span class="viarow"><i class="viakey"></i>amber edge: ships via Hormuz</span>`;', 1),

    ('if (fk) fk.style.borderTopColor = "#ffd60a";', 'if (fk) fk.style.borderTopColor = st.mat && st.mode === "exports" ? "#8fd0f5" : "#ffd60a";', 1),
    ('(st.mode === "exports" ? "Trade flows of this product, blinking at the buyer" : "Arcs: where its ingredients come from, blinking where they land") : "Click a country for its supplier and trade arcs")',
     '(st.mode === "exports" ? "Trade flows, blinking at the buyer" : "Where its inputs come from") : "Click a country to see its arcs")', 1),

    # tooltips: both layers, and a flag on every country
    ('      const m = mats[st.mat], iso = isoOf[name], r = tableOf(m, st.mode).find((x) => x.iso3 === iso);\n'
     '      return `<b>${iso ? flagImg(iso) + " " : ""}${escH(name === "United States of America" ? "United States" : name)}</b><span>${escH(m.short || m.name)} ${st.mode === "exports" ? "shipped" : "made"}: <span class="mono">${r ? shareTxt(r) : "not listed"}</span></span>',
     '      const m = mats[st.mat], iso = isoOf[name];\n'
     '      const row = (md, lab) => { const r = tableOf(m, md).find((x) => x.iso3 === iso); return `<span${md === st.mode ? "" : \' class="faint"\'}>${lab}: <span class="mono">${r ? shareTxt(r) : "not listed"}</span></span>`; };\n'
     '      return `<b>${iso ? flagImg(iso) + " " : ""}${escH(name === "United States of America" ? "United States" : name)}</b>${row("production", "Made")}${row("exports", "Shipped")}', 1),
    ('return `<b>${escH(name)}</b><span>Exposure',
     'return `<b>${isoOf[name] ? flagImg(isoOf[name]) + " " : ""}${escH(name === "United States of America" ? "United States" : name)}</b><span>Exposure', 1),
]
