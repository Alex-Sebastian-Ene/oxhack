# Runs last, after patch_countryoil.py, on hormuz-flow.html.
# Both straits drive the World view: Bab el-Mandeb joins Hormuz on the shock card and on the map.
# 1. The shock card gets a Bab el-Mandeb control under the Hormuz slider: points of that strait's normal flow lost, with
#    presets from our notes (normal; the 2024 Houthi diversion; the Sep 2026 Houthi blockade of Saudi shipping).
# 2. It is turned into Hormuz points with our own numbers, read at build time from notes/mandeb-link.json
#    (experiments/flow_events.py mandeb, from the same PortWatch flows and events as notes/flow-events.md):
#      Hormuz-equivalent = Hormuz lost + Bab el-Mandeb lost x 0.369 (tonnage) x (1 - 63% rerouted round the Cape in 2024)
#                          + Hormuz lost x Yanbu's share of the Gulf's lost exports in 2026 x the share of that bypass lost
#    That one number drives Brent, the release table and every chain effect, so each country's fuel cost, inflation and
#    exposure follow both straits. The Hormuz slider, the flow through Hormuz and the country's own Hormuz numbers stay
#    Hormuz's. The chain's tables stop at 100 (Hormuz shut): a combined loss above that is shown at 100 and the card says
#    so (no extrapolation). The 2026 closure preset replays what happened, Red Sea included, so it adds nothing.
# 3. The map draws Bab el-Mandeb, the Red Sea route to Europe through it, Yanbu's crude to Asia (the East-West pipeline's
#    Red Sea end), and the Cape route rerouted ships take, each saying on hover what is modelled and what is assumed.
# Data is read from notes/ at build time.
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


# ---------------------------------------------------------------- data: notes/mandeb-link.json
link = json.loads((root / "notes" / "mandeb-link.json").read_text(encoding="utf-8"))
div, blk, yb = link["diversion_2024"], link["blockade_2026"], link["yanbu_bypass"]
pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
BAB = {
    "per": link["hormuz_per_mandeb_point"], "rerouted": div["rerouted_share"], "bypass": yb["share"],
    "generated": link["generated"],
    "y2024": {"lost": round(div["lost"]), "from": div["day0"], "to": div["to"], "rerouted": div["rerouted_share"]},
    "b2026": {"lost": round(blk["lost"]), "f": blk["yanbu_lost"], "declared": blk["declared"], "month": blk["month"],
              "cape": blk["cape_gain"]},
    "yanbu": {"share": yb["share"], "before": yb["share_before_blockade"], "from": yb["closure_start"], "to": yb["to"]},
}
assert 0 < BAB["per"] < 1 and 0 <= BAB["rerouted"] < 1 and 0 <= BAB["bypass"] < 1 and 0 <= BAB["b2026"]["f"] <= 1, BAB
SRC = ("Bab el-Mandeb: experiments/flow_events.py mandeb (notes/mandeb-link.json, generated "
       f"{link['generated']}), IMF PortWatch tanker flows and port exports, as notes/flow-events.md")
TIP = (f"Our model: one point of Bab el-Mandeb's normal tanker tonnage is {BAB['per']:.3f} Hormuz points (PortWatch, 2019-2024 "
       f"means); in the 2024 diversion {pct(BAB['rerouted'])} of the lost flow went round the Cape; Yanbu made up "
       f"{pct(BAB['bypass'])} of the Gulf's lost exports over the 2026 closure. Assumed: any Red Sea loss reroutes as in 2024; "
       "Yanbu's extra crude all sails through Bab el-Mandeb; losing a share of the strait's flow loses the same share of "
       "Yanbu's bypass unless measured (Sep 2026). " + SRC)
TIP24 = (f"The 2023-24 Houthi attacks: {div['lost']:.0f} points of Bab el-Mandeb's flow lost by {div['to']} (from "
         f"{div['day0']}, against the flow before), {pct(div['rerouted_share'])} of it rerouted round the Cape (PortWatch, "
         "notes/flow-events.md)")
