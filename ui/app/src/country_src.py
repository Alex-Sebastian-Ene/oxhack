"""The country card's source notes (Cost of living, Trade, Economy, Trends) move behind a Sources button at the foot of
each tab, applied after the other swaps in build.py. The notes stay in the page, hidden, so the page keeps writing them;
each button's sheet shows its note as it stands when pressed.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""
from product import src_button

NOTES = {   # WINFO key: (the note's id, the sheet's title)
    "colsrc": ("col-src", "Sources: cost of living"),
    "xsrc": ("x-src", "Sources: exports and imports"),
    "esrc": ("e-src", "Sources: economy"),
    "trsrc": ("tr-src", "Sources: trends"),
}
WINFO = "".join(f'    {k}: {{ title: "{t}", get html() {{ const n = $("{i}"); return n && n.textContent.trim() ? `<p>${{n.innerHTML}}</p>` : "<p>No sources for this view.</p>"; }} }},\n'
                for k, (i, t) in NOTES.items())

SWAPS = [
    ('<p class="faint" id="col-src"></p>', '<p class="faint" id="col-src"></p>' + src_button("colsrc", "Sources for the cost of living"), 1),
    ('<p class="faint" id="e-src"></p>', '<p class="faint" id="e-src"></p>' + src_button("esrc", "Sources for the economy"), 1),
    ('<p class="faint" id="tr-src"></p>', '<p class="faint" id="tr-src"></p>' + src_button("trsrc", "Sources for the trends"), 1),
    ('<div id="x-body"></div></div>', '<div id="x-body"></div>' + src_button("xsrc", "Sources for exports and imports") + '</div>', 1),
    ('h += `<p class="faint">${codes.length ? `${escH(TRADE.wdi.name)}', 'h += `<p class="faint" id="x-src">${codes.length ? `${escH(TRADE.wdi.name)}', 1),
    ('  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {',
     WINFO + '  };\n  document.querySelectorAll("[data-winfo]").forEach((b) => b.addEventListener("click", () => {', 1),
]

CSS = """
/* country_src.py: the country card's source notes, behind their Sources buttons */
#col-src, #x-src, #e-src, #tr-src { display: none !important; }
#x-sec .hz-srcbtn { margin-top: 10px; }
"""
