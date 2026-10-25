import base64, pathlib, sys
HERE = pathlib.Path(__file__).parent
REPO = HERE.resolve().parents[2]  # the repo root
F = REPO / "ui/app/vendor/fonts"
THUMBS = [(1, "skyline"), (2, "radar"), (3, "pour"), (4, "globe"), (5, "gauge"), (6, "arcade"), (7, "spike"), (8, "maze")]
def face(fam, f, w, extra=""):
    b = base64.b64encode((F / f).read_bytes()).decode()
    return f'@font-face{{font-family:"{fam}";src:url(data:font/woff2;base64,{b}) format("woff2");font-weight:{w};font-display:block;{extra}}}'
fonts = "\n".join([face("Pixelify Sans", "pixelify-sans-latin-400-normal.woff2", 400), face("Pixelify Sans", "pixelify-sans-latin-700-normal.woff2", 700),
                   face("VT323", "vt323-latin-400-normal.woff2", 400)])
lib = (HERE / "src/lib.js").read_text()
extra = {"globe": [(REPO / "ui/app/vendor/js/d3-7.9.0.min.js").read_text(), (REPO / "ui/globe/data/countries.js").read_text()]}
only = sys.argv[1:]
for n, slug in THUMBS:
    if only and slug not in only: continue
    js = HERE / f"src/t{n}.js"
    if not js.exists(): continue
    ex = "".join(f"<script>{e}</script>\n" for e in extra.get(slug, []))
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hormuz Flow thumbnail {n}: {slug}</title>
<!-- fonts: Pixelify Sans and VT323, SIL Open Font License 1.1 -->
<style>{fonts}
html,body{{margin:0;background:#04060c;height:100%}}body{{display:grid;place-items:center}}
canvas{{display:block;width:min(100vw,177.78vh);height:auto;aspect-ratio:16/9;image-rendering:pixelated}}</style></head>
<body><canvas id="c" width="1280" height="720"></canvas>
{ex}<script>{lib}
{js.read_text()}</script></body></html>"""
    (HERE / f"thumb-{n}-{slug}.html").write_text(html)
    print("wrote", f"thumb-{n}-{slug}.html")