TIP26 = (f"After the Houthis declared a blockade of Saudi shipping on {blk['declared']} (news reports): {blk['lost']:.0f} points "
         f"of the strait's flow lost in {blk['month']} against the flow before, and Yanbu's extra exports gone "
         f"({pct(blk['yanbu_lost'])}; PortWatch). The Cape gained nothing ({blk['cape_gain']:+.0f} points)")

# ---------------------------------------------------------------- state and the rule
sub('const st = { key: "aug2026", path26: false,', 'const st = { key: "aug2026", path26: false, bab: 0, babF: 0, eq: 82, babQ: null,')
BAB_JS = (
    "  // Bab el-Mandeb in Hormuz points (patch_straits.py), notes/mandeb-link.json from experiments/flow_events.py mandeb:\n"
    "  // per: Hormuz points per Bab el-Mandeb point (tonnage); rerouted: share round the Cape in 2024; bypass: Yanbu's share\n"
    "  // of the Gulf's lost exports over the 2026 closure (built into the per-point curve, and lost with the Red Sea)\n"
    f"  const BAB = {json.dumps(BAB, separators=(',', ':'))};\n"
    f"  const BAB_SRC = {json.dumps(SRC)};\n"
) + r'''  function eqOf(lost = st.lost, bab = st.bab, f = st.babF) {
    const red = bab * BAB.per * (1 - BAB.rerouted), byp = lost * BAB.bypass * f, raw = lost + red + byp;
    return { red, byp, raw, eq: Math.min(100, raw), capped: raw > 100 };
  }
  // the loss that drives Brent and the chain; the 2026 replay already holds what happened in the Red Sea
  function syncEq() {
    st.babQ = st.path26 ? { red: 0, byp: 0, raw: st.lost, eq: st.lost, capped: false } : eqOf();
    st.eq = st.babQ.eq;
  }
  function setBab(v, f) {
    st.bab = Math.max(0, Math.min(100, Math.round(v)));
    st.babF = f == null ? st.bab / 100 : f;
    if ($("bab")) $("bab").value = st.bab;
    if (st.path26 && st.bab) setLost(st.lost);
    else { syncEq(); st.brent = Math.round(brentRes()); $("brent").value = st.brent; }
  }
  // "With 67% of Hormuz oil lost", naming Bab el-Mandeb when it adds something
  function lostWords(html) {
    const b = (x) => (html ? `<b>${x}</b>` : x), q = st.babQ;
    if (!st.bab || st.path26) return `With ${b(`${st.lost}%`)} of Hormuz oil lost`;
    const eq = `${Math.round(q.raw)} Hormuz-equivalent points${q.capped ? ", counted as 100" : ""}`;
    return st.lost ? `With ${b(`${st.lost}%`)} of Hormuz oil and ${b(`${st.bab}%`)} of Bab el-Mandeb's flow lost (${eq})`
      : `With ${b(`${st.bab}%`)} of Bab el-Mandeb's flow lost and Hormuz normal (${eq})`;
  }
'''
sub("  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n",
    "  const brentFor = (lost, e = PREM.mid) => BRENT0 * Math.exp(e * lost);\n" + BAB_JS)

# the combined loss drives the chain, the release table and Brent
sub("  function chainEffect(series, month = 12, lost = st.lost, pol = st.rel) {\n    const a = st.path26 && lost === st.lost &&",
    "  function chainEffect(series, month = 12, lost = st.eq, pol = st.rel) {\n    const a = st.path26 && lost === st.eq &&")
sub("  const resAt = (lost = st.lost, pol = st.rel) =>", "  const resAt = (lost = st.eq, pol = st.rel) =>")
sub('    const iea = [PREM.low, PREM.mid, PREM.high][k] * st.lost, base = resAt(st.lost, "2026")[k];',
    '    const iea = [PREM.low, PREM.mid, PREM.high][k] * st.eq, base = resAt(st.eq, "2026")[k];')
sub("    st.brent = Math.round(brentRes());\n", "    syncEq();\n    st.brent = Math.round(brentRes());\n", count=2)
sub('    if (!st.lost) return "No lost flow, so no stocks are needed.";', '    if (!st.eq) return "No lost flow, so no stocks are needed.";')
sub("chainEffect(sr, 3, st.lost, pol)", "chainEffect(sr, 3, st.eq, pol)")

