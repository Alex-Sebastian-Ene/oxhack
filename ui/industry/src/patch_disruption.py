# Runs last, after patch_industry.py, on hormuz-flow.html. The two fixes from the data audit (Hormuz Flow data audit doc):
# 1. Fuel in a supply disruption: Seb's cost-of-living model (OXH-3, 25 Oct 2026) finds retail motor fuel moves
#    1.49 times its normal link in supply-disruption months (extra share +0.49, 90% interval 0.08 to 0.89; pooled over
#    the US, UK and euro area; out of sample on the 2026 closure). That replaces the hand-set 0.8 shortage premium,
#    which also scaled by each country's Hormuz share: Seb finds the extra pass-through is global, so it no longer does.
#    It applies to every fuel cost on the page: the country card, the exposure score, the fuel cost path and the
#    Industries tab.
# 2. Where the slider starts: the flow-premium curve was fitted on PortWatch's AIS-visible flow (82 points lost in the
#    2026 closure), so the 2026 scenarios start the slider there. Edward's estimate of the true flow (dark tankers
#    included, on simulated ships) is shown beside it, not fed into the curve.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- 1. the disruption multiplier
sub("  // Shortage premium for oil that came through Hormuz: an assumption, not fitted to data.\n  const SHORT = 0.8;",
    "  // In a supply disruption retail fuel moves 1.49x its normal link (Seb's cost-of-living model, OXH-3: +0.49, 90% interval\n"
    "  // 0.08 to 0.89, pooled over the US, UK and euro area; an assumption for other countries). Replaces the hand-set 0.8 premium.\n"
    "  const DISRUPT = { mid: 0.49, lo: 0.08, hi: 0.89 };\n"
    "  const inDisruption = (s) => s > 0.005;")
sub("    const fuel = price + s * hz * SHORT;              // plus the assumed shortage premium",
    "    const fuel = price * (1 + (inDisruption(s) ? DISRUPT.mid : 0));   // the normal link, times 1.49 in a disruption")
# the 12-month path: the multiplier fades as the flow recovers
sub("      return 100 * (1 + fuelFrac(Math.log(1 + dB)) + s * k.hz * SHORT);",
    "      return 100 * (1 + fuelFrac(Math.log(1 + dB)) * (1 + DISRUPT.mid * (inDisruption(k.s) ? s / k.s : 0)));")
# industries: the same fuel price, with the multiplier's own range widening the row's range
sub("      const lo = sh.s * fuelFrac(k.dlog, 1), hi = sh.s * fuelFrac(k.dlog, 0);",
    "      const dz = inDisruption(k.s);\n"
    "      const lo = sh.s * fuelFrac(k.dlog, 1) * (1 + (dz ? DISRUPT.lo : 0)), hi = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.hi : 0));\n"
    "      const mid = sh.s * fuelFrac(k.dlog, 0) * (1 + (dz ? DISRUPT.mid : 0));")
sub("      return { key, label, why, v: hi, lo: Math.min(lo, hi), hi: Math.max(lo, hi), src: sh.src, lag: sh.lag, sec };",
    "      return { key, label, why, v: mid, lo: Math.min(lo, hi), hi: Math.max(lo, hi), src: sh.src, lag: sh.lag, sec };")
sub("${k.hz > 0.01 ? `, with an extra shortage premium because ${f0(k.hz * 100)}% of its oil came through Hormuz` : \"\"}",
    "${inDisruption(k.s) ? \", with fuel moving about 1.5 times its usual link, as in past supply disruptions\" : \"\"}")

# ---------------------------------------------------------------- 2. the slider starts at the AIS-visible loss
sub('const st = { key: "aug2026", rel: "2026", lost: 69, brent: 104,', 'const st = { key: "aug2026", rel: "2026", lost: 82, brent: 99, est: null,')
sub("    setLost(lostOfFlow(Math.min(D.scenarios[key].estimate.total.p50, PREWAR)));",
    "    // the curve was fitted on AIS-visible flow, 82 points lost in the 2026 closure; Edward's true-flow estimate is shown beside it\n"
    "    st.est = { ...D.scenarios[key].estimate.total, label: D.scenarios[key].label };\n"
    "    setLost(key === \"prewar\" ? 0 : AIS_LOST);")
sub("  function loadScenario(key) {", "  const AIS_LOST = 82;   // PortWatch AIS-visible loss in the 2026 closure, the loss the flow-premium curve was fitted on\n  function loadScenario(key) {")
sub('<b id="lost-v">69</b><span>points of normal flow lost</span>', '<b id="lost-v">82</b><span>points of normal flow lost, as AIS sees it</span>')
sub('max="100" step="1" value="69" aria-describedby="shock-explain">', 'max="100" step="1" value="82" aria-describedby="shock-explain">')
sub('<span>million barrels a day still getting through</span>', '<span>million barrels a day getting through, AIS-visible</span>')
sub('<span>million barrels a day missing vs the pre-war 20</span></div>\n          </div>',
    '<span>million barrels a day missing vs the pre-war 20</span></div>\n          </div>\n          <p class="sub west" id="w-est"></p>')
sub("    $(\"w-flow\").textContent = st.flow.toFixed(1);",
    "    $(\"w-flow\").textContent = st.flow.toFixed(1);\n"
    "    const e = st.est, f1 = (x) => Number(x).toFixed(1);\n"
    "    $(\"w-est\").innerHTML = e && st.key !== \"prewar\" ? `<b>Edward's estimate of the true flow, dark tankers included: ${f1(e.p50)} mb/d</b> (${f1(e.p5)}\\u2013${f1(e.p95)}), on the simulated \"${escH(e.label)}\" scenario. Shown for comparison: the price curve was fitted on AIS-visible flow, so the slider uses that measure.` : \"\";")

CSS = """
.west { margin: 2px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--panel2); font-size: 13px; line-height: 1.5; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
