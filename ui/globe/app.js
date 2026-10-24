// Materials Globe: click a material to see who makes and who ships it; click a country to see where its
// ingredients come from and where its exports go; drag Brent to see the modelled price change. Data:
// data/materials.js, written by `uv run experiments/globe_data.py` from the sourced tables in notes/materials/.
//
// Made and Shipped are drawn together. The one in front is bright (raised land, solid arcs); the other is
// faded (see-through columns, thin arcs). Add ?single to the URL for the older one-layer view.
(() => {
  const M = window.MATERIALS;
  const C = window.COUNTRIES;
  const $ = (id) => document.getElementById(id);
  const svg = (p) => `<svg viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ICON = {
    steel: '<path d="M5 4h14M5 20h14M12 4v16"/><path d="M8 4v2M16 4v2M8 18v2M16 18v2"/>',
    jet_fuel: '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/>',
    aluminium: '<path d="M7 4h10l-1 16H8z"/><path d="M7.4 8h9.2"/>',
    fertiliser: '<path d="M12 21v-8"/><path d="M12 13C12 8 8 6 4 6c0 4 3 7 8 7z"/><path d="M12 11c0-4 3-6 8-6 0 4-3 6-8 6z"/>',
    polyethylene: '<path d="M10 2h4v3l2 3v12a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8l2-3z"/><path d="M8 12h8"/>',
    production: '<path d="M3 21V10l6 4V10l6 4V5h6v16z"/>',
    exports: '<path d="M3 16h18l-3 5H6z"/><path d="M7 16V9h7l3 7"/><path d="M10 9V5"/>',
    oil: '<path d="M12 3c3 4 6 7 6 11a6 6 0 0 1-12 0c0-4 3-7 6-11z"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.5"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3 3 15 0 18c-3-3-3-15 0-18z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    note: '<path d="M5 4h10l4 4v12H5z"/><path d="M9 12h6M9 16h4"/>',
  };
  const COL = { land: [42, 52, 66], production: [240, 162, 59], exports: [92, 184, 240], sea: "#0b2236" };
  const SOFT = { production: "#f5bd6e", exports: "#8fd0f5" };
  const LABEL = { production: "Made", exports: "Shipped" };
  const DUAL = !/[?&]single\b/.test(location.search);
  const other = (mode) => (mode === "exports" ? "production" : "exports");
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const hexA = (h, a) => { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

  // ---------------------------------------------------------------- lookups
  const where = {};
  for (const f of C.features) where[f.properties.iso3] = { name: f.properties.name, lat: f.properties.lat, lng: f.properties.lng };
  for (const [k, p] of Object.entries(C.points)) where[k] = p;
  const nameOf = (iso) => (where[iso] && where[iso].name) || iso;
  const FLAGS = (window.FLAGS && window.FLAGS.flags) || {};
  // A country's flag (offline SVG); heavy flags we left out fall back to the letter code.
  const flag = (iso, cls = "") => (FLAGS[iso] ? `<img class="flag ${cls}" src="${FLAGS[iso]}" alt="${esc(nameOf(iso))}" title="${esc(nameOf(iso))}">`
    : `<span class="flag none ${cls}" title="${esc(nameOf(iso))}">${esc(iso)}</span>`);
  const named = (iso) => `<span class="cn">${flag(iso)}<span>${esc(nameOf(iso))}</span></span>`;
  // Optional AI country briefs from a local Gemini proxy (experiments/country_brief.py): add ?brief=1 to the URL.
  const BRIEF = (() => { const b = new URLSearchParams(location.search).get("brief"); return b ? (b === "1" ? "http://127.0.0.1:8787" : b) : null; })();
  const mats = Object.fromEntries(M.materials.map((m) => [m.id, m]));

  const state = { mat: M.materials[0].id, mode: "production", country: null, input: null, brent: 60 };

  // What the globe is coloured by right now: the material, or one of its inputs.
  function subject() {
    const m = mats[state.mat];
    return state.input ? M.inputs[state.input] : m;
  }
  function table(item, mode = state.mode) {
    if (mode === "exports") return (item.exports && item.exports.list) || [];
    return item.producers || [];
  }
  // Colouring weight per country (share of world, or relative size when no shares exist).
  function weights(mode = state.mode) {
    return Object.fromEntries(table(subject(), mode).map((r) => [r.iso3, r.w]));
  }
  const hasShares = (mode = state.mode) => table(subject(), mode).some((r) => r.share != null);
  function unitOf(item, mode = state.mode) { return mode === "exports" ? (item.exports && item.exports.unit) || "" : item.unit || ""; }
  function fmtRow(r) {
    if (r.share != null) return `${r.approx ? "≈" : ""}${(r.share * 100).toFixed(r.share < 0.1 ? 1 : 0)}%`;
    return `${r.value}`;
  }
  const pctOf = (x) => `${Math.round(x * 100)}%`;
  function flowLabel(f, item) {
    const bits = [`${nameOf(f.from)} → ${nameOf(f.to)}`];
    if (f.value != null) bits.push(`${f.value} ${(item.exports && item.exports.unit) || ""}`.trim());
    if (f.share_of_importer != null) bits.push(`${pctOf(f.share_of_importer)} of ${nameOf(f.to)}'s imports`);
    else if (f.share_of_exporter != null) bits.push(`${pctOf(f.share_of_exporter)} of ${nameOf(f.from)}'s exports`);
    if (f.period || f.year) bits.push(String(f.period || f.year));
    return bits.join(" · ");
  }

  // ---------------------------------------------------------------- oil price maths
  // Rises use the +10% row and falls the -10% row (they differ), scaled in log terms. The band is the
  // 90% interval of the average effect only (parameter uncertainty), so single outcomes vary more.
  function priceMove(oil) {
    if (!oil || !oil.up) return null;
    const x = state.brent / 100;
    const [row, base] = x >= 0 ? [oil.up, 1.1] : [oil.down, 0.9];
    const f = Math.log(1 + x) / Math.log(base);
    const a = row[1] * f, b = row[2] * f;
    return { mean: row[0] * f, lo: Math.min(a, b), hi: Math.max(a, b) };
  }
  function shockRange(oil) {   // event-based range, given per +10% Brent
    if (!oil || !oil.disruption || state.brent <= 0) return null;
    const f = Math.log(1 + state.brent / 100) / Math.log(1.1);
    return { lo: oil.disruption.lo * f, hi: oil.disruption.hi * f };
  }
  const pct = (x, d = 0) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}%`;

  // ---------------------------------------------------------------- globe
  const globe = Globe()($("globe"))
    .backgroundColor("#04070c")
    .showAtmosphere(true).atmosphereColor("#5cb8f0").atmosphereAltitude(0.18)
    .polygonsData(C.features)
    .polygonSideColor(() => "rgba(4,7,12,0.35)")
    .polygonStrokeColor(() => "rgba(61,75,92,0.9)")
    .polygonsTransitionDuration(600)
    .pointsTransitionDuration(600)
    .arcDashLength(0.45).arcDashGap(0.25).arcAltitudeAutoScale(0.45)
    .onPolygonClick((f) => pickCountry(f.properties.iso3))
    .onPointClick((p) => pickCountry(p.iso3))
    .onPolygonHover(hover)
    .onPointHover((p) => hover(p ? { properties: { iso3: p.iso3 } } : null));
  globe.globeMaterial().color.set(COL.sea);
  const controls = globe.controls();
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.35;
  globe.pointOfView({ lat: 22, lng: 60, altitude: 2.4 });
  ["pointerdown", "wheel", "touchstart"].forEach((ev) => $("globe").addEventListener(ev, () => { controls.autoRotate = false; }, { passive: true }));
  const fit = () => globe.width(window.innerWidth).height(window.innerHeight);
  window.addEventListener("resize", fit);
  fit();

  function mix(t, mode = state.mode) {
    const hi = COL[mode];
    const c = COL.land.map((v, i) => Math.round(v + (hi[i] - v) * t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }
  function paint() {
    const front = state.mode, back = other(front);
    const s = weights(front), g = DUAL ? weights(back) : {};
    const max = Math.max(...Object.values(s), 0.01), gmax = Math.max(...Object.values(g), 0.01);
    const sel = state.country;
    const lift = (iso) => 0.006 + (s[iso] ? 0.12 * Math.sqrt(s[iso] / max) : 0) + (iso === sel ? 0.03 : 0);
    globe
      .polygonCapColor((f) => {
        const iso = f.properties.iso3, v = s[iso];
        if (iso === sel) return "#ffe2b0";
        if (v) return mix(0.25 + 0.75 * Math.sqrt(v / max));
        if (g[iso]) return mix(0.14, back);   // only in the faded layer: a faint tint of its colour
        return mix(0);
      })
      .polygonAltitude((f) => lift(f.properties.iso3));
    const pts = [];
    // small countries have no polygon at this scale: pins carry the bright layer
    for (const [iso3, p] of Object.entries(C.points)) {
      if (s[iso3]) pts.push({ iso3, lat: p.lat, lng: p.lng, alt: 0.02 + 0.12 * Math.sqrt(s[iso3] / max), r: 0.6, color: SOFT[front] });
    }
    // the faded layer: a see-through column standing on each country
    for (const [iso3, v] of Object.entries(g)) {
      const w = where[iso3];
      if (!w) continue;
      const small = !!C.points[iso3];
      pts.push({ iso3, lat: w.lat, lng: w.lng + (small && s[iso3] ? 0.9 : 0), r: small ? 0.45 : 0.85, color: rgba(COL[back], 0.4),
                 alt: (small ? 0 : lift(iso3)) + 0.015 + 0.14 * Math.sqrt(v / gmax) });
    }
    globe.pointsData(pts).pointColor((d) => d.color).pointAltitude((d) => d.alt).pointRadius((d) => d.r);
    drawArcs();
    legend(max);
    const w = sel && where[sel];
    globe.ringsData(w ? [{ lat: w.lat, lng: w.lng }] : [])
      .ringColor(() => (t) => `rgba(255,226,176,${1 - t})`).ringMaxRadius(6).ringPropagationSpeed(2.5).ringRepeatPeriod(1100);
  }

  // Rays from the chosen country: Made arcs bring its ingredients in from their suppliers; Shipped arcs
  // are the biggest sourced trade flows from or to it (or worldwide, when no country is chosen).
  function drawArcs() {
    const m = mats[state.mat], item = subject(), sel = state.country;
    const arcs = [];
    const add = (from, to, color, weight, label, mode) => {
      const a = where[from], b = where[to];
      if (!a || !b || from === to) return;
      arcs.push({ startLat: a.lat, startLng: a.lng, endLat: b.lat, endLng: b.lng, color, weight, label, faded: mode !== state.mode });
    };
    if (sel && (DUAL || state.mode === "production")) {
      for (const l of m.links.filter((l) => l.to === sel && (!state.input || l.input === state.input))) {
        const inp = M.inputs[l.input];
        add(l.from, l.to, inp ? inp.color : "#e7ecf2", l.share, `${inp ? inp.name : l.input}: ${nameOf(l.from)} → ${nameOf(l.to)} ${pctOf(l.share)}`, "production");
      }
    }
    if (DUAL || state.mode === "exports") {
      const flows = (item.flows || []).filter((f) => !sel || f.from === sel || f.to === sel);
      const maxv = Math.max(...flows.map((f) => f.value || 0), 1);
      for (const f of flows.slice(0, 14)) {
        const wgt = f.value != null ? f.value / maxv : f.share_of_importer || f.share_of_exporter || 0.1;
        add(f.from, f.to, "#8fd0f5", wgt, flowLabel(f, item), "exports");
      }
    }
    globe.arcsData(arcs)
      .arcColor((d) => (d.faded ? [hexA(d.color, 0.04), hexA(d.color, 0.3)] : [hexA(d.color, 0.25), d.color]))
      .arcStroke((d) => (d.faded ? 0.45 : 1) * (0.25 + 1.4 * Math.sqrt(d.weight || 0.1)))
      .arcDashAnimateTime((d) => (d.faded ? 4400 : 2200))
      .arcLabel((d) => esc(d.label));
  }

  function legend(max) {
    const front = state.mode, back = other(front);
    const right = hasShares() ? `up to ${Math.round(max * 100)}% of world` : "relative to the largest";
    let html = `<div class="lg">${svg(ICON[front])}<span class="ramp" style="background:linear-gradient(90deg,${mix(0.25)},${mix(1)})"></span><b>${LABEL[front]}</b><span>raised land · ${right}</span></div>`;
    if (DUAL) html += `<div class="lg faded">${svg(ICON[back])}<span class="col" style="background:${rgba(COL[back], 0.45)}"></span><b>${LABEL[back]}</b><span>faded columns</span></div>`;
    $("legend").innerHTML = html;
  }

  const tip = $("tip");
  window.addEventListener("pointermove", (e) => { tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 14}px`; });
  function hover(f) {
    if (!f) { tip.hidden = true; return; }
    const iso = f.properties.iso3;
    const part = (mode) => {
      const r = table(subject(), mode).find((x) => x.iso3 === iso);
      return `<span class="tp ${mode} ${mode === state.mode ? "" : "faded"}">${svg(ICON[mode])}<b>${r ? fmtRow(r) + (r.share == null ? " " + esc(unitOf(subject(), mode)) : "") : "–"}</b></span>`;
    };
    tip.innerHTML = `${named(iso)} ${part(state.mode)}${DUAL ? part(other(state.mode)) : ""}`;
    tip.hidden = false;
  }

  // ---------------------------------------------------------------- side card
  function bars(rows, mode, ghost) {
    const max = Math.max(...rows.map((r) => r.w), 0.01);
    const gmax = Math.max(...Object.values(ghost || {}), 0.01);
    return `<div class="bars">${rows.slice(0, 7).map((r) => {
      const gw = ghost && ghost[r.iso3];
      return `<button type="button" data-iso="${r.iso3}" title="${esc(nameOf(r.iso3))}">
      <span class="iso">${flag(r.iso3)}<span>${esc(nameOf(r.iso3))}</span></span><span class="track"><i><span style="width:${r.w / max * 100}%;background:var(--${mode === "exports" ? "ship" : "made"})"></span></i>${ghost ? `<i class="g"><span style="width:${gw ? gw / gmax * 100 : 0}%;background:${rgba(COL[other(mode)], 0.55)}"></span></i>` : ""}</span>
      <span class="v">${fmtRow(r)}</span></button>`;
    }).join("")}</div>`;
  }
  function priceBlock(m) {
    const p = priceMove(m.oil);
    if (!p) return `<div class="price">${svg(ICON[m.id])}<div><b class="none">?</b><small>No fitted oil link yet${m.oil && m.oil.note ? ` · ${esc(m.oil.note)}` : ""}</small></div></div>`;
    const d = shockRange(m.oil);
    return `<div class="price"><div><b>${pct(p.mean)}</b><small>price in 12 months if Brent ${pct(state.brent)}${m.oil.validated ? "" : " · not validated"}</small>
      <small>average-effect band ${pct(p.lo)} to ${pct(p.hi)}; single moves vary more</small>
      ${d ? `<small>past supply shocks: ${pct(d.lo)} to ${pct(d.hi)}</small>` : ""}</div></div>`;
  }
  const modeHead = (mode, extra = "") => `<button type="button" class="lh ${mode}" data-mode-to="${mode}" ${mode === state.mode ? "disabled" : ""}>${svg(ICON[mode])}<span>${LABEL[mode]}</span>${extra}</button>`;
  const layer = (mode, html) => `<section class="layer ${mode === state.mode ? "on" : "off"}">${html}</section>`;

  function madeDetails(m, iso) {
    const ins = (state.input ? [state.input] : m.inputs).map((id) => M.inputs[id]).filter(Boolean);
    let html = `<div class="inputs">${ins.map((inp) => {
      const ls = m.links.filter((l) => l.to === iso && l.input === inp.id).sort((a, b) => b.share - a.share);
      const chips = ls.length ? ls.slice(0, 6).map((l) => `<span class="chip ${l.from === iso ? "dom" : ""}" title="${esc(nameOf(l.from))}: ${esc(l.basis || "")} (${l.year || ""})">${flag(l.from)}${pctOf(l.share)}</span>`).join("")
        : `<span class="fine">No sourced supplier split</span>`;
      const drill = state.input || !(inp.producers.length || (inp.exports && inp.exports.list.length)) ? ""
        : `<button type="button" class="go" data-input="${inp.id}" aria-label="Show where ${esc(inp.name)} comes from worldwide">${svg(ICON.globe)}</button>`;
      return `<div class="input"><div class="top"><span class="name"><span class="dot" style="background:${inp.color}"></span>${esc(inp.name)}</span>${drill}</div>
        <div class="chips">${chips}</div></div>`;
    }).join("")}</div>`;
    if (state.input) html += `<p class="fine">Globe: who makes and ships ${esc(M.inputs[state.input].name.toLowerCase())} worldwide. Arcs: what reaches ${esc(nameOf(iso))}.</p>`;
    return html;
  }
  function shipDetails(item, iso) {
    const flows = (item.flows || []).filter((f) => f.from === iso || f.to === iso);
    return flows.length ? `<div class="chips">${flows.map((f) => `<span class="chip ship" title="${esc(flowLabel(f, item))}">${flag(f.from)}→${flag(f.to)}${f.value != null ? ` ${f.value}` : f.share_of_importer != null ? ` ${pctOf(f.share_of_importer)}` : ""}</span>`).join("")}</div>`
      : `<p class="empty">No sourced flows for ${esc(nameOf(iso))}.</p>`;
  }
  function stat(item, iso, mode) {
    const r = table(item, mode).find((x) => x.iso3 === iso);
    const sub = !r ? `not among listed ${mode === "exports" ? "exporters" : "producers"}` : r.share != null ? `of world ${mode === "exports" ? "exports" : "output"}` : unitOf(item, mode);
    return `<button type="button" class="stat ${mode} ${mode === state.mode ? "on" : "off"}" data-mode-to="${mode}" ${mode === state.mode ? "disabled" : ""}>
      <span class="k">${svg(ICON[mode])}${LABEL[mode]}</span><b>${r ? fmtRow(r) : "–"}</b><span class="u">${esc(sub)}</span></button>`;
  }
  function srcLine(item) {
    const src = state.mode === "exports" ? item.exports : item;
    return `<div class="srcline"><span class="fine">${esc((src && src.unit) || "")}${src && src.year ? ` · ${src.year}` : ""}</span>
      <button type="button" class="pill" data-info="sources">${svg(ICON.info)}<span>Sources</span></button></div>`;
  }

  function render() {
    const m = mats[state.mat];
    const crumbs = [`<button type="button" data-crumb="mat">${esc(m.name)}</button>`];
    if (state.country) crumbs.push(`<span>›</span><button type="button" data-crumb="country">${named(state.country)}</button>`);
    if (state.input) crumbs.push(`<span>›</span><button type="button" data-crumb="input">${esc(M.inputs[state.input].name)}</button>`);
    $("crumbs").innerHTML = crumbs.join("");
    const body = $("card-body");
    const item = subject();
    const front = state.mode, back = other(front);
    const order = DUAL ? [front, back] : [front];

    if (!state.country) {
      const sections = order.map((mode) => {
        const rows = table(item, mode);
        if (mode === front) {
          return layer(mode, `${modeHead(mode, `<small>${mode === "exports" ? "top exporters" : "top producers"}</small>`)}
            ${rows.length ? bars(rows, mode, DUAL ? weights(back) : null) : `<p class="empty">No ${mode === "exports" ? "export" : "production"} data yet.</p>`}`);
        }
        return layer(mode, `${modeHead(mode, `<small>tap to bring forward</small>`)}
          <div class="chips">${rows.length ? rows.slice(0, 5).map((r) => `<span class="chip" title="${esc(nameOf(r.iso3))}">${flag(r.iso3)}${fmtRow(r)}</span>`).join("") : `<span class="fine">No ${mode === "exports" ? "export" : "production"} data yet</span>`}</div>`);
      }).join("");
      body.innerHTML = `<div class="head">${svg(ICON[m.id])}<div><div class="t">${esc(item.name)}</div><div class="s">${state.input ? `ingredient of ${esc(m.name.toLowerCase())}` : "who makes it, who ships it"}</div></div></div>
        ${state.input ? "" : priceBlock(m)}${sections}${srcLine(item)}`;
    } else {
      const iso = state.country;
      const details = (mode) => (mode === "production" ? madeDetails(m, iso) : shipDetails(item, iso));
      body.innerHTML = `<div class="head">${flag(iso, "big")}<div><div class="t">${esc(nameOf(iso))}</div><div class="s">${esc(item.name)}</div></div>
          <button type="button" class="pill more" data-info="country">${svg(ICON.globe)}<span>More</span></button></div>
        <div class="pair">${order.map((mode) => stat(item, iso, mode)).join("")}</div>
        ${order.map((mode) => layer(mode, `${modeHead(mode, `<small>${mode === "exports" ? "trade flows" : "where its ingredients come from"}</small>`)}${details(mode)}`)).join("")}
        ${srcLine(item)}`;
    }
    body.querySelectorAll("[data-iso]").forEach((b) => b.addEventListener("click", () => pickCountry(b.dataset.iso)));
    body.querySelectorAll("[data-mode-to]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.modeTo)));
    body.querySelectorAll("[data-input]").forEach((b) => b.addEventListener("click", () => {
      state.input = b.dataset.input; update();
      const w = where[state.country]; if (w) globe.pointOfView({ lat: w.lat, lng: w.lng, altitude: 2.8 }, 900);
    }));
    $("crumbs").querySelectorAll("[data-crumb]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.crumb === "mat") { state.country = null; state.input = null; }
      if (b.dataset.crumb === "country") state.input = null;
      update();
    }));
    body.querySelectorAll("[data-info]").forEach(bindInfo);
  }

  function renderRail() {
    $("rail").innerHTML = M.materials.map((m) => {
      const p = priceMove(m.oil);
      return `<button type="button" class="mat" data-mat="${m.id}" aria-pressed="${m.id === state.mat}" title="${esc(m.name)}">${svg(ICON[m.id])}
        <span>${esc(m.short || m.name)}</span><span class="delta ${p ? "" : "none"}">${p ? pct(p.mean) : "?"}</span></button>`;
    }).join("");
    $("rail").querySelectorAll("[data-mat]").forEach((b) => b.addEventListener("click", () => {
      state.mat = b.dataset.mat; state.country = null; state.input = null; update(); flyToTop();
    }));
  }

  function pickCountry(iso) {
    if (iso === state.country) {   // clicking the chosen country again puts it back down
      state.country = null; state.input = null; update(); return;
    }
    state.country = iso;
    state.input = null;
    const w = where[iso];
    if (w) { controls.autoRotate = false; globe.pointOfView({ lat: w.lat, lng: w.lng, altitude: 2.3 }, 900); }
    update();
  }
  // Swing the globe to the biggest producer or exporter of whatever is now in front.
  function flyToTop() {
    const top = table(subject())[0];
    const w = top && where[top.iso3];
    if (w) globe.pointOfView({ lat: Math.max(-40, Math.min(55, w.lat)), lng: w.lng, altitude: 2.4 }, 1100);
  }
  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.mode === mode)));
    update();
    if (!state.country) flyToTop();
  }

  function update() { paint(); render(); renderRail(); }

  // ---------------------------------------------------------------- info sheets
  const URL_RE = /https?:\/\/[^\s;,)|]+/g;
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
  // Source text with each URL shown as a short domain pill that links to the page.
  const linkify = (s) => esc(s).replace(URL_RE, (u) => `<a class="src" href="${u}" target="_blank" rel="noopener" title="${u}">${host(u)}</a>`);
  const urls = (s) => String(s || "").match(URL_RE) || [];
  const KIND = {
    production: { label: "Made", icon: ICON.production, cls: "k-made" },
    exports: { label: "Shipped", icon: ICON.exports, cls: "k-ship" },
    oil: { label: "Oil → price", icon: ICON.oil, cls: "k-oil" },
    note: { label: "Oil exposure", icon: ICON.note, cls: "k-note" },
  };
  const badge = (k) => `<span class="kind ${KIND[k].cls}">${svg(KIND[k].icon)}${KIND[k].label}</span>`;

  function datasets(m) {
    const rows = [{ kind: "production", what: m.name, unit: m.unit, year: m.year, source: m.source }];
    if (m.exports) rows.push({ kind: "exports", what: m.name, unit: m.exports.unit, year: m.exports.year, source: m.exports.source, note: m.exports.note_2026 });
    if (m.oil && m.oil.source) rows.push({ kind: "oil", what: m.oil.series, unit: `${m.oil.horizon}; ${m.oil.interval || ""}`, source: m.oil.source, note: m.oil.disruption ? `Supply-shock range ${m.oil.disruption.lo}–${m.oil.disruption.hi}% per +10% Brent: ${m.oil.disruption.note}` : "" });
    else if (m.oil) rows.push({ kind: "oil", what: "No fitted link yet", unit: m.oil.note || "" });
    for (const id of m.inputs) {
      const i = M.inputs[id];
      if (!i) continue;
      rows.push({ kind: "production", input: i, what: i.name, unit: i.unit, year: i.year, source: i.source });
      if (i.exports) rows.push({ kind: "exports", input: i, what: i.name, unit: i.exports.unit, year: i.exports.year, source: i.exports.source, note: i.exports.note_2026 });
    }
    if (m.oil_notes) rows.push({ kind: "note", what: "How oil reaches it", note: m.oil_notes.notes, source: (m.oil_notes.sources || []).join(" ; ") });
    return rows;
  }
  function allFlows(m) {
    const out = (m.flows || []).map((f) => ({ f, item: m }));
    for (const id of m.inputs) for (const f of (M.inputs[id] && M.inputs[id].flows) || []) out.push({ f, item: M.inputs[id] });
    return out;
  }
  function sourcesHtml() {
    const seen = new Set(), domains = {}, isos = new Set(), years = [];
    const cite = (s) => { for (const u of urls(s)) { if (!seen.has(u)) { seen.add(u); const h = host(u); domains[h] = (domains[h] || 0) + 1; } } };
    for (const m of M.materials) {
      for (const d of datasets(m)) { cite(d.source); if (d.year) years.push(+d.year); }
      for (const l of m.links) { cite(l.source); isos.add(l.to); isos.add(l.from); if (l.year) years.push(+l.year); }
      for (const { f } of allFlows(m)) { cite(f.source); isos.add(f.from); isos.add(f.to); }
      for (const r of [...m.producers, ...((m.exports && m.exports.list) || [])]) isos.add(r.iso3);
    }
    for (const i of Object.values(M.inputs)) for (const r of [...i.producers, ...((i.exports && i.exports.list) || [])]) isos.add(r.iso3);
    const nLinks = M.materials.reduce((a, m) => a + m.links.length, 0);
    const nFlows = M.materials.reduce((a, m) => a + allFlows(m).length, 0);
    const top = Object.entries(domains).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const tmax = top.length ? top[0][1] : 1;

    const tiles = `<div class="tiles">
      <div class="tile"><b>${seen.size}</b><span>source pages</span></div>
      <div class="tile"><b>${isos.size}</b><span>countries</span></div>
      <div class="tile"><b>${nLinks + nFlows}</b><span>supplier links and trade flows</span></div>
      <div class="tile"><b>${Math.min(...years)}–${Math.max(...years)}</b><span>data years</span></div></div>`;
    const callout = `<div class="callout">${svg(ICON.info)}<p>Collected by web search on ${M.generated}. Most primary sites were blocked from our sandbox, so figures are from <b>search-result snippets</b> of the pages cited. <b>≈</b> marks a share we estimated from the table's own ratio; "derived" means our arithmetic; "unconfirmed" is said where it applies. Nothing here is live.</p></div>`;
    const domainBars = `<div class="dom"><h3>Most-cited sites</h3>${top.map(([h, n]) => `<div class="drow"><span class="dn">${h}</span><span class="dt"><span style="width:${n / tmax * 100}%"></span></span><span class="dv">${n}</span></div>`).join("")}</div>`;

    const cards = M.materials.map((m, idx) => {
      const rows = datasets(m).map((d) => `<div class="ds">
        <div class="dsh">${badge(d.kind)}${d.input ? `<span class="dot" style="background:${d.input.color}"></span>` : ""}<b>${esc(d.what)}</b>${d.year ? `<span class="yr">${d.year}</span>` : ""}</div>
        ${d.unit ? `<div class="fine">${esc(d.unit)}</div>` : ""}
        ${d.source ? `<div class="srcs">${linkify(d.source)}</div>` : ""}
        ${d.note ? `<div class="fine note">${linkify(d.note)}</div>` : ""}</div>`).join("");
      const links = m.links.slice().sort((a, b) => (a.to + a.input).localeCompare(b.to + b.input) || b.share - a.share);
      const linkTable = links.length ? `<details class="more"><summary>${svg(ICON.link)} ${links.length} supplier links (the Made arcs)</summary><table>
        <tr><th>Into</th><th>Ingredient</th><th>From</th><th>Share</th><th>Basis</th><th>Year</th><th>Source</th></tr>
        ${links.map((l) => { const i = M.inputs[l.input]; return `<tr><td>${named(l.to)}</td><td><span class="dot" style="background:${i ? i.color : "#e7ecf2"}"></span>${esc(i ? i.name : l.input)}</td><td>${named(l.from)}</td><td class="num">${pctOf(l.share)}</td><td>${esc(l.basis || "")}</td><td>${l.year || ""}</td><td>${linkify(l.source)}</td></tr>`; }).join("")}</table></details>` : "";
      const flows = allFlows(m);
      const flowTable = flows.length ? `<details class="more"><summary>${svg(ICON.exports)} ${flows.length} trade flows (the Shipped arcs)</summary><table>
        <tr><th>Flow</th><th>What</th><th>Detail</th><th>Source</th></tr>
        ${flows.map(({ f, item }) => `<tr><td><span class="cn">${flag(f.from)}→${flag(f.to)}</span></td><td>${esc(item.name)}</td><td>${esc(flowLabel(f, item).split(" · ").slice(1).join(" · "))}${f.note ? ` (${esc(f.note)})` : ""}</td><td>${linkify(f.source)}</td></tr>`).join("")}</table></details>` : "";
      return `<details class="mcard" ${idx === 0 ? "open" : ""}><summary><span class="mi">${svg(ICON[m.id])}</span><span class="mt"><b>${esc(m.name)}</b><small>${datasets(m).length} datasets · ${m.links.length} links · ${flows.length} flows</small></span><span class="chev">${svg('<path d="M6 9l6 6 6-6"/>')}</span></summary>
        <div class="mbody">${rows}${linkTable}${flowTable}</div></details>`;
    }).join("");
    return `${tiles}${callout}<div class="cards">${cards}</div>${domainBars}
      <p class="fine">Coastlines: ${esc(C.source)}. Full notes in <code>notes/materials/</code>; build with <code>uv run experiments/globe_data.py</code>.</p>`;
  }

  // An illustration of the globe itself: raised land, a faded column, rays, and a pulse on the chosen country.
  const HERO = `<svg class="hero-art" viewBox="0 0 360 170" role="img" aria-label="Illustration: countries rise by output, faded columns show exports, and rays link suppliers">
    <defs><radialGradient id="hsea" cx="40%" cy="35%" r="75%"><stop offset="0" stop-color="#16405f"/><stop offset="1" stop-color="#071624"/></radialGradient>
      <radialGradient id="hglow" r="60%"><stop offset=".7" stop-color="#5cb8f0" stop-opacity="0"/><stop offset="1" stop-color="#5cb8f0" stop-opacity=".35"/></radialGradient></defs>
    <g class="stars">${Array.from({ length: 26 }, (_, i) => `<circle cx="${(i * 67) % 360}" cy="${(i * 41) % 170}" r="${i % 3 ? 0.8 : 1.3}"/>`).join("")}</g>
    <circle cx="180" cy="98" r="86" fill="url(#hglow)"/>
    <circle cx="180" cy="98" r="72" fill="url(#hsea)"/>
    <g class="grat"><ellipse cx="180" cy="98" rx="72" ry="24"/><ellipse cx="180" cy="98" rx="30" ry="72"/><path d="M108 98h144"/></g>
    <path class="land" d="M128 70c10-8 26-6 32 2s-4 18-14 20-24-12-18-22z"/>
    <path class="land up" d="M188 62c14-6 34 0 38 12s-8 22-22 22-28-8-26-18 2-12 10-16z"/>
    <path class="land up side" d="M188 62c14-6 34 0 38 12l0 6c-4-12-24-18-38-12z"/>
    <path class="land" d="M150 118c8-4 20-2 22 6s-8 14-16 12-14-12-6-18z"/>
    <path class="land" d="M222 116c6-3 16 0 16 7s-8 10-14 8-8-12-2-15z"/>
    <rect class="col" x="146" y="40" width="7" height="34" rx="2"/>
    <rect class="col" x="226" y="94" width="6" height="26" rx="2"/>
    <path class="ray made" d="M160 122C170 70 190 60 206 76"/>
    <path class="ray made2" d="M230 120C238 90 224 80 210 80"/>
    <path class="ray ship" d="M206 76C220 30 290 30 306 60"/>
    <circle class="pulse" cx="206" cy="78" r="6"/><circle class="pulse p2" cx="206" cy="78" r="6"/>
    <circle cx="206" cy="78" r="3" fill="#ffe2b0"/>
    <circle cx="306" cy="60" r="3" fill="#8fd0f5"/>
  </svg>`;
  const step = (n, art, title, text) => `<div class="step"><div class="art">${art}</div><div><span class="n">${n}</span><b>${title}</b><p>${text}</p></div></div>`;
  function aboutHtml() {
    const chain = M.materials.map((m) => {
      const p = priceMove(m.oil);
      return `<div class="link"><span class="mi">${svg(ICON[m.id])}</span><b class="${p ? "" : "none"}">${p ? pct(p.mean) : "?"}</b><span>${esc(m.short)}</span></div>`;
    }).join("");
    return `<div class="hero">${HERO}<div class="hero-t"><b>Where things are made, where they ship, and what oil does to their price</b><span>Five oil-exposed materials and their ingredients, from published sources.</span></div></div>
      <div class="steps">
        ${step(1, `<div class="minirail">${["steel", "jet_fuel", "aluminium"].map((k, i) => `<span class="${i === 1 ? "on" : ""}">${svg(ICON[k])}</span>`).join("")}</div>`, "Pick a material", "Countries rise and glow by their share of world output.")}
        ${step(2, `<div class="minimodes"><span class="on">${svg(ICON.production)}</span><span class="off">${svg(ICON.exports)}</span></div>`, "Made and Shipped together", "The layer in front is bright. The other is faded: see-through columns and thin rays. Tap either to swap.")}
        ${step(3, `<svg viewBox="0 0 80 48" class="mini"><circle cx="58" cy="30" r="5" fill="#ffe2b0"/><circle class="pulse" cx="58" cy="30" r="5"/><path class="ray made" d="M12 36C18 8 44 6 56 28"/><circle cx="12" cy="36" r="3" fill="#e07a5f"/></svg>`, "Click a country", "Rays fly in from where its ingredients come from, and out to where it ships. Click it again to put it back down.")}
        ${step(4, `<svg viewBox="0 0 80 48" class="mini"><circle cx="40" cy="24" r="16" fill="none" stroke="#a3afbd" stroke-width="2"/><path d="M24 24h32M40 8c6 6 6 26 0 32c-6-6-6-26 0-32" fill="none" stroke="#a3afbd" stroke-width="2"/><circle cx="62" cy="10" r="7" fill="#172231" stroke="#f0a23b" stroke-width="2"/><path d="M62 6v8M58 10h8" stroke="#f0a23b" stroke-width="2"/></svg>`, "Open an ingredient", "The globe button on an ingredient re-colours the world by who makes and ships it, for example Guinea's bauxite.")}
      </div>
      <div class="chain"><div class="brent">${svg(ICON.oil)}<b>${pct(state.brent)}</b><span>Brent</span></div><span class="arrow">${svg('<path d="M4 12h14M13 6l6 6-6 6"/>')}</span><div class="links">${chain}</div></div>
      <p>Prices are the 12-month response from the team's Bayesian pass-through model: rises use the +10% response and falls the −10% one, scaled in log terms. The band is the 90% interval of the <b>average</b> effect, so single moves vary more. "?" means no fitted link yet. Jet fuel's supply-shock range comes from past disruptions (OXH-4).</p>
      <p class="fine">Coastlines: ${esc(C.source)}. Every figure is from a published source with its year; nothing here is live.</p>`;
  }

  // ---------------------------------------------------------------- country sheet: everything we hold on one country
  function countryFacts(iso) {
    const out = [];
    for (const m of M.materials) {
      const roles = [];
      const role = (item, mode) => {
        const rows = table(item, mode), i = rows.findIndex((r) => r.iso3 === iso);
        if (i >= 0) roles.push({ item, mode, r: rows[i], rank: i + 1, of: rows.length });
      };
      role(m, "production"); role(m, "exports");
      for (const id of m.inputs) if (M.inputs[id]) { role(M.inputs[id], "production"); role(M.inputs[id], "exports"); }
      const into = m.links.filter((l) => l.to === iso);
      const supplies = m.links.filter((l) => l.from === iso && l.to !== iso);
      const flows = allFlows(m).filter(({ f }) => f.from === iso || f.to === iso);
      if (roles.length || into.length || supplies.length || flows.length) out.push({ m, roles, into, supplies, flows });
    }
    return out;
  }
  function countryHtml(iso) {
    const facts = countryFacts(iso);
    const partners = new Set();
    for (const x of facts) {
      for (const l of x.into) if (l.from !== iso) partners.add(l.from);
      for (const l of x.supplies) partners.add(l.to);
      for (const { f } of x.flows) partners.add(f.from === iso ? f.to : f.from);
    }
    const tiles = `<div class="tiles">
      <div class="tile"><b>${facts.length}<small>/${M.materials.length}</small></b><span>materials it shows up in</span></div>
      <div class="tile"><b>${facts.reduce((a, x) => a + x.roles.filter((r) => r.mode === "production").length, 0)}</b><span>top-producer listings</span></div>
      <div class="tile"><b>${facts.reduce((a, x) => a + x.roles.filter((r) => r.mode === "exports").length, 0)}</b><span>top-exporter listings</span></div>
      <div class="tile"><b>${partners.size}</b><span>trade partners linked</span></div></div>`;
    const partnerRow = partners.size ? `<div class="partners">${[...partners].map((p) => `<button type="button" class="chip" data-go="${p}" title="${esc(nameOf(p))}">${flag(p)}</button>`).join("")}</div>` : "";
    const cards = facts.map((x) => {
      const roles = x.roles.map(({ item, mode, r, rank, of }) => `<div class="role ${mode}">${svg(ICON[mode])}
          <span class="rw"><b>${fmtRow(r)}</b> ${r.share != null ? `of world ${mode === "exports" ? "exports" : "output"}` : esc(unitOf(item, mode))}</span>
          <span class="rn">${esc(item.name)}</span><span class="rank">#${rank}<small> of ${of} listed</small></span></div>`).join("");
      const linkChips = (ls, side) => ls.map((l) => {
        const i = M.inputs[l.input], p = side === "from" ? l.from : l.to;
        return `<span class="chip ${p === iso ? "dom" : ""}" title="${esc(l.basis || "")} · ${l.year || ""}"><span class="dot" style="background:${i ? i.color : "#e7ecf2"}"></span>${flag(p)}${esc(i ? i.name : l.input)} ${pctOf(l.share)}</span>`;
      }).join("");
      return `<div class="ccard"><div class="ch"><span class="mi">${svg(ICON[x.m.id])}</span><b>${esc(x.m.name)}</b></div>
        ${roles}
        ${x.into.length ? `<div class="cl"><span class="fine">Its ingredients come from</span><div class="chips">${linkChips(x.into, "from")}</div></div>` : ""}
        ${x.supplies.length ? `<div class="cl"><span class="fine">It supplies ingredients to</span><div class="chips">${linkChips(x.supplies, "to")}</div></div>` : ""}
        ${x.flows.length ? `<div class="cl"><span class="fine">Trade flows</span><div class="chips">${x.flows.map(({ f, item }) => `<span class="chip ship" title="${esc(flowLabel(f, item))}">${flag(f.from)}→${flag(f.to)} ${esc(item.name)}</span>`).join("")}</div></div>` : ""}
      </div>`;
    }).join("");
    const brief = BRIEF ? `<div class="brief" id="brief"><div class="bh">${svg('<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>')}<b>AI brief</b><span class="fine">Gemini with Google Search, written on request</span></div>
        <button type="button" class="pill go-brief" id="brief-go">Write a brief on ${esc(nameOf(iso))}</button><div id="brief-out"></div></div>` : "";
    return `<div class="chero">${flag(iso, "huge")}<div><b>${esc(nameOf(iso))}</b><span>${facts.length ? `In our data for ${facts.map((x) => esc(x.m.short)).join(", ")}` : "Not in our sourced tables yet"}</span></div></div>
      ${tiles}${partnerRow}${brief}<div class="ccards">${cards || `<p class="empty">No sourced rows mention ${esc(nameOf(iso))}.</p>`}</div>
      <p class="fine">Every row above is from the sourced tables (see Sources).${BRIEF ? " The AI brief is not: it is written by a language model and must be checked before quoting." : ""}</p>`;
  }
  // Ask the local Gemini proxy for a short brief, giving it our sourced rows as the facts to start from.
  async function writeBrief(iso) {
    const out = $("brief-out"), btn = $("brief-go");
    btn.disabled = true;
    out.innerHTML = `<p class="fine">Writing…</p>`;
    const facts = [];
    for (const x of countryFacts(iso)) {
      for (const { item, mode, r } of x.roles) facts.push(`${item.name}, ${mode === "exports" ? "exports" : "production"}: ${fmtRow(r)}${r.share == null ? ` ${unitOf(item, mode)}` : " of world"} (${(mode === "exports" ? item.exports : item).year}; ${urls((mode === "exports" ? item.exports : item).source)[0] || "see notes"})`);
      for (const l of x.into) facts.push(`${x.m.name}: ${pctOf(l.share)} of ${nameOf(iso)}'s ${(M.inputs[l.input] || {}).name || l.input} from ${nameOf(l.from)} (${l.basis}; ${l.year}; ${urls(l.source)[0] || ""})`);
    }
    try {
      const res = await fetch(`${BRIEF}/brief`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ iso3: iso, country: nameOf(iso), material: mats[state.mat].name, facts }) });
      const b = await res.json();
      if (!res.ok) throw new Error(b.error || res.statusText);
      const when = new Date(b.generated_at).toLocaleString();
      out.innerHTML = `<div class="btext">${esc(b.text).replace(/^\s*[*-]\s+/gm, "• ").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")}</div>
        ${b.sources && b.sources.length ? `<div class="srcs">${b.sources.map((x) => `<a class="src" href="${esc(x.uri)}" target="_blank" rel="noopener" title="${esc(x.uri)}">${esc(x.title || host(x.uri))}</a>`).join("")}</div>` : ""}
        <p class="fine warn">AI-written by ${esc(b.model)}${b.cached ? `, cached, written ${esc(when)}` : `, ${esc(when)}`}. Not checked by the team: verify before quoting.</p>`;
    } catch (e) {
      out.innerHTML = `<p class="fine warn">No brief: ${esc(e.message || e)}. Is <code>uv run experiments/country_brief.py</code> running with a GEMINI_API_KEY?</p>`;
      btn.disabled = false;
    }
  }
  const INFO = {
    about: () => ({ title: "Materials Globe", wide: true, html: aboutHtml() }),
    country: () => ({ title: nameOf(state.country), wide: true, html: countryHtml(state.country), after: () => {
      $("sheet-body").querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => { $("sheet").hidden = true; pickCountry(b.dataset.go); }));
      const go = $("brief-go"); if (go) go.addEventListener("click", () => writeBrief(state.country));
    } }),
    sources: () => ({ title: "Sources", wide: true, html: `<p class="lede">Every number on the globe, where it came from and when.</p>${sourcesHtml()}` }),
  };
  function bindInfo(b) {
    b.addEventListener("click", () => {
      const i = INFO[b.dataset.info]();
      $("sheet-title").textContent = i.title;
      $("sheet-body").innerHTML = i.html;
      $("sheet").classList.toggle("wide", !!i.wide);
      $("sheet").hidden = false;
      if (i.after) i.after();
      $("sheet").scrollTop = 0;
    });
  }
  document.querySelectorAll("[data-info]").forEach(bindInfo);
  $("sheet-close").addEventListener("click", () => { $("sheet").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("sheet").hidden = true; });

  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("brent").addEventListener("input", (e) => {
    state.brent = Number(e.target.value);
    $("brent-label").textContent = pct(state.brent);
    render(); renderRail();
  });

  update();
})();
