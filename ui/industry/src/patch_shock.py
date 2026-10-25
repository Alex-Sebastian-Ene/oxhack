# Runs after patch_panel.py on hormuz-flow.html.
# Yasmin's layout pass on the World view's right panel:
# 1. The country card comes first, then "The shock" card, then the product card and the ranking.
# 2. "The shock" card reads as three steps, so a reader can tell what the slider changes:
#    (1) what the scenario sets, (2) the Brent price you choose, (3) what follows from it,
#    with price markers, quick prices and a plain-English sentence that updates as the slider moves.
# The numbers are unchanged: same LINK fits (notes/oil-chain-links.md) and the same calc() for the country.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


# ---------------------------------------------------------------- 1. country card first
a = s.index('      <section class="card" id="country-card"')
b = s.index("      </section>\n", a) + len("      </section>\n")
country = s[a:b]
s = s[:a] + s[b:]
# "The shock" card is the first plain card after the product card; take it out too
sa = s.index('      <section class="card">', s.index('<section class="card" id="prod-card"'))
assert "The shock</span>" in s[sa:sa + 400]
sb = s.index("      </section>\n", sa) + len("      </section>\n")
shock = s[sa:sb]
s = s[:sa] + s[sb:]
top = s.index('      <section class="card" id="prod-card"')
s = s[:top] + country + "\n" + shock + "\n" + s[top:]
assert s.index('id="country-card"') < s.index("The shock</span>") < s.index('id="prod-card"') < s.index("Most exposed</span>")

# ---------------------------------------------------------------- 2. "The shock" card as three steps
OLD_CARD = '''        <div class="kpis">
          <div><b id="w-flow" class="hurt">–</b><span>mb/d through Hormuz (est.)</span></div>
          <div><b id="w-miss" class="hurt">–</b><span>mb/d missing vs pre-war 20</span></div>
          <div><b id="w-brent">–</b><span>Brent, vs $70 pre-war</span></div>
        </div>
        <label class="price" for="brent">Brent assumption <input id="brent" type="range" min="60" max="150" step="1" value="104"> <b id="brent-v">$104</b></label>
        <div class="kpis">
          <div><b id="w-petrol">–</b><span id="w-petrol-r">Petrol and diesel</span></div>
          <div><b id="w-ecpi">–</b><span id="w-ecpi-r">Energy prices (CPI)</span></div>
          <div><b id="w-cpi">–</b><span id="w-cpi-r">Headline inflation, 12 months</span></div>
        </div>
        <p class="faint">US pass-through validated on FRED data: fitted 1991–2008, tested on 2009–2026. Core inflation, the Fed and mortgages barely move, so they aren't shown.</p>'''
NEW_CARD = '''        <div class="step">
          <div class="stephead"><span class="num">1</span> How much oil is getting through <span class="hint">set by the scenario menu</span></div>
          <div class="kpis kpis2">
            <div><b id="w-flow" class="hurt">–</b><span>million barrels a day through Hormuz now (est.)</span></div>
            <div><b id="w-miss" class="hurt">–</b><span>million barrels a day missing vs the pre-war 20</span></div>
          </div>
        </div>
        <div class="step">
          <div class="stephead you"><span class="num">2</span> You choose: the price of oil <span class="hint">drag the slider</span></div>
          <p class="ask">What if a barrel of Brent crude cost…</p>
          <div class="pricebig"><b id="brent-v">$104</b><span class="delta" id="w-brent">–</span><span>a barrel</span></div>
          <div class="slidewrap">
            <label for="brent" class="sr">Brent crude price, dollars a barrel</label>
            <input id="brent" type="range" min="60" max="150" step="1" value="104" aria-describedby="shock-explain">
            <div class="marks" aria-hidden="true">
              <span style="left:11.1%">$70<br>pre-war</span>
              <span style="left:54.4%">$109<br>18 Oct</span>
              <span class="last" style="left:100%">$150</span>
            </div>
          </div>
          <div class="presets" role="group" aria-label="Quick prices">
            <button type="button" data-brent="70" aria-pressed="false">Pre-war · $70</button>
            <button type="button" data-brent="109" aria-pressed="false">18 Oct · $109</button>
            <button type="button" data-brent="140" aria-pressed="false">Severe · $140</button>
          </div>
        </div>
        <div class="step">
          <div class="stephead"><span class="num">3</span> What that does over the next 12 months <span class="hint">follows the slider</span></div>
          <div class="kpis">
            <div><b id="w-petrol">–</b><span id="w-petrol-r">Petrol and diesel at the pump</span></div>
            <div><b id="w-ecpi">–</b><span id="w-ecpi-r">Energy bills</span></div>
            <div><b id="w-cpi">–</b><span id="w-cpi-r">Overall inflation, in points</span></div>
          </div>
          <p class="explain" id="shock-explain" aria-live="polite"></p>
        </div>
        <p class="faint">US figures (FRED): fitted on 1991–2008, tested on 2009–2026. The range under each number is the gap between those two fits. Core inflation, interest rates and mortgages barely move, so they aren't shown. Brent on 18 Oct 2026: about $109.</p>'''
