# Runs after patch_economy.py on hormuz-flow.html.
# Wires the page to Seb's recommended chain (docs/chain.md): lost Hormuz flow -> Brent (flow-premium curve) ->
# knock-ons (equal mix of bayes_own, global_lin and global, plus the margin member on the fuel targets).
# 1. The shock card's slider sets lost Hormuz flow (points of normal, 0 to 100), not a Brent price.
#    Brent becomes an output: pre-war $70 times the flow-premium curve's average log premium over the next
#    12 months (notes/flow-premium-iea.csv: per point of the IEA's lost strait flow, OXH-9), with its 90% band.
#    Everything that still needs a Brent price (steel and aluminium links, country fuel costs, energy bills) uses that.
# 2. Jet fuel, nitrogen fertiliser and plastics resin, diesel at the pump, CPI and unemployment come from the
#    chain's scenario table (notes/chain-scenarios-3m-margins.csv), interpolated between its 0/25/50/82/100 points.
#    Shown as the extra change against no disruption (the table's 0-point mean includes normal trend), with the
#    table's 90% range of outcomes.
# Data is read from notes/ at build time.
import csv, json, math, pathlib, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- data from Seb's chain
SERIES = {"ind_djfuelusgulf": "jet fuel (US Gulf)", "ind_pcu325311325311": "nitrogen fertiliser (US PPI)",
          "ind_pcu325211325211": "plastics resin (US PPI)", "ind_gasdesw": "diesel at the pump (US)",
          "ind_pcu481111481111": "passenger air fares (US PPI)", "ind_pcu481112481112": "air freight (US PPI)",
          "ind_pcu324110324110": "petroleum refineries (US PPI)",
          **{f"{e}_{t}": f"{e}_{t}" for e in ("us", "uk", "ea") for t in ("cpi", "unemp")}}
chain, meta = {}, {}
for r in csv.DictReader((root / "notes" / "chain-scenarios-3m-margins.csv").open(encoding="utf-8")):
    if r["series"] not in SERIES:
        continue
    d = chain.setdefault(r["series"], {"unit": r["unit"], "validated": r["validated"], "pts": {}})
    d["pts"].setdefault(r["flow_drop_points"], {})[r["months_ahead"]] = [round(float(r[k]), 3) for k in ("mean", "q05", "q95")]
    meta = {k: r[k] for k in ("origin", "fitted_to", "generated", "source")}
assert sorted(chain) == sorted(SERIES), sorted(set(SERIES) - set(chain))
for d in chain.values():
    assert sorted(d["pts"], key=int) == ["0", "25", "50", "82", "100"] and all(sorted(m, key=int) == ["1", "3", "6", "12"] for m in d["pts"].values())

prem = list(csv.DictReader((root / "notes" / "flow-premium-iea.csv").open(encoding="utf-8")))
year = [r for r in prem if int(r["trading_day"]) <= 252]          # about 12 months of trading days
PREM = {k: round(sum(float(r[f"e_{k}"]) for r in year) / len(year), 6) for k in ("low", "mid", "high")}
PREM.update(days=len(year), generated=prem[0]["generated"])
assert PREM["low"] <= PREM["mid"] <= PREM["high"]

