# Runs last on hormuz-flow.html.
# The exposure score and the shortage premium came with the original Hormuz Flow artifact and are not from a model:
# the score's weights (0.4 / 0.6, /3, +0.15, x60) and the premium (0.8) are hand-set, with no source yet. Until
# Edward or Seb replies on OXH-3, every place that shows them says so.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


TIP_SCORE = "Illustrative: the score's weights are hand-set, not from a model (asked on OXH-3)"
TIP_FUEL = "In a supply disruption fuel moves 1.49 times its normal link (Seb's cost-of-living model, 90% range 1.08 to 1.89; fitted on the US, UK and euro area, an assumption elsewhere)"
TAG_SCORE = f'<i class="illus" title="{TIP_SCORE}">illustrative</i>'
TAG_FUEL = f'<i class="illus" title="{TIP_FUEL}">disruption ×1.49</i>'
TIP_PATH = "Illustrative: the fuel cost (with the disruption multiplier) decayed at hand-set recovery speeds, not a model forecast"
TAG_PATH = f'<i class="illus" title="{TIP_PATH}">illustrative</i>'

# map legend
sub('<span id="wttl">Exposure score</span>', '<span id="wttl">Exposure score (illustrative)</span>')
sub('`${m.name}: ${st.mode === "exports" ? "who ships it" : "who makes it"}` : "Exposure score";',
    '`${m.name}: ${st.mode === "exports" ? "who ships it" : "who makes it"}` : "Exposure score (illustrative)";')
# country card
sub('<div><b id="c-score">–</b><span>Exposure score</span></div>', f'<div><b id="c-score">–</b><span>Exposure score {TAG_SCORE}</span></div>')
sub('<div><b id="c-fuel">–</b><span>Fuel cost now vs pre-war</span></div>', f'<div><b id="c-fuel">–</b><span>Fuel cost now vs pre-war {TAG_FUEL}</span></div>')
# the 12-month fuel-cost chart: fuel cost with the premium, decayed at hand-set speeds
sub('<span class="label">Fuel cost forecast, next 12 months <span class="mono faint" style="margin:0">(pre-war = 100)</span></span>',
    f'<span class="label">Fuel cost path, next 12 months <span class="mono faint" style="margin:0">(pre-war = 100)</span> {TAG_PATH}</span>')
# pop-up
sub('kpi(fmtS(k.score), "exposure score", k.score', 'kpi(fmtS(k.score), "exposure score, illustrative", k.score', count=2)
sub('kpi(pct(k.fuel), "fuel cost vs pre-war",', 'kpi(pct(k.fuel), "fuel cost, in a disruption",')
# ranking
sub("</svg> Most exposed</span>", f"</svg> Most exposed</span> {TAG_SCORE}")
# info sheets
sub('    score: { title: "Exposure score", html: `<p>',
    '    score: { title: "Exposure score (illustrative)", html: `<p class="illus-note"><b>Illustrative, not from a model.</b> The weights below (0.4 and 0.6 for importers; ÷3, +0.15 and ×60 for exporters) are hand-set and have no source: they came with the original Hormuz Flow page, and Seb confirmed on OXH-3 (25 Oct 2026) that the models cannot fit them. The fuel cost inside the score now uses Seb’s supply-disruption multiplier (1.49), which replaced a hand-set shortage premium. The inputs they combine are cited: EIA 2024 Hormuz volumes and Energy Institute consumption.</p><p>')
sub("plus a shortage premium for the share of a country's oil that came through Hormuz.",
    "plus a shortage premium for the share of a country's oil that came through Hormuz. That premium has been replaced by Seb's supply-disruption multiplier (fuel moves 1.49 times its normal link).")

CSS = """
.illus { display: inline-block; margin-left: 4px; padding: 0 6px; border-radius: 999px; border: 1px dashed var(--line2); font: 600 10.5px/1.6 var(--sans); font-style: normal; color: var(--muted); vertical-align: 1px; white-space: nowrap; cursor: help; }
.illus-note { padding: 10px 12px; border-radius: 8px; background: #fff6e5; border-left: 3px solid #c78100; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