sub(OLD_CARD, NEW_CARD)

OLD_JS = '''    const pct = (st.brent / BRENT0 - 1) * 100;
    $("w-brent").textContent = `$${st.brent}`;
    $("w-brent").className = pct > 2 ? "hurt" : pct < -2 ? "gain" : "";
    const dl = Math.log(st.brent / BRENT0);
    const show = (id, key, unit, label) => {
      const [lo, hi] = rangeOf(key, dl), v = viaLink(key, dl, 0);
      const sign = (x) => (x > 0.05 ? "+" : x < -0.05 ? "−" : "");
      $(id).textContent = `${sign(v)}${Math.abs(v).toFixed(1)}${unit}`;
      $(id).className = v > 0.05 ? "hurt" : v < -0.05 ? "gain" : "";
      $(`${id}-r`).textContent = `${label} · ${sign(lo)}${Math.abs(lo).toFixed(1)} to ${sign(hi)}${Math.abs(hi).toFixed(1)}`;
    };
    show("w-petrol", "petrol", "%", "Petrol and diesel");
    show("w-ecpi", "ecpi", "%", "Energy prices (CPI)");
    show("w-cpi", "cpi12", " pp", "Headline inflation, 12 mo");
    $("brent-v").textContent = `$${st.brent}`;
  }'''
NEW_JS = r'''    const pct = (st.brent / BRENT0 - 1) * 100;
    $("w-brent").textContent = Math.abs(pct) < 0.5 ? "same as pre-war" : `${pct > 0 ? "+" : "−"}${Math.abs(pct).toFixed(0)}% vs pre-war`;
    $("w-brent").className = "delta " + (pct > 2 ? "hurt" : pct < -2 ? "gain" : "");
    const dl = Math.log(st.brent / BRENT0);
    const sign = (x) => (x > 0.05 ? "+" : x < -0.05 ? "−" : "");
    const show = (id, key, unit, label) => {
      const [lo, hi] = rangeOf(key, dl), v = viaLink(key, dl, 0);
      const txt = `${sign(v)}${Math.abs(v).toFixed(1)}${unit}`;
      if ($(id).textContent !== txt && $(id).textContent !== "–") shockFlash($(id).parentElement);
      $(id).textContent = txt;
      $(id).className = v > 0.05 ? "hurt" : v < -0.05 ? "gain" : "";
      $(`${id}-r`).textContent = Math.abs(hi - lo) < 0.05 ? label : `${label} · range ${sign(lo)}${Math.abs(lo).toFixed(1)} to ${sign(hi)}${Math.abs(hi).toFixed(1)}${unit}`;
    };
    show("w-petrol", "petrol", "%", "Petrol and diesel at the pump");
    show("w-ecpi", "ecpi", "%", "Energy bills");
    show("w-cpi", "cpi12", "", "Overall inflation, in points");
    $("brent-v").textContent = `$${st.brent}`;
    document.querySelectorAll("[data-brent]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.brent) === st.brent)));
    renderShockExplain();
  }
  // The same numbers in one plain-English sentence, plus the selected country when there is one.
  function renderShockExplain() {
    const dl = Math.log(st.brent / BRENT0), pct = (st.brent / BRENT0 - 1) * 100;
    const petrol = viaLink("petrol", dl, 0), ecpi = viaLink("ecpi", dl, 0), cpi = viaLink("cpi12", dl, 0);
    const a = Math.abs, f0 = (x) => a(x).toFixed(0), f1 = (x) => a(x).toFixed(1);
    const out = [];
    if (a(pct) < 0.5) out.push(`At <b>$${st.brent}</b> a barrel, oil costs about what it did before the war, so pump prices, energy bills and inflation barely move from the price alone.`);
    else {
      const up = pct > 0, rise = up ? "up" : "down";
      out.push(`At <b>$${st.brent}</b> a barrel, oil costs <b>${f0(pct)}% ${up ? "more" : "less"}</b> than before the war.`);
      out.push(`Within a year that pushes petrol and diesel <b>${rise} about ${f0(petrol)}%</b>, energy bills <b>${rise} about ${f0(ecpi)}%</b>, and overall inflation <b>${rise} about ${f1(cpi)} points</b> (US figures).`);
    }
    if (st.sel) {
      const k = calc(st.sel), nm = st.sel === "United States of America" ? "the United States" : st.sel;
      if (k.kind === "gulf") out.push(`${nm} is a Gulf producer: what hurts it is oil it can't ship, not the price.`);
      else if (k.kind === "exp") out.push(`${nm} sells oil abroad, so a higher price helps it.`);
      else if (a(k.fuel) >= 0.005) out.push(`For ${nm}, fuel would cost about <b>${f0(k.fuel * 100)}% ${k.fuel > 0 ? "more" : "less"}</b> than before the war${k.hz > 0.01 ? `, with an extra shortage premium because ${f0(k.hz * 100)}% of its oil came through Hormuz` : ""}.`);
    }
    $("shock-explain").innerHTML = out.join(" ");
  }
  function shockFlash(el) { el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); }'''