CHAIN_JS = (
    "  // Seb's recommended chain (docs/chain.md): scenario table, notes/chain-scenarios-3m-margins.csv, as\n"
    "  // series -> lost-flow points -> months ahead -> [mean, q05, q95], in 100 x log change (pp for unemployment)\n"
    f"  const CHAIN = {json.dumps(chain, separators=(',', ':'))};\n"
    f"  const CHAIN_META = {json.dumps(meta)};\n"
    "  // flow-premium curve, notes/flow-premium-iea.csv: average log Brent premium per point of the IEA's lost flow over the next\n"
    f"  // {PREM['days']} trading days (about 12 months), with its 90% band\n"
    f"  const PREM = {json.dumps(PREM)};\n"
) + r'''  const LOSTPTS = [0, 25, 50, 82, 100];
  const CHAIN_PROD = { jet_fuel: "ind_djfuelusgulf", fertiliser: "ind_pcu325311325311", polyethylene: "ind_pcu325211325211" };
  // the table's [mean, q05, q95] at any lost-flow level, straight lines between its five points
  function chainAt(series, lost, month) {
    const t = CHAIN[series].pts, v = Math.max(0, Math.min(100, lost));
    let i = 1; while (i < LOSTPTS.length - 1 && LOSTPTS[i] < v) i++;
    const a = LOSTPTS[i - 1], b = LOSTPTS[i], w = (v - a) / (b - a), A = t[a][month], B = t[b][month];
    return A.map((x, k) => x + w * (B[k] - x));
  }
  // what the shock adds against no disruption: in % for prices, in points for CPI (already about %) and unemployment
  function chainEffect(series, month = 12, lost = st.lost) {
    const a = chainAt(series, lost, month), z = chainAt(series, 0, month)[0];
    const asPct = !/cpi|unemp/.test(series), f = (x) => (asPct ? (Math.exp((x - z) / 100) - 1) * 100 : x - z);
    return { mean: f(a[0]), lo: f(a[1]), hi: f(a[2]) };
  }
  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);
  const lostOfFlow = (flow) => Math.round(Math.max(0, Math.min(100, (1 - flow / PREWAR) * 100)));
  function setLost(v) {
    st.lost = Math.max(0, Math.min(100, Math.round(v)));
    st.flow = PREWAR * (1 - st.lost / 100);
    st.brent = Math.round(brentFor(st.lost));
    $("brent").value = st.brent;
    if ($("lost")) $("lost").value = st.lost;
  }
  const chainSrc = () => `Seb's recommended chain (bayes_own + global_lin + global, with the margin member on fuels), notes/chain-scenarios-3m-margins.csv: fitted to ${CHAIN_META.fitted_to}, started ${CHAIN_META.origin}, generated ${CHAIN_META.generated}`;
'''
sub("  function priceMoveM(m) {\n", CHAIN_JS + "  function priceMoveM(m) {\n    if (m && CHAIN_PROD[m.id]) return { ...chainEffect(CHAIN_PROD[m.id]), chain: true };\n")
sub("    const d = m && m.oil && m.oil.disruption, x = st.brent / BRENT0 - 1;",
    "    if (m && CHAIN_PROD[m.id]) return null;   // the chain's range already covers supply shocks\n"
    "    const d = m && m.oil && m.oil.disruption, x = st.brent / BRENT0 - 1;")
# the product card says where a chain number comes from and what its range means
sub('    $("m-band").textContent = p ? `Brent',
    '    $("m-band").textContent = p && p.chain ? `${st.lost} points of Hormuz flow lost (Brent about $${st.brent}). Extra change against no disruption after 12 months; '
    '90% range of outcomes ${pctP(p.lo)} to ${pctP(p.hi)}. ${chainSrc()}.` : p ? `Brent')

# ---------------------------------------------------------------- state: lost flow is the driver
sub('const st = { key: "aug2026", brent: 104,', 'const st = { key: "aug2026", lost: 69, brent: 104,')
sub("    st.flow = Math.min(D.scenarios[key].estimate.total.p50, PREWAR);\n    st.brent = BRENT_DEFAULT[key] || 90;\n    $(\"brent\").value = st.brent;\n",
    "    setLost(lostOfFlow(Math.min(D.scenarios[key].estimate.total.p50, PREWAR)));\n")
sub('''  $("brent").addEventListener("input", (e) => { st.brent = Number(e.target.value); update(); });
  document.querySelectorAll("[data-brent]").forEach((b) => b.addEventListener("click", () => {
    st.brent = Number(b.dataset.brent); $("brent").value = st.brent; update();
  }));''',
'''  $("lost").addEventListener("input", (e) => { setLost(Number(e.target.value)); update(); });
  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => { setLost(Number(b.dataset.lost)); update(); }));''')

