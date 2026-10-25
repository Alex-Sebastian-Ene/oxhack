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
  // a card's sources sit behind its info button (as on the Households page): each number's note and date, then the notes
  const INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.5"/></svg>';
  function sources(c) {
    const row = (what, path, date) => `<li><b>${esc(what)}</b><br>${src(path, date)}</li>`;
    const nums = [...c.stats.map((s) => row(s.label, s.src, s.date)),
      ...(c.table ? [row("The links table", c.table.src, c.table.date)] : []),
      ...(c.bars ? [row(c.bars.title, c.bars.src, c.bars.date)] : [])];
    return `<div class="msrc" id="msrc-${esc(c.id)}" hidden><p>Every number is read from the team's notes when the app is built.</p>
      <ul>${nums.join("")}</ul><p><b>Notes behind this model</b></p><ul>${c.files.map((f) => `<li>${src(f.path, f.date)}</li>`).join("")}</ul></div>`;
  }

  // ------------------------------------------------------------ the parts of a card
  // a headline number: the value, what it measures, its context, and the note it came from
  function stat(s) {
    const [v, pm] = s.v.split(" ± ");
    const zero = !/[1-9]/.test(v.replace(/[^\d.]/g, ""));   // −0.0000 is zero: no colour
    const sign = zero ? "" : /^\+/.test(v) ? " pos" : /^[−-]/.test(v) ? " neg" : "";   // + in green, − in red
    return `<div class="st"><b class="v${sign}">${esc(v)}${pm ? `<small> ± ${esc(pm)}</small>` : ""}</b>
      <span class="l">${esc(s.label)}</span>${s.note ? `<span class="n">${esc(s.note)}</span>` : ""}</div>`;
  }
  // the knock-on links and how they held up across folds
  function links(t) {
    const tone = (v) => (/^holds/i.test(v) ? "ok" : /^fails/i.test(v) ? "bad" : "mid");
    return `<table class="lt"><thead><tr>${t.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${t.rows.map((r) =>
      `<tr><td>${esc(r[0])}</td><td><span class="mono">${esc(r[1])}</span><small>${esc(r[2])}</small></td><td class="mono">${esc(r[3].replace(" of ", " of "))}</td>
       <td class="vd ${tone(r[4])}">${esc(r[4])}</td></tr>`).join("")}</tbody></table>`;
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
      <p class="ax">0 = climatology, the series' own history; higher is better.</p></figure>`;
  }
  function card(c) {
    return `<article class="card hz-mc${c.wide ? " wide" : ""}${c.full ? " full" : ""}" id="mod-${esc(c.id)}">
      <div class="mh"><h3>${esc(c.title)}</h3><span class="kind">${esc(c.kind)}</span>
        <button type="button" class="ib hz-i" data-msrc="msrc-${esc(c.id)}" aria-label="Sources for ${esc(c.title)}">${INFO}</button></div>
      <p class="asks">${md(c.asks)}</p>
      <div class="stats">${c.stats.map(stat).join("")}</div>
      ${c.table ? links(c.table) : ""}${c.bars ? bars(c.bars) : ""}
      <div class="row"><span class="tl">Tested</span><p>${md(c.tested)}</p></div>
      <div class="row lim"><span class="tl">Can't</span><ul>${c.limits.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>
      ${sources(c)}
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
    <p class="how"><b>Skill</b> = 1 − CRPS ÷ the CRPS of climatology (each series' own history): 0 is no better than the historical average,
      higher is better. <b>Given the oil path</b> means the run knew the oil price that happened; <b>forecasting oil too</b> means it knew nothing
      after the forecast date. All scores are backtests on real, revised data.</p>
    <div class="seg ctabs hz-mtabs" role="tablist" aria-label="Model groups">${groups.map(([g, title, cs]) =>
      `<button type="button" role="tab" id="mtab-${esc(g)}" data-mtab="${esc(g)}" aria-controls="mgrp-${esc(g)}">${esc(title)} <span class="mtn">${cs.length}</span></button>`).join("")}</div>
  </header>
  ${groups.map(([g, title, cs]) => `<section class="hz-mgrp" id="mgrp-${esc(g)}" role="tabpanel" aria-labelledby="mtab-${esc(g)}"><h2 class="gt">${esc(title)}</h2>
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
  // one group of models at a time, as tabs
  const TKEY = "hz-models-tab";
  const tabs = [...page.querySelectorAll("[data-mtab]")];
  function tab(g, focus) {
    if (!tabs.some((b) => b.dataset.mtab === g)) g = tabs[0].dataset.mtab;
    tabs.forEach((b) => {
      const on = b.dataset.mtab === g;
      b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1;
      $(`mgrp-${b.dataset.mtab}`).hidden = !on;
      if (on && focus) b.focus();
    });
    try { localStorage.setItem(TKEY, g); } catch (e) {}
  }
  page.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mtab]"); if (b) tab(b.dataset.mtab);
    const i = e.target.closest("[data-msrc]");
    if (i && $("sheet")) {
      $("sheet-title").textContent = `Sources: ${i.closest(".hz-mc").querySelector("h3").textContent}`;
      $("sheet-body").innerHTML = $(i.dataset.msrc).innerHTML;
      $("sheet").hidden = false; $("sheet-close").focus();
    }
  });
  page.querySelector(".hz-mtabs").addEventListener("keydown", (e) => {
    const i = tabs.indexOf(document.activeElement), d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (i < 0 || !d) return;
    e.preventDefault(); tab(tabs[(i + d + tabs.length) % tabs.length].dataset.mtab, true);
  });
  let savedTab = "";
  try { savedTab = localStorage.getItem(TKEY) || ""; } catch (e) {}
  tab(savedTab);
  page.querySelectorAll(".hz-mc").forEach((c) => { c.tabIndex = -1; });

  let saved = "";
  try { saved = localStorage.getItem(KEY) || ""; } catch (e) {}
  if (location.hash === "#models" || (saved === "models" && !["#mandeb", "#households"].includes(location.hash))) show(true, true);
  return { show };
})();
