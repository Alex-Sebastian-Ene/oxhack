"""Build the Hormuz Flow app (ui/app/index.html): Eileen's integrated page (ui/industry/index.html: World map
and globe, Strait simulation, PortWatch stats, Seb's chain) with a pixel-art landing page, synthesised sound
and one night-shift theme across every view.

    python ui/app/src/build.py                      # writes ui/app/index.html
    python ui/app/src/build.py --fragment out.html  # also writes the page body for a claude.ai artifact

The industry page is used as it is; only the colours below are swapped, and each swap must find its text
exactly once, so the build fails loudly if the page changes underneath it. Needs Python 3 and, for the syntax
check, node on PATH.
"""
import base64, pathlib, re, shutil, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import copy_text, flags, gas, households, mandeb, models, strait, world  # noqa: E402  (World view, flags, gas lines, households, Bab el-Mandeb, Strait layout, models, copy)

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent
SRC = APP.parent / "industry" / "index.html"
FONTS = APP / "vendor" / "fonts"
JS = APP / "vendor" / "js"
# the industry page loads these two from cdnjs; the app bundles the same versions so it runs offline
CDN = {
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>': ("d3-7.9.0.min.js", "d3 7.9.0, ISC licence (ui/app/vendor/js/d3.LICENSE)"),
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/topojson/3.0.2/topojson.min.js"></script>': ("topojson-3.0.2.min.js", "topojson 3.0.2, BSD-3-Clause licence (ui/app/vendor/js/topojson.LICENSE)"),
}

# (old, new, how many times old must appear). Day colours from the industry page, re-lit for night.
SWAPS = [
    # Strait view canvas: sea, land, lanes and labels
    ('const COL = { seen: "#0a4fd0", oil: "#f26b00", oilSoft: "#c24f00", fake: "#e0201b", sea: "#a8d8f8", land: "#efe1c2",\n'
     '    landEdge: "#c2a978", lane: "#ffdc2e", laneEdge: "rgba(20,32,46,0.4)", text: "#14202e", faint: "#1f5f8f", white: "#14202e", other: "#5e6b7a" };',
     'const COL = { seen: "#5aa9ff", oil: "#ffa424", oilSoft: "#ffbf5c", fake: "#ff4d3a", sea: "#0a2342", land: "#363a50",\n'
     '    landEdge: "#6a7194", lane: "#d9a92e", laneEdge: "rgba(0,0,0,0.55)", text: "#f1e8d2", faint: "#8fbbe3", white: "#f1e8d2", other: "#8b97ad" };', 1),
    ('ctx.fillStyle = "rgba(20,32,46,0.5)";', 'ctx.fillStyle = "rgba(241,232,210,0.45)";', 1),
    ('ctx.strokeStyle = "rgba(20,32,46,0.5)";', 'ctx.strokeStyle = "rgba(241,232,210,0.55)";', 1),
    ('ctx.strokeStyle = `rgba(20,32,46,${a})`;', 'ctx.strokeStyle = `rgba(241,232,210,${a})`;', 1),
    ('c.strokeStyle = "rgba(20,32,46,0.7)"', 'c.strokeStyle = "rgba(241,232,210,0.75)"', 1),
    # World view: product ramps run from dark to bright on a night map; no-data and the selected country's gap
    ('.range([d3.interpolateLab("#ffffff", h)(0.32), h, d3.hsl(h).darker(0.9).formatHex()])',
     '.range([d3.interpolateLab("#1a2439", h)(0.4), h, d3.hsl(h).brighter(0.75).formatHex()])', 1),
    ('if (!v) return "#eceff3";', 'if (!v) return "#243049";', 1),
    ('const NODATA = "#eceff3";', 'const NODATA = "#243049";', 1),
    ('c.properties.name === st.sel ? "#aab5c2" : fillFor(c.properties.name)', 'c.properties.name === st.sel ? "#070b16" : fillFor(c.properties.name)', 1),
    ('(n === st.sel ? "#14202e" : "var(--bg)")', '(n === st.sel ? "#ffd27a" : "var(--bg)")', 1),
    # 3D globe: a night sea, light labels, a gold edge and ring for the chosen country
    ('G3.globeMaterial().color.set("#a8d8f8"); G3.globeMaterial().emissive.set("#a8d8f8"); G3.globeMaterial().emissiveIntensity = 0.08;',
     'G3.globeMaterial().color.set("#0b2240"); G3.globeMaterial().emissive.set("#0b2a4f"); G3.globeMaterial().emissiveIntensity = 0.35;', 1),
    ('x.cont ? "rgba(20,32,46,0.75)"', 'x.cont ? "rgba(241,232,210,0.85)"', 1),
    ('"rgba(26,84,130,', '"rgba(143,187,227,', 2),
    ('f.properties.name === st.sel ? "#14202e" : st.mat', 'f.properties.name === st.sel ? "#ffd27a" : st.mat', 1),
    ('f.properties.name === st.sel ? "rgba(20,32,46,0.6)"', 'f.properties.name === st.sel ? "rgba(255,196,64,0.7)"', 1),
    ('color: "#14202e", max: 5', 'color: "#ffd27a", max: 5', 1),
]
# The exposure scale, re-lit: teal for gains, a dark slate for no change, and harm heating from rust to fire.
STOPS_RE = re.compile(r"const STOPS = \[\[-40, [^;]*\]\];")
STOPS_NEW = ('const STOPS = [[-40, "#3ff0c8"], [-15, "#1e9e88"], [0, "#2b3653"], [10, "#6e3a33"], [25, "#b8492e"], '
             '[40, "#ff5a33"], [65, "#ffcf5a"]];')

HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
"""


def font_css() -> str:
    def face(family, file, weight, extra=""):
        b64 = base64.b64encode((FONTS / file).read_bytes()).decode()
        return (f'@font-face {{ font-family: "{family}"; src: url(data:font/woff2;base64,{b64}) format("woff2"); '
                f"font-weight: {weight}; font-style: normal; font-display: swap;{extra} }}")
    return "\n".join([
        "/* Pixelify Sans and VT323, SIL Open Font License 1.1 (ui/app/vendor/fonts), bundled so the app works offline */",
        face("Pixelify Sans", "pixelify-sans-latin-400-normal.woff2", 400),
        face("Pixelify Sans", "pixelify-sans-latin-700-normal.woff2", 700),
        face("VT323", "vt323-latin-400-normal.woff2", 400, " size-adjust: 122%;"),
    ])


def gas_data() -> str:
    """window.GAS from ui/app/data/gas.json (experiments/gas_routes.py), or nothing if it isn't there yet."""
    f = APP / "data" / "gas.json"
    if not f.exists():
        return ""
    return f"<script>/* gas routes: ui/app/data/gas.json */\nwindow.GAS = {f.read_text(encoding='utf-8').strip()};\n</script>\n"


def mandeb_data() -> str:
    """window.STRAITS.mandeb from ui/strait/data/mandeb-scenarios.js (strait_flow.py --strait mandeb), if present."""
    f = APP.parent / "strait" / "data" / "mandeb-scenarios.js"
    return f"<script>/* Bab el-Mandeb: ui/strait/data/mandeb-scenarios.js */\n{f.read_text(encoding='utf-8').strip()}\n</script>\n" if f.exists() else ""


def main() -> None:
    page = SRC.read_text(encoding="utf-8")
    for old, new, n in SWAPS + world.SWAPS + gas.SWAPS + mandeb.SWAPS + strait.SWAPS + copy_text.SWAPS + flags.SWAPS:
        got = page.count(old)
        if got != n:
            sys.exit(f"expected {n} of {old[:70]!r}, found {got}: the industry page changed, update SWAPS")
        page = page.replace(old, new)
    for tag, (file, note) in CDN.items():
        if page.count(tag) != 1:
            sys.exit(f"expected one {tag}")
        page = page.replace(tag, f"<script>/* {note} */\n{(JS / file).read_text(encoding='utf-8')}\n</script>")
    if len(STOPS_RE.findall(page)) != 1:
        sys.exit("expected one STOPS table in the industry page")
    page = STOPS_RE.sub(STOPS_NEW, page)

    # drop the industry page's own head, reset and title; keep everything from its main <style> on
    body = page[page.index("<style>", page.index('<meta name="claude:viewport-fit-sides"')):]
    first_style_end = body.index("</style>") + len("</style>")
    read = lambda f: (HERE / f).read_text(encoding="utf-8")
    models_data = models.script()   # the Models page, from Seb's notes; empty if no card could be read
    early = (
        f"\n<style>\n{font_css()}\n{read('theme.css')}\n{gas.CSS}\n{mandeb.CSS}\n{strait.CSS}\n{households.CSS}\n{flags.CSS}\n{read('landing.css')}\n{read('ai.css')}\n{read('steps.css')}\n{read('models.css')}\n{read('info.css')}</style>\n"
        f"{gas_data()}{mandeb_data()}{flags.script()}{households.script()}{models_data}<script>\n{read('mandeb.js')}\n</script>\n"
        f"{read('landing.html')}"
        f"<script>\n{read('pixel.js')}\n</script>\n<script>\n{read('sound.js')}\n</script>\n<script>\n{read('landing.js')}\n</script>\n"
    )
    body = body[:first_style_end] + early + body[first_style_end:]
    body += f"\n<script>\n{read('shell.js')}\n</script>\n<script>\n{read('ai.js')}\n</script>\n<script>\n{read('strait.js')}\n</script>\n"
    if households.data() is not None:   # the Households page, from Seb's notes (OXH-8)
        body += f"<script>\n{read('households.js')}\n</script>\n"
    if models_data:   # the Models page: each model's results, tests and limits, read from notes/ and docs/
        body += f"<script>\n{read('models.js')}\n</script>\n"
    body += f"<script>\n{read('infokey.js')}\n</script>\n"   # last: one behaviour for every info key
    fragment = '<title>Hormuz Flow</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n' + body

    if shutil.which("node"):
        for f in ("pixel.js", "sound.js", "landing.js", "shell.js", "ai.js", "strait.js", "mandeb.js", "households.js", "models.js", "infokey.js"):
            r = subprocess.run(["node", "--check", str(HERE / f)], capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"{f}: {r.stderr.strip()}")
    out = APP / "index.html"
    out.write_text(HEAD + fragment.replace("<title>", "<title>", 1).replace(
        '<meta name="claude:viewport-fit-sides" content="cover">\n', '<meta name="claude:viewport-fit-sides" content="cover">\n</head><body>\n', 1)
        + "</body></html>\n", encoding="utf-8")
    print(f"wrote {out.relative_to(APP.parent.parent)} ({out.stat().st_size // 1024} KB)")
    if "--fragment" in sys.argv:
        dest = pathlib.Path(sys.argv[sys.argv.index("--fragment") + 1])
        dest.write_text(fragment, encoding="utf-8")
        print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
