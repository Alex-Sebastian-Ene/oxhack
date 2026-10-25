"""A flag beside every country name used as a title in the World view, applied after the other swaps in build.py:
the Most exposed list, the country card's heading, and the US / UK / euro area economy picks and their lines.

Two sets of flags join the page's own table (window.FLAGS.flags), where the rest of the app (ai.js, households.js)
finds them too: the heavy flags the page leaves out (Spain, Sri Lanka and 20 more, ui/app/data/flags-extra.json
from flags_extra.py), and the EU flag, drawn here, standing in for the euro area as "EUU".

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""
import json
import math
import pathlib
import urllib.parse

EXTRA = pathlib.Path(__file__).resolve().parents[1] / "data" / "flags-extra.json"

_stars = "".join(f'<circle cx="{15 + 6 * math.sin(i * math.pi / 6):.2f}" cy="{10 - 6 * math.cos(i * math.pi / 6):.2f}" r="1" fill="#fc0"/>'
                 for i in range(12))
EU = "data:image/svg+xml," + urllib.parse.quote(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#039"/>{_stars}</svg>')


def script() -> str:
    flags = json.loads(EXTRA.read_text(encoding="utf-8"))["flags"] if EXTRA.exists() else {}
    flags["EUU"] = EU
    return (f"<script>/* flags the industry page leaves out (ui/app/data/flags-extra.json) and the EU flag for the euro area */\n"
            f"window.HZFlagsExtra = {json.dumps(flags, separators=(',', ':'))};\n</script>\n")


SWAPS = [
    # the extra flags join the page's flag table
    ('const MAT = window.MATERIALS, CN = window.COUNTRIES, FLAGS = (window.FLAGS && window.FLAGS.flags) || {};',
     'const MAT = window.MATERIALS, CN = window.COUNTRIES, FLAGS = Object.assign((window.FLAGS && window.FLAGS.flags) || {}, window.HZFlagsExtra || {});', 1),
    # the economy picks: a flag on each button
    ('  const flagImg = (iso) => (FLAGS[iso] ? `<img class="flag" src="${FLAGS[iso]}" alt="">` : `<span class="flag none">${escH(iso)}</span>`);\n',
     '  const flagImg = (iso) => (FLAGS[iso] ? `<img class="flag" src="${FLAGS[iso]}" alt="">` : `<span class="flag none">${escH(iso)}</span>`);\n'
     '  const ECO_ISO = { us: "USA", uk: "GBR", ea: "EUU" };\n'
     '  document.querySelectorAll("[data-eco]").forEach((b) => b.insertAdjacentHTML("afterbegin", flagImg(ECO_ISO[b.dataset.eco])));\n', 1),
    # Most exposed
    ('<span class="n">${i + 1}</span><span>${n === "United States of America" ? "United States" : n}</span>',
     '<span class="n">${i + 1}</span><span class="rk-n">${isoOf[n] ? flagImg(isoOf[n]) : ""}${n === "United States of America" ? "United States" : n}</span>', 1),
    # the country card's heading (its text stays the bare name: ai.js reads it)
    ('    $("c-name").textContent = name;\n',
     '    $("c-name").innerHTML = `${isoOf[name] ? flagImg(isoOf[name]) : ""}${escH(name)}`;\n', 1),
    # "Figures for the United Kingdom", and the comparison line
    ('? (own === "ea" ? `${nm} uses the euro, so these are <b>euro-area</b> figures.` : `Figures for <b>${ECO_NAME[own]}</b>.`)\n'
     '      : `The model covers only the US, the UK and the euro area, not ${nm}. Showing <b>${ECO_NAME[eco]}</b> for comparison.`;',
     '? (own === "ea" ? `${nm} uses the euro, so these are ${flagImg("EUU")} <b>euro-area</b> figures.` : `Figures for ${flagImg(ECO_ISO[own])} <b>${ECO_NAME[own]}</b>.`)\n'
     '      : `The model covers only the US, the UK and the euro area, not ${nm}. Showing ${flagImg(ECO_ISO[eco])} <b>${ECO_NAME[eco]}</b> for comparison.`;', 1),
]

CSS = """/* flags beside country titles (flags.py) */
#c-name { display: flex; align-items: center; gap: 8px; }
#c-name .flag { width: 26px; height: 19px; }
.rank .rk-n { display: inline-flex; align-items: center; gap: 7px; min-width: 0; }
.eseg button .flag { margin-right: 5px; }
#e-who .flag { vertical-align: -2px; }
"""
