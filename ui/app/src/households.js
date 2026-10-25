// The Households page (OXH-8): Seb's household cost-of-living data, from window.HOUSEHOLDS (households.py).
//  - Real pay against 2019 by region, essentials against pay, and UK household costs by group: real series,
//    each with its source, code and fetch date from notes/household-panel.csv.
//  - Real pay under each lost-flow scenario (notes/household-scenarios.csv) and each UK group's costs under a
//    closure (notes/household-group-scenarios.csv): model output, labelled so, and following the lost-flow slider.
// The page is a third view beside World and Strait; the slider's "The shock" card gets a short households step.
window.HZHouseholds = (() => {
  const $ = (id) => document.getElementById(id);
  const D = window.HOUSEHOLDS, d3 = window.d3, FLAGS = (window.FLAGS && window.FLAGS.flags) || {};
  const seg = document.querySelector(".modeseg"), straitStage = $("strait-stage");
  if (!D || !d3 || !seg || !straitStage) return {};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const mon = (m) => `${MON[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
  const sgn = (v, d = 1) => { const s = Math.abs(v).toFixed(d); return `${+s === 0 ? "" : v > 0 ? "+" : "−"}${s}`; };

  // regions: the EU flag (EUU, flags.py) stands for the euro area
  const REG = {
    us: { name: "United States", short: "US", color: "#8fd0f5", flag: FLAGS.USA },
    uk: { name: "United Kingdom", short: "UK", color: "#ffa424", flag: FLAGS.GBR },
    ea: { name: "Euro area", short: "Euro area", tag: "EA", color: "#b58cff", flag: FLAGS.EUU },
  };
  const flag = (g) => `<img class="flag" src="${REG[g].flag}" alt="" title="${REG[g].name}">`;
  const PARTS = [["fuel", "Motor fuel", "#ffa424"], ["energy", "Home energy", "#ffd166"], ["food", "Food", "#7ee0b0"], ["rest", "Everything else", "#5b6d95"]];

  // provenance: label (SOURCE code, fetched date) for one series of notes/household-panel.csv
  const SRC = { fred: "FRED", ons: "ONS", eurostat: "Eurostat", boe: "Bank of England", hmlr: "HM Land Registry" };
  const cite = (k) => { const m = D.meta[k]; return m ? `${esc(m[0])} (${SRC[m[1]] || esc(m[1])} ${esc(String(m[2]).split("?")[0])}, fetched ${esc(m[3])})` : esc(k); };
  // the panel behind each card's blue info key: short sections, and one line per source with its code and fetch date
  const sec = (h, body) => `<section class="hz-sec"><h4>${h}</h4>${body}</section>`;
  const srcRow = (who, name, meta) => `<li><span class="who">${who}</span><b>${name}</b>${meta ? `<span class="meta">${meta}</span>` : ""}</li>`;
  const srcs = (rows) => `<ul class="hz-srcl">${rows.map(([who, k]) => { const m = D.meta[k];
    return m ? srcRow(who, esc(m[0]), `${SRC[m[1]] || esc(m[1])} · ${esc(String(m[2]).split("?")[0])} · fetched ${esc(m[3])}`) : srcRow(who, esc(k)); }).join("")}</ul>`;
  const MODEL = '<span class="tagm" title="Model output, not observed data">MODEL OUTPUT</span>';
  const REAL = '<span class="tagr" title="Observed data, saved from its source">REAL DATA</span>';

  // ------------------------------------------------------------ scenario state, tied to the lost-flow slider
  const DROPS = [...new Set(D.scen.map((r) => r.drop))].filter((d) => d !== "iea").sort((a, b) => a - b);
  const HAS_IEA = D.scen.some((r) => r.drop === "iea");
  // the 2026 preset (ui/industry/src/patch_iea.py): the chain replayed on 2026 as the IEA counts it. The group
  // scenarios run the 2026 closure at a quarter, half and full size, so its March-October average (67 points)
  // sets their scale on the slider; an older page without the preset kept 2026 at 82 points
  const pathBtn = document.querySelector("[data-path]");
  const AVG26 = pathBtn ? Number(pathBtn.dataset.avg) : 82, PATH_TXT = pathBtn ? pathBtn.dataset.txt : "";
  const onPath = () => !!pathBtn && pathBtn.getAttribute("aria-pressed") === "true";
  const SEV = [["none", 0], ["closure_25", 0.25], ["closure_50", 0.5], ["closure_100", 1]];
  const SEV_NAME = { none: "No closure", closure_25: "A quarter of 2026's closure", closure_50: "Half of 2026's closure", closure_100: "A 2026-sized closure" };
  const sevName = (sev) => (sev === "closure_100" && onPath() ? "The 2026 closure" : SEV_NAME[sev]);
  const lostEl = $("lost");
  const st = { lost: lostEl ? Number(lostEl.value) : 82, h: 12, outlook: false, gtype: "income decile" };
  const near = (arr, v) => arr.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
  const dropFor = (lost) => (onPath() && HAS_IEA ? "iea" : near(DROPS, lost));
  const sevFor = (lost) => (onPath() ? "closure_100" : SEV.reduce((a, b) => (Math.abs(b[1] * AVG26 - lost) < Math.abs(a[1] * AVG26 - lost) ? b : a))[0]);
  function setLost(v) {
    if (!lostEl) { st.lost = v; draw(); return; }
    lostEl.value = String(v);
    lostEl.dispatchEvent(new Event("input", { bubbles: true }));
  }
  const scenRow = (g, drop, h) => D.scen.find((r) => r.region === g && r.drop === drop && r.h === h);
  const gRow = (group, scen, h) => D.gscen.find((r) => r.group === group && r.scen === scen && r.h === h);
  // any amount of flow lost, not just the modelled runs: straight lines between the two runs either side of it
  const lerpRow = (a, b, w) => {
    if (!a || !b) return a || b;
    const o = { ...a };
    for (const k of ["q05", "q50", "q95", "energy", "fuel", "food"]) if (a[k] != null && b[k] != null) o[k] = a[k] + (b[k] - a[k]) * w;
    return o;
  };
  const between = (xs, x) => { const v = Math.max(xs[0], Math.min(xs[xs.length - 1], x)), j = Math.max(1, xs.findIndex((d) => d >= v)), a = xs[j - 1], b = xs[j]; return [a, b, b === a ? 0 : (v - a) / (b - a)]; };
  function scenAt(g, lost, h) {
    if (onPath() && HAS_IEA) return scenRow(g, "iea", h);
    const [a, b, w] = between(DROPS, lost);
    return lerpRow(scenRow(g, a, h), scenRow(g, b, h), w);
  }
  // the group runs are none, a quarter, a half and a full 2026-sized closure, placed on the slider by 2026's average
  function gAt(group, lost, h) {
    if (onPath()) return gRow(group, "closure_100", h);
    const [a, b, w] = between(SEV.map((s) => s[1]), lost / AVG26), name = (f) => SEV.find((s) => s[1] === f)[0];
    return lerpRow(gRow(group, name(a), h), gRow(group, name(b), h), w);
  }
  const lostTxt = () => (onPath() ? `2026 as the IEA counts it (${esc(PATH_TXT)})` : `${st.lost} points of Hormuz flow lost`);
  const runsTxt = () => { if (onPath() || DROPS.includes(st.lost)) return ""; const [a, b] = between(DROPS, st.lost); return ` Between the model's runs at ${a} and ${b} points, on a straight line.`; };

  // ------------------------------------------------------------ UK household groups
  const NAME = {
    "All Households": "All households", "Decile 1": "Lowest tenth", "Decile 10": "Highest tenth",
    "Non-Retired": "Not retired", "Retired": "Retired", "With Children": "With children", "Without Children": "No children",
    "Private renter": "Private renters", "Social and other renter": "Social renters", "Mortgagor and other owner occupier": "Mortgage holders",
    "Outright owner occupier": "Own outright",
  };
  const ord = (n) => `${n}${n === 2 ? "nd" : n === 3 ? "rd" : "th"} tenth`;
  const gname = (g) => NAME[g] || (g.startsWith("Decile ") ? ord(+g.slice(7)) : g);
  const decile = (g) => (g.startsWith("Decile ") ? +g.slice(7) : 0);
  const GTYPES = [["income decile", "By income"], ["tenure", "By home"], ["other", "Retired, children"]];
  const groupsOf = (t) => {
    const all = D.groups.find((g) => g.type === "all");
    const list = D.groups.filter((g) => (t === "other" ? g.type === "retirement" || g.type === "children" : g.type === t))
      .sort((a, b) => decile(a.group) - decile(b.group));
    return [all, ...list].filter(Boolean);
  };

  // ------------------------------------------------------------ the page
  const btn = document.createElement("button");
  btn.type = "button"; btn.dataset.hmode = "households"; btn.setAttribute("aria-pressed", "false");
  btn.textContent = "Households";
  btn.title = "Households: pay and bills";
  seg.append(btn);
  const page = document.createElement("main");
  page.className = "stage hz-hh"; page.id = "hz-households"; page.hidden = true; page.setAttribute("aria-label", "Households: pay and bills");
  // one control, the same setting as the World view's shock card: a slider for any amount of flow lost, and 2026
  const drops = `<input type="range" id="hh-lost" min="0" max="100" step="1" aria-label="Points of Hormuz flow lost"><b class="mono" id="hh-lost-v"></b>`
    + (HAS_IEA && pathBtn ? `<div class="seg presets"><button type="button" data-hdrop="iea" aria-pressed="false" title="${esc(pathBtn.title)}">2026 closure</button></div>` : "");
  const hs = (k, list) => list.map((h) => `<button type="button" data-${k}="${h}" aria-pressed="false">${h} mo</button>`).join("");
  // each card: a number, a plain question, a REAL DATA or MODEL OUTPUT tag, and an info button with its sources
  const INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.5"/></svg>';
  const head = (n, q, tag, src) => `<div class="hz-ch"><span class="hz-n">${n}</span><h3>${q}</h3>${tag}<button type="button" class="ib hz-i" data-hsrc="${src}" aria-label="About this card: method and sources">${INFO}</button></div>`;
  page.innerHTML = `
    <section class="card hz-head" id="hh-head" aria-live="polite">
      <span class="hz-kick">The short version</span>
      <p class="hz-hl" id="hh-hl"></p>
      <div class="hz-hlnums" id="hh-hlnums"></div>
    </section>
    <section class="card hz-bar" id="hh-bar" aria-label="Closure and months for the short version and cards 2 and 3">
      <div class="ctrl"><span class="bg hz-lostbg"><span class="bl">Flow lost</span>${drops}</span>
        <span class="bg"><span class="bl">Months on</span><div class="seg" role="group" aria-label="Months on">${hs("hh", [3, 6, 12])}</div></span></div>
      <p class="src">The same setting as the World view's shock card. Sets the short version and cards 2 and 3.</p>
    </section>
    <section class="card" id="hh-pay">
      ${head(1, "Where did households start?", REAL, "hh-pay-src")}
      <p class="lede" id="hh-pay-lede"></p>
      <p class="src mono" id="hh-pay-read" aria-live="polite"></p>
      <div class="chartbox" id="hh-pay-chart"></div>
      <div class="keys hz-keys-c" id="hh-pay-keys"></div>
      <p class="src" id="hh-pay-src" hidden></p>
    </section>
    <section class="card" id="hh-scen">
      ${head(2, "What does a closure do to pay?", MODEL, "hh-scen-src")}
      <p class="lede">Change in real pay from Feb 2026, for the amount of Hormuz flow lost picked above.</p>
      <p class="src" id="hh-scen-pick"></p>
      <div class="rows" id="hh-scen-rows"></div>
      <div class="keys"><span><i style="background:var(--muted)"></i>90% range</span><span><i style="background:var(--text);width:4px;height:12px;vertical-align:-1px"></i>Middle forecast</span><span><i style="background:#7ee0b0;width:4px;height:12px;vertical-align:-1px"></i>What happened</span></div>
      <p class="src" id="hh-scen-src" hidden></p>
    </section>
    <section class="card" id="hh-gs">
      ${head(3, "Who is hit hardest?", MODEL, "hh-gs-src")}
      <p class="lede" id="hh-gs-lede"></p>
      <div class="ctrl"><button type="button" class="hz-outlook" data-hout aria-pressed="false" title="The year ahead from Sep 2026">Year ahead</button></div>
      <p class="src" id="hh-gs-pick"></p>
      <div class="keys">${PARTS.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>
      <div class="rows" id="hh-gs-rows"></div>
      <p class="src" id="hh-gs-src" hidden></p>
    </section>
    <section class="card" id="hh-who">
      ${head(4, "Why them? What they spend on", REAL, "hh-who-src")}
      <p class="lede">UK household costs by group, with the share of spending on food, home energy and motor fuel.</p>
      <div class="ctrl"><div class="seg" role="group" aria-label="Which groups">${GTYPES.map(([k, l]) => `<button type="button" data-hgt="${k}" aria-pressed="false">${l}</button>`).join("")}</div></div>
      <div class="keys">${PARTS.slice(0, 3).map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>
      <table id="hh-who-t"></table>
      <p class="src" id="hh-who-src" hidden></p>
    </section>
    <section class="card" id="hh-ess">
      ${head(5, "How does it feel day to day?", REAL, "hh-ess-src")}
      <p class="lede">How much more work each essential takes than in 2019.</p>
      <table id="hh-ess-t"></table>
      <p class="lede" id="hh-petrol"></p>
      <p class="src" id="hh-ess-src" hidden></p>
    </section>
    <p class="src hz-saved">Real data is saved from each source on its fetch date, not live. Model output is marked ${MODEL}.</p>`;
  straitStage.after(page);

  // ------------------------------------------------------------ real pay chart
  function payChart() {
    const box = $("hh-pay-chart"), W = Math.max(280, box.clientWidth || 600), H = W < 480 ? 220 : 260;
    const m = { t: 14, r: W < 480 ? 64 : 92, b: 24, l: 36 };
    const parse = d3.timeParse("%Y-%m");
    const ser = Object.entries(D.real_pay).map(([g, s]) => ({ g, pts: s.map(([t, v]) => ({ t, d: parse(t), v })) }));
    const all = ser.flatMap((s) => s.pts);
    const x = d3.scaleTime().domain(d3.extent(all, (p) => p.d)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([Math.min(90, d3.min(all, (p) => p.v) - 1), Math.max(110, d3.max(all, (p) => p.v) + 1)]).nice().range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("class", "chart").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Real pay, 2019 = 100: " + ser.map((s) => `${REG[s.g].name} ${s.pts[s.pts.length - 1].v.toFixed(1)} in ${mon(s.pts[s.pts.length - 1].t)}`).join("; "));
    svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
    svg.append("g").selectAll("text").data(y.ticks(5)).join("text").attr("x", m.l - 6).attr("y", (v) => y(v) + 4).attr("text-anchor", "end").text((v) => v);
    svg.append("g").selectAll("text").data(x.ticks(W < 480 ? 4 : 7)).join("text").attr("x", x).attr("y", H - 6).attr("text-anchor", "middle").text(d3.timeFormat("%Y"));
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(100)).attr("y2", y(100)).attr("stroke", "var(--text)").attr("stroke-dasharray", "4 3").attr("opacity", 0.6);
    svg.append("text").attr("class", "halo").attr("x", W - m.r - 4).attr("y", y(100) + 15).attr("text-anchor", "end").style("fill", "var(--text)").text("2019 = 100");
    const cx = x(parse("2026-03"));
    svg.append("line").attr("x1", cx).attr("x2", cx).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", "#ff4d3a").attr("stroke-dasharray", "2 3");
    svg.append("text").attr("x", cx - 4).attr("y", m.t + 10).attr("text-anchor", "end").attr("class", "halo").style("fill", "#ff8a6a").text("closure");
    const line = d3.line().x((p) => x(p.d)).y((p) => y(p.v));
    for (const s of ser) {
      svg.append("path").attr("d", line(s.pts)).attr("fill", "none").attr("stroke", REG[s.g].color).attr("stroke-width", 2.2).attr("stroke-linejoin", "round");
    }
    // end labels, nudged apart
    const ends = ser.map((s) => ({ g: s.g, p: s.pts[s.pts.length - 1] })).map((e) => ({ ...e, y: y(e.p.v) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15;
    for (const e of ends) {
      svg.append("circle").attr("cx", x(e.p.d)).attr("cy", y(e.p.v)).attr("r", 3).attr("fill", REG[e.g].color);
      svg.append("text").attr("x", x(e.p.d) + 6).attr("y", e.y + 4).style("fill", REG[e.g].color).text(`${REG[e.g].tag || REG[e.g].short} ${e.p.v.toFixed(1)}`);
    }
    // hover: the values in the nearest month
    const rule = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).attr("stroke", "var(--muted)").attr("opacity", 0);
    const read = $("hh-pay-read"), idle = "Hover the chart for a month.";
    read.textContent = idle;
    svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b).attr("fill", "transparent")
      .on("pointermove", (ev) => {
        const t = x.invert(d3.pointer(ev)[0]);
        const vals = ser.map((s) => { const p = s.pts[Math.min(s.pts.length - 1, d3.bisector((q) => q.d).center(s.pts, t))]; return { g: s.g, p }; });
        const at = vals.find((v) => v.g === "us") || vals[0];
        rule.attr("x1", x(at.p.d)).attr("x2", x(at.p.d)).attr("opacity", 0.7);
        read.textContent = vals.map((v) => `${REG[v.g].short} ${v.p.v.toFixed(1)} (${mon(v.p.t)})`).join(" · ");
      })
      .on("pointerleave", () => { rule.attr("opacity", 0); read.textContent = idle; });
    box.replaceChildren(svg.node());
  }

  // ------------------------------------------------------------ static cards
  function payText() {
    const last = (g) => D.real_pay[g][D.real_pay[g].length - 1];
    const low = (g) => D.real_pay[g].filter(([t]) => t >= "2021-01" && t <= "2024-12").reduce((a, b) => (b[1] < a[1] ? b : a));
    $("hh-pay-lede").innerHTML = `Pay after prices, 2019 = 100. The euro area is ${last("ea")[1] < 100 ? "<b>still below 2019</b>" : "back above 2019"}: ${last("ea")[1].toFixed(1)} in ${mon(last("ea")[0])}, after a low of ${low("ea")[1].toFixed(1)} in ${mon(low("ea")[0])}.`;
    $("hh-pay-keys").innerHTML = Object.keys(D.real_pay).map((g) => `<span>${flag(g)} <i style="background:${REG[g].color}"></i>${REG[g].name}</span>`).join("");
    $("hh-pay-src").innerHTML = sec("How it's worked out", "<p>Real pay is pay divided by consumer prices, indexed so 2019 = 100.</p><p>Euro-area pay is quarterly and starts in 2009.</p>")
      + sec("Sources", srcs(Object.keys(D.real_pay).flatMap((g) => [[`${REG[g].short} pay`, `${g}_pay`], [`${REG[g].short} prices`, `${g}_cpi`]])));
  }
  // rows of the essentials table: (label, item per region); the UK has no CPI rent index, so its row is housing
  const ESS = [["Food", { us: "food", uk: "food", ea: "food" }], ["Home energy", { us: "energy_home", uk: "energy_home", ea: "energy_home" }],
    ["Motor fuel", { us: "motor_fuel", uk: "motor_fuel", ea: "motor_fuel" }], ["Rent", { us: "rent", uk: "housing", ea: "rent" }]];
  function essText() {
    const regs = Object.keys(D.essentials);
    const cell = (g, item) => {
      const r = D.essentials[g].find((x) => x.item === item);
      if (!r) return "<td><small>–</small></td>";
      const v = r.value - 100, cls = v > 5 ? "hot" : v < -5 ? "ok" : "";
      return `<td title="${esc(`${REG[g].name}, ${cite(`${g}_${item}`).replace(/<[^>]+>/g, "")}: ${r.value} in ${mon(r.month)} (2019 = 100); peak ${r.peak} in ${mon(r.peak_month)}`)}"><span class="${cls}">${sgn(v, 0)}%</span>${item === "housing" ? "<sup>*</sup>" : ""}<br><small>peak ${sgn(r.peak - 100, 0)}%</small></td>`;
    };
    $("hh-ess-t").innerHTML = `<thead><tr><th>Item</th>${regs.map((g) => `<th><span class="hz-th">${flag(g)}${REG[g].short}</span></th>`).join("")}</tr></thead>
      <tbody>${ESS.map(([l, by]) => `<tr><td>${l}</td>${regs.map((g) => cell(g, by[g])).join("")}</tr>`).join("")}</tbody>`;
    const months = [...new Set(regs.map((g) => D.essentials[g][0] && D.essentials[g][0].month))].filter(Boolean);
    const P = D.petrol;
    $("hh-petrol").innerHTML = `${flag("us")} A gallon of US petrol took <b>${P.y2019}</b> minutes of work in 2019, <b>${P.peak}</b> at the peak (${mon(P.peak_month)}) and <b>${P.now}</b> in ${mon(P.month)}.`;
    $("hh-ess-src").innerHTML = sec("How it's worked out", `<p>Each item's price index divided by pay, with 2019 = 100: how much more work the item takes than in 2019. Petrol minutes are the US petrol price divided by hourly pay.</p>`
      + `<p>Latest month: ${months.map(mon).join(", ")}. <sup>*</sup>The UK rent row is housing, water and fuels: there is no CPI rent index here.</p>`)
      + sec("Sources", srcs([...regs.flatMap((g) => [...ESS.map(([l, by]) => [`${REG[g].short} ${l.toLowerCase()}`, `${g}_${by[g]}`]), [`${REG[g].short} pay`, `${g}_pay`]]), ["US petrol", "us_p_petrol"]]));
  }
  function whoTable() {
    const rows = groupsOf(st.gtype), maxShare = 25, all = rows.find((g) => g.type === "all");
    // each group against all households, so the real differences stand out
    const vsAll = (g, k) => (g.type === "all" || !all || g[k] == null || all[k] == null ? "" : ` <small class="${g[k] - all[k] > 0.05 ? "hurt" : g[k] - all[k] < -0.05 ? "gain" : ""}">${sgn(g[k] - all[k])} vs all</small>`);
    const bar = (s) => `<span class="mini" aria-hidden="true">${PARTS.slice(0, 3).map(([k, , c]) => `<i style="width:${(100 * (s[k] || 0) / maxShare).toFixed(1)}%;background:${c}"></i>`).join("")}</span>`;
    $("hh-who-t").innerHTML = `<thead><tr><th>Group</th><th>Fuel · energy · food</th><th title="All items, Dec 2019 to the latest month">Since 2019</th><th title="Official 12-month rate">Last 12 mo</th></tr></thead>
      <tbody>${rows.map((g) => { const s = g.shares || {};
        return `<tr${g.type === "all" ? ' class="all"' : ""}><td>${esc(gname(g.group))}</td><td title="${esc(`Of spending (${D.weights_year} weights): food ${s.food}%, home energy ${s.energy}%, motor fuel ${s.fuel}%`)}">${bar(s)} <small>${((s.food || 0) + (s.energy || 0) + (s.fuel || 0)).toFixed(0)}%</small></td>
          <td>${g.since2019 != null ? `+${g.since2019.toFixed(1)}%${vsAll(g, "since2019")}` : "–"}</td><td>${g.rate != null ? `${g.rate.toFixed(1)}%${vsAll(g, "rate")}` : "–"}</td></tr>`; }).join("")}</tbody>`;
    const m = D.groups[0] && D.groups[0].month;
    $("hh-who-src").innerHTML = sec("What it shows", `<p>Household Costs Indices, all items, to ${m ? mon(m) : "the latest month"}. Spending shares are the ${D.weights_year} weights.</p><p>Official statistics in development.</p>`)
      + sec("Source", `<ul class="hz-srcl">${srcRow("UK groups", esc(D.groups_source), `fetched ${esc(D.groups_fetched || "–")}`)}</ul>`);
  }

  // ------------------------------------------------------------ the two model cards
  // a range bar on a shared axis lo..hi: the 90% band, the middle forecast and, if known, what happened
  function track(lo, hi) {
    const pos = (v) => `${(100 * (v - lo) / (hi - lo)).toFixed(2)}%`;
    return (r, color) => `<div class="track">${lo < 0 && hi > 0 ? `<span class="zero" style="left:${pos(0)}"></span>` : ""}
      <span class="band" style="left:${pos(r.q05)};width:${(100 * (r.q95 - r.q05) / (hi - lo)).toFixed(2)}%;background:${color}"></span>
      <span class="mid" style="left:${pos(r.q50)};background:var(--text)"></span>
      ${r.actual != null ? `<span class="mid act" style="left:${pos(r.actual)};background:#7ee0b0" title="What happened: ${sgn(r.actual)}%"></span>` : ""}</div>`;
  }
  function scenCard() {
    const drop = onPath() && HAS_IEA ? "iea" : st.lost, regs = Object.keys(REG);
    page.querySelectorAll("[data-hdrop]").forEach((b) => b.setAttribute("aria-pressed", String(onPath())));
    page.querySelectorAll("[data-hh]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.hh === st.h)));
    if ($("hh-lost")) { $("hh-lost").value = String(st.lost); $("hh-lost-v").textContent = onPath() ? "2026" : `${st.lost} pts`; }
    $("hh-scen-pick").innerHTML = `${lostTxt()}, ${st.h} months on.${runsTxt()}`;
    const rows = regs.map((g) => ({ g, r: scenAt(g, st.lost, st.h), base: scenRow(g, 0, st.h) })).filter((x) => x.r);
    const vals = D.scen.filter((r) => r.h === st.h).flatMap((r) => [r.q05, r.q95, r.actual]).filter((v) => v != null);
    const lo = Math.min(-1, Math.floor(Math.min(...vals))), hi = Math.max(1, Math.ceil(Math.max(...vals)));
    const t = track(lo, hi);
    $("hh-scen-rows").innerHTML = rows.map(({ g, r, base }) => `<div class="rrow"><span class="nm">${flag(g)}${REG[g].short}</span>${t(r, REG[g].color)}
      <span class="v" title="${esc(`Middle ${sgn(r.q50, 2)}%, 90% range ${sgn(r.q05)} to ${sgn(r.q95)}%${base && drop ? `; with no flow lost ${sgn(base.q50)}%` : ""}${r.actual != null ? `; what happened ${sgn(r.actual)}%` : ""}`)}">${sgn(r.q50)}%<br><small>${sgn(r.q05)} to ${sgn(r.q95)}</small></span></div>`).join("")
      + `<div class="rrow axis"><span></span><span class="ax"><span>${sgn(lo, 0)}%</span><span>${sgn(hi, 0)}%</span></span><span></span></div>`;
    const acts = rows.filter((x) => x.r.actual != null);
    $("hh-scen-src").innerHTML = sec("How the model works", "<p>The team's household model. Consumer prices follow the knock-on chain's paths for each scenario.</p><p>Nominal pay keeps its pace of the 12 months before Feb 2026, so the range is the price range.</p>")
      + sec("What happened", `<p>${acts.length ? `The green marks (${acts.map((x) => REG[x.g].short).join(", ")}) use the same pay and price series as card 1.` : `Nothing to compare with yet at ${st.h} months.`}</p>`);
  }
  // how far apart the groups are, against the model's own range: a "hardest hit" group only when the gap is real
  function groupSpread(rows) {
    const all = rows.find((x) => x.g.type === "all"), rest = rows.filter((x) => x.g.type !== "all").sort((a, b) => b.total - a.total);
    if (!all || rest.length < 2) return null;
    const gap = rest[0].total - rest[rest.length - 1].total, band = (all.r.q95 - all.r.q05) / 2;
    return { all, top: rest[0], low: rest[rest.length - 1], gap, band, clear: gap > 0.25 * band };
  }
  function gsCard() {
    const scen = st.outlook ? "outlook" : null, h = st.h, none = !st.outlook && !onPath() && st.lost <= 0;
    page.querySelector("[data-hout]").setAttribute("aria-pressed", String(st.outlook));
    $("hh-gs-lede").innerHTML = st.outlook ? "Each group's costs over the year ahead from Sep 2026, split by what drives them."
      : "What the closure adds to each group's costs, on top of no closure, split by what drives it. Largest first.";
    $("hh-gs-pick").innerHTML = st.outlook ? `The year ahead from Sep 2026, ${h} months on. Change in costs, %.`
      : `${onPath() ? "The 2026 closure as it happened" : lostTxt()}, from Feb 2026, ${h} months on.${!onPath() && st.lost > AVG26 ? ` Above ${AVG26} points this uses the model's largest run, a 2026-sized closure.` : ""}`;
    const rows = groupsOf(st.gtype).map((g) => {
      const r = scen ? gRow(g.group, scen, h) : gAt(g.group, st.lost, h), base = gRow(g.group, "none", h);
      if (!r) return null;
      const part = (k) => (k === "rest" ? r.q50 - r.energy - r.fuel - r.food : r[k]) - (st.outlook || !base ? 0 : k === "rest" ? base.q50 - base.energy - base.fuel - base.food : base[k]);
      return { g, r, base, parts: PARTS.map(([k, l, c]) => ({ k, l, c, v: part(k) })), total: st.outlook || !base ? r.q50 : r.q50 - base.q50 };
    }).filter(Boolean).sort((a, b) => (a.g.type === "all" ? -1 : b.g.type === "all" ? 1 : b.total - a.total));
    const maxv = Math.max(0.1, ...rows.map((x) => x.parts.reduce((a, p) => a + Math.max(0, p.v), 0)));
    const allTot = (rows.find((x) => x.g.type === "all") || {}).total, sp = st.outlook || none ? null : groupSpread(rows);
    const note = !sp ? "" : sp.clear
      ? `<p class="src">Hit hardest: <b>${esc(phrase(sp.top.g.group))}</b>, <b>${sgn(sp.top.total - sp.all.total, 2)} pts</b> more added to costs than all households, and ${sgn(sp.top.total - sp.low.total, 2)} more than ${esc(phrase(sp.low.g.group))}.</p>`
      : `<p class="src">These groups differ by at most <b>${sp.gap.toFixed(2)} pts</b>, small next to the model's own range (±${sp.band.toFixed(1)} pts for all households): the closure hits them about equally. What differs is what they spend it on (card 4).</p>`;
    $("hh-gs-rows").innerHTML = note + (st.outlook || !none ? rows.map(({ g, r, base, parts, total }) => {
      let left = 0;
      const segs = parts.filter((p) => p.v > 0).map((p) => { const w = 100 * p.v / maxv, s = `<span class="seg2" style="left:${left.toFixed(2)}%;width:${w.toFixed(2)}%;background:${p.c}" title="${esc(`${p.l}: ${sgn(p.v, 2)} pts`)}"></span>`; left += w; return s; }).join("");
      const tip = st.outlook ? `Costs ${sgn(r.q50, 2)}% (range up to ${sgn(r.q05)} to ${sgn(r.q95)}%)` : `Costs ${sgn(r.q50, 2)}% against ${sgn(base.q50, 2)}% with no closure`;
      return `<div class="rrow${g.type === "all" ? " all" : ""}"><span class="nm">${esc(gname(g.group))}</span><div class="track">${segs}</div>
        <span class="v" title="${esc(`${tip}. ${parts.map((p) => `${p.l} ${sgn(p.v, 2)}`).join(", ")} pts`)}">${sgn(total, 2)}${st.outlook ? "%" : " pts"} <small>${st.outlook ? `${sgn(r.q05)} to ${sgn(r.q95)}` : g.type === "all" ? "the average" : `${sgn(total - allTot, 2)} vs all`}</small></span></div>`;
    }).join("") : `<p class="src">No closure, so nothing added. Pick an amount of flow lost above.</p>`);
    $("hh-gs-src").innerHTML = sec("How the model works", `<p>The team's household model. Item price ranges from the basket-item model, weighted by each group's ${D.weights_year} spending shares. Mortgage interest is held flat.</p><p>First-order sums, so the range is an upper bound on its width.</p>`)
      + sec("Inputs", `<ul class="hz-srcl">${srcRow("Prices", "Basket-item model", `run ${esc(D.fans_generated || "–")}`)}${srcRow("Shares", esc(D.groups_source), `${D.weights_year} weights`)}</ul>`);
  }

  // ------------------------------------------------------------ the shock card's households step (World view)
  const explain = $("shock-explain"), step3 = explain && explain.closest(".step");
  let mini = null;
  if (step3) {
    mini = document.createElement("div");
    mini.className = "step hz-hhstep";
    mini.innerHTML = `<div class="stephead"><span class="num">4</span> What it does to households ${MODEL}</div>
      <div class="hz-hhmini" id="hh-mini"></div><p class="sub" id="hh-mini-g"></p>
      <p class="faint" id="hh-mini-src"></p><button type="button" class="hz-hhgo" data-hgo>Households page →</button>`;
    step3.after(mini);
  }
  function miniStep() {
    if (!mini) return;
    const any = onPath() || st.lost > 0;
    $("hh-mini").innerHTML = `<span class="hz-mh">Real pay 12 months on from Feb 2026${onPath() ? " (2026 as the IEA counts it)" : ""}</span>` + Object.keys(REG).map((g) => {
      const r = scenAt(g, st.lost, 12), b = scenRow(g, 0, 12);
      return r ? `<span class="hz-mr">${flag(g)}<b>${REG[g].short}</b><span class="mono">${sgn(r.q50)}%</span><small>${any ? `no loss ${sgn(b.q50)}%` : `${sgn(r.q05)} to ${sgn(r.q95)}`}</small></span>` : "";
    }).join("");
    const lo = gAt("Decile 1", st.lost, 12), hi = gAt("Decile 10", st.lost, 12), lo0 = gRow("Decile 1", "none", 12), hi0 = gRow("Decile 10", "none", 12);
    $("hh-mini-g").innerHTML = !any || !lo || !hi ? `${flag("uk")} No closure in the UK household model at this setting.`
      : `${flag("uk")} ${onPath() ? "The 2026 closure" : `${st.lost} points of flow lost`} adds <b>${sgn(lo.q50 - lo0.q50, 2)}</b> pts to the lowest-income tenth's costs over 12 months, <b>${sgn(hi.q50 - hi0.q50, 2)}</b> to the highest's.`;
    $("hh-mini-src").innerHTML = `Model output: the team's household model${onPath() || DROPS.includes(st.lost) ? "" : ", on a straight line between its runs"}.`;
  }

  // ------------------------------------------------------------ show / hide, and drawing
  const KEY = "hz-page";
  function show(on, quiet) {
    page.hidden = !on;
    btn.setAttribute("aria-pressed", String(on));
    const sc = $("scenario");
    if (on) {
      $("world-stage").hidden = true; straitStage.hidden = true;
      $("view-seg").hidden = true; $("hsearch").hidden = true; if (sc) sc.hidden = true;
      document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      draw(); payChart();
      if (!quiet) window.scrollTo({ top: 0 });
    } else if (sc) sc.hidden = false;
    try { localStorage.setItem(KEY, on ? "households" : ""); } catch (e) {}
  }
  // a group's name as it reads inside a sentence ("the 8th income tenth", "outright owners")
  const PHRASE = { "All Households": "all households", "Decile 1": "the lowest-income tenth", "Decile 10": "the highest-income tenth",
    "Non-Retired": "non-retired households", "Retired": "retired households", "With Children": "households with children",
    "Without Children": "households without children", "Private renter": "private renters", "Social and other renter": "social renters",
    "Mortgagor and other owner occupier": "mortgage holders", "Outright owner occupier": "outright owners" };
  const phrase = (g) => PHRASE[g] || (g.startsWith("Decile ") ? `the ${ord(+g.slice(7)).replace(" tenth", "")} income tenth` : g);
  function headline() {
    const h = st.h, when = h === 12 ? "after a year" : `after ${h} months`;
    const diff = (g) => { const r = scenAt(g, st.lost, h), b = scenRow(g, 0, h); return r && b ? r.q50 - b.q50 : null; };
    const what = onPath() ? "The 2026 closure, as the IEA counts it," : `Losing ${st.lost} of every 100 barrels of Hormuz flow`;
    const us = diff("us"), uk = diff("uk"), ea = diff("ea");
    const word = (v) => (v < 0 ? "cuts" : "raises");
    if (!onPath() && st.lost <= 0) {
      $("hh-hl").innerHTML = "With Hormuz flowing normally, the model adds nothing: real pay follows its usual path. Move the flow-lost slider below.";
      $("hh-hlnums").innerHTML = "";
      return;
    }
    // every UK group (income, home, retired, children), what the closure adds to its costs
    const rows = D.groups.map((g) => { const r = gAt(g.group, st.lost, h), b = gRow(g.group, "none", h); return r && b ? { g, r, total: r.q50 - b.q50 } : null; }).filter(Boolean);
    const sp = groupSpread(rows);
    $("hh-hl").innerHTML = `${what} ${word(us)} real pay by about <b>${Math.abs(us).toFixed(1)} points</b> in the US and <b>${Math.abs(uk).toFixed(1)}</b> in the UK ${when}, compared with no closure.` +
      (!sp ? "" : sp.clear ? ` In the UK, the hardest hit are <b>${esc(phrase(sp.top.g.group))}</b>; the least, <b>${esc(phrase(sp.low.g.group))}</b>.`
        : ` In the UK it hits every household group about equally: they differ by at most ${sp.gap.toFixed(2)} pts.`);
    const tile = (lab, v, unit, sub, cls) => `<div class="hz-t ${cls || ""}"><b>${sgn(v)}${unit}</b><span>${lab}</span><small>${sub}</small></div>`;
    $("hh-hlnums").innerHTML =
      tile(`${flag("us")} US real pay`, us, " pts", `vs no closure, ${h} months`, us < 0 ? "hurt" : "") +
      tile(`${flag("uk")} UK real pay`, uk, " pts", `vs no closure, ${h} months`, uk < 0 ? "hurt" : "") +
      tile(`${flag("ea")} Euro-area real pay`, ea, " pts", `vs no closure, ${h} months`, ea < 0 ? "hurt" : "") +
      (!sp ? "" : sp.clear ? tile(`${flag("uk")} Hardest hit: ${esc(phrase(sp.top.g.group))}`, sp.top.total, " pts", `added to costs, ${h} months`, "hurt")
        : tile(`${flag("uk")} UK costs, every group`, sp.all.total, " pts", `added in ${h} months; groups within ${sp.gap.toFixed(2)}`, "hurt"));
  }
  function draw() { headline(); scenCard(); gsCard(); miniStep(); }
  btn.addEventListener("click", () => { if (page.hidden) show(true); });
  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { if (!page.hidden) show(false); }));
  document.addEventListener("click", (e) => { if (e.target.closest("[data-hgo]")) show(true); });
  page.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const d = b.dataset;
    if (d.hsrc != null) {
      const card = b.closest(".card"), q = card.querySelector("h3").textContent;
      const tag = card.querySelector(".tagr, .tagm");
      $("sheet-title").textContent = q;
      $("sheet-body").innerHTML = `${tag ? `<div class="hz-tagline">${tag.outerHTML}</div>` : ""}${$(d.hsrc).innerHTML}`;
      $("sheet").hidden = false; $("sheet-close").focus();
      return;
    }
    if (d.hdrop != null) st.outlook = false;
    if (d.hdrop === "iea") { pathBtn.click(); return; }
    else if (d.hdrop != null) setLost(+d.hdrop);
    else if (d.hh != null) st.h = +d.hh;
    else if (d.hout != null) st.outlook = !st.outlook;
    else if (d.hgt != null) { st.gtype = d.hgt; page.querySelectorAll("[data-hgt]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); whoTable(); }
    else return;
    draw();
  });
  if (lostEl) lostEl.addEventListener("input", () => { st.lost = Number(lostEl.value); draw(); });
  // this page's slider drives the shared one, so the World view and this page always show the same setting
  if ($("hh-lost")) $("hh-lost").addEventListener("input", (e) => { st.outlook = false; setLost(Number(e.target.value)); });
  document.querySelectorAll("[data-lost], [data-path], [data-rel]").forEach((b) => b.addEventListener("click", () => setTimeout(() => { st.lost = Number(lostEl.value); draw(); }, 0)));
  new ResizeObserver(() => { if (!page.hidden) payChart(); }).observe(page);

  payText(); essText();
  page.querySelector('[data-hgt="income decile"]').setAttribute("aria-pressed", "true"); whoTable();
  draw();
  let saved = "";
  try { saved = localStorage.getItem(KEY) || ""; } catch (e) {}
  if (location.hash === "#households" || (saved === "households" && location.hash !== "#mandeb")) show(true, true);
  return { show, draw };
})();
