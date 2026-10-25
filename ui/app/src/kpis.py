"""The headline figures on the World and Strait cards, applied after the other swaps in build.py.

- A pixel-art oil barrel, drawn here, beside every "million barrels a day" figure: the flow getting through and the
  flow missing in the World view's "The shock" card, and the estimate in the Strait view.
- Step 3 of "The shock" card (diesel at the pump, energy bills, overall inflation): each tile's name in bold, its range
  on the line below without the word "range", and an info key at the foot of the tile that says what the range is and
  where the number comes from.
- The shock card's source note (what the figures compare, where they come from) moves behind an info key at the foot
  of the card.
- "Most oil cut off" lists the top 10 and a "More" button adds 10 at a time.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

# 12 x 13 pixels: K outline, T lid, B bung, R/r steel hoops (light/shade), L/O/D the drum's amber body (light/mid/shade)
BARREL = [
    "..KKKKKKKK..",
    ".KTTTTTTBTK.",
    ".KRRRRRRRrK.",
    ".KLOOOOODDK.",
    "KLLOOOOOODDK",
    "KRRRRRRRRRrK",
    "KLLOOOOOODDK",
    "KLLOOOOOODDK",
    "KRRRRRRRRRrK",
    "KLLOOOOOODDK",
    ".KLOOOOODDK.",
    ".KRRRRRRRrK.",
    "..KKKKKKKK..",
]
COLORS = {"K": "#04060c", "T": "#3a4867", "B": "#ffd27a", "R": "#a9b6d3", "r": "#5b6d95",
          "L": "#ffd27a", "O": "#ffa424", "D": "#c4660f"}


def barrel_svg() -> str:
    """The barrel as inline SVG, one rect per pixel, like window.HZPixIcon in pixel.js (that runs too late for these)."""
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{COLORS[c]}"/>'
                    for y, row in enumerate(BARREL) for x, c in enumerate(row) if c in COLORS)
    return (f'<svg class="pxi hz-barrel" viewBox="0 0 {len(BARREL[0])} {len(BARREL)}" shape-rendering="crispEdges" '
            f'aria-hidden="true">{rects}</svg>')


INFO_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/>'
             '<path d="M12 7.5v.5"/></svg>')


def tile(id_: str, name: str, key: str) -> str:
    return (f'<div class="hz-kpi"><b id="{id_}">–</b><span class="hz-kn">{name}</span><span id="{id_}-r" class="hz-kr"></span>'
            f'<button type="button" class="ib hz-ki" data-winfo="{key}" aria-label="About {name.lower()}: its range and source">'
            f'{INFO_ICON}</button></div>')


# What each step-3 info key says. Getters, so the text follows the current setting when the key is pressed.
WINFO = r'''    diesel: { title: "Diesel at the pump", get html() { const d = chainEffect("ind_gasdesw"), s = (x) => `${x > 0.05 ? "+" : x < -0.05 ? "−" : ""}${Math.abs(x).toFixed(0)}%`;
      return `<p>How much more a gallon of diesel costs at US pumps 12 months on, against a world with no disruption: <b>${s(d.mean)}</b> at the flow you set.</p>
      <ul><li><b>The range</b> under it (${s(d.lo)} to ${s(d.hi)}) holds 90% of the model's outcomes.</li>
      <li><b>Series:</b> US retail diesel, all types (EIA, via FRED: GASDESW).</li></ul>
      <p class="faint">${chainSrc()}; generated ${CHAIN_META.generated}. Modelled, not live.</p>`; } },
    energy: { title: "Energy bills", get html() { const dl = Math.log(st.brent / BRENT0), [lo, hi] = rangeOf("ecpi", dl), s = (x) => `${x > 0.05 ? "+" : x < -0.05 ? "−" : ""}${Math.abs(x).toFixed(1)}%`;
      return `<p>How much US household energy prices (the energy part of the consumer price index) move with the oil price: <b>${s(viaLink("ecpi", dl, 0))}</b> at Brent $${st.brent}.</p>
      <ul><li><b>The range</b> under it (${s(lo)} to ${s(hi)}) runs between two fits of the same link: 1991–2008 (${LINK.ecpi[0].toFixed(1)}% per 10% rise in oil) and 2009–2026 (${LINK.ecpi[1].toFixed(1)}%). It is not a 90% band.</li>
      <li><b>Series:</b> US CPI energy (BLS, via FRED), fetched 24 Oct 2026; the fit is in notes/oil-chain-links.md.</li></ul>
      <p class="faint">Modelled, not live.</p>`; } },
    inflation: { title: "Overall inflation, in points", get html() { const c = chainEffect("us_cpi"), s = (x) => `${x > 0.05 ? "+" : x < -0.05 ? "−" : ""}${Math.abs(x).toFixed(1)}`;
      return `<p>How many percentage points the shock adds to US consumer price inflation 12 months on, against no disruption: <b>${s(c.mean)}</b> at the flow you set.</p>
      <ul><li><b>The range</b> under it (${s(c.lo)} to ${s(c.hi)} points) holds 90% of the model's outcomes.</li>
      <li><b>Series:</b> US CPI, all items (BLS, via FRED).</li></ul>
      <p class="faint">${chainSrc()}; generated ${CHAIN_META.generated}. Modelled, not live.</p>`; } },
    shocksrc: { title: "What these figures compare", get html() {
      const t = $("w-src").textContent, rest = t.replace(/^12 months on, vs no disruption, US\. 90% ranges\.\s*/, "");
      return `<p><b>US figures, 12 months on, against a world with no disruption.</b> Ranges hold 90% of outcomes, except energy bills, whose range runs between two fits of the same link (its own info key says more).</p>
      <p>${escH(rest)}</p><p class="faint">Modelled, not live.</p>`; } },
'''

SWAPS = [
    # barrels beside the "million barrels a day" figures
    ('<div><b id="w-flow" class="hurt">–</b><span>million barrels a day',
     f'<div class="hz-bbl"><b id="w-flow" class="hurt">–</b>{barrel_svg()}<span>million barrels a day', 1),
    ('<div><b id="w-miss" class="hurt">–</b><span>million barrels a day',
     f'<div class="hz-bbl"><b id="w-miss" class="hurt">–</b>{barrel_svg()}<span>million barrels a day', 1),
    ('<p class="big"><span id="est-p50" class="mono">–</span><span class="unit">million barrels a day',
     f'<p class="big hz-bbl"><span id="est-p50" class="mono">–</span>{barrel_svg()}<span class="unit">million barrels a day', 1),

    # step 3: name in bold, the range below it, an info key at the foot
    ('<div><b id="w-petrol">–</b><span id="w-petrol-r">Diesel at the pump</span></div>', tile("w-petrol", "Diesel at the pump", "diesel"), 1),
    ('<div><b id="w-ecpi">–</b><span id="w-ecpi-r">Energy bills</span></div>', tile("w-ecpi", "Energy bills", "energy"), 1),
    ('<div><b id="w-cpi">–</b><span id="w-cpi-r">Overall inflation, in points</span></div>', tile("w-cpi", "Overall inflation, in points", "inflation"), 1),
    ('`Diesel at the pump · range ${sign(dsl.lo)}${a(dsl.lo).toFixed(0)} to ${sign(dsl.hi)}${a(dsl.hi).toFixed(0)}%`',
     '`${sign(dsl.lo)}${a(dsl.lo).toFixed(0)} to ${sign(dsl.hi)}${a(dsl.hi).toFixed(0)}%`', 1),
    ('`Energy bills · range ${sign(elo)}${a(elo).toFixed(1)} to ${sign(ehi)}${a(ehi).toFixed(1)}%`',
     '`${sign(elo)}${a(elo).toFixed(1)} to ${sign(ehi)}${a(ehi).toFixed(1)}%`', 1),
    ('`Overall inflation, in points · range ${sign(cpi.lo)}${a(cpi.lo).toFixed(1)} to ${sign(cpi.hi)}${a(cpi.hi).toFixed(1)}`',
     '`${sign(cpi.lo)}${a(cpi.lo).toFixed(1)} to ${sign(cpi.hi)}${a(cpi.hi).toFixed(1)} points`', 1),
    ('  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {',
     WINFO + '  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {', 1),

    # the shock card's source note: kept (the page still writes it) but hidden, and read by its info key
    ('<p class="faint" id="w-src"></p>',
     '<div class="hz-srcrow"><button type="button" class="ib" data-winfo="shocksrc" aria-label="What these figures compare, and their sources">'
     f'{INFO_ICON}</button><span>US, 12 months on · sources</span></div><p class="faint" id="w-src" hidden></p>', 1),

    # "Most oil cut off": a More button under the top 10
    ('<div class="rank" id="w-rank"></div>\n      </section>',
     '<div class="rank" id="w-rank"></div>\n        <button type="button" class="hz-rk-more" id="w-rank-more" hidden></button>\n      </section>', 1),
    ('  function renderRank() {\n', '  let rankN = 10;   // how many "Most oil cut off" shows; More adds 10\n  function renderRank() {\n', 1),
    ('.filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]).slice(0, 10);\n    const box = $("w-rank");\n',
     '.filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]), rest = list.splice(rankN);\n    const box = $("w-rank"), more = $("w-rank-more");\n'
     '    more.hidden = !rest.length && rankN <= 10 || list[0][1] < 0.5;\n'
     '    more.textContent = rest.length ? `More (${list.length} of ${list.length + rest.length} shown)` : "Show the top 10 only";\n'
     '    more.onclick = () => { rankN = rest.length ? rankN + 10 : 10; renderRank(); more.focus({ preventScroll: true }); };\n', 1),
]

CSS = """
/* kpis.py: the oil barrel beside each "million barrels a day" figure */
.hz-bbl { position: relative; }
.kpis .hz-bbl { padding-right: 46px !important; }
.kpis .hz-bbl svg.hz-barrel { position: absolute; top: 10px; right: 10px; width: 26px; height: 28px; }
.big.hz-bbl { align-items: center; }
.big.hz-bbl svg.hz-barrel { width: 30px; height: 33px; align-self: center; }
@media (max-width: 560px) { .kpis .hz-bbl { padding-right: 38px !important; } .kpis .hz-bbl svg.hz-barrel { width: 20px; height: 22px; top: 8px; right: 8px; } }
/* kpis.py: step 3's tiles: the name in bold, the range under it, the info key at the foot */
.kpis .hz-kpi { display: flex; flex-direction: column; }
.kpis .hz-kpi .hz-kn { font-weight: 700; color: var(--text); }
.kpis .hz-kpi .hz-kr { margin-bottom: 8px; font-family: var(--mono, monospace); font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.kpis .hz-kpi .hz-ki { margin-top: auto; align-self: flex-start; }
/* kpis.py: the shock card's sources behind an info key */
.hz-srcrow { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--faint); }
/* kpis.py: More under "Most oil cut off" */
.hz-rk-more { align-self: flex-start; min-height: 34px; padding: 0 12px; font-size: 13px; }
"""
