"""The World view's Product card (pick Jet fuel, Fertiliser...), applied after the other swaps in build.py.

- Sources move off the card into a Sources button at its foot: the price note keeps what it is (the setting, 12 months
  on, the range) and the sheet lists every source behind the card, with links.
- "What it costs buyers" is drawn rather than written: a bar for the product's share of the buyer's costs, the sum
  (share x price move = cost move) as chips, a range bar where the figure is a model's price forecast, and how fast it
  reaches costs as a chip with a pixel clock.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

OLD_BUYERS = r'''    $("m-buyers").innerHTML = (BUYERS[m.id] || []).map(([ind, share, src, lag, alt]) => {
      if (alt && alt.chain) {
        const e = chainEffect(alt.chain), cls = e.mean > 0.05 ? "hurt" : e.mean < -0.05 ? "gain" : "";
        return `<li><span class="nm">${escH(ind)}</span><span class="lv mono ${cls}">${pctP(e.mean)} prices</span>
        <span class="why">No sourced fuel share, so this is ${alt.text} after 12 months (Seb's chain, 90% range ${pctP(e.lo, 0)} to ${pctP(e.hi, 0)}). Reaches costs ${escH(lag)}.</span></li>`;
      }
      if (alt && alt.indirect) return `<li><span class="nm">${escH(ind)}</span><span class="lv">indirect</span>
        <span class="why">${escH(alt.indirect)}. Reaches costs ${escH(lag)}.</span></li>`;
      const c = share == null || !p ? null : share * p.mean / 100;
      const cls = c == null ? "" : c > 0.05 ? "hurt" : c < -0.05 ? "gain" : "";
      return `<li><span class="nm">${escH(ind)}</span><span class="lv mono ${cls}">${c == null ? "no data" : pctP(c) + " costs"}</span>
        <span class="why">${c == null ? `${escH(src)}.` : `${escH(src)} × ${pctP(p.mean)} price.`} Reaches costs ${escH(lag)}.</span></li>`;
    }).join("");
'''

NEW_BUYERS = r'''    // product.py: each buyer drawn as a share bar, the sum as chips, a range bar for a model forecast, and its pace
    const PX = (rows) => window.HZPixIcon ? window.HZPixIcon(rows, { K: "currentColor" }) : "";
    const CLOCK = PX(["..KKKKK..", ".K.....K.", "K...K...K", "K...K...K", "K...KKK.K", "K.......K", "K.......K", ".K.....K.", "..KKKKK.."]);
    const NOTE = PX(["KKKKKKK", "K.....K", "K.KKK.K", "K.....K", "K.KKK.K", "K.....K", "KKKKKKK"]);
    const tone = (v) => (v > 0.05 ? "hurt" : v < -0.05 ? "gain" : "");
    const pace = (lag) => {
      const [main, note] = String(lag || "").split(/\s*\((.*)\)\s*$/);
      return `<span class="hz-by-chip pace">${CLOCK}Hits costs: ${escH(main)}</span>${note ? `<span class="hz-by-chip">${NOTE}${escH(note[0].toUpperCase() + note.slice(1))}</span>` : ""}`;
    };
    const what = escH(m.short || m.name);
    $("m-buyers").innerHTML = (BUYERS[m.id] || []).map(([ind, share, src, lag, alt]) => {
      if (alt && alt.chain) {
        const e = chainEffect(alt.chain), lo = Math.min(e.lo, 0), hi = Math.max(e.hi, 0), at = (v) => ((v - lo) / (hi - lo || 1) * 100).toFixed(1);
        return `<li class="hz-by"><span class="nm">${escH(ind)}</span><span class="lv mono ${tone(e.mean)}">${pctP(e.mean)} prices</span>
        <div class="hz-by-body"><p class="hz-by-what">${escH(alt.text[0].toUpperCase() + alt.text.slice(1))}, 12 months on (no sourced ${what.toLowerCase()} share of their costs yet):</p>
          <div class="hz-by-range" role="img" aria-label="${pctP(e.mean)}, 90% of outcomes ${pctP(e.lo, 0)} to ${pctP(e.hi, 0)}"><span class="track"><span class="band" style="left:${at(e.lo)}%;width:${(at(e.hi) - at(e.lo)).toFixed(1)}%"></span><span class="zero" style="left:${at(0)}%"></span><span class="mid" style="left:${at(e.mean)}%"></span></span>
            <span class="ends mono"><span>${pctP(e.lo, 0)}</span><span>${pctP(e.hi, 0)}</span></span></div>
          <div class="hz-by-chips">${pace(lag)}</div></div></li>`;
      }
      if (alt && alt.indirect) return `<li class="hz-by"><span class="nm">${escH(ind)}</span><span class="lv">indirect</span>
        <div class="hz-by-body"><p class="hz-by-what">${escH(alt.indirect)}.</p><div class="hz-by-chips">${pace(lag)}</div></div></li>`;
      const c = share == null || !p ? null : share * p.mean / 100;
      if (c == null) return `<li class="hz-by"><span class="nm">${escH(ind)}</span><span class="lv">no data</span>
        <div class="hz-by-body"><div class="hz-by-chips"><span class="hz-by-chip dim">No sourced share of their costs yet</span>${pace(lag)}</div></div></li>`;
      return `<li class="hz-by"><span class="nm">${escH(ind)}</span><span class="lv mono ${tone(c)}">${pctP(c)} costs</span>
        <div class="hz-by-body"><div class="hz-by-share"><span class="bar" role="img" aria-label="${share}% of costs"><span style="width:${Math.min(100, share)}%"></span></span><span>${what} is <b>${share}%</b> of their costs</span></div>
          <div class="hz-by-sum"><span class="hz-by-chip">${share}% of costs</span><i aria-hidden="true">×</i><span class="hz-by-chip ${tone(p.mean)}">${pctP(p.mean)} price</span><i aria-hidden="true">=</i><span class="hz-by-chip res ${tone(c)}">${pctP(c)} costs</span></div>
          <div class="hz-by-chips">${pace(lag)}</div></div></li>`;
    }).join("");
'''

SRC_ICON = ('<svg class="pxi" viewBox="0 0 11 9" shape-rendering="crispEdges" aria-hidden="true">'
            + "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="currentColor"/>'
                      for y, row in enumerate(["KKKKK.KKKKK", "K...KKK...K", "K.KKK.KKK.K", "K...K.K...K", "K.KKK.KKK.K",
                                               "K...K.K...K", "K.KKK.KKK.K", "K...K.K...K", "KKKKKKKKKKK"])
                      for x, c in enumerate(row) if c == "K")
            + "</svg>")

def src_button(key: str, aria: str) -> str:
    """A Sources button that opens the shared info sheet (the page's WINFO entry `key`); also used by country_src.py."""
    return f'<button type="button" class="hz-srcbtn" data-winfo="{key}" aria-label="{aria}">{SRC_ICON}<span>Sources</span></button>'


# the Sources sheet, read when the button is pressed, so it follows the product and the setting
WINFO = r'''    prodsrc: { title: "Sources", get html() {
      const m = mats[st.mat];
      if (!m) return "<p>Pick a product first.</p>";
      const p = priceMoveM(m), li = (k, v) => (v ? `<li><b>${k}:</b> ${v}</li>` : "");
      const link = (t) => escH(t).replace(/https?:\/\/[^\s)<,;]+/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}</a>`);
      const buyers = (BUYERS[m.id] || []).map(([ind, share, src, lag, alt]) => {
        const c = CSV_BUY[`${m.id}|${ind}`];
        if (alt && alt.chain) return li(ind, `${escH(alt.text)}: ${chainSrc().replace(/^Source: /, "")}; generated ${CHAIN_META.generated}`);
        if (alt && alt.indirect) return li(ind, escH(alt.indirect));
        return li(ind, `${escH(c ? c.src : src)}${c && c.url ? ` (<a href="${escH(c.url)}" target="_blank" rel="noopener">${escH(c.url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>)` : ""}`);
      }).join("");
      return `<ul>${li("Price in 12 months", p && p.chain ? `${chainSrc().replace(/^Source: /, "")}; generated ${CHAIN_META.generated}. Ranges hold 90% of outcomes` : p ? `past US price moves (FRED, 2001–2026)${m.oil && m.oil.series ? `, ${escH(m.oil.series)}` : ""}${m.oil && m.oil.source ? `: ${link(m.oil.source)}` : ""}` : "no fitted oil link yet")}
        ${li(`Who makes it (${escH(m.year || "")})`, link(m.source || ""))}${m.exports ? li(`Who ships it (${escH(m.exports.year || "")})`, link(m.exports.source || "")) : ""}
        ${li("Hormuz", escH(HORMUZ[m.id] || ""))}</ul>
        ${buyers ? `<p><b>What it costs buyers</b>: the product's share of their costs × its price move.</p><ul>${buyers}</ul>` : ""}
        <p class="faint">Collected 24 to 25 Oct 2026; modelled figures are not live. Check at source before quoting.</p>`; } },
'''

SWAPS = [
    # the price note: what the figure is, without its source
    ('${pctP(p.hi, 0)}. ${chainSrc()}.` : p ?', '${pctP(p.hi, 0)}.` : p ?', 1),
    (' Source: past US price moves (FRED, 2001–2026).', '', 1),
    (OLD_BUYERS, NEW_BUYERS, 1),
    ('<ul class="inds" id="m-buyers"></ul>',
     '<ul class="inds" id="m-buyers"></ul>\n          ' + src_button("prodsrc", "Sources for this product"), 1),
    ('  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {',
     WINFO + '  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {', 1),
]

CSS = """
/* product.py: the Product card's buyers, drawn */
#m-buyers li.hz-by { padding: 12px 0; }
.hz-by-body { grid-column: 1 / -1; display: flex; flex-direction: column; gap: 8px; }
.hz-by-what { margin: 0; font-size: 13px; line-height: 1.5; color: var(--muted); }
.hz-by-share { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted); }
.hz-by-share b { color: var(--text); font-family: var(--mono, monospace); }
.hz-by-share .bar { flex: 0 0 120px; height: 12px; background: var(--panel2); box-shadow: inset 0 0 0 2px var(--ink); position: relative; }
.hz-by-share .bar span { position: absolute; inset: 2px auto 2px 2px; max-width: calc(100% - 4px); background: var(--oil);
  background-image: repeating-linear-gradient(90deg, transparent 0 6px, rgba(0, 0, 0, .25) 6px 8px); }
.hz-by-sum { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.hz-by-sum i { font-style: normal; font: 700 15px var(--mono, monospace); color: var(--faint); }
.hz-by-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.hz-by-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; font: 12.5px var(--mono, monospace); color: var(--text);
  background: var(--panel2); border: 2px solid var(--ink); box-shadow: inset 0 0 0 1px var(--line2); }
.hz-by-chip.hurt { color: var(--hurt); } .hz-by-chip.gain { color: var(--gain); }
.hz-by-chip.res { font-weight: 700; box-shadow: inset 0 0 0 1px currentColor; }
.hz-by-chip.pace { color: var(--oil-soft); font-family: var(--sans, sans-serif); }
.hz-by-chip.dim { color: var(--faint); font-family: var(--sans, sans-serif); }
.hz-by-chip .pxi { width: 12px; height: 12px; flex: none; }
.hz-by-range { display: flex; flex-direction: column; gap: 3px; }
.hz-by-range .track { position: relative; height: 14px; background: var(--panel2); box-shadow: inset 0 0 0 2px var(--ink); }
.hz-by-range .band { position: absolute; top: 3px; bottom: 3px; background: rgba(255, 164, 36, .45); }
.hz-by-range .zero { position: absolute; top: 1px; bottom: 1px; width: 2px; margin-left: -1px; background: var(--faint); }
.hz-by-range .mid { position: absolute; top: -2px; bottom: -2px; width: 4px; margin-left: -2px; background: var(--hurt); box-shadow: 0 0 0 1px var(--ink); }
.hz-by-range .ends { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--faint); }
/* product.py: the Sources button at the card's foot */
.hz-srcbtn { align-self: flex-start; min-height: 32px; padding: 0 12px; gap: 8px; font-size: 13px; margin-top: 4px; }
.hz-srcbtn .pxi { width: 14px; height: 12px; color: var(--seen-soft); }
"""
