# Runs after patch_tidy.py on hormuz-flow.html.
# Emergency oil stocks (experiments/reserves.py, notes/reserves.md):
# 1. The shock card gets a release choice under the lost-flow slider: no release, as in 2026 (the default, which
#    leaves every number as it was) or the IEA's maximum rate. Brent follows the reserve-aware premium
#    (notes/reserve-scenarios.csv: the flow-premium curve restated per net barrel missing). The chain's knock-ons
#    are the published table plus the policy's difference from the 2026 run in the chain's own replays under each
#    policy (notes/chain-scenarios-3m-d2000-margins*.csv: same members, 2,000 draws on the same random numbers).
# 2. The country card and pop-up show the country's oil stocks in days of net imports
#    (notes/reserves/country-cover.csv) and, for importers, how long they would replace its lost Hormuz oil.
# Data is read from notes/ at build time.
import csv, json, pathlib, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- data
rows = list(csv.DictReader((root / "notes" / "reserve-scenarios.csv").open(encoding="utf-8")))
RES = {}
for r in rows:
    RES.setdefault(r["policy"], []).append([round(float(r[k]), 5) for k in
        ("logprem_low", "logprem_mid", "logprem_high", "release_mean_mbd", "release_total_mb")]
        + [int(r[k]) if r[k] else None for k in ("runout_day", "end_day")])
assert sorted(RES) == ["2026", "max", "none"] and all(len(v) == 101 for v in RES.values()), sorted(RES)


def chain_table(policy):
    f = root / "notes" / f"chain-scenarios-3m-d2000-margins{'' if policy == '2026' else '-release-' + policy}.csv"
    t = {}
    for r in csv.DictReader(f.open(encoding="utf-8")):
        t[(r["series"], r["flow_drop_points"], r["months_ahead"])] = [float(r[k]) for k in ("mean", "q05", "q95")]
    return t, r["generated"]


base, chain_gen = chain_table("2026")
DELTA = {}
for pol in ("none", "max"):
    t, _ = chain_table(pol)
    for (series, pts, month), v in t.items():
        if f'"{series}":' in s[s.index("const CHAIN = "):s.index("const CHAIN_META")]:  # the series the page shows
            DELTA.setdefault(pol, {}).setdefault(series, {}).setdefault(pts, {})[month] = [
                round(a - b, 3) for a, b in zip(v, base[(series, pts, month)])]
assert all(DELTA[p][x]["0"][m] == [0, 0, 0] for p in DELTA for x in DELTA[p] for m in DELTA[p][x]["0"]), "lost 0 must not move"
stock = [r for r in csv.DictReader((root / "notes" / "reserves" / "stocks.csv").open(encoding="utf-8")) if r["releasable"] == "yes"]
RES_META = {"generated": rows[0]["generated"], "stock_mb": round(sum(float(r["volume_mb"]) for r in stock)),
            "rate_mbd": round(sum(float(r["max_rate_mbd"] or 0) for r in stock), 1),
            "as_of": max(r["as_of"] for r in stock)}
COVER = {r["country"]: {"v": float(r["value"]), "unit": r["unit"], "asof": r["as_of"], "basis": r["basis"], "src": r["source"], "url": r["url"]}
         for r in csv.DictReader((root / "notes" / "reserves" / "country-cover.csv").open(encoding="utf-8"))}

