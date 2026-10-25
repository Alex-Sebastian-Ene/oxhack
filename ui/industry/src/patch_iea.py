# Runs last, after patch_disruption.py. The 2026 preset on the IEA's lost flow (OXH-9, docs/chain.md step 1).
# patch_chain.py reads the premium curve per point of the IEA's lost strait flow (notes/flow-premium-iea.csv). On that
# count 82 points held for 12 months is harsher than 2026 was, so:
# 1. "2026 closure" is no longer the slider at 82. It is the chain's replay of 2026 as the IEA counts it
#    (notes/chain-scenarios-2026-3m-margins.csv, flow_drop_points = iea_2026_path: 89 points lost in March to 47 in
#    September, later months holding the last). Its Brent is pre-war $70 times the curve's mean log premium over the
#    first 252 trading days of that path, with the curve's 90% band. The slider shows the path's March-October
#    average (67 points) and the slider's mark moves from 82 to it.
# 2. The release choice: reserves.py has not been restated on the IEA curve yet (notes/reserve-scenarios.csv is per
#    point of PortWatch's trough). Until it is, "No release" and "Maximum" keep their premium's ratio to the 2026
#    releases at the same lost flow, applied to the IEA curve, so no release never comes out cheaper than 2026's.
# 3. Where the slider starts: patch_disruption.py starts the 2026 scenarios at 82 points "as AIS sees it", because the
#    old curve was fitted on PortWatch's AIS-visible count. The IEA's count includes dark transits and ship-to-ship
#    transfers, so the 2026 scenarios now open on the 2026 preset and the slider is worded for the IEA's count.
#    Edward's true-flow estimate stays beside it, not fed into the curve, because its ships are simulated.
# Data is read from notes/ at build time.
import csv, datetime, json, math, pathlib, re, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- data: the 2026 path, its Brent and its knock-ons
note = (root / "notes" / "chain-replay-2026-3m-margins.md").read_text(encoding="utf-8")
m = re.search(r"IEA 2026:\*\*[^:]*: ([\d, ]+) points of February's strait flow lost in (\d{4})-(\d{2})\.\.(\d{4})-(\d{2})", note)
assert m, "the IEA 2026 path in notes/chain-replay-2026-3m-margins.md"
path = [int(x) for x in m.group(1).split(",")]
y0, m0 = int(m.group(2)), int(m.group(3))
assert len(path) == (int(m.group(4)) - y0) * 12 + int(m.group(5)) - m0 + 1, path
# the curve's trading days: weekdays from day 1 = 2026-03-05 (holidays ignored); months after the path hold its last
prem = list(csv.DictReader((root / "notes" / "flow-premium-iea.csv").open(encoding="utf-8")))
DAYS, day, lost, e = 252, datetime.date(2026, 3, 5), [], {k: [] for k in ("low", "mid", "high")}
while len(lost) < DAYS:
    if day.weekday() < 5:
        i = (day.year - y0) * 12 + day.month - m0
        lost.append(path[min(i, len(path) - 1)])
        r = prem[min(len(lost), len(prem)) - 1]
        for k in e:
            e[k].append(float(r[f"e_{k}"]))
    day += datetime.timedelta(days=1)
P26 = {k: round(sum(a * b for a, b in zip(e[k], lost)) / DAYS, 6) for k in e}
avg_months = path + [path[-1]]                                   # March to October, October holding September
P26.update(path=path, start=f"{y0}-{m0:02d}", avg=round(sum(avg_months) / len(avg_months)), days=DAYS)
assert P26["low"] <= P26["mid"] <= P26["high"] and P26["avg"] == 67, P26

keys = json.loads(re.search(r"  const CHAIN = (\{.*?\});\n", s).group(1)).keys()
chain26, meta26 = {}, {}
for r in csv.DictReader((root / "notes" / "chain-scenarios-2026-3m-margins.csv").open(encoding="utf-8")):
    if r["series"] in keys:
        assert r["flow_drop_points"] == "iea_2026_path", r["flow_drop_points"]
        chain26.setdefault(r["series"], {})[r["months_ahead"]] = [round(float(r[k]), 3) for k in ("mean", "q05", "q95")]
        meta26 = {k: r[k] for k in ("origin", "fitted_to", "generated")}
assert sorted(chain26) == sorted(keys) and all(sorted(v, key=int) == ["1", "3", "6", "12"] for v in chain26.values()), sorted(set(keys) - set(chain26))

# ---------------------------------------------------------------- the preset, the slider mark and the state
sub('              <span style="left:82%">82<br>2026</span>\n', f'              <span style="left:{P26["avg"]}%">{P26["avg"]}<br>2026 avg</span>\n')
tip = (f"The 2026 closure as the IEA counts it: {path[0]} points lost in March, {path[-1]} by September "
       f"(average {P26['avg']}). Seb's chain replayed on that path")