# ---------------------------------------------------------------- the shock card: you choose the lost flow, Brent follows
a = s.index('        <div class="step">\n          <div class="stephead"><span class="num">1</span>')
b = s.rindex('        <div class="step">', a, s.index('<span class="num">3</span>'))
s = s[:a] + '''        <div class="step">
          <div class="stephead you"><span class="num">1</span> You choose: how much Hormuz oil is lost <span class="hint">drag the slider</span></div>
          <div class="pricebig"><b id="lost-v">69</b><span>points of normal flow lost</span></div>
          <div class="slidewrap">
            <label for="lost" class="sr">Lost Hormuz flow, points of the pre-war 20 million barrels a day</label>
            <input id="lost" type="range" min="0" max="100" step="1" value="69" aria-describedby="shock-explain">
            <input id="brent" type="hidden" value="104">
            <div class="marks" aria-hidden="true">
              <span style="left:0%">0<br>normal</span>
              <span style="left:50%">50<br>half</span>
              <span style="left:82%">82<br>2026</span>
              <span class="last" style="left:100%">100<br>shut</span>
            </div>
          </div>
          <div class="presets" role="group" aria-label="Quick choices">
            <button type="button" data-lost="0" aria-pressed="false">Normal · 0</button>
            <button type="button" data-lost="50" aria-pressed="false">Half · 50</button>
            <button type="button" data-lost="82" aria-pressed="false">2026 closure · 82</button>
            <button type="button" data-lost="100" aria-pressed="false">Shut · 100</button>
          </div>
          <div class="kpis kpis2">
            <div><b id="w-flow" class="hurt">–</b><span>million barrels a day still getting through</span></div>
            <div><b id="w-miss" class="hurt">–</b><span>million barrels a day missing vs the pre-war 20</span></div>
          </div>
        </div>
        <div class="step">
          <div class="stephead"><span class="num">2</span> What that does to the oil price <span class="hint">Seb's flow-premium curve</span></div>
          <div class="pricebig"><b id="brent-v">$104</b><span class="delta" id="w-brent">–</span><span>a barrel, average over the next 12 months</span></div>
          <p class="sub" id="w-brent-r"></p>
        </div>
''' + s[b:]
sub('<p class="faint">US figures (FRED): fitted on 1991–2008, tested on 2009–2026. The range under each number is the gap between those two fits. Core inflation, interest rates and mortgages barely move, so they aren\'t shown. Brent on 18 Oct 2026: about $109.</p>',
    '<p class="faint" id="w-src"></p>')
sub('<div><b id="w-petrol">–</b><span id="w-petrol-r">Petrol and diesel at the pump</span></div>', '<div><b id="w-petrol">–</b><span id="w-petrol-r">Diesel at the pump</span></div>')