RES_JS = (
    "  // Emergency stocks (experiments/reserves.py), notes/reserve-scenarios.csv: policy -> lost points 0..100 ->\n"
    "  // [12-month mean log Brent premium low, mid, high; mean release mb/d; total mb; day the stocks run out;\n"
    "  //  day the release ends] (calendar days from the start of the loss)\n"
    f"  const RES = {json.dumps(RES, separators=(',', ':'))};\n"
    f"  const RES_META = {json.dumps(RES_META | {'chain_generated': chain_gen})};\n"
    "  // the chain under each policy minus the chain as in 2026 (notes/chain-scenarios-3m-d2000-margins*.csv), as\n"
    "  // policy -> series -> lost points -> months ahead -> [mean, q05, q95], added to CHAIN\n"
    f"  const RES_DELTA = {json.dumps(DELTA, separators=(',', ':'))};\n"
    "  // stocks by country in their source's own unit, notes/reserves/country-cover.csv\n"
    f"  const COVER = {json.dumps(COVER, separators=(',', ':'))};\n"
) + r'''  const resAt = (lost = st.lost, pol = st.rel) => RES[pol][Math.max(0, Math.min(100, Math.round(lost)))];
  // "2026" is the flow-premium curve as it is (factor 1), so it keeps the chain's own Brent to the dollar
  const brentRes = (k = 1) => (st.rel === "2026" ? brentFor(st.lost, [PREM.low, PREM.mid, PREM.high][k]) : BRENT0 * Math.exp(resAt()[k]));
  // a country's stocks in its source's unit, and the days they would replace its lost Hormuz oil (as reserves.py)
  function coverOf(name) {
    const cv = COVER[name], d = info(name);
    if (!cv) return null;
    const kb = cv.unit === "days of net imports" ? cv.v * d.c * Math.max(d.m, 0) : cv.unit === "days of demand" ? cv.v * d.c
      : cv.unit === "million barrels" ? cv.v * 1000 : null, gap = d.h * st.lost / 100;
    const txt = cv.unit === "million barrels" ? `about ${Math.round(cv.v).toLocaleString("en-GB")} million barrels`
      : `about ${Math.round(cv.v)} ${cv.unit.replace(" (official claim)", "")}`;
    return { ...cv, txt, replace: kb && gap > 0 ? kb / gap : null };
  }
  const daysTxt = (x) => (x > 365 ? "more than a year" : `about ${Math.round(x)} days`);
'''
sub("  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n",
    "  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n" + RES_JS)
sub("    st.brent = Math.round(brentFor(st.lost));\n", "    st.brent = Math.round(brentRes());\n")
sub("  function chainAt(series, lost, month) {", "  function chainAt(series, lost, month, pol = st.rel) {")
sub("    return A.map((x, k) => x + w * (B[k] - x));\n",
    "    const D = (RES_DELTA[pol] || {})[series], dA = D ? D[a][month] : [0, 0, 0], dB = D ? D[b][month] : [0, 0, 0];\n"
    "    return A.map((x, k) => x + dA[k] + w * (B[k] + dB[k] - x - dA[k]));\n")
sub('''  function chainEffect(series, month = 12, lost = st.lost) {
    const a = chainAt(series, lost, month), z = chainAt(series, 0, month)[0];''',
    '''  function chainEffect(series, month = 12, lost = st.lost, pol = st.rel) {
    const a = chainAt(series, lost, month, pol), z = chainAt(series, 0, month, pol)[0];''')
sub('const st = { key: "aug2026", lost: 69,', 'const st = { key: "aug2026", rel: "2026", lost: 69,')

# ---------------------------------------------------------------- the shock card: a release choice under the slider
sub('''            <div><b id="w-miss" class="hurt">–</b><span>million barrels a day missing vs the pre-war 20</span></div>
          </div>
''', '''            <div><b id="w-miss" class="hurt">–</b><span>million barrels a day missing vs the pre-war 20</span></div>
          </div>
          <div class="resv">
            <span class="label">Emergency oil stocks <i class="illus" title="Assumption: Brent's premium scales with the barrels still missing after releases (one closure cannot test it). Stocks and the 2026 releases are sourced: notes/reserves.md">assumed</i></span>
            <div class="presets" role="group" aria-label="Emergency stock release">
              <button type="button" data-rel="none" aria-pressed="false">No release</button>
              <button type="button" data-rel="2026" aria-pressed="true">As in 2026</button>
              <button type="button" data-rel="max" aria-pressed="false">Maximum</button>
            </div>
            <p class="sub" id="w-res"></p>
          </div>
''')
sub(".presets { display: flex; flex-wrap: wrap; gap: 6px; }\n",
    ".presets { display: flex; flex-wrap: wrap; gap: 6px; }\n.resv { display: grid; gap: 6px; margin-top: 10px; }\n.resv .sub { margin: 0; }\n")
sub('''    $("w-brent-r").textContent = st.lost ? `90% range $${Math.round(brentFor(st.lost, PREM.low))} to $${Math.round(brentFor(st.lost, PREM.high))}.''',
    '''    $("w-brent-r").textContent = st.lost ? `90% range $${Math.round(brentRes(0))} to $${Math.round(brentRes(2))}.''')
sub('''    document.querySelectorAll("[data-lost]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.lost) === st.lost)));
    renderShockExplain();''', '''    document.querySelectorAll("[data-lost]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.lost) === st.lost)));
    document.querySelectorAll("[data-rel]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rel === st.rel)));
    $("w-res").textContent = resLine();
    $("w-src").textContent += " Emergency stocks: IEA (the 2026 releases to 15 Oct 2026; stocks held for release as of March 2026).";
    renderShockExplain();''')
