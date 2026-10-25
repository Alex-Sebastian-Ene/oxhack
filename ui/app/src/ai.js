// Sources and country profiles, with optional Gemini panels.
//  - Sources (the book key in the header): every material and ingredient, who makes and ships it, every
//    dataset with its source pages and year, and "What is it?": a Gemini description and pixel-art picture.
//  - Profile (in a country's pop-up and panel): its main export and its rank in every table we hold, the
//    exposure numbers from the panel, and "Summarise with Gemini", written only from those numbers.
// The sourced parts are built from the page's own data. The Gemini parts are labelled AI-written. They come from
// answers baked into the build (window.HZ_AI_BAKED, ui/app/data/ai-panels.json, written at the 2026-closure
// setting by `uv run experiments/country_brief.py bake`), or for anything not baked, from the local service
// (experiments/country_brief.py, http://127.0.0.1:8787, or ?ai=<url>).
window.HZAI = (() => {
  const $ = (id) => document.getElementById(id);
  const M = window.MATERIALS, CN = window.COUNTRIES, FLAGS = (window.FLAGS && window.FLAGS.flags) || {};
  if (!M || !CN) return {};
  const AI = (() => { try { return new URLSearchParams(location.search).get("ai") || "http://127.0.0.1:8787"; } catch (e) { return "http://127.0.0.1:8787"; } })();
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const px = (rows, color) => window.HZPixIcon(rows, { K: "currentColor", G: "rgba(255,255,255,.55)" }).replace("<svg", `<svg style="color:${color}"`);
  const ICON = {
    steel: ["KKKKKKKKK", "KKKKKKKKK", "...KKK...", "...KKK...", "...KKK...", "...KKK...", "...KKK...", "KKKKKKKKK", "KKKKKKKKK"],
    jet_fuel: ["....K....", "...KKK...", "...KKK...", "KKKKKKKKK", ".KKKKKKK.", "...KKK...", "...KKK...", "..KKKKK..", "....K...."],
    aluminium: ["..KKKKK..", ".K.....K.", ".KKKKKKK.", ".KGGGGGK.", ".KGKKKGK.", ".KGGGGGK.", ".KKKKKKK.", ".K.....K.", "..KKKKK.."],
    fertiliser: ["..KK.KK..", ".KKK.KKK.", ".KKKKKKK.", "..KKKKK..", "....K....", "....K....", "...KKK...", "..KKKKK..", ".KKKKKKK."],
    polyethylene: ["...KKK...", "...KKK...", "..KKKKK..", ".KKKKKKK.", ".KGGGGGK.", ".KGGGGGK.", ".KKKKKKK.", ".KKKKKKK.", "..KKKKK.."],
    ore: ["..KKKK...", ".KKKKKK..", "KKKGKKKK.", "KKKKKKKKK", ".KKKKGKKK", "..KKKKKK.", "...KKK..."],
    book: ["KKKKK.KKKKK", "K...KKK...K", "K.KKK.KKK.K", "K...K.K...K", "K.KKK.KKK.K", "K...K.K...K", "K.KKK.KKK.K", "K...K.K...K", "KKKKKKKKKKK"],
    spark: ["....K....", "....K....", "...KKK...", "KKKKKKKKK", "...KKK...", "....K....", "....K...."],
    flag: ["K.......", "KKKKKKK.", "KKKKKKKK", "KKKKKKK.", "K.......", "K.......", "K......."],
  };
  const HUE = { steel: "#7f95ff", jet_fuel: "#ff8a3d", aluminium: "#3fd0ee", fertiliser: "#5fd86e", polyethylene: "#ff5cbf" };
  const where = {}, isoOf = {};
  for (const f of CN.features) { where[f.properties.iso3] = f.properties; isoOf[f.properties.name] = f.properties.iso3; }
  for (const [k, p] of Object.entries(CN.points)) { where[k] = p; if (!isoOf[p.name]) isoOf[p.name] = k; }
  const nameOf = (iso) => { const n = (where[iso] && where[iso].name) || iso; return n === "United States of America" ? "United States" : n; };
  const flag = (iso, cls = "") => (FLAGS[iso] ? `<img class="flag ${cls}" src="${FLAGS[iso]}" alt="" title="${esc(nameOf(iso))}">` : `<span class="flag none ${cls}">${esc(iso)}</span>`);
  const share = (r) => (r.share != null ? `${r.approx ? "≈" : ""}${(r.share * 100).toFixed(r.share < 0.1 ? 1 : 0)}%` : `${r.value}`);
  const URL_RE = /https?:\/\/[^\s;,)|]+/g;
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
  const linkify = (s) => esc(s).replace(URL_RE, (u) => `<a class="hz-src" href="${u}" target="_blank" rel="noopener" title="${u}">${host(u)}</a>`);
  const firstHost = (s) => { const u = String(s || "").match(URL_RE); return u ? host(u[0]) : "see notes"; };
  const play = (k) => window.HZSound && window.HZSound.play(k);
  const BAKED = window.HZ_AI_BAKED || {}, bakedRes = BAKED.resources || {}, bakedCty = BAKED.countries || {};
  const day = (t) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  // the 2026 closure preset in "The shock" card, the setting the baked country summaries were written at
  const onClosure = () => { const b = document.querySelector('[data-path="iea2026"]'); return !!b && b.getAttribute("aria-pressed") === "true"; };

  // ------------------------------------------------------------ one panel for both views
  const panel = document.createElement("div");
  panel.className = "hz-panel"; panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); panel.setAttribute("aria-labelledby", "hz-p-title");
  panel.innerHTML = `<div class="hz-p-box"><div class="hz-p-head"><h2 id="hz-p-title"></h2><button type="button" class="hz-p-x" id="hz-p-x" aria-label="Close">✕</button></div><div class="hz-p-body" id="hz-p-body"></div></div>`;
  document.body.append(panel);
  let back = null;
  function open(title, html, after) {
    back = document.activeElement;
    $("hz-p-title").innerHTML = title; $("hz-p-body").innerHTML = html; panel.hidden = false; $("hz-p-body").scrollTop = 0;
    play("paper"); $("hz-p-x").focus({ preventScroll: true });
    if (after) after($("hz-p-body"));
  }
  function close() { if (panel.hidden) return; panel.hidden = true; play("blip"); if (back && back.focus) back.focus({ preventScroll: true }); }
  $("hz-p-x").addEventListener("click", close);
  panel.addEventListener("click", (e) => { if (e.target === panel) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) { e.stopPropagation(); close(); } }, true);

  // ------------------------------------------------------------ Gemini calls
  async function ask(path, body) {
    let res;
    try { res = await fetch(`${AI}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
    catch (e) { throw new Error("the local Gemini service isn't reachable from this page"); }
    const b = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(b.error || `HTTP ${res.status}`);
    return b;
  }
  const bullets = (text, nFacts) => `<ul class="hz-ai-list">${String(text).split(/\n+/).map((l) => l.replace(/^\s*[-*•]\s*/, "").trim()).filter(Boolean)
    .map((l) => `<li>${esc(l).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[(\d+)\]/g, (m, n) => (Number(n) <= nFacts ? `<span class="hz-ref">[${n}]</span>` : `<span class="hz-ref bad" title="No such fact">[${n}?]</span>`))}</li>`).join("")}</ul>`;
  const stamp = (b, extra = "") => `<p class="hz-ai-stamp">AI-written by ${esc(b.model)}${b.image_model ? `, picture by ${esc(b.image_model)}` : ""}, ${b.cached ? "cached, written " : ""}${esc(new Date(b.generated_at).toLocaleString())}. Not checked by the team${extra}.</p>`;
  const bakedStamp = (b, extra = "") => `<p class="hz-ai-stamp"><b>AI-written by Gemini</b> (${esc(b.model)}), ${esc(day(b.generated_at))}. Written ahead and baked into this page, not live${extra}. Not checked by the team.</p>`;
  const nBaked = Object.keys(bakedRes).length + Object.keys(bakedCty).length;
  const helpLine = (msg) => (nBaked ? `<p class="hz-ai-off">Not written ahead for this one yet: so far Gemini has written ${Object.keys(bakedRes).length} resources and ${Object.keys(bakedCty).length} countries for this page (its free daily quota ran out). The rest follow in a later build.</p>` : "")
    + `<p class="hz-ai-off">No live answer: ${esc(msg)}. Run <code>uv run experiments/country_brief.py</code> with <code>GEMINI_API_KEY</code> in <code>.env</code>.</p>`;
  function aiBox(id, label, run, pre) {
    return `<div class="hz-ai" id="${id}"><div class="hz-ai-head">${px(ICON.spark, "#ffd27a")}<b>${label}</b><span>${pre ? `AI-written by Gemini, ${esc(day(pre.generated_at))}` : "Gemini, on request"}</span></div>
      <button type="button" class="hz-ai-go" data-run="${id}">${run}</button><div class="hz-ai-out" aria-live="polite"></div></div>`;
  }

  // ------------------------------------------------------------ Sources: every resource and every dataset
  const items = () => [
    ...M.materials.map((m) => ({ id: m.id, item: m, kind: "Material", icon: ICON[m.id] || ICON.ore, color: HUE[m.id] || "#ffa424" })),
    ...Object.values(M.inputs).map((i) => ({ id: i.id, item: i, kind: "Ingredient", icon: ICON.ore, color: i.color || "#c4baa3" })),
  ];
  const usedIn = (id) => M.materials.filter((m) => m.inputs.includes(id)).map((m) => m.name);
  // flags in rank order; the name is on hover. Border by share of world: gold 40%+, silver 20%+, bronze 10%+
  const tier = (r) => (r.share == null ? "" : r.share >= 0.4 ? " gold" : r.share >= 0.2 ? " silver" : r.share >= 0.1 ? " bronze" : "");
  const tip = (r, i) => `#${i + 1} ${nameOf(r.iso3)} · ${share(r)}`;
  function flagRow(rows) { return rows.map((r, i) => `<span class="hz-fc${tier(r)}" title="${esc(tip(r, i))}" aria-label="${esc(tip(r, i))}">${flag(r.iso3)}<b>${share(r)}</b></span>`).join(""); }
  function flagStrip(rows, n = 10) { return rows.slice(0, n).map((r, i) => `<span class="hz-fs${tier(r)}" title="${esc(tip(r, i))}">${flag(r.iso3)}</span>`).join("") + (rows.length > n ? `<span class="hz-more">+${rows.length - n}</span>` : ""); }
  function resourceFacts(x) {
    const it = x.item, out = [];
    const made = it.producers || [], ship = (it.exports && it.exports.list) || [];
    made.slice(0, 4).forEach((r, i) => out.push(`${it.name} production: #${i + 1} ${nameOf(r.iso3)}, ${share(r)}${r.share != null ? " of world" : ` ${it.unit || ""}`} (${it.year || ""}; ${firstHost(it.source)})`));
    ship.slice(0, 3).forEach((r, i) => out.push(`${it.name} exports: #${i + 1} ${nameOf(r.iso3)}, ${share(r)}${r.share != null ? " of world exports" : ` ${(it.exports && it.exports.unit) || ""}`} (${(it.exports && it.exports.year) || ""}; ${firstHost(it.exports && it.exports.source)})`));
    const u = usedIn(x.id); if (u.length) out.push(`An ingredient of: ${u.join(", ")}`);
    if (it.inputs) out.push(`Made from: ${it.inputs.map((id) => (M.inputs[id] || {}).name || id).join(", ")}`);
    if (it.exports && it.exports.note_2026) out.push(`2026: ${String(it.exports.note_2026).slice(0, 220)}`);
    return out;
  }
  function sourcesHtml() {
    const all = items(), pages = new Set(), isos = new Set(), years = [];
    const cite = (s) => (String(s || "").match(URL_RE) || []).forEach((u) => pages.add(u));
    for (const x of all) {
      const it = x.item; cite(it.source); if (it.year) years.push(+it.year);
      if (it.exports) { cite(it.exports.source); if (it.exports.year) years.push(+it.exports.year); }
      for (const r of [...(it.producers || []), ...((it.exports && it.exports.list) || [])]) isos.add(r.iso3);
      for (const l of it.links || []) { cite(l.source); isos.add(l.to); isos.add(l.from); }
      for (const f of it.flows || []) cite(f.source);
    }
    const links = M.materials.reduce((a, m) => a + m.links.length, 0);
    const cards = all.map((x) => {
      const it = x.item, made = it.producers || [], ship = (it.exports && it.exports.list) || [], u = usedIn(x.id);
      return `<details class="hz-res" style="--hue:${x.color}"><summary><span class="hz-res-i">${px(x.icon, x.color)}</span><span class="hz-res-t"><b>${esc(it.name)}</b>
          <small>${x.kind}${u.length ? ` · in ${esc(u.join(", "))}` : ""}</small>${made.length ? `<span class="hz-fstrip" aria-label="Top makers">${flagStrip(made)}</span>` : ""}</span><span class="hz-chev">▾</span></summary>
        <div class="hz-res-b">
          ${made.length ? `<div class="hz-row"><span class="hz-k">Made by</span><div class="hz-chips">${flagRow(made)}</div></div>` : ""}
          ${ship.length ? `<div class="hz-row"><span class="hz-k">Shipped by</span><div class="hz-chips">${flagRow(ship)}</div></div>` : ""}
          <div class="hz-ds"><span class="hz-badge made">Made</span><span class="hz-yr">${esc(it.year || "")}</span><span class="hz-fine">${esc(it.unit || "")}</span><div class="hz-srcs">${linkify(it.source || "")}</div></div>
          ${it.exports ? `<div class="hz-ds"><span class="hz-badge ship">Shipped</span><span class="hz-yr">${esc(it.exports.year || "")}</span><span class="hz-fine">${esc(it.exports.unit || "")}</span><div class="hz-srcs">${linkify(it.exports.source || "")}</div>${it.exports.note_2026 ? `<p class="hz-fine">${linkify(it.exports.note_2026)}</p>` : ""}</div>` : ""}
          ${aiBox(`hz-res-${x.id}`, `What is ${esc(it.name.toLowerCase())}?`, bakedRes[x.id] ? "What is it?" : "Explain it, with a picture", bakedRes[x.id])}
        </div></details>`;
    }).join("");
    return `<p class="hz-lede">Every material on the map, who makes and ships it, and the source of each number.</p><p class="hz-tierkey"><span><i style="border-color:#ffcf3f"></i>40%+ of world</span><span><i style="border-color:#c9d3e3"></i>20%+</span><span><i style="border-color:#c98a4b"></i>10%+</span><span>Hover a flag for its country</span></p>
      <div class="hz-tiles"><div><b>${pages.size}</b><span>source pages</span></div><div><b>${isos.size}</b><span>countries</span></div>
        <div><b>${links}</b><span>supplier links</span></div><div><b>${Math.min(...years)}–${Math.max(...years)}</b><span>data years</span></div></div>
      <p class="hz-note">Collected ${esc(M.generated)} from search results of the pages cited. ≈ is our estimate from the table. Not live.</p>
      <div class="hz-res-list">${cards}</div>`;
  }
  async function runResource(box) {
    const id = box.id.replace("hz-res-", ""), x = items().find((y) => y.id === id), out = box.querySelector(".hz-ai-out"), btn = box.querySelector("button");
    const facts = resourceFacts(x);
    const show = (b, st) => {
      out.innerHTML = `<div class="hz-ai-res${b.image ? "" : " nopic"}">${b.image ? `<figure class="hz-pic"><img src="${esc(b.image)}" alt="AI-made pixel-art picture of ${esc(x.item.name)}"><figcaption>AI-made picture</figcaption></figure>` : ""}
        <div>${bullets(b.text, (b.facts || facts).length)}<details class="hz-facts"><summary>The ${(b.facts || facts).length} facts Gemini was given</summary><ol>${(b.facts || facts).map((f) => `<li>${esc(f)}</li>`).join("")}</ol></details></div></div>${st}`;
      play("select");
    };
    btn.disabled = true;
    if (bakedRes[id]) return show(bakedRes[id], bakedStamp(bakedRes[id]));
    out.innerHTML = `<p class="hz-ai-wait">Asking Gemini… <span class="hz-dots">▮▮▮</span></p>`;
    try { const b = await ask("/resource", { id, name: x.item.name, facts }); show(b, stamp(b)); }
    catch (e) { out.innerHTML = helpLine(e.message); btn.disabled = false; play("clank"); }
  }

  // ------------------------------------------------------------ country profile
  function tables(iso) {
    const rows = [];
    const add = (it, kind, mode) => {
      const list = mode === "exports" ? (it.exports && it.exports.list) || [] : it.producers || [], i = list.findIndex((r) => r.iso3 === iso);
      if (i < 0) return;
      const src = mode === "exports" ? it.exports : it;
      rows.push({ it, kind, mode, r: list[i], rank: i + 1, of: list.length, year: src.year, unit: src.unit, source: src.source });
    };
    for (const m of M.materials) { add(m, "material", "production"); add(m, "material", "exports"); }
    for (const i of Object.values(M.inputs)) { add(i, "ingredient", "production"); add(i, "ingredient", "exports"); }
    return rows;
  }
  // the strongest role: the best rank, with the share of world breaking ties
  const strength = (x) => 1 / x.rank + (x.r.share || 0);
  function profileFacts(iso, rows) {
    const out = [], name = nameOf(iso);
    const card = $("c-name") && $("c-name").textContent === (where[iso] && where[iso].name) ? $("country-card") : null;
    if (card) {
      const t = (id) => ($(id) ? $(id).textContent.trim() : "");
      out.push(`${name} in this page's Hormuz model at the current setting (${$("hz-read") ? $("hz-read").textContent : ""}): ${t("c-score")} ${t("c-score-l")}; fuel cost ${t("c-fuel")} vs pre-war; ${t("c-dep")} of its oil imports came from the Gulf; ${t("c-tag")}`);
      if (t("col-now")) out.push(`${t("col-now")} (FAOSTAT)`);
      for (const li of document.querySelectorAll("#col-list li[data-colitem]")) out.push(`${li.querySelector(".nm").textContent.trim()}: ${li.querySelector(".lv").textContent.trim()}. ${li.querySelector(".why").textContent.trim()}`);
    }
    for (const x of rows) out.push(`${x.it.name} ${x.mode === "exports" ? "exports" : "production"}: ${name} ranks #${x.rank} of ${x.of} listed, ${share(x.r)}${x.r.share != null ? (x.mode === "exports" ? " of world exports" : " of world output") : ` ${x.unit || ""}`} (${x.year || ""}; ${firstHost(x.source)})`);
    for (const m of M.materials) for (const l of m.links.filter((l) => l.to === iso && l.from !== iso).sort((a, b) => b.share - a.share).slice(0, 2))
      out.push(`For ${m.name}, ${Math.round(l.share * 100)}% of ${name}'s ${(M.inputs[l.input] || {}).name || l.input} comes from ${nameOf(l.from)} (${l.basis}; ${l.year}; ${firstHost(l.source)})`);
    return out.slice(0, 40);
  }
  function profileHtml(iso) {
    const rows = tables(iso), ex = rows.filter((x) => x.mode === "exports").sort((a, b) => strength(b) - strength(a)), mk = rows.filter((x) => x.mode === "production").sort((a, b) => strength(b) - strength(a));
    const best = (x, verb) => (x ? `<div class="hz-best"><span class="hz-k">${verb}</span><b>${esc(x.it.name)}</b><span>#${x.rank} of ${x.of} listed · ${share(x.r)}${x.r.share != null ? " of world" : ` ${esc(x.unit || "")}`} · ${esc(x.year || "")}</span></div>` : "");
    const card = $("c-name") && $("c-name").textContent === (where[iso] && where[iso].name);
    const t = (id) => esc($(id) ? $(id).textContent : "–");
    const tile = (v, l, cls = "") => `<div><b class="${cls}">${v}</b><span>${l}</span></div>`;
    const colLv = (k) => { const li = document.querySelector(`#col-list li[data-colitem="${k}"] .lv`); return esc(li ? li.textContent : "–"); };
    const bars = rows.map((x) => {
      const w = Math.max(6, Math.round((x.r.share != null ? Math.min(1, x.r.share / 0.6) : (x.of - x.rank + 1) / x.of) * 100));
      return `<div class="hz-rk ${x.mode}"><span class="hz-rk-n">${esc(x.it.name)} <small>${x.mode === "exports" ? "shipped" : "made"}</small></span><span class="hz-rk-b"><i style="width:${w}%"></i></span><span class="hz-rk-v">#${x.rank}<small>/${x.of}</small> ${share(x.r)}</span></div>`;
    }).join("");
    const into = [];
    for (const m of M.materials) for (const l of m.links.filter((l) => l.to === iso && l.from !== iso).sort((a, b) => b.share - a.share).slice(0, 3))
      into.push(`<span class="hz-chip" title="${esc(l.basis)} · ${esc(l.year)}">${esc((M.inputs[l.input] || {}).name || l.input)} ← ${flag(l.from)}<b>${Math.round(l.share * 100)}%</b></span>`);
    return `<div class="hz-prof-hero">${flag(iso, "huge")}<div><b>${esc(nameOf(iso))}</b><span>${rows.length ? `In ${rows.length} of our production and export tables` : "Not in our sourced tables yet"}</span></div></div>
      ${card ? `<div class="hz-tiles">${tile(colLv("food"), "groceries in 12 months", "hot")}${tile(t("c-fuel"), "fuel cost vs pre-war", "hot")}${tile(t("c-score"), t("c-score-l"))}${tile(t("c-dep"), "of its oil imports from the Gulf")}</div><p class="hz-note">${t("col-now")}</p>` : ""}
      <div class="hz-bests">${best(ex[0], "Main export in our tables")}${best(mk[0], "Biggest role in production")}</div>
      ${rows.length ? `<h3 class="hz-h3">Where it ranks</h3><div class="hz-rks">${bars}</div>` : ""}
      ${into.length ? `<h3 class="hz-h3">Key inputs come from</h3><div class="hz-chips">${into.join("")}</div>` : ""}
      ${aiBox("hz-prof-ai", `${esc(nameOf(iso))} in a few lines`, "Summarise with Gemini", bakedCty[iso])}
      <p class="hz-note">Ranks are within each table's listed countries. Numbers come from Sources or this page's model.</p>`;
  }
  let profIso = null;
  async function runProfile(box) {
    const iso = profIso, out = box.querySelector(".hz-ai-out"), btn = box.querySelector("button"), facts = profileFacts(iso, tables(iso));
    const show = (b, st) => {
      const fx = b.facts || facts;
      out.innerHTML = `${bullets(b.text, fx.length)}<details class="hz-facts"><summary>The ${fx.length} facts Gemini was given</summary><ol>${fx.map((f) => `<li>${esc(f)}</li>`).join("")}</ol></details>${st}`;
      play("select");
    };
    btn.disabled = true;
    const pre = bakedCty[iso];
    if (pre) return show(pre, bakedStamp(pre, `; written at the ${esc(BAKED.setting || "2026-closure")} setting${onClosure() ? "" : ", so its numbers can differ from the tiles above, which follow your setting"}; numbers in [brackets] point to the facts`));
    out.innerHTML = `<p class="hz-ai-wait">Asking Gemini… <span class="hz-dots">▮▮▮</span></p>`;
    try { const b = await ask("/country", { iso3: iso, country: nameOf(iso), facts }); show(b, stamp(b, "; numbers in [brackets] point to the facts")); }
    catch (e) { out.innerHTML = helpLine(e.message); btn.disabled = false; play("clank"); }
  }
  function openProfile(iso) {
    if (!iso) return;
    profIso = iso;
    open(`${window.HZPixIcon(ICON.flag, { K: "currentColor" })} Profile`, profileHtml(iso), (body) => {
      body.querySelector('[data-run="hz-prof-ai"]').addEventListener("click", () => runProfile($("hz-prof-ai")));
    });
  }
  const selectedIso = () => { const n = $("c-name") && $("c-name").textContent; return n && isoOf[n]; };

  // ------------------------------------------------------------ hooks into the app
  const bar = document.querySelector(".hz-keys");
  if (bar) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "hz-key"; b.id = "hz-sources"; b.title = "Sources and resources"; b.setAttribute("aria-label", "Sources and resources");
    b.innerHTML = window.HZPixIcon(ICON.book, { K: "currentColor" });
    bar.prepend(b);
    b.addEventListener("click", () => open(`${window.HZPixIcon(ICON.book, { K: "currentColor" })} Sources and resources`, sourcesHtml(), (body) => {
      body.querySelectorAll("[data-run]").forEach((btn) => btn.addEventListener("click", () => runResource($(btn.dataset.run))));
      body.querySelectorAll("details.hz-res").forEach((d) => d.addEventListener("toggle", () => d.open && play("blip")));
    }));
  }
  const profBtn = (id, cls) => { const b = document.createElement("button"); b.type = "button"; b.id = id; b.className = cls; b.innerHTML = `${window.HZPixIcon(ICON.flag, { K: "currentColor" })}<span>Profile</span>`; b.addEventListener("click", () => openProfile(selectedIso())); return b; };
  const more = $("cp-more");
  if (more) more.after(profBtn("hz-cp-prof", "more hz-prof-btn"));
  const ct = document.querySelector("#country-card .ctitle .row");
  if (ct) ct.prepend(profBtn("hz-c-prof", "hz-prof-btn small"));
  // the facts each Gemini panel sends, for `node ui/app/src/ai_facts.cjs` (country facts need the country selected)
  const facts = { resources: () => items().map((x) => ({ id: x.id, name: x.item.name, facts: resourceFacts(x) })),
    country: (iso) => ({ iso3: iso, country: nameOf(iso), facts: profileFacts(iso, tables(iso)) }), countries: () => Object.keys(where) };
  return { openProfile, openSources: () => $("hz-sources") && $("hz-sources").click(), AI, facts, selectedIso };
})();