old_a = s.index("    const pct = (st.brent / BRENT0 - 1) * 100;\n    $(\"w-brent\").textContent = Math.abs(pct) < 0.5 ? \"same as pre-war\"")
old_b = s.index("  function shockFlash(el)")
s = s[:old_a] + r'''    const pct = (st.brent / BRENT0 - 1) * 100, sign = (x) => (x > 0.05 ? "+" : x < -0.05 ? "−" : ""), a = Math.abs;
    $("lost-v").textContent = st.lost;
    $("w-brent").textContent = a(pct) < 0.5 ? "same as pre-war" : `${pct > 0 ? "+" : "−"}${a(pct).toFixed(0)}% vs pre-war`;
    $("w-brent").className = "delta " + (pct > 2 ? "hurt" : pct < -2 ? "gain" : "");
    $("brent-v").textContent = `$${st.brent}`;
    $("w-brent-r").textContent = st.lost ? `90% range $${Math.round(brentFor(st.lost, PREM.low))} to $${Math.round(brentFor(st.lost, PREM.high))}. The curve is fitted to the 2026 closure; the Bab el-Mandeb disruption of 2023–24 checks it out of sample.` : "No lost flow: Brent stays at its pre-war $70 in this curve.";
    const put = (id, v, txt, label) => {
      if ($(id).textContent !== txt && $(id).textContent !== "–") shockFlash($(id).parentElement);
      $(id).textContent = txt;
      $(id).className = v > 0.05 ? "hurt" : v < -0.05 ? "gain" : "";
      $(`${id}-r`).textContent = label;
    };
    const dsl = chainEffect("ind_gasdesw"), cpi = chainEffect("us_cpi");
    const dl = Math.log(st.brent / BRENT0), ec = viaLink("ecpi", dl, 0), [elo, ehi] = rangeOf("ecpi", dl);
    put("w-petrol", dsl.mean, `${sign(dsl.mean)}${a(dsl.mean).toFixed(0)}%`, `Diesel at the pump · range ${sign(dsl.lo)}${a(dsl.lo).toFixed(0)} to ${sign(dsl.hi)}${a(dsl.hi).toFixed(0)}%`);
    put("w-ecpi", ec, `${sign(ec)}${a(ec).toFixed(1)}%`, `Energy bills · range ${sign(elo)}${a(elo).toFixed(1)} to ${sign(ehi)}${a(ehi).toFixed(1)}%`);
    put("w-cpi", cpi.mean, `${sign(cpi.mean)}${a(cpi.mean).toFixed(1)}`, `Overall inflation, in points · range ${sign(cpi.lo)}${a(cpi.lo).toFixed(1)} to ${sign(cpi.hi)}${a(cpi.hi).toFixed(1)}`);
    $("w-src").textContent = `Diesel and inflation (US): ${chainSrc()}. Extra change against no disruption, 12 months on. Energy bills: the linear Brent link in notes/oil-chain-links.md, at that Brent. Ranges are 90% of outcomes.`;
    document.querySelectorAll("[data-lost]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.lost) === st.lost)));
    renderShockExplain();
  }
  // The same numbers in one plain-English sentence, plus the selected country when there is one.
  function renderShockExplain() {
    const pct = (st.brent / BRENT0 - 1) * 100, a = Math.abs, f0 = (x) => a(x).toFixed(0), f1 = (x) => a(x).toFixed(1);
    const dsl = chainEffect("ind_gasdesw").mean, cpi = chainEffect("us_cpi").mean, out = [];
    if (!st.lost) out.push("With Hormuz flowing normally, Seb's chain adds nothing to oil, diesel or inflation.");
    else {
      out.push(`With <b>${st.lost}%</b> of Hormuz oil lost, Brent averages about <b>$${st.brent}</b> over the next year, <b>${f0(pct)}% more</b> than before the war.`);
      out.push(`Within a year that pushes diesel at the pump <b>up about ${f0(dsl)}%</b> and overall inflation <b>up about ${f1(cpi)} points</b> (US figures, against no disruption).`);
    }
    if (st.sel) {
      const k = calc(st.sel), nm = st.sel === "United States of America" ? "the United States" : st.sel;
      if (k.kind === "gulf") out.push(`${nm} is a Gulf producer: what hurts it is oil it can't ship, not the price.`);
      else if (k.kind === "exp") out.push(`${nm} sells oil abroad, so a higher price helps it.`);
      else if (a(k.fuel) >= 0.005) out.push(`For ${nm}, fuel would cost about <b>${f0(k.fuel * 100)}% ${k.fuel > 0 ? "more" : "less"}</b> than before the war${k.hz > 0.01 ? `, with an extra shortage premium because ${f0(k.hz * 100)}% of its oil came through Hormuz` : ""}.`);
    }
    $("shock-explain").innerHTML = out.join(" ");
  }
''' + s[old_b:]

# ---------------------------------------------------------------- Economy tab: the chain's CPI and unemployment, 12 months
sub('''  function ecoPath(series) {
    const x = st.brent / BRENT0 - 1;''', '''  // months 0 to 12 from the chain (straight lines between its 1, 3, 6 and 12-month points), against no disruption
  function ecoPath(series) {
    const at = { 0: { mean: 0, lo: 0, hi: 0 } };
    for (const m of [1, 3, 6, 12]) at[m] = chainEffect(series, m);
    const ks = [0, 1, 3, 6, 12], out = [];
    for (let i = 0; i <= 12; i++) {
      let j = 1; while (ks[j] < i) j++;
      const A = at[ks[j - 1]], B = at[ks[j]], w = (i - ks[j - 1]) / (ks[j] - ks[j - 1]);
      out.push([A.mean + w * (B.mean - A.mean), A.lo + w * (B.lo - A.lo), A.hi + w * (B.hi - A.hi)]);
    }
    return out;
  }
  function ecoPathBayes(series) {
    const x = st.brent / BRENT0 - 1;''')
# the chart takes the path's own length (13 points now, not 37)
sub("    const x = (i) => L + i / 36 * (W - L - Rr), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);",
    "    const N = pts.length - 1, x = (i) => L + i / N * (W - L - Rr), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);")
sub('    [[0, "now"], [12, "12 mo"], [24, "24"], [36, "36"]].forEach(',
    '    (N > 12 ? [[0, "now"], [12, "12 mo"], [24, "24"], [36, "36"]] : [[0, "start"], [3, "3"], [6, "6"], [12, "12 mo"]]).forEach(')