sub('            <button type="button" data-lost="82" aria-pressed="false">2026 closure · 82</button>\n',
    f'            <button type="button" data-path="iea2026" data-avg="{P26["avg"]}" data-txt="{path[0]} points lost in March, {path[-1]} by September" '
    f'aria-pressed="false" title="{tip}">2026 closure</button>\n')
# the slider's numbers on the IEA's count, not patch_disruption.py's AIS-visible one; the unit line is kept for the held case
LOST_U = "points of normal flow lost, as the IEA counts it"
sub('<b id="lost-v">82</b><span>points of normal flow lost, as AIS sees it</span>',
    f'<b id="lost-v">{P26["avg"]}</b><span id="lost-u">{LOST_U}</span>')
sub('max="100" step="1" value="82" aria-describedby="shock-explain">', f'max="100" step="1" value="{P26["avg"]}" aria-describedby="shock-explain">')
sub("<span>million barrels a day getting through, AIS-visible</span>", "<span>million barrels a day getting through, as the IEA counts it</span>")
sub('<span>a barrel, average over the next 12 months</span>', '<span id="brent-u">a barrel, average over the next 12 months</span>')
sub('const st = { key: "aug2026", rel: "2026",', 'const st = { key: "aug2026", path26: false, rel: "2026",')

IEA_JS = (
    "  // the 2026 closure as the IEA counts it (OXH-9): notes/chain-scenarios-2026-3m-margins.csv as series -> months ahead ->\n"
    "  // [mean, q05, q95], and its Brent: the mean log premium per day over 252 trading days of the path (notes/flow-premium-iea.csv)\n"
    f"  const CHAIN26 = {json.dumps(chain26, separators=(',', ':'))};\n"
    f"  const CHAIN26_META = {json.dumps(meta26)};\n"
    f"  const P26 = {json.dumps(P26)};\n"
) + r'''  const pathTxt = () => `${P26.path[0]} points lost in March, ${P26.path[P26.path.length - 1]} by September`;
  function setPath26() {
    st.path26 = true; st.rel = "2026";
    st.lost = P26.avg; st.flow = PREWAR * (1 - st.lost / 100);
    st.brent = Math.round(brentRes());
    $("brent").value = st.brent;
    if ($("lost")) $("lost").value = st.lost;
  }
'''
sub("  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n",
    "  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n" + IEA_JS)
# the chain's 2026 replay when the preset is on (its no-disruption baseline stays the slider table's 0 points)
sub("    const a = chainAt(series, lost, month, pol), z = chainAt(series, 0, month, pol)[0];",
    "    const a = st.path26 && lost === st.lost && pol === \"2026\" ? CHAIN26[series][month] : chainAt(series, lost, month, pol), z = chainAt(series, 0, month, pol)[0];")
# Brent: the path's own premium; the other release policies at their ratio to 2026's, on the IEA curve
sub('  const brentRes = (k = 1) => (st.rel === "2026" ? brentFor(st.lost, [PREM.low, PREM.mid, PREM.high][k]) : BRENT0 * Math.exp(resAt()[k]));',
    '''  const brentRes = (k = 1) => {
    const iea = [PREM.low, PREM.mid, PREM.high][k] * st.lost, base = resAt(st.lost, "2026")[k];
    if (st.path26) return BRENT0 * Math.exp([P26.low, P26.mid, P26.high][k]);
    return BRENT0 * Math.exp(st.rel === "2026" || !base ? iea : iea * resAt()[k] / base);
  };''')
sub("  function setLost(v) {\n    st.lost = ", "  function setLost(v) {\n    st.path26 = false;\n    st.lost = ")
sub('''  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => { setLost(Number(b.dataset.lost)); update(); }));''',
    '''  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => { setLost(Number(b.dataset.lost)); update(); }));
  document.querySelectorAll("[data-path]").forEach((b) => b.addEventListener("click", () => { setPath26(); update(); }));''')
# the 2026 scenarios open on the 2026 preset, not at patch_disruption.py's 82 AIS-visible points
sub("  const AIS_LOST = 82;   // PortWatch AIS-visible loss in the 2026 closure, the loss the flow-premium curve was fitted on\n", "")
sub('''    // the curve was fitted on AIS-visible flow, 82 points lost in the 2026 closure; Edward's true-flow estimate is shown beside it
    st.est = { ...D.scenarios[key].estimate.total, label: D.scenarios[key].label };
    setLost(key === "prewar" ? 0 : AIS_LOST);''',
    '''    // the curve counts the IEA's lost flow, dark transits included, so the 2026 scenarios open on its 2026 path;
    // Edward's true-flow estimate is on simulated ships, so it is shown beside it, not fed into the curve
    st.est = { ...D.scenarios[key].estimate.total, label: D.scenarios[key].label };
    if (key === "prewar") setLost(0); else setPath26();''')
