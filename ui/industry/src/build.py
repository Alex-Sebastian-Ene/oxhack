"""Build ui/industry/index.html from Edward's strait page (v8.html) and his materials globe (ui/globe).

Each step reads and rewrites src/hormuz-flow.html; the last one's output is the published artifact.
index.html is the same page with a document head, so it also opens straight from disk.
Run: python ui/industry/src/build.py   (needs node on PATH for the syntax checks)
"""
import pathlib, subprocess, sys

here = pathlib.Path(__file__).parent
STEPS = [
    "patch_world2.py",   # World view: materials globe, flat + 3D, product search, country pop-up
    "patch_colors.py",   # one colour per job, seas and continents, floating country with flag tag, space backdrop
    "patch_vivid.py",    # light-blue sea, one vivid colour per product, Gulf producers outlined amber
    "patch_pulse.py",    # yellow lines, blinking destinations, Hormuz routes on the globe
    "patch_strait.py",   # Strait view on the same palette
    "patch_metals.py",   # Seb's OXH-5 steel and aluminium links
    "patch_panel.py",    # roomier right panel, country card in tabs (Overview, Industries, Trade)
    "patch_shock.py",    # country card first; "The shock" card in three steps with quick prices and a plain-English line
    "patch_economy.py",  # Economy tab: prices and unemployment for the US, UK or euro area (Seb's Bayesian responses)
    "patch_suppliers.py",  # Your suppliers: rate a company's own list (Gemini reads it, our numbers rate it)
]
for step in STEPS:
    r = subprocess.run([sys.executable, "-I", str(here / step)], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or "ok" not in out:
        sys.exit(f"{step} failed:\n{out}")
    print(f"{step}: ok")
(here / "chk.js").unlink(missing_ok=True)
page = (here / "hormuz-flow.html").read_text(encoding="utf-8")
head = '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
(here.parent / "index.html").write_text(head + page, encoding="utf-8")
(here / "hormuz-flow.html").unlink()
print("wrote", here.parent / "index.html")