# ---------------------------------------------------------------- the shock card: a Bab el-Mandeb control under the Hormuz one
sub('''          <div class="resv">
            <span class="label">Emergency oil stocks''', f'''          <div class="babv">
            <span class="label">And Bab el-Mandeb, the Red Sea's southern gate <i class="illus" title="{TIP}">model + assumptions</i></span>
            <div class="babhead"><b id="bab-v">0</b><span id="bab-u">points of its normal flow lost</span></div>
            <label for="bab" class="sr">Lost Bab el-Mandeb flow, points of its normal tanker flow</label>
            <input id="bab" type="range" min="0" max="100" step="1" value="0">
            <div class="presets" role="group" aria-label="Bab el-Mandeb quick choices">
              <button type="button" data-bab="0" aria-pressed="true">Normal · 0</button>
              <button type="button" data-bab="{BAB['y2024']['lost']}" aria-pressed="false" title="{TIP24}">2024 diversion · {BAB['y2024']['lost']}</button>
              <button type="button" data-bab="{BAB['b2026']['lost']}" data-babf="{BAB['b2026']['f']}" aria-pressed="false" title="{TIP26}">Sep 2026 blockade · {BAB['b2026']['lost']}</button>
            </div>
            <p class="sub" id="w-bab"></p>
          </div>
          <div class="resv">
            <span class="label">Emergency oil stocks''')
sub(".resv { display: grid; gap: 6px; margin-top: 10px; }\n",
    ".resv { display: grid; gap: 6px; margin-top: 10px; }\n"
    ".babv { display: grid; gap: 6px; margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--line2); }\n"
    ".babv .sub { margin: 0; }\n.babv .sub b { color: var(--text); }\n"
    ".babhead { display: flex; align-items: baseline; gap: 8px; }\n"
    ".babhead b { font: 500 26px/1 var(--mono); color: #d6337a; }\n.babhead span { font-size: 13px; color: var(--muted); }\n"
    ".babv input { width: 100%; margin: 0; accent-color: #d6337a; min-height: 28px; display: block; }\n"
    ".babv .presets button[aria-pressed=\"true\"] { background: #d6337a; border-color: #d6337a; }\n"
    ".babv .tagm { font-style: normal; font-size: 11px; color: var(--muted); }\n")

