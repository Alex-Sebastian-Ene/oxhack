# python3 make.py [slug...]: one HTML per still (fonts, d3, countries, flows, kit inlined)
import base64, pathlib, sys
HERE = pathlib.Path(__file__).parent
REPO = HERE.resolve().parents[2]  # the repo root
F = REPO / "ui/app/vendor/fonts"
# (number, name, width, height): 16:9 unless given; 5 is the classic at 3:2
STILLS = [(1, "classic", 1920, 1080), (2, "horizon", 1920, 1080), (3, "knockon", 1920, 1080), (4, "control", 1920, 1080), (5, "classic-3x2", 1920, 1280)]
def face(fam, f, w):
    return f'@font-face{{font-family:"{fam}";src:url(data:font/woff2;base64,{base64.b64encode((F / f).read_bytes()).decode()}) format("woff2");font-weight:{w};font-display:block}}'
fonts = "\n".join([face("Pixelify Sans", "pixelify-sans-latin-400-normal.woff2", 400), face("Pixelify Sans", "pixelify-sans-latin-700-normal.woff2", 700), face("VT323", "vt323-latin-400-normal.woff2", 400)])
libs = "".join(f"<script>{p.read_text()}</script>\n" for p in [REPO / "ui/app/vendor/js/d3-7.9.0.min.js", REPO / "ui/globe/data/countries.js", HERE / "data.js"])
only = sys.argv[1:]
for n, slug, w, h in STILLS:
    js = HERE / f"g{n}.js"
    if (only and slug not in only) or not js.exists(): continue
    (HERE / f"still-{n}-{slug}.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hormuz Flow still {n}: {slug}</title><style>{fonts}
html,body{{margin:0;background:#04060c;height:100%}}body{{display:grid;place-items:center}}canvas{{display:block;width:min(100vw,{100 * w / h:.2f}vh);height:auto}}</style></head>
<body><canvas id="c" width="{w}" height="{h}"></canvas><script>window.STILL_W = {w}; window.STILL_H = {h};</script>
{libs}<script>{(HERE / "lib.js").read_text()}
{(HERE / "kit.js").read_text()}
{js.read_text()}</script></body></html>""")
    print("wrote", f"still-{n}-{slug}.html")
