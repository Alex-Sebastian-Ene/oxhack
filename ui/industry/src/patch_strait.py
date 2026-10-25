# Runs after patch_pulse.py on hormuz-flow.html.
# The Strait view takes the World view's palette: the same light-blue sea, yellow for the shipping lanes
# (yellow = lines everywhere), amber for oil that goes dark, red for fake positions, and sand-coloured land.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


SEEN, OIL, OIL_SOFT, FAKE = "#0a4fd0", "#f26b00", "#c24f00", "#e0201b"
# shared tokens, brighter (the Strait HUD cards and charts read these)
sub("--seen: #1f7fc0; --seen-soft: #3b95d1; --oil: #d9821c; --oil-soft: #a85f0c; --model: #7a62c9; --ok: #2f9a68;",
    f"--seen: {SEEN}; --seen-soft: #2f7ee8; --oil: {OIL}; --oil-soft: {OIL_SOFT}; --model: #7c3aed; --ok: #16a34a;")
sub(".chart .band { fill: rgba(240,162,59,0.18); }", ".chart .band { fill: rgba(242,107,0,0.16); }")
sub('<i style="background:rgba(240,162,59,0.3)"></i>', '<i style="background:rgba(242,107,0,0.28)"></i>')

# the canvas palette
sub('''  const COL = { seen: "#1f7fc0", oil: "#d9821c", oilSoft: "#a85f0c", sea: "#dfeaf3", land: "#cdd5df",
    landEdge: "#aab6c3", lane: "rgba(31,127,192,0.14)", text: "#334155", faint: "#68768a", white: "#14202e", other: "#8a96a3" };''',
f'''  const COL = {{ seen: "{SEEN}", oil: "{OIL}", oilSoft: "{OIL_SOFT}", fake: "{FAKE}", sea: "#a8d8f8", land: "#efe1c2",
    landEdge: "#c2a978", lane: "#ffdc2e", laneEdge: "rgba(20,32,46,0.4)", text: "#14202e", faint: "#1f5f8f", white: "#14202e", other: "#5e6b7a" }};''')
# lanes get the same thin dark edge as the World lines, and dark direction arrows
sub('''    ctx.strokeStyle = COL.lane;
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(5, 3.2 * scale());
    for (const lane of Object.values(lanes)) { path(lane.points); ctx.stroke(); }''',
'''    ctx.lineCap = ctx.lineJoin = "round";
    ctx.strokeStyle = COL.laneEdge;
    ctx.lineWidth = Math.max(5, 3.2 * scale()) + 2;
    for (const lane of Object.values(lanes)) { path(lane.points); ctx.stroke(); }
    ctx.strokeStyle = COL.lane;
    ctx.lineWidth = Math.max(5, 3.2 * scale());
    for (const lane of Object.values(lanes)) { path(lane.points); ctx.stroke(); }''')
sub('    ctx.fillStyle = "rgba(31,127,192,0.35)";\n    for (const lane of Object.values(lanes)) {',
    '    ctx.fillStyle = "rgba(20,32,46,0.5)";\n    for (const lane of Object.values(lanes)) {')
# trails behind tankers: blue when seen on AIS, amber when dark
sub('ctx.strokeStyle = p.aisOn ? "rgba(31,127,192,0.35)" : "rgba(217,130,28,0.4)";',
    'ctx.strokeStyle = p.aisOn ? "rgba(10,79,208,0.45)" : "rgba(242,107,0,0.55)";')
sub('ctx.strokeStyle = "rgba(217,130,28,0.55)";', 'ctx.strokeStyle = "rgba(242,107,0,0.7)";')
# white edge on solid tankers so they pop off the sea
sub('    if (fill) { ctx.fillStyle = fill; ctx.fill(); }\n',
    '    if (fill) { ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = "rgba(255,255,255,0.9)"; ctx.lineWidth = 1; ctx.stroke(); }\n')
# fake AIS positions are harm: red, in the map and in the key
sub("    ctx.strokeStyle = COL.oilSoft;\n    ctx.lineWidth = 2;\n    for (const v of ships) for (const [tp, lon, lat] of v.spoof_points || []) {",
    "    ctx.strokeStyle = COL.fake;\n    ctx.lineWidth = 2;\n    for (const v of ships) for (const [tp, lon, lat] of v.spoof_points || []) {")
sub("keyRow((c) => { c.strokeStyle = COL.oilSoft; c.lineWidth = 2;", "keyRow((c) => { c.strokeStyle = COL.fake; c.lineWidth = 2;")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