RENDER_BAB = r'''  // the Bab el-Mandeb control: what it adds, which parts are our model and which are assumed
  function renderBab() {
    const q = st.babQ || eqOf(), f1 = (x) => x.toFixed(1), M = '<i class="tagm">(our model)</i>', A = '<i class="tagm">(assumption)</i>';
    $("bab-v").textContent = st.path26 ? "2026" : st.bab;
    $("bab-u").textContent = st.path26 ? "as it happened, inside the 2026 replay" : "points of its normal flow lost";
    document.querySelectorAll("[data-bab]").forEach((b) => b.setAttribute("aria-pressed", String(!st.path26 && Number(b.dataset.bab) === st.bab
      && (b.dataset.babf == null || Number(b.dataset.babf) === st.babF))));
    let t;
    if (st.path26) t = `The 2026 closure replays what happened, the Red Sea included: after the Houthis declared a blockade of Saudi shipping (${ymLabel(BAB.b2026.declared.slice(0, 7))}), Bab el-Mandeb lost ${BAB.b2026.lost} points of its flow and Yanbu's bypass to Asia stopped. Pick a level here to set your own; Hormuz is then held at ${st.lost}.`;
    else if (!st.bab) t = `Normal: nothing added. Bab el-Mandeb carries about ${BAB.per.toFixed(2)} times Hormuz's tanker tonnage ${M}${st.lost ? `, and while Hormuz is shut it also carries the Saudi crude piped across Arabia to Yanbu and shipped on to Asia` : ""}.`;
    else {
      const via = st.babF === BAB.b2026.f && st.bab === BAB.b2026.lost ? `${Math.round(st.babF * 100)}% of it, as measured in ${ymLabel(BAB.b2026.month)}` : `${Math.round(st.babF * 100)}% of it, the same share as the strait's flow ${A}`;
      t = `<b>${st.bab}</b> points of its flow are ${f1(st.bab * BAB.per)} Hormuz points of tanker tonnage ${M}. ${Math.round(BAB.rerouted * 100)}% of that goes round the Cape and still arrives, as in 2024 ${A}, so <b>${f1(q.red)}</b> count.`;
      if (st.lost) t += ` With Hormuz down ${st.lost} points, Yanbu's bypass sails through Bab el-Mandeb too: it made up ${Math.round(BAB.bypass * 100)}% of the Gulf's lost exports in 2026 ${M}, and losing ${via} adds <b>${f1(q.byp)}</b>.`;
      t += ` Brent and every number below follow <b>${st.lost} + ${f1(q.red)}${st.lost ? ` + ${f1(q.byp)}` : ""} = ${f1(q.raw)}</b> Hormuz-equivalent points.`;
      if (q.capped) t += ` <b>That is above 100</b>, where the chain's tables stop (Hormuz shut), so they are shown at 100 and understate it.`;
    }
    $("w-bab").innerHTML = t;
  }
'''
sub("  // What the chosen release does, in one line\n", RENDER_BAB + "  // What the chosen release does, in one line\n")
sub('''    $("w-brent-r").textContent = st.lost ? `90% range $${Math.round(brentRes(0))} to $${Math.round(brentRes(2))}.` : "No lost flow: Brent stays at its pre-war $70.";''',
    '''    $("w-brent-r").textContent = st.eq ? `90% range $${Math.round(brentRes(0))} to $${Math.round(brentRes(2))}.${st.bab && !st.path26 ? ` From ${Math.round(st.babQ.raw)} Hormuz-equivalent points: Hormuz and Bab el-Mandeb together${st.babQ.capped ? ", counted as 100" : ""}.` : ""}` : "No lost flow: Brent stays at its pre-war $70.";''')
sub('''    $("w-res").textContent = resLine();\n''', '''    $("w-res").textContent = resLine();\n    renderBab();\n''')
sub('''    $("w-src").textContent += " Emergency stocks: IEA (the 2026 releases to 15 Oct 2026; stocks held for release as of March 2026).";''',
    '''    $("w-src").textContent += " Emergency stocks: IEA (the 2026 releases to 15 Oct 2026; stocks held for release as of March 2026)." + (st.bab && !st.path26 ? ` ${BAB_SRC}.` : "");''')
# the plain-English summary names both straits
sub('''    else if (!st.lost) out.push("With Hormuz flowing normally''', '''    else if (st.bab) {
      out.push(`${lostWords(true)}, Brent averages about <b>$${st.brent}</b> over the next year, <b>${f0(pct)}% more</b> than before the war.`);
      out.push(`Within a year that pushes diesel at the pump <b>up about ${f0(dsl)}%</b> and overall inflation <b>up about ${f1(cpi)} points</b> (US figures, against no disruption).`);
      if (st.rel !== "2026") out.push(st.rel === "none" ? "That assumes no emergency stocks are released." : "That assumes emergency stocks are released as fast as the IEA says its members could.");
    }
    else if (!st.lost) out.push("With Hormuz flowing normally''')
# events: the slider and the presets
sub('''  document.querySelectorAll("[data-path]").forEach((b) => b.addEventListener("click", () => { setPath26(); update(); }));''',
    '''  document.querySelectorAll("[data-path]").forEach((b) => b.addEventListener("click", () => { setPath26(); update(); }));
  $("bab").addEventListener("input", (e) => { setBab(Number(e.target.value)); update(); });
  document.querySelectorAll("[data-bab]").forEach((b) => b.addEventListener("click", () => {
    if (st.path26 && !Number(b.dataset.bab)) return;
    setBab(Number(b.dataset.bab), b.dataset.babf == null ? null : Number(b.dataset.babf)); update();
  }));''')

