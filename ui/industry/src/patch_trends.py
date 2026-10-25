# Runs last, after patch_tidy.py, on hormuz-flow.html.
# A fifth tab in the country card, "Trends": the country's prices over time and how well we forecast them.
# - How well we forecast it: the industry run's forecast skill for the country's producer prices and output
#   (1 - CRPS / CRPS of a naive forecast, over all horizons), shown as "% less error than a naive forecast".
# - Consumer prices: annual inflation from 2007, all items against one item (food, motor fuels, electricity, gas).
# - One industry at a time: its producer price index from 2007, the extra change the industry run gives those prices
#   over 12 months at the shock card's Brent price (the +10% response scaled in log terms, like the product prices;
#   average effect only, the run gives no range), and its output index (history only: oil doesn't move output reliably).
# Numbers: notes/country-trends.json (experiments/country_trends.py; global_lin in the sector run), read at build time.
# Covers Europe and the US; other countries say so.
import json, pathlib, subprocess

here = pathlib.Path(__file__).parent
root = here.parents[2]
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


data = json.loads((root / "notes" / "country-trends.json").read_text(encoding="utf-8"))
assert data["horizons"] == [1, 3, 6, 12], "the shock path expects the 1, 3, 6 and 12-month responses"
TRENDS_JS = ("  // Country trends (notes/country-trends.json): prices over time, forecast skill and the industry run's oil effects.\n"
             f"  const TRENDS = {json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<' + chr(92) + '/')};\n")

# ---------------------------------------------------------------- markup: the tab's content, moved into its pane by the tab code
SEC = '''        <div id="tr-sec">
          <p class="sub" id="tr-who"></p>
          <div class="eco-block" id="tr-skill-block">
            <span class="label">How well we forecast it</span>
            <div class="tr-skill" id="tr-skill"></div>
            <p class="faint" id="tr-skill-note"></p>
          </div>
          <div class="eco-block" id="tr-cons-block">
            <span class="label">Consumer prices: change on a year earlier</span>
            <div class="seg eseg" role="group" aria-label="Compare all items with" id="tr-pick"></div>
            <p class="eco-head" id="tr-cons-head"></p>
            <div class="chartbox" id="tr-cons-chart"></div>
            <div class="legend2" id="tr-cons-leg"></div>
          </div>
          <div class="eco-block" id="tr-ind-block">
            <span class="label">One industry</span>
            <label class="sr" for="tr-ind">Industry</label><select id="tr-ind"></select>
            <p class="eco-head" id="tr-price-head"></p>
            <div class="chartbox" id="tr-price-chart"></div>
            <p class="eco-head" id="tr-shock-head"></p>
            <div class="chartbox" id="tr-shock-chart"></div>
            <p class="eco-head" id="tr-out-head"></p>
            <div class="chartbox" id="tr-out-chart"></div>
          </div>
          <p class="faint" id="tr-src"></p>
        </div>
'''
a = s.index('<section class="card" id="country-card"')
b = s.index("      </section>", a)
s = s[:b] + SEC + s[b:]

# ---------------------------------------------------------------- the tab
sub('const CTABS = [["overview", "Overview"], ["inds", "Industries"], ["trade", "Trade"], ["econ", "Economy"]];',
    'const CTABS = [["overview", "Overview"], ["inds", "Industries"], ["trade", "Trade"], ["econ", "Economy"], ["trends", "Trends"]];')
sub('pane("econ", [$("e-sec")])];', 'pane("econ", [$("e-sec")]), pane("trends", [$("tr-sec")])];')