sub("  // The same numbers in one plain-English sentence, plus the selected country when there is one.\n", r'''  // What the chosen release does, in one line
  function resLine() {
    const [, , , mean, total, out, end] = resAt(), mb = (x) => `${Math.round(x).toLocaleString("en-GB")} million barrels`;
    const left = out ? `The stocks held for release (${mb(RES_META.stock_mb)}) run out after ${out} days; then those barrels go missing too.`
      : st.rel === "max" && end ? `The release tapers to nothing after ${end} days, as the IEA expects of a maximum drawdown.` : "";
    if (!st.lost) return "No lost flow, so no stocks are needed.";
    // releases act early, so say what the chain gives after 3 months next to the 2026 releases
    const e3 = (sr, pol) => chainEffect(sr, 3, st.lost, pol).mean, f0 = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(0)}%`, f1 = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)}`;
    const early = ` After 3 months: diesel ${f0(e3("ind_gasdesw", st.rel))} (${f0(e3("ind_gasdesw", "2026"))} with the 2026 releases), US prices ${f1(e3("us_cpi", st.rel))} points (${f1(e3("us_cpi", "2026"))}).`;
    if (st.rel === "none") return "No stocks released: every lost barrel is missing from the market, so Brent rises more than it did in 2026." + early;
    if (st.rel === "2026") return `Stocks replace the same share of the lost barrels as the 2026 releases did: about ${mean.toFixed(1)} mb/d on average over the year, ${mb(total)} in total. ${left}`.trim();
    return `Stocks released as fast as the IEA says its members could (up to ${RES_META.rate_mbd} mb/d for two months, never more than the barrels lost): about ${mean.toFixed(1)} mb/d on average over the year, ${mb(total)} in total. ${left}${early}`.trim();
  }
  // The same numbers in one plain-English sentence, plus the selected country when there is one.
''')
sub('''  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => { setLost(Number(b.dataset.lost)); update(); }));
''', '''  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => { setLost(Number(b.dataset.lost)); update(); }));
  document.querySelectorAll("[data-rel]").forEach((b) => b.addEventListener("click", () => { st.rel = b.dataset.rel; setLost(st.lost); update(); }));
''')
# after the two summary lines, which the app's copy_text.py shortens as a pair
sub(''' and overall inflation <b>up about ${f1(cpi)} points</b> (US figures, against no disruption).`);
''', ''' and overall inflation <b>up about ${f1(cpi)} points</b> (US figures, against no disruption).`);
      if (st.rel !== "2026") out.push(st.rel === "none" ? "That assumes no emergency stocks are released." : "That assumes emergency stocks are released as fast as the IEA says its members could.");
''')

# ---------------------------------------------------------------- the country card and pop-up: stock cover
sub('''          <div><b id="c-dep">–</b><span>Oil use sourced via Hormuz</span></div>
        </div>
''', '''          <div><b id="c-dep">–</b><span>Oil use sourced via Hormuz</span></div>
        </div>
        <p class="sub" id="c-res" hidden></p>
''')
sub('''    $("c-dep").textContent = k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–";
''', '''    $("c-dep").textContent = k.kind === "imp" ? `${(k.hz * 100).toFixed(0)}%` : "–";
    const cv = coverOf(name);
    $("c-res").hidden = !cv;
    $("c-res").title = cv ? `${cv.src}: ${cv.url}` : "";
    if (cv) $("c-res").textContent = `Oil stocks: ${cv.txt} (${cv.basis}, ${ymLabel(cv.asof)}${cv.basis === "official claim" ? "; not comparable" : ""}).`
      + (k.kind === "imp" && cv.replace != null ? ` At ${st.lost} points lost they would replace its lost Hormuz oil for ${daysTxt(cv.replace)}, if all of them could be drawn.` : "");
''')
sub('''"Sells oil abroad, so a higher price brings in revenue." : "Pick a product above to see what it makes and trades.";''',
    '''"Sells oil abroad, so a higher price brings in revenue." : (coverOf(name) ? `Oil stocks: ${coverOf(name).txt}. ` : "") + "Pick a product above to see what it makes and trades.";''')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()), "| policies", sorted(RES), "| countries", len(COVER), "| stock", RES_META)
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