# ---------------------------------------------------------------- the Economy tab, the product card and the explainer
sub('''    $("e-cpi-head").innerHTML = !st.lost''', '''    $("e-cpi-head").innerHTML = !st.eq''')
sub('''`${st.path26 ? "In the 2026 closure as the IEA counts it" : `With <b>${st.lost}%</b> of Hormuz oil lost`}, prices in ${ECO_NAME[eco]} end up''',
    '''`${st.path26 ? "In the 2026 closure as the IEA counts it" : lostWords(true)}, prices in ${ECO_NAME[eco]} end up''')
sub('''    $("e-un-note").textContent = !st.lost ? "" :''', '''    $("e-un-note").textContent = !st.eq ? "" :''')
sub('''`${st.path26 ? "In the 2026 closure as the IEA counts it" : `With ${st.lost}% of Hormuz flow lost`} (Brent about $${st.brent}), 12 months on.''',
    '''`${st.path26 ? "In the 2026 closure as the IEA counts it" : st.bab ? lostWords(false) : `With ${st.lost}% of Hormuz flow lost`} (Brent about $${st.brent}), 12 months on.''')
sub("${st.lost} points of normal Hormuz flow lost as the IEA counts it, held for 12 months (the reader's choice)`}",
    "${st.lost} points of normal Hormuz flow lost as the IEA counts it, held for 12 months (the reader's choice)"
    "${st.bab ? `, and ${st.bab} points of Bab el-Mandeb's normal flow lost, which with the rerouting round the Cape and the "
    "Yanbu bypass makes ${st.babQ.raw.toFixed(0)} Hormuz-equivalent points${st.babQ.capped ? ' (counted as 100: the chain stops there)' : ''} "
    "(flow_events.py: one Bab el-Mandeb point is ${BAB.per} Hormuz points of tanker tonnage, ${Math.round(BAB.rerouted * 100)}% rerouted in 2024)` : ''}`}")
sub("<li><b>Lines:</b> tanker routes from the strait. Faint lines show pre-war volume, bright lines today's estimated flow.</li>",
    "<li><b>Lines:</b> tanker routes from the strait. Faint lines show pre-war volume, bright lines today's estimated flow.</li>\n"
    "      <li><b>Bab el-Mandeb</b> (pink): the Red Sea's southern gate, on the route to Europe and for the Saudi crude piped to "
    "Yanbu while Hormuz is shut. Its lost flow is added in Hormuz points: our flow model gives the conversion by tanker "
    "tonnage and the share rerouted round the Cape in 2024 (PortWatch); that the same share reroutes again is an assumption. "
    "Paths are approximate.</li>")