JS = TRENDS_JS + r'''  // the World map's names for countries whose names differ in the data
  const TR_GEO = { "United States of America": "US", "Macedonia": "MK", "Bosnia and Herz.": "BA", "Turkey": "TR" };
  Object.entries(TRENDS.countries).forEach(([g, c]) => { if (!(c.name in TR_GEO)) TR_GEO[c.name] = g; });
  const TR_IND = Object.fromEntries(TRENDS.industries);
  const TR_ITEM = { TOTAL: "All items", CP01: "Food", CP0722: "Motor fuels", CP0451: "Electricity", CP0452: "Gas" };
  const TR_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let trPick = "CP0722", trInd = "C";
  const trAbs = (from, i = 0) => { const [y, m] = from.split("-").map(Number); return y * 12 + m - 1 + i; };
  const trMonth = (k) => `${TR_MON[k % 12]} ${Math.floor(k / 12)}`;
  const trNum = (v, d = 1) => `${v > 0.5 * 10 ** -d ? "+" : v < -0.5 * 10 ** -d ? "−" : ""}${Math.abs(v).toFixed(d)}`;
  const trLast = (ser) => { for (let i = ser.v.length - 1; i >= 0; i--) if (ser.v[i] != null) return [trAbs(ser.from, i), ser.v[i], i]; return null; };
  // Monthly lines from TRENDS.start, with a crosshair read-out. lines: [{ ser, cls, name }]; ref: a reference value and its label.
  function trChart(box, lines, { unit = "", ref = null, refLab = "", digits = 1 } = {}) {
    const W = 340, H = 160, L = 40, Rr = 58, T = 12, B = 24, k0 = trAbs(TRENDS.start);
    const pts = lines.map((ln) => ln.ser.v.map((v, i) => [trAbs(ln.ser.from, i) - k0, v]));
    const kn = Math.max(...pts.map((p) => p[p.length - 1][0]));
    const vals = pts.flat().filter((q) => q[1] != null).map((q) => q[1]).concat(ref == null ? [] : [ref]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = Math.max((hi - lo) * 0.08, 0.5);
    lo -= pad; hi += pad;
    const x = (i) => L + i / kn * (W - L - Rr), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200].find((st_) => (hi - lo) / st_ <= 5) || 500;
    let g = "";
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) g += `<line class="gl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 6}" y="${y(v) + 3.5}" text-anchor="end">${unit === "%" ? trNum(v, 0) : v.toFixed(0)}</text>`;
    const y0 = Math.floor(k0 / 12);
    for (let yr = Math.ceil(y0 / 4) * 4; yr * 12 - k0 <= kn; yr += 4) if (yr * 12 >= k0) g += `<text class="ax" x="${x(yr * 12 - k0)}" y="${H - 6}" text-anchor="middle">${yr}</text>`;
    const path = (p) => p.map(([i, v], j) => (v == null ? "" : `${j && p[j - 1][1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join("");
    const ends = pts.map((p) => p.filter((q) => q[1] != null).pop());
    const ly = ends.map(([, v]) => y(v) + 4);
    if (ly.length === 2 && Math.abs(ly[0] - ly[1]) < 12) { const up = ly[0] < ly[1] ? 0 : 1; ly[up] = Math.min(ly[up], ly[1 - up]) - 6; ly[1 - up] = ly[up] + 12; }
    const lab = ends.map(([i, v], j) => `<circle class="tr-dot ${lines[j].cls}" cx="${x(i)}" cy="${y(v)}" r="3"/><text class="endlab" x="${x(i) + 7}" y="${ly[j]}">${unit === "%" ? trNum(v) + "%" : v.toFixed(digits)}</text>`).join("");
    const refl = ref == null ? "" : `<line class="ref" x1="${L}" x2="${W - Rr}" y1="${y(ref)}" y2="${y(ref)}"/><text class="reflab" x="${L + 4}" y="${y(ref) - 4}">${refLab}</text>`;
    const name = lines.map((ln, j) => `${ln.name} ${unit === "%" ? trNum(ends[j][1]) + "%" : ends[j][1].toFixed(digits)} in ${trMonth(ends[j][0] + k0)}`).join("; ");
    box.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escH(name)}">${g}${refl}
      ${lines.map((ln, j) => `<path class="tr-line ${ln.cls}" d="${path(pts[j])}"/>`).join("")}${lab}
      <line class="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/>
      <rect class="hit" x="${L}" y="${T}" width="${W - L - Rr}" height="${H - T - B}"/></svg><div class="ctip" hidden></div>`;
    const sv = box.querySelector("svg"), cx = sv.querySelector(".cross"), ct = box.querySelector(".ctip");
    const at = pts.map((p) => new Map(p.map(([i, v]) => [i, v])));
    const move = (e) => {
      const r = sv.getBoundingClientRect();
      const i = Math.max(0, Math.min(kn, Math.round(((e.clientX - r.left) / r.width * W - L) / (W - L - Rr) * kn)));
      cx.setAttribute("x1", x(i)); cx.setAttribute("x2", x(i)); cx.setAttribute("visibility", "visible");
      ct.hidden = false;
      ct.innerHTML = `${trMonth(i + k0)} · ` + lines.map((ln, j) => { const v = at[j].get(i); return `${escH(ln.name)} <b>${v == null ? "–" : unit === "%" ? trNum(v) + "%" : v.toFixed(digits)}</b>`; }).join(" · ");
      ct.style.left = `${Math.min(Math.max(x(i) / W * r.width - ct.offsetWidth / 2, 0), r.width - ct.offsetWidth)}px`;
      ct.style.top = "-6px";
    };
    const hit = sv.querySelector(".hit");
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { ct.hidden = true; cx.setAttribute("visibility", "hidden"); });
  }
  // The extra change at the shock card's Brent, months 0 to 12: the +10% response scaled by ln(Brent/70)/ln(1.1).
  function trShock(box, resp) {
    const W = 340, H = 120, L = 40, Rr = 58, T = 12, B = 24, f = Math.log(st.brent / BRENT0) / Math.log(1.1);
    const pts = [[0, 0]].concat(TRENDS.horizons.map((h, j) => [h, resp[j] * f]));
    let lo = Math.min(0, ...pts.map((q) => q[1])), hi = Math.max(0, ...pts.map((q) => q[1]));
    const pad = Math.max((hi - lo) * 0.15, 0.2);
    lo -= pad; hi += pad;
    const x = (i) => L + i / 12 * (W - L - Rr), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
    const step = [0.1, 0.2, 0.5, 1, 2, 5, 10].find((st_) => (hi - lo) / st_ <= 4) || 20;
    let g = "";
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) g += `<line class="gl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 6}" y="${y(v) + 3.5}" text-anchor="end">${trNum(v, step < 1 ? 1 : 0)}</text>`;
    [[0, "now"], [3, "3"], [6, "6"], [12, "12 mo"]].forEach(([i, t]) => (g += `<text class="ax" x="${x(i)}" y="${H - 6}" text-anchor="middle">${t}</text>`));
    const end = pts[pts.length - 1][1];
    box.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Extra change from the oil shock: ${trNum(end)}% after 12 months">${g}
      <line class="ref" x1="${L}" x2="${W - Rr}" y1="${y(0)}" y2="${y(0)}"/><text class="reflab" x="${W - Rr + 6}" y="${y(0) + 3.5}">no oil move</text>
      <path class="base" d="M${pts.map(([i, v]) => `${x(i)},${y(v)}`).join("L")}"/>
      ${pts.slice(1).map(([i, v]) => `<circle class="end" cx="${x(i)}" cy="${y(v)}" r="3"/>`).join("")}
      <text class="endlab" x="${x(12) + 7}" y="${y(end) + (Math.abs(y(end) - y(0)) < 10 ? -6 : 4)}">${trNum(end)}%</text></svg>`;
  }
  const trSkill = (v) => `${Math.abs(Math.round(v * 100))}% ${v >= 0 ? "less" : "more"} error`;
  function renderTrends() {
    if (!st.sel || !$("tr-sec")) return;
    const geo = TR_GEO[st.sel], c = geo && TRENDS.countries[geo];
    const nm = geo === "US" ? "the United States" : geo === "UK" ? "the United Kingdom" : c ? c.name : st.sel;
    const show = (id, on) => { $(id).hidden = !on; };
    if (!c) {
      $("tr-who").innerHTML = `No trends for ${escH(nm)}: the price series and the industry model cover Europe and the United States.`;
      ["tr-skill-block", "tr-cons-block", "tr-ind-block"].forEach((id) => show(id, false));
      $("tr-src").textContent = "";
      return;
    }
    const sk = c.skill || {}, inds = TRENDS.industries.map(([k]) => k).filter((k) => (c.price && c.price[k]) || (c.output && c.output[k]));
    $("tr-who").innerHTML = inds.length ? `Prices in <b>${escH(nm)}</b> over time, and how well our industry model forecasts them.`
      : `Consumer prices in <b>${escH(nm)}</b> over time. The industry model has no series for ${escH(nm)}.`;
    // forecast skill: the country's producer prices and output
    show("tr-skill-block", !!(sk.price || sk.output));
    $("tr-skill").innerHTML = [["price", "Producer prices"], ["output", "Output"]].filter(([t]) => sk[t]).map(([t, lab]) =>
      `<div class="tr-tile"><b>${trSkill(sk[t].skill)}</b><span>${lab}</span><small>than a naive forecast; better on ${sk[t].beats} of ${sk[t].of} industries</small></div>`).join("");
    $("tr-skill-note").textContent = `Compared with a naive forecast (each series' usual change and spread) over 1 to 12 months, on ${TRENDS.run.origins} months from ${TRENDS.run.first.slice(0, 4)} to ${TRENDS.run.last.slice(0, 4)}, given the oil price that happened.` +
      (sk.output && sk.price && sk.output.skill < sk.price.skill / 2 ? " Output is much harder to forecast than prices: oil and its own history explain little of it." : "");
    // consumer prices
    const cons = c.consumer || {};
    show("tr-cons-block", !!cons.TOTAL);
    if (cons.TOTAL) {
      const items = Object.keys(TR_ITEM).filter((k) => k !== "TOTAL" && cons[k]);
      if (!cons[trPick]) trPick = items[0] || null;
      $("tr-pick").innerHTML = items.map((k) => `<button type="button" data-trpick="${k}" aria-pressed="${k === trPick}">${TR_ITEM[k]}</button>`).join("");
      $("tr-pick").hidden = !items.length;
      const lines = [{ ser: cons.TOTAL, cls: "tr-a", name: "All items" }].concat(trPick ? [{ ser: cons[trPick], cls: "tr-b", name: TR_ITEM[trPick] }] : []);
      const [ka, va] = trLast(cons.TOTAL), b = trPick && trLast(cons[trPick]);
      $("tr-cons-head").innerHTML = `Prices were <b>${Math.abs(va).toFixed(1)}%</b> ${va >= 0 ? "higher" : "lower"} in ${trMonth(ka)} than a year earlier` +
        (b ? `; ${TR_ITEM[trPick].toLowerCase()} <b>${trNum(b[1])}%</b>.` : ".");
      trChart($("tr-cons-chart"), lines, { unit: "%", ref: 0, refLab: "" });
      $("tr-cons-leg").innerHTML = lines.map((ln) => `<span><i class="${ln.cls}"></i>${ln.name}</span>`).join("");
    }
    // one industry: producer prices, the oil shock's extra change, output
    show("tr-ind-block", inds.length > 0);
    if (inds.length) {
      if (!inds.includes(trInd)) trInd = inds[0];
      $("tr-ind").innerHTML = inds.map((k) => `<option value="${k}"${k === trInd ? " selected" : ""}>${escH(TR_IND[k])}</option>`).join("");
      const pr = c.price && c.price[trInd], out = c.output && c.output[trInd], ind = TR_IND[trInd];
      show("tr-price-chart", !!pr); show("tr-shock-chart", !!pr); show("tr-shock-head", !!pr);
      if (pr) {
        const [k, v, i] = trLast(pr), yr = i >= 12 && pr.v[i - 12] != null ? (v / pr.v[i - 12] - 1) * 100 : null;
        $("tr-price-head").innerHTML = `<b>Producer prices:</b> ${v.toFixed(1)} in ${trMonth(k)} (2021 = 100)` + (yr == null ? "." : `, ${trNum(yr)}% on a year earlier.`) +
          ` Forecasts have ${trSkill(pr.skill)} than a naive one.`;
        trChart($("tr-price-chart"), [{ ser: pr, cls: "tr-a", name: ind }], { ref: 100, refLab: "2021 = 100" });
        const x = st.brent / BRENT0 - 1;
        if (x <= 0.005 || pr.resp.some((r) => r == null)) {
          $("tr-shock-head").innerHTML = x <= 0.005 ? `At $${st.brent} a barrel, oil is at its pre-war price, so there is no knock-on to these prices.` : "The industry model has no oil effect for this series.";
          $("tr-shock-chart").hidden = true;
        } else {
          const p12 = pr.resp[pr.resp.length - 1] * Math.log(1 + x) / Math.log(1.1);
          $("tr-shock-head").innerHTML = `<b>The shock:</b> at <b>$${st.brent}</b> a barrel, these prices end up about <b>${Math.abs(p12).toFixed(1)}%</b> ${p12 >= 0 ? "higher" : "lower"} after 12 months than with no oil move. Average effect only; single outcomes vary.`;
          trShock($("tr-shock-chart"), pr.resp);
        }
      } else $("tr-price-head").innerHTML = `<b>Producer prices:</b> not published for ${escH(ind.toLowerCase())} in ${escH(nm)}.`;
      show("tr-out-chart", !!out);
      if (out) {
        const [k, v] = trLast(out);
        $("tr-out-head").innerHTML = `<b>Output:</b> ${v.toFixed(1)} in ${trMonth(k)} (2021 = 100). Forecasts have ${trSkill(out.skill)} than a naive one. History only: oil doesn't move output reliably in our tests, so there is no what-if.`;
        trChart($("tr-out-chart"), [{ ser: out, cls: "tr-a", name: "Output" }], { ref: 100, refLab: "2021 = 100" });
      } else $("tr-out-head").innerHTML = `<b>Output:</b> not published for ${escH(ind.toLowerCase())} in ${escH(nm)}.`;
    }
    const src = TRENDS.sources.consumer[geo === "US" || geo === "UK" ? geo : "eu"];
    $("tr-src").textContent = `Consumer prices: ${src}. Industries: ${TRENDS.sources.industry}. Forecast skill and oil effect: our industry model, ` +
      `tested ${TRENDS.run.first.slice(0, 4)} to ${TRENDS.run.last.slice(0, 4)}; the oil effect is its average response to a 10% Brent rise, scaled to the chosen price.`;
  }
  $("tr-pick") && $("tr-pick").addEventListener("click", (e) => { const b = e.target.closest("[data-trpick]"); if (b) { trPick = b.dataset.trpick; renderTrends(); } });
  $("tr-ind") && $("tr-ind").addEventListener("change", (e) => { trInd = e.target.value; renderTrends(); });
'''
sub("  function renderCountry() {\n", JS + "  function renderCountry() {\n")
sub("    renderTrade();\n    renderEcon();\n  }", "    renderTrade();\n    renderEcon();\n    renderTrends();\n  }")

CSS = """
/* Trends tab: prices over time and forecast skill for one country. */
#tr-sec { display: flex; flex-direction: column; gap: 16px; }
.tr-skill { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.tr-tile { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel2); }
.tr-tile b { font: 600 17px var(--mono); color: var(--text); }
.tr-tile span { font-size: 13px; color: var(--text); font-weight: 600; }
.tr-tile small { font-size: 12px; color: var(--muted); line-height: 1.4; }
.chart .tr-line { fill: none; stroke-width: 1.6; stroke-linejoin: round; }
.chart .tr-line.tr-a { stroke: var(--text); stroke-width: 2; }
.chart .tr-line.tr-b { stroke: var(--faint); stroke-width: 1.2; stroke-dasharray: 4 2; }
.chart .tr-dot.tr-a { fill: var(--text); stroke: var(--panel); stroke-width: 2; }
.chart .tr-dot.tr-b { fill: var(--faint); stroke: var(--panel); stroke-width: 2; }
.legend2 i.tr-a { background: var(--text); height: 3px; }
.legend2 i.tr-b { background: repeating-linear-gradient(90deg, var(--faint) 0 4px, transparent 4px 6px); height: 2px; }
#tr-ind { width: 100%; }
#tr-pick button { padding: 0 4px; }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
