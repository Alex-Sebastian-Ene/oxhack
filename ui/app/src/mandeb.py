"""Bab el-Mandeb in the Strait view, applied after world.SWAPS in build.py.

The strait block in the industry page reads its data once, when the page loads, so the app switches straits by
reloading on #mandeb (mandeb.js). These swaps make that block read window.STRAITS.mandeb in that case
(ui/strait/data/mandeb-scenarios.js, from `uv run experiments/strait_flow.py --strait mandeb`), scale the map at
the strait's own latitude, count laden tankers both ways, and keep the World view on Hormuz.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

SWAPS = [
    # the strait block: which strait's data
    ('  const D = window.STRAIT;\n  const geo = D.geo;',
     '  const D = window.HZStrait.data();\n  const geo = D.geo;', 1),
    ('const KX = KM_LAT * Math.cos(26.4 * Math.PI / 180);', 'const KX = KM_LAT * Math.cos((geo.lat0 || 26.4) * Math.PI / 180);', 1),
    ('const state = { key: "aug2026", view: "truth"', 'const state = { key: window.HZStrait.id === "mandeb" ? "sep2026" : "aug2026", view: "truth"', 1),
    ('const shortLabel = { prewar: "Pre-war", aug2026: "Aug 2026", sep2026: "Sep 2026" };',
     'const shortLabel = { prewar: "Pre-war", aug2026: "Aug 2026", sep2026: "Sep 2026", pre2023: "2023", y2024: "2024", q2_2026: "Q2 2026" };', 1),
    ('  sel.add(new Option("Real · PortWatch", "real"));\n',
     '  if (window.HZStrait.id === "hormuz") sel.add(new Option("Real · PortWatch", "real"));\n', 1),
    # PortWatch counts in this page are Hormuz's
    ('const lastReal = (window.PORTWATCH && window.PORTWATCH.dates) ?', 'const lastReal = (window.HZStrait.id === "hormuz" && window.PORTWATCH && window.PORTWATCH.dates) ?', 1),
    # Bab el-Mandeb carries laden tankers both ways; Hormuz only outbound
    ('if (v.kind !== "tanker" || v.lane !== "outbound" || !v.laden',
     'if (v.kind !== "tanker" || (window.HZStrait.id === "hormuz" && v.lane !== "outbound") || !v.laden', 1),
    ('const MAXP = 22;', 'const MAXP = window.HZStrait.id === "mandeb" ? 12 : 22;', 1),
    ('"Laden tankers out of the Gulf so far";', '(window.HZStrait.id === "mandeb" ? "Laden tankers through, both ways" : "Laden tankers out of the Gulf so far");', 1),
    ('"Laden tankers out of the Gulf so far · simulated";', '(window.HZStrait.id === "mandeb" ? "Laden tankers through, both ways · simulated" : "Laden tankers out of the Gulf so far · simulated");', 1),
    ('const dir = v.lane === "outbound" ? "Outbound, leaving the Gulf" : "Inbound, into the Gulf";',
     'const dir = window.HZStrait.id === "mandeb" ? (v.lane === "outbound" ? "Southbound, out of the Red Sea" : "Northbound, into the Red Sea")\n'
     '      : v.lane === "outbound" ? "Outbound, leaving the Gulf" : "Inbound, into the Gulf";', 1),
    # the World view stays on Hormuz whichever strait is on the map
    ('$("scenario").addEventListener("change", (e) => loadScenario(e.target.value));',
     '$("scenario").addEventListener("change", (e) => { if (window.HZStrait.id === "hormuz") loadScenario(e.target.value); });', 1),
    ('loadScenario($("scenario").value || "aug2026");',
     'loadScenario(window.HZStrait.id === "hormuz" ? ($("scenario").value || "aug2026") : "aug2026");', 1),
]

CSS = """/* Bab el-Mandeb mode (mandeb.py, mandeb.js): Hormuz-only cards hidden, a strait switch in the header */
body.hz-mandeb #link-card, body.hz-mandeb #pw-card, body.hz-mandeb #cap-card { display: none !important; }
.hz-straitseg[hidden] { display: none !important; }
.hz-straitseg button { white-space: nowrap; }
@media (max-width: 720px) { .hz-straitseg button { padding: 0 8px; font-size: 12px; } }
"""