# ---------------------------------------------------------------- the map: Bab el-Mandeb, its two flows and the Cape route
PINK = "#ff4f9a"
LANES = {
    # the Red Sea route between the Indian Ocean and Suez, on into the Mediterranean towards Europe
    "red": [[57, 14.6], [52, 13.3], [45, 12.2], [43.3, 12.7], [40, 17], [36, 23], [33.8, 27.6], [32.6, 29.9], [32.4, 31.5], [28, 33.5], [21, 35]],
    # Saudi crude piped across Arabia to Yanbu, then south through the strait to Asia
    "yanbu": [[38.06, 24.09], [38.7, 21.5], [40, 17], [42.4, 14], [43.3, 12.7], [45, 12.2], [52, 13.3], [60, 13.5], [66, 15.5],
              [73, 9.5], [77.5, 5.8], [81, 5.3], [88, 5.7], [94.5, 6.3], [98, 4.6], [100.6, 2.9], [103.6, 1.15]],
    # the East-West pipeline (Petroline), Abqaiq to Yanbu
    "pipe": [[49.68, 25.94], [47.6, 25.0], [45.3, 24.6], [42.5, 24.4], [40, 24.2], [38.06, 24.09]],
    # round the Cape of Good Hope to north-west Europe, the way rerouted ships go
    "cape": [[57, 14.6], [56, 0], [46, -15], [41, -25], [33, -33], [20, -36], [12, -30], [8, -15], [2, -2], [-12, 4], [-19, 15],
             [-18, 27], [-11, 36], [-9.8, 43], [-5.5, 48.3], [-2, 49.9]],
}
MAP_JS = (
    "  // ---- Bab el-Mandeb on the map (patch_straits.py): the strait, the Red Sea route to Europe, Yanbu's crude to Asia\n"
    "  // and the Cape route rerouted ships take. Paths are approximate; widths follow the shock card.\n"
    f"  const BAB_PT = [43.4, 12.6], BAB_LANES = {json.dumps(LANES, separators=(',', ':'))};\n"
) + r'''  // move a projected line a few pixels to its right, so a lane sits beside the oil route it shares
  function babBeside(pts, px) {
    return pts.map((p, i) => { const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], n = Math.hypot(dx, dy) || 1;
      return [p[0] - (dy / n) * px, p[1] + (dx / n) * px]; });
  }
  // what each line carries now, 0 to 1 (drawn width), and what it says on hover
  function babLines() {
    const pass = st.path26 ? 1 - BAB.b2026.lost / 100 : 1 - st.bab / 100, f = st.path26 ? BAB.b2026.f : st.babF;
    const run = st.lost / 100 * (1 - f), cape = st.path26 ? 0 : st.bab / 100 * BAB.rerouted;
    const pc = (x) => `${Math.round(x * 100)}%`;
    return [
      { k: "pipe", v: st.lost ? 0.5 : 0.2, solid: true, idle: !st.lost,
        tip: "East–West pipeline (Petroline), Abqaiq to Yanbu: the Saudi way round Hormuz. Path approximate." },
      { k: "cape", v: cape, dash: "cape", idle: !cape,
        tip: `Round the Cape of Good Hope: ${pc(BAB.rerouted)} of the Red Sea flow lost in 2024 went this way (PortWatch, our model). That the same share reroutes now is an assumption; these cargoes still arrive, two to three weeks later. Path approximate.` },
      { k: "red", v: pass, off: 4,
        tip: `Bab el-Mandeb and the Red Sea route to Europe through Suez: ${pc(pass)} of its normal flow passing${st.path26 ? ` (${ymLabel(BAB.b2026.month)})` : ", as set on the shock card"}. One point of its flow is ${BAB.per} Hormuz points of tanker tonnage (PortWatch, our model). Path approximate.` },
      { k: "yanbu", v: run, idle: !st.lost, off: -4,
        tip: st.lost ? `Yanbu bypass: Saudi crude piped to Yanbu on the Red Sea, then south through Bab el-Mandeb to Asia. It made up ${pc(BAB.bypass)} of the Gulf's lost exports over the 2026 closure (PortWatch, our model); ${pc(1 - f)} of it sails now${st.path26 ? " (stopped by the blockade)" : ""}. That it all goes through Bab el-Mandeb is an assumption. Path approximate.`
          : "Yanbu bypass to Asia: used while Hormuz is shut (none lost now). Path approximate." },
    ];
  }
  function layoutBab() {
    const ls = babLines();
    gBab.selectAll("path.bcase").data(ls, (d) => d.k).join("path").attr("class", "bcase")
      .attr("d", (d) => line(babBeside(BAB_LANES[d.k].map((q) => proj(q)), d.off || 0)));
    gBab.selectAll("path.blane").data(ls, (d) => d.k).join("path").attr("class", "blane")
      .attr("d", (d) => line(babBeside(BAB_LANES[d.k].map((q) => proj(q)), d.off || 0)))
      .selectAll("title").data((d) => [d]).join("title").text((d) => d.tip);
  }
  function babMarker() {
    const b = proj(BAB_PT);
    gH.append("circle").attr("class", "bab-pulse").attr("cx", b[0]).attr("cy", b[1]).attr("r", 4);
    gH.append("circle").attr("class", "bab-pt").attr("cx", b[0]).attr("cy", b[1]).attr("r", 4.5)
      .append("title").text("Bab el-Mandeb: the strait between Yemen and Djibouti, the Red Sea's southern gate");
    gH.append("text").attr("class", "bablabel").attr("x", b[0] - 8).attr("y", b[1] + 16).attr("text-anchor", "end").text("BAB EL-MANDEB");
  }
  function rescaleBab(k) {
    const b = proj(BAB_PT);
    gH.select("text.bablabel").attr("font-size", 12 / k).attr("x", b[0] - 8 / k).attr("y", b[1] + 16 / k);
  }
  function paintBab() {
    const ls = babLines(), key = document.getElementById("wbabkey");
    gBab.style("display", st.mat ? "none" : null);
    if (key) key.hidden = !!st.mat;
    const wd = (d) => (d.solid ? 1.4 + 1.4 * d.v : 0.9 + 4.2 * Math.sqrt(Math.max(d.v, 0)));
    gBab.selectAll("path.blane").data(ls, (d) => d.k).attr("stroke-width", wd)
      .attr("class", (d) => `blane${d.solid ? " solid" : ""}${d.dash ? " cape" : ""}${d.idle ? " idle" : ""}`)
      .style("animation-duration", (d) => `${(1.8 / Math.max(d.v, 0.15)).toFixed(2)}s`)
      .selectAll("title").data((d) => [d]).join("title").text((d) => d.tip);
    gBab.selectAll("path.bcase").data(ls, (d) => d.k).attr("stroke-width", (d) => wd(d) + 2.2).attr("class", (d) => `bcase${d.idle ? " idle" : ""}`);
    const pass = st.path26 ? 100 - BAB.b2026.lost : 100 - st.bab;
    const t = document.getElementById("wbabtxt");
    if (t) t.textContent = `Through Bab el-Mandeb (pink): the Red Sea route to Europe, ${pass}% of normal${st.lost ? "; Yanbu's crude to Asia" : ""}${!st.path26 && st.bab ? "; dashed: round the Cape" : ""}`;
  }
  // the 3D globe: the same lines and a point for the strait, added to what paint3d set
  function babGlobe() {
    if (!G3 || st.mat) return;
    const ls = babLines().filter((d) => !d.idle);
    const base = (G3.pathsData() || []).filter((d) => !d.bab);
    const pc = G3.pathColor(), pw = G3.pathStroke(), pl = G3.pathLabel();
    const call = (fn, d, dflt) => (typeof fn === "function" ? fn(d) : fn == null ? dflt : fn);
    G3.pathsData([...base, ...ls.map((d) => ({ bab: true, pts: BAB_LANES[d.k].map(([lng, lat]) => [lat, lng + (d.off || 0) * 0.08]), w: 0.4 + 1.6 * Math.sqrt(d.v), tip: d.tip }))])
      .pathColor((d) => (d.bab ? ["rgba(255,79,154,0.35)", "''' + PINK + r'''"] : call(pc, d, "#ffd60a")))
      .pathStroke((d) => (d.bab ? d.w : call(pw, d, 1)))
      .pathLabel((d) => (d.bab ? escH(d.tip) : typeof pl === "function" ? pl(d) : ""));
    G3.pointsData([...(G3.pointsData() || []).filter((d) => !d.bab), { bab: true, name: "Bab el-Mandeb", lat: BAB_PT[1], lng: BAB_PT[0], alt: 0.02, r: 0.4, color: "''' + PINK + r'''" }]);
  }
'''
sub('  const gPulse = root.append("g").attr("aria-hidden", "true").style("pointer-events", "none");\n',
    '  const gPulse = root.append("g").attr("aria-hidden", "true").style("pointer-events", "none");\n'
    '  // Bab el-Mandeb lines sit just above the oil routes (patch_straits.py)\n'
    '  const gBab = d3.select(gR.node().parentNode.insertBefore(document.createElementNS("http://www.w3.org/2000/svg", "g"), gR.node().nextSibling)).attr("class", "babl");\n')
