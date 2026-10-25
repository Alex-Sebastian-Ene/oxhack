// The Models page: what each of Seb's statistical and ML models answers, its headline numbers (each with the note it
// was read from and the date that note was generated), how it was tested and what it can't do, from window.MODELS
// (models.py). A fourth view beside World, Strait and Households.
window.HZModels = (() => {
  const $ = (id) => document.getElementById(id);
  const D = window.MODELS, seg = document.querySelector(".modeseg"), straitStage = $("strait-stage");
  if (!D || !seg || !straitStage) return {};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const src = (path, date) => `<span class="mf">${esc(path)}${date ? ` · ${esc(date)}` : ""}</span>`;

  // ------------------------------------------------------------ the parts of a card
  // a headline number: the value, what it measures, its context, and the note it came from
  function stat(s) {
    const [v, pm] = s.v.split(" ± ");
    return `<div class="st"><b class="v">${esc(v)}${pm ? `<small> ± ${esc(pm)}</small>` : ""}</b>
      <span class="l">${esc(s.label)}</span>${s.note ? `<span class="n">${esc(s.note)}</span>` : ""}${src(s.src, s.date)}</div>`;
  }
  // the knock-on links and how they held up across folds
  function links(t) {
    const tone = (v) => (/^holds/i.test(v) ? "ok" : /^fails/i.test(v) ? "bad" : "mid");
    return `<table class="lt"><thead><tr>${t.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${t.rows.map((r) =>
      `<tr><td>${esc(r[0])}</td><td><span class="mono">${esc(r[1])}</span><small>${esc(r[2])}</small></td><td class="mono">${esc(r[3].replace(" of ", " of "))}</td>
       <td class="vd ${tone(r[4])}">${esc(r[4])}</td></tr>`).join("")}</tbody></table>${src(t.src, t.date)}`;
  }
  // skill against the institutions: one bar each from zero, ours in amber and labelled, the benchmarks in blue
  function bars(b) {
    const rows = [...b.bars].sort((x, y) => y.v - x.v);
    const lo = Math.min(0, ...rows.map((r) => r.v)) * 1.08, hi = Math.max(0, ...rows.map((r) => r.v)) * 1.08;
    const x = (v) => (100 * (v - lo)) / (hi - lo);
    const fmt = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(3)}`;
    return `<figure class="mb" aria-label="${esc(b.title)}">
      <figcaption>${esc(b.title)}</figcaption>
      <div class="keys"><span><i class="ours"></i>Our models</span><span><i></i>Surveys, the Fed's model and a naive rule</span></div>
      <div class="bars" role="table">${rows.map((r) => `<div class="br${r.ours ? " ours" : ""}" role="row" tabindex="0" title="${esc(r.name)}: skill ${fmt(r.v)}">
        <span class="nm" role="cell">${esc(r.name)}${r.ours ? ' <em>ours</em>' : ""}</span>
        <span class="tr" role="cell"><span class="z" style="left:${x(0).toFixed(2)}%"></span>
          <span class="bar" style="left:${x(Math.min(0, r.v)).toFixed(2)}%;width:${(x(Math.abs(r.v)) - x(0)).toFixed(2)}%"></span></span>
        <span class="val mono" role="cell">${fmt(r.v)}</span></div>`).join("")}</div>
      <p class="ax">0 = climatology, the series' own history; higher is better.</p>${src(b.src, b.date)}</figure>`;
  }
  // ------------------------------------------------------------ our models against the experts, by region
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = (ym) => `${MON[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`;
  const val = (s) => parseFloat(String(s).replace("−", "-"));
  const pc = (v) => `${v < 0 ? "−" : "+"}${Math.abs(v).toFixed(1)}%`;
  const WHO = [["stats", "Our stats model", "Bayesian pass-through"], ["ml", "Our ML model", "Global network"],
    ["expert", "Experts", "best in the row"], ["naive", "Naive rule", "last 12 months' pace carries on"]];
  const mark = (k) => `<i class="mk ${k}" aria-hidden="true"></i>`;
  function experts(E) {
    // how accurate: skill per region, a thin bar from zero under each number, the best in each row marked
    const all = E.rows.flatMap((r) => [r.stats, r.ml, r.naive, r.expert && r.expert.v].filter(Boolean).map(val));
    const lo = Math.min(0, ...all), hi = Math.max(0, ...all), x = (v) => (100 * (v - lo)) / (hi - lo);
    const sk = (k, s, top, extra = "") => {
      const v = val(s);
      return `<td class="sk ${k}${top ? " top" : ""}"${extra}><b class="mono">${esc(s)}</b>
        <span class="mt"><span class="z" style="left:${x(0).toFixed(1)}%"></span><span class="b" style="left:${x(Math.min(0, v)).toFixed(1)}%;width:${(x(Math.max(0, v)) - x(Math.min(0, v))).toFixed(1)}%"></span></span>${top ? '<span class="best">best</span>' : ""}</td>`;
    };
    const rows = E.rows.map((r) => {
      const vs = { stats: val(r.stats), ml: val(r.ml), naive: val(r.naive), ...(r.expert ? { expert: val(r.expert.v) } : {}) };
      const top = Object.keys(vs).reduce((a, b) => (vs[b] > vs[a] ? b : a));
      const ex = r.expert
        ? sk("expert", r.expert.v, top === "expert", ` title="${esc([r.expert.name, ...r.expert.others.map((o) => `${o[0]} ${o[1]}`)].join(" · "))}"`)
          .replace("</b>", `</b><small>${esc(r.expert.name.replace(/.*\((\w+)\)$/, "$1").replace(" model", ""))}</small>`)
        : `<td class="sk none"><span>none collected</span></td>`;
      return `<tr><th scope="row">${esc(r.region)}${r.region === "All three" ? "<small>US, UK, euro area</small>" : ""}</th>
        ${sk("stats", r.stats, top === "stats")}${sk("ml", r.ml, top === "ml")}${ex}${sk("naive", r.naive, top === "naive")}</tr>`;
    }).join("");
    const us = E.rows.find((r) => r.expert);
    const sig = (t) => Math.abs(val(t)) >= 2;
    const read = us ? `${esc(us.region)}: ${val(us.expert.v) > Math.max(val(us.stats), val(us.ml)) ? `the ${esc(us.expert.name.toLowerCase().replace(/ \(.*/, ""))} lead` : "our models lead"};
      the gap is ${sig(us.expert.t.stats) || sig(us.expert.t.ml) ? "" : "not "}significant (t ${esc(us.expert.t.stats)} for the stats model, ${esc(us.expert.t.ml)} for ML).` : "";
    const none = E.rows.filter((r) => !r.expert && r.region !== "All three").map((r) => `the ${r.region.replace(/^Euro/, "euro")}`);

    // what each expected: one lane per forecaster on a shared % axis, the outcome as a line through the lanes
    const pts = E.pred.flatMap((p) => [p.actual, p.stats, p.ml, p.expert, p.naive, ...p.stats_band, ...p.ml_band]).filter((v) => v != null);
    const a = Math.floor(Math.min(...pts)), b = Math.ceil(Math.max(...pts)), px = (v) => (100 * (v - a)) / (b - a);
    const lane = (p, k, name) => {
      const v = p[k], band = p[`${k}_band`];
      if (v == null) return `<div class="ln ${k} gap"><span class="nm">${mark(k)}${esc(name)}</span><span class="tr"><span class="act" style="left:${px(p.actual).toFixed(1)}%"></span><em>no forecast collected</em></span><span class="vl"></span></div>`;
      const say = `${name}: ${pc(v)}${band ? ` (90% range ${pc(band[0])} to ${pc(band[1])})` : ""}`;
      return `<div class="ln ${k}" role="listitem" aria-label="${esc(say)}" title="${esc(say)}"><span class="nm">${mark(k)}${esc(name)}</span>
        <span class="tr"><span class="act" style="left:${px(p.actual).toFixed(1)}%"></span>${band ? `<span class="bd" style="left:${px(band[0]).toFixed(1)}%;width:${(px(band[1]) - px(band[0])).toFixed(1)}%"></span>` : ""}
        <span class="dot" style="left:${px(v).toFixed(1)}%"></span></span><span class="vl mono">${pc(v)}</span></div>`;
    };
    const ticks = Array.from({ length: b - a + 1 }, (_, i) => a + i);
    const strips = E.pred.map((p) => `<div class="rg" role="list" aria-label="${esc(p.region)}: actual ${pc(p.actual)}">
      <div class="rh"><b>${esc(p.region)}</b><span>actual <b class="mono">${pc(p.actual)}</b></span></div>
      ${lane(p, "stats", "Stats")}${lane(p, "ml", "ML")}${lane(p, "expert", us && p.region === us.region ? us.expert.name.replace(/.*\((\w+)\)$/, "$1") : "Experts")}${lane(p, "naive", "Naive")}</div>`).join("");

    return `<section class="card hz-mx" id="mod-experts" aria-label="Our models against the experts">
      <div class="xh"><h2>Against the experts</h2><span class="kind">Forecasting oil too · 12 months ahead</span></div>
      <p class="asks">Inflation over the next 12 months: our statistical and ML models against professional forecasters and a naive rule.
        Every forecast uses only what was known on the day it was made. Backtest ${esc(month(E.span.split("–")[0]))} to ${esc(month(E.span.split("–")[1]))}.</p>
      <p class="keys">${WHO.map(([k, n, d]) => `<span>${mark(k)}<b>${esc(n)}</b> ${esc(d)}</span>`).join("")}</p>
      <div class="xg">
        <figure class="xa"><figcaption>How accurate <small>skill: 0 = the series' own history, higher is better; shaded: best in the row</small></figcaption>
          <table><thead><tr><th scope="col">Region</th>${WHO.map(([k, n]) => `<th scope="col" class="${k}">${mark(k)}${esc(n.replace("Our ", ""))}</th>`).join("")}</tr></thead>
          <tbody>${rows}</tbody></table>
          <p class="rd">${read} ${none.length ? `For ${esc(none.join(" and "))} no expert forecasts have been collected yet, so the naive rule is the only benchmark.` : ""}</p>
        </figure>
        <figure class="xp"><figcaption>What each expected <small>% change in consumer prices, ${esc(month(E.origin))} to ${esc(month(E.end))}; bars are 90% ranges</small></figcaption>
          ${strips}
          <div class="ax" aria-hidden="true"><span class="nm"></span><span class="tr">${ticks.map((t) => `<span style="left:${px(t).toFixed(1)}%">${t}%</span>`).join("")}</span><span class="vl"></span></div>
        </figure>
      </div>
      ${src(E.src, E.date)}
    </section>`;
  }
  function card(c) {
    return `<article class="card hz-mc${c.wide ? " wide" : ""}" id="mod-${esc(c.id)}">
      <div class="mh"><h3>${esc(c.title)}</h3><span class="kind">${esc(c.kind)}</span></div>
      <p class="asks">${md(c.asks)}</p>
      <div class="stats">${c.stats.map(stat).join("")}</div>
      ${c.table ? links(c.table) : ""}${c.bars ? bars(c.bars) : ""}
      <div class="row"><span class="tl">Tested</span><p>${md(c.tested)}</p></div>
      <div class="row lim"><span class="tl">Can't</span><ul>${c.limits.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>
      <p class="files">Notes: ${c.files.map((f) => src(f.path, f.date)).join(" ")}</p>
    </article>`;
  }

  // ------------------------------------------------------------ the page
  const btn = document.createElement("button");
  btn.type = "button"; btn.dataset.hmode = "models"; btn.setAttribute("aria-pressed", "false");
  btn.textContent = "Models";
  btn.title = "Models: what each one does, how it was tested and what it can't do";
  seg.append(btn);
  const page = document.createElement("main");
  page.className = "stage hz-mod"; page.id = "hz-models"; page.hidden = true; page.setAttribute("aria-label", "Models: how the numbers are made");
  const groups = D.groups.map(([g, title]) => [g, title, D.cards.filter((c) => c.group === g)]).filter((x) => x[2].length);
  page.innerHTML = `
  <header class="card hz-mtop">
    <h2>The models behind the numbers</h2>
    <p class="lede">Each card says what one of our models answers, its headline results, how it was tested and what it can't do.
      Every number is read from the team's notes when the app is built, and shows the note it came from and the date the note was generated.</p>
    <p class="how"><b>Skill</b> = 1 − CRPS ÷ the CRPS of climatology (each series' own history): 0 is no better than the historical average,
      higher is better. <b>Given the oil path</b> means the run knew the oil price that happened; <b>forecasting oil too</b> means it knew nothing
      after the forecast date. All scores are backtests on real, revised data.</p>
    <nav class="jump" aria-label="Models">${D.experts ? `<span class="jg"><span class="jt">Compare</span><button type="button" data-mjump="experts">Against the experts</button></span>` : ""}${groups.map(([, title, cs]) => `<span class="jg"><span class="jt">${esc(title)}</span>${cs.map((c) =>
      `<button type="button" data-mjump="${esc(c.id)}">${esc(c.title)}</button>`).join("")}</span>`).join("")}</nav>
  </header>
  ${D.experts ? experts(D.experts) : ""}
  ${groups.map(([g, title, cs]) => `<section class="hz-mgrp" aria-label="${esc(title)}"><h2 class="gt">${esc(title)}</h2>
    <div class="grid">${cs.map(card).join("")}</div></section>`).join("")}`;
  ($("hz-households") || straitStage).after(page);

  // ------------------------------------------------------------ show / hide, beside the other views
  const KEY = "hz-page";
  function show(on, quiet) {
    const hh = $("hz-households");
    if (on && hh && !hh.hidden && window.HZHouseholds && window.HZHouseholds.show) window.HZHouseholds.show(false, true);
    page.hidden = !on;
    btn.setAttribute("aria-pressed", String(on));
    const sc = $("scenario");
    if (on) {
      $("world-stage").hidden = true; straitStage.hidden = true;
      $("view-seg").hidden = true; $("hsearch").hidden = true; if (sc) sc.hidden = true;
      document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      if (!quiet) { page.scrollTop = 0; window.scrollTo({ top: 0 }); }
      try { localStorage.setItem(KEY, "models"); } catch (e) {}
    } else {
      if (sc && (!hh || hh.hidden)) sc.hidden = false;   // the Households page keeps the scenario menu hidden
      try { if (localStorage.getItem(KEY) === "models") localStorage.setItem(KEY, ""); } catch (e) {}
    }
  }
  btn.addEventListener("click", () => { if (page.hidden) show(true); });
  // World, Strait and Households run their own handlers first; this one only steps aside
  seg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && b !== btn && !page.hidden) show(false); });
  page.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mjump]");
    const el = b && $(`mod-${b.dataset.mjump}`);
    if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ block: "start" }); }
  });
  page.querySelectorAll(".hz-mc, .hz-mx").forEach((c) => { c.tabIndex = -1; });

  let saved = "";
  try { saved = localStorage.getItem(KEY) || ""; } catch (e) {}
  if (location.hash === "#models" || (saved === "models" && !["#mandeb", "#households"].includes(location.hash))) show(true, true);
  return { show };
})();