sub(OLD_JS, NEW_JS)

# quick prices, and the sentence follows the selected country
sub('''  $("brent").addEventListener("input", (e) => { st.brent = Number(e.target.value); update(); });''',
    '''  $("brent").addEventListener("input", (e) => { st.brent = Number(e.target.value); update(); });
  document.querySelectorAll("[data-brent]").forEach((b) => b.addEventListener("click", () => {
    st.brent = Number(b.dataset.brent); $("brent").value = st.brent; update();
  }));''')

CSS = """
/* "The shock" card in three numbered steps: what the scenario sets, what the slider sets, what follows. */
.step { display: flex; flex-direction: column; gap: 8px; }
.step + .step { border-top: 1px solid var(--line); padding-top: 12px; }
.stephead { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
.stephead .num { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--panel2); border: 1px solid var(--line2); font: 600 11.5px var(--mono); color: var(--text); flex: none; }
.stephead.you { color: var(--text); font-weight: 600; }
.stephead.you .num { background: var(--oil); border-color: var(--oil); color: #fff; }
.stephead .hint { margin-left: auto; font-size: 12px; font-weight: 400; color: var(--faint); text-align: right; }
.kpis.kpis2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ask { margin: 0; font-size: 14px; color: var(--text); }
.pricebig { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.pricebig b { font: 500 36px/1 var(--mono); color: var(--oil-soft); }
.pricebig span { font-size: 13px; color: var(--muted); }
.pricebig .delta { font: 500 13px var(--mono); padding: 2px 8px; border-radius: 999px; background: var(--panel2); }
.pricebig .delta.hurt { background: #fde3d6; color: var(--harm); }
.pricebig .delta.gain { background: #d9f3ee; color: var(--gain-soft); }
.slidewrap { position: relative; padding-bottom: 32px; }
.slidewrap input { width: 100%; margin: 0; accent-color: var(--oil); min-height: 32px; display: block; }
.marks { position: absolute; left: 8px; right: 8px; top: 30px; height: 30px; }
.marks span { position: absolute; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; font: 11px/1.25 var(--mono); color: var(--faint); white-space: nowrap; }
.marks span::before { content: ""; width: 1px; height: 6px; background: var(--line2); margin-bottom: 2px; }
.marks span.last { transform: translateX(-100%); align-items: flex-end; }
.presets { display: flex; flex-wrap: wrap; gap: 6px; }
.presets button { min-height: 34px; font-size: 13px; padding: 0 12px; border-radius: 999px; background: var(--panel); }
.presets button[aria-pressed="true"] { background: var(--text); border-color: var(--text); color: #fff; }
.explain { margin: 0; padding: 12px 14px; border-radius: 10px; background: var(--panel2); border-left: 3px solid var(--oil); font-size: 14px; line-height: 1.55; color: var(--text); }
.explain b { font-family: var(--mono); font-weight: 600; }
@keyframes bump { 0% { background: #ffe0c2; } 100% { background: var(--panel2); } }
.kpis div.bump { animation: bump .7s ease-out; }
@media (prefers-reduced-motion: reduce) { .kpis div.bump { animation: none; } }
"""
sub('</style>\n<div class="app">', CSS + '</style>\n<div class="app">')

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