sub("  function drawLift() {", MAP_JS + "  function drawLift() {")
sub('    gR.selectAll("path").data(routes).join("path").attr("class", "route").attr("d", ([, d]) => line(d.r.map((p) => proj(p))));\n',
    '    gR.selectAll("path").data(routes).join("path").attr("class", "route").attr("d", ([, d]) => line(d.r.map((p) => proj(p))));\n'
    '    layoutBab();\n')
sub('.text("HORMUZ");\n', '.text("HORMUZ");\n    babMarker();\n')
sub("    const hz = proj([56.4, 26.5]);\n    gH.select(\"text\").attr(\"x\", hz[0] - 8 / k).attr(\"y\", hz[1] - 10 / k);\n",
    "    const hz = proj([56.4, 26.5]);\n    gH.select(\"text\").attr(\"x\", hz[0] - 8 / k).attr(\"y\", hz[1] - 10 / k);\n    rescaleBab(k);\n")
sub("    drawPulses();\n    paint3d();\n  }", "    drawPulses();\n    paintBab();\n    paint3d();\n  }")
sub("      .pathDashLength(0.06).pathDashGap(0.02).pathDashAnimateTime(9000).pathTransitionDuration(0);\n",
    "      .pathDashLength(0.06).pathDashGap(0.02).pathDashAnimateTime(9000).pathTransitionDuration(0);\n    babGlobe();\n")