sub("    const m12 = pts[12][0], m36 = pts[36][0];", "    const m12 = pts[12][0], m36 = pts[N][0];")
sub('      <rect class="eco-scen" x="${x(12)}" y="${T}" width="${x(36) - x(12)}" height="${H - T - B}"/>',
    '      ${N > 12 ? `<rect class="eco-scen" x="${x(12)}" y="${T}" width="${x(N) - x(12)}" height="${H - T - B}"/>` : ""}')
sub('''      <circle class="end" cx="${x(36)}" cy="${y(m36)}" r="3.5"/>
      <text class="endlab" x="${x(36) + 7}" y="${y(m36) + 4}">${fmt(m36)}${unit}</text></svg>`;''',
    '''      ${N > 12 ? `<circle class="end" cx="${x(N)}" cy="${y(m36)}" r="3.5"/><text class="endlab" x="${x(N) + 7}" y="${y(m36) + 4}">${fmt(m36)}${unit}</text>` : ""}</svg>`;''')
# the tab's wording: lost flow, the chain, 12 months
s, n = __import__("re").subn(r'    \$\("e-cpi-head"\)\.innerHTML = a\(pct\) < 0\.5\n.*?\n(?=    ecoChart\(\$\("e-cpi-chart"\))',
    '''    $("e-cpi-head").innerHTML = !st.lost
      ? "With Hormuz flowing normally, the chain adds nothing to prices."
      : `With <b>${st.lost}%</b> of Hormuz oil lost, prices in ${ECO_NAME[eco]} end up about <b>${a(c12[0]).toFixed(1)}% ${c12[0] >= 0 ? "higher" : "lower"}</b> after 12 months than with no disruption (90% range ${sg(c12[1])}${a(c12[1]).toFixed(1)} to ${sg(c12[2])}${a(c12[2]).toFixed(1)}%). That adds roughly that much to the year's inflation.`;
''', s, count=1, flags=__import__("re").S)
assert n == 1, "e-cpi-head"
s, n = __import__("re").subn(r'    \$\("e-un-note"\)\.textContent = .*?;\n(?=    \$\("e-src"\))',
    '''    $("e-un-note").textContent = !st.lost ? "" :
      `The chain's unemployment path (grey) moves ${u12[0] < 0 ? "down" : "up"} about ${a(u12[0]).toFixed(2)} points against no disruption, but it has no causal oil link: Seb marks it "forecast only", so it isn't used as an effect (docs/chain.md).`;
''', s, count=1, flags=__import__("re").S)
assert n == 1, "e-un-note"
s, n = __import__("re").subn(r'    \$\("e-src"\)\.textContent = .*?;\n(?=  \})',
    '''    $("e-src").textContent = `${chainSrc()}. Change against no disruption at the chosen lost flow, months 1 to 12 (straight lines between its 1, 3, 6 and 12-month points). The range is 90% of outcomes.`;
''', s, count=1, flags=__import__("re").S)
assert n == 1, "e-src"
s, n = __import__("re").subn(r'<span><i class="eco-sc"></i>[^<]*</span>', "", s, count=1)
assert n == 1, "legend"
sub("    const pct = (st.brent / BRENT0 - 1) * 100, sg = (v) => (v > 0.005 ? \"+\" : v < -0.005 ? \"−\" : \"\"), a = Math.abs;",
    "    const sg = (v) => (v > 0.005 ? \"+\" : v < -0.005 ? \"−\" : \"\"), a = Math.abs;")

# ---------------------------------------------------------------- info sheet
sub("      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)",
    "      <li><b>The model:</b> Seb's recommended chain (<code>docs/chain.md</code>). You set the lost Hormuz flow; Brent follows from the flow-premium curve (<code>notes/flow-premium-iea.csv</code>, per point of the IEA's lost strait flow, fitted to the 2026 closure, checked on Bab el-Mandeb 2023–24); jet fuel, fertiliser, plastics resin, diesel, CPI and unemployment come from its scenario table (<code>notes/chain-scenarios-3m-margins.csv</code>), as the change against no disruption with the 90% range of outcomes. Steel and aluminium use Seb's linear links (OXH-5) at that Brent.</li>\n"
    "      <li><b>Bundled:</b> globe.gl 2.41.4 (MIT)")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()), "| PREM", PREM, "| Brent at 69/82 pts:", round(70 * math.exp(PREM["mid"] * 69)), round(70 * math.exp(PREM["mid"] * 82)))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