sub("Shown for comparison: the price curve was fitted on AIS-visible flow, so the slider uses that measure.",
    "Shown for comparison only: its ships are simulated, so the price uses the IEA's count, which includes dark tankers too.")

# ---------------------------------------------------------------- what the shock card, the explainers and the sources say
sub('    $("lost-v").textContent = st.lost;\n',
    '    $("lost-v").textContent = st.lost;\n'
    '    $("lost-u").textContent = st.path26 ? `points lost on average in 2026 as the IEA counts it (${P26.path[0]} in March, ${P26.path[P26.path.length - 1]} by September)` : ' + json.dumps(LOST_U) + ';\n'
    '    $("brent-u").textContent = st.path26 ? "a barrel, average over the 12 months from March 2026" : "a barrel, average over the next 12 months";\n')
sub('''    document.querySelectorAll("[data-lost]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.lost) === st.lost)));''',
    '''    document.querySelectorAll("[data-lost]").forEach((b) => b.setAttribute("aria-pressed", String(!st.path26 && Number(b.dataset.lost) === st.lost)));
    document.querySelectorAll("[data-path]").forEach((b) => b.setAttribute("aria-pressed", String(st.path26)));''')
sub('''    const dsl = chainEffect("ind_gasdesw").mean, cpi = chainEffect("us_cpi").mean, out = [];
    if (!st.lost)''', '''    const dsl = chainEffect("ind_gasdesw").mean, cpi = chainEffect("us_cpi").mean, out = [];
    if (st.path26) {
      out.push(`2026 as the IEA counts it (${pathTxt()}): Brent about <b>$${st.brent}</b> over the 12 months from March (<b>+${f0(pct)}%</b>).`);
      out.push(`Diesel <b>${dsl >= 0 ? "+" : "−"}${f0(dsl)}%</b>, inflation <b>${cpi >= 0 ? "+" : "−"}${f1(cpi)} pts</b> within a year (US, vs no disruption).`);
    }
    else if (!st.lost)''')
sub('    if (!st.lost) return "No lost flow, so no stocks are needed.";\n',
    '    if (st.path26) return "As it happened: the 2026 path already includes the emergency stocks released in 2026.";\n'
    '    if (!st.lost) return "No lost flow, so no stocks are needed.";\n')
sub('      : `With <b>${st.lost}%</b> of Hormuz oil lost, prices in ${ECO_NAME[eco]} end up',
    '      : `${st.path26 ? "In the 2026 closure as the IEA counts it" : `With <b>${st.lost}%</b> of Hormuz oil lost`}, prices in ${ECO_NAME[eco]} end up')
sub('`With ${st.lost}% of Hormuz flow lost (Brent about $${st.brent}), 12 months on.',
    '`${st.path26 ? "In the 2026 closure as the IEA counts it" : `With ${st.lost}% of Hormuz flow lost`} (Brent about $${st.brent}), 12 months on.')
# the explainer's scenario line, reworded from patch_explain.py's AIS-visible count
sub("${st.lost} points of normal Hormuz flow lost as AIS sees it (the reader's choice; the price curve was fitted on AIS-visible flow)",
    "${st.lost} points of normal Hormuz flow lost as the IEA counts it, held for 12 months (the reader's choice)")
s, n = re.subn(r"(  const scenFact = \(\) => `Scenario: )(\$\{st\.lost\} points of normal Hormuz flow lost[^`]*?\)), so",
               lambda g: g.group(1) + "${st.path26 ? `the 2026 closure as the IEA counts it (${pathTxt()}; ${st.lost} on average)` : `" + g.group(2) + "`}, so", s, count=1)
assert n == 1, "scenFact"
sub("  const chainSrc = () => `Source: the team's oil-shock model, fitted to data up to ${ymLabel(CHAIN_META.fitted_to)}`;",
    "  const chainSrc = () => `Source: the team's oil-shock model, fitted to data up to ${ymLabel(CHAIN_META.fitted_to)}${st.path26 ? \", replayed on 2026 as the IEA counts it\" : \"\"}`;")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()), "| P26", {k: P26[k] for k in ("low", "mid", "high", "avg")}, "| Brent on the 2026 path:",
      round(70 * math.exp(P26["mid"])), "| 82 held:", round(70 * math.exp(json.loads(re.search(r"const PREM = (\{[^}]*\})", s).group(1))["mid"] * 82)))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