sub('<div class="flowkey"><i></i><span id="wflowkey">Oil leaving Hormuz, width = volume</span></div>',
    '<div class="flowkey"><i></i><span id="wflowkey">Oil leaving Hormuz, width = volume</span></div>\n'
    '        <div class="flowkey babkey" id="wbabkey"><i></i><span id="wbabtxt">Through Bab el-Mandeb (pink)</span></div>')
CSS = f"""
/* Bab el-Mandeb on the World map (patch_straits.py) */
#world .babl path {{ fill: none; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
#world .babl .bcase {{ stroke: rgba(20,32,46,.55); pointer-events: none; }}
#world .babl .blane {{ stroke: {PINK}; stroke-dasharray: 6 5; animation: oilflow 1.8s linear infinite; pointer-events: stroke; opacity: .95; }}
#world .babl .blane.solid {{ stroke-dasharray: none; animation: none; }}
#world .babl .blane.cape {{ stroke-dasharray: 2 6; }}
#world .babl .idle {{ opacity: .3; }}
#world .babl .bcase.idle {{ opacity: .15; }}
#world .bab-pt {{ fill: {PINK}; stroke: #14202e; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
#world .bab-pulse {{ fill: none; stroke: {PINK}; vector-effect: non-scaling-stroke; animation: pulse 2.4s ease-out infinite; transform-box: fill-box; transform-origin: center; }}
#world .bablabel {{ fill: #d6337a; font: 600 12px var(--mono); letter-spacing: .6px; paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }}
.legendbar .babkey i {{ border-top: 3px dashed {PINK} !important; filter: drop-shadow(0 0 1px rgba(20,32,46,.9)); }}
.legendbar .babkey[hidden] {{ display: none; }}
@media (prefers-reduced-motion: reduce) {{ #world .babl .blane {{ animation: none; }} #world .bab-pulse {{ display: none; }} }}
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()), "| BAB", {k: BAB[k] for k in ("per", "rerouted", "bypass")}, "| presets",
      BAB["y2024"]["lost"], BAB["b2026"]["lost"], "(Yanbu lost", BAB["b2026"]["f"], ")")
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)

# the page's rule gives the same Hormuz-equivalent as flow_events.hormuz_equivalent on the note's worked examples
a = s.index("  function eqOf("); b = s.index("\n  }\n", a) + 4
check = (f"const BAB = {json.dumps(BAB)}, st = {{}};\n" + s[a:b] +
         f"\nconst ex = {json.dumps(link['examples'])};\n"
         "const bad = ex.filter((e) => { const q = eqOf(e.lost, e.bab, e.bypass_lost == null ? e.bab / 100 : e.bypass_lost);\n"
         "  return [[q.red, e.red], [q.byp, e.bypass], [q.raw, e.raw], [q.eq, e.eq]].some(([x, y]) => Math.abs(x - y) > 1e-3) || q.capped !== e.capped; });\n"
         "console.log(bad.length ? 'MISMATCH ' + JSON.stringify(bad) : 'rule ok (' + ex.length + ' examples)');\n")
(here / "chk.js").write_text(check, encoding="utf-8")
r = subprocess.run(["node", str(here / "chk.js")], capture_output=True, text=True)
out = (r.stdout + r.stderr).strip()
assert out.startswith("rule ok"), out
print(out.replace("ok", "matches flow_events.py"))
