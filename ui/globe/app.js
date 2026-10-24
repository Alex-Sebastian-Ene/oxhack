// Materials Globe: click a material to see who makes or ships it; click a country to see where its
// ingredients come from; drag Brent to see the modelled price change. Data: data/materials.js,
// written by `uv run experiments/globe_data.py` from the sourced tables in notes/materials/.
(() => {
  const M = window.MATERIALS;
  const C = window.COUNTRIES;
  const $ = (id) => document.getElementById(id);
  const svg = (p) => `<svg viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`;
  const ICON = {
    steel: '<path d="M5 4h14M5 20h14M12 4v16"/><path d="M8 4v2M16 4v2M8 18v2M16 18v2"/>',
    jet_fuel: '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/>',
    aluminium: '<path d="M7 4h10l-1 16H8z"/><path d="M7.4 8h9.2"/>',
    fertiliser: '<path d="M12 21v-8"/><path d="M12 13C12 8 8 6 4 6c0 4 3 7 8 7z"/><path d="M12 11c0-4 3-6 8-6 0 4-3 6-8 6z"/>',
    polyethylene: '<path d="M10 2h4v3l2 3v12a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8l2-3z"/><path d="M8 12h8"/>',
  };
  const COL = { land: [42, 52, 66], made: [240, 162, 59], ship: [92, 184, 240], sea: "#0b2236" };

  // ---------------------------------------------------------------- lookups
  const where = {};
  for (const f of C.features) where[f.properties.iso3] = { name: f.properties.name, lat: f.properties.lat, lng: f.properties.lng };
  for (const [k, p] of Object.entries(C.points)) where[k] = p;
  const nameOf = (iso) => (where[iso] && where[iso].name) || iso;
  const mats = Object.fromEntries(M.materials.map((m) => [m.id, m]));

  const state = { mat: M.materials[0].id, mode: "production", country: null, input: null, brent: 60 };

  // What the globe is coloured by right now: the material, or one of its inputs.
  function subject() {
    const m = mats[state.mat];
    return state.input ? M.inputs[state.input] : m;
  }
  function table(item) {
    if (state.mode === "exports") return (item.exports && item.exports.list) || [];
    return item.producers || [];
  }
  // Colouring weight per country (share of world, or relative size when no shares exist).
  function shares() {
    return Object.fromEntries(table(subject()).map((r) => [r.iso3, r.w]));
  }
  const hasShares = () => table(subject()).some((r) => r.share != null);
  function unitOf(item) { return state.mode === "exports" ? (item.exports && item.exports.unit) || "" : item.unit || ""; }
  function fmtRow(r, item) {
    if (r.share != null) return `${r.approx ? "≈" : ""}${(r.share * 100).toFixed(r.share < 0.1 ? 1 : 0)}%`;
    return `${r.value}`;
  }

  // ---------------------------------------------------------------- oil price maths
  // Rises use the +10% row and falls the -10% row (they differ), scaled in log terms.
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
    .arcDashLength(0.45).arcDashGap(0.25).arcDashAnimateTime(2200).arcAltitudeAutoScale(0.45)
    .pointAltitude(0.02).pointRadius(0.6)
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

  function mix(t) {
    const hi = state.mode === "exports" ? COL.ship : COL.made;
    const c = COL.land.map((v, i) => Math.round(v + (hi[i] - v) * t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }
  function paint() {
    const s = shares();
    const max = Math.max(...Object.values(s), 0.01);
    const sel = state.country;
    globe
      .polygonCapColor((f) => {
        const v = s[f.properties.iso3] || 0;
        if (f.properties.iso3 === sel) return "#ffe2b0";
        return v ? mix(0.25 + 0.75 * Math.sqrt(v / max)) : mix(0);
      })
      .polygonAltitude((f) => {
        const v = s[f.properties.iso3] || 0;
        return 0.006 + (v ? 0.12 * Math.sqrt(v / max) : 0) + (f.properties.iso3 === sel ? 0.03 : 0);
      });
    // small producers have no polygon at this scale: show them as pins
    const pins = Object.entries(C.points).filter(([k]) => s[k]).map(([iso3, p]) => ({ iso3, lat: p.lat, lng: p.lng, share: s[iso3] }));
    globe.pointsData(pins).pointColor(() => (state.mode === "exports" ? "#8fd0f5" : "#f5bd6e"))
      .pointAltitude((p) => 0.02 + 0.12 * Math.sqrt(p.share / max));
    drawArcs();
    legend(max);
    const w = sel && where[sel];
    globe.ringsData(w ? [{ lat: w.lat, lng: w.lng }] : [])
      .ringColor(() => (t) => `rgba(255,226,176,${1 - t})`).ringMaxRadius(6).ringPropagationSpeed(2.5).ringRepeatPeriod(1100);
  }

  function drawArcs() {
    const m = mats[state.mat];
    let arcs = [];
    const arc = (from, to, color, weight, label) => {
      const a = where[from], b = where[to];
      if (!a || !b || from === to) return;
      arcs.push({ startLat: a.lat, startLng: a.lng, endLat: b.lat, endLng: b.lng, color, weight, label });
    };
    if (state.mode === "production") {
      if (state.country) {
        for (const l of m.links.filter((l) => l.to === state.country && (!state.input || l.input === state.input))) {
          const inp = M.inputs[l.input];
          arc(l.from, l.to, inp ? inp.color : "#ffffff", l.share, `${inp ? inp.name : l.input}: ${nameOf(l.from)} → ${nameOf(l.to)} ${Math.round(l.share * 100)}%`);
        }
      }
    } else {
      const item = subject();
      const flows = (item.flows || []).filter((f) => !state.country || f.from === state.country || f.to === state.country);
      const maxv = Math.max(...flows.map((f) => f.value || 0), 1);
      for (const f of flows.slice(0, 14)) arc(f.from, f.to, "#8fd0f5", (f.value || 0) / maxv, `${nameOf(f.from)} → ${nameOf(f.to)}${f.value ? ` · ${f.value} ${item.exports ? item.exports.unit : ""}` : ""}`);
    }
    globe.arcsData(arcs)
      .arcColor((d) => [d.color + "33", d.color])
      .arcStroke((d) => 0.25 + 1.4 * Math.sqrt(d.weight || 0.1))
      .arcLabel((d) => d.label);
  }

  function legend(max) {
    const lo = mix(0.25), hi = mix(1);
    const right = hasShares() ? `${Math.round(max * 100)}% of world` : `largest listed (${unitOf(subject())})`;
    $("legend").innerHTML = `<span>low</span><span class="ramp" style="background:linear-gradient(90deg,${lo},${hi})"></span><span>${right}</span>`;
  }

  const tip = $("tip");
  let mouse = [0, 0];
  window.addEventListener("pointermove", (e) => { mouse = [e.clientX, e.clientY]; tip.style.left = `${mouse[0] + 14}px`; tip.style.top = `${mouse[1] + 14}px`; });
  function hover(f) {
    if (!f) { tip.hidden = true; return; }
    const iso = f.properties.iso3;
    const r = table(subject()).find((x) => x.iso3 === iso);
    tip.innerHTML = `${nameOf(iso)} <b>${r ? fmtRow(r) + (r.share == null ? " " + unitOf(subject()) : "") : "–"}</b>`;
    tip.hidden = false;
  }

  // ---------------------------------------------------------------- side card
  function bars(rows, color) {
    const max = Math.max(...rows.map((r) => r.w), 0.01);
    return `<div class="bars">${rows.slice(0, 7).map((r) => `<button type="button" data-iso="${r.iso3}" title="${nameOf(r.iso3)}">
      <span class="iso">${r.iso3}</span><span class="track"><span class="fill" style="display:block;width:${r.w / max * 100}%;background:${color}"></span></span>
      <span class="v">${fmtRow(r)}</span></button>`).join("")}</div>`;
  }
  function priceBlock(m) {
    const p = priceMove(m.oil);
    if (!p) return `<div class="price">${svg(ICON[m.id])}<div><b class="none">?</b><small>No fitted oil link yet${m.oil && m.oil.note ? ` · ${m.oil.note}` : ""}</small></div></div>`;
    const d = shockRange(m.oil);
    return `<div class="price"><div><b>${pct(p.mean)}</b><small>price in 12 months if Brent ${pct(state.brent)} · 90%: ${pct(p.lo)} to ${pct(p.hi)}${m.oil.validated ? "" : " · not validated"}</small>
      ${d ? `<small>supply shock: ${pct(d.lo)} to ${pct(d.hi)}</small>` : ""}</div></div>`;
  }

  function render() {
    const m = mats[state.mat];
    const color = state.mode === "exports" ? "var(--ship)" : "var(--made)";
    // breadcrumbs
    const crumbs = [`<button type="button" data-crumb="mat">${m.name}</button>`];
    if (state.country) crumbs.push(`<span>›</span><button type="button" data-crumb="country">${nameOf(state.country)}</button>`);
    if (state.input) crumbs.push(`<span>›</span><button type="button" data-crumb="input">${M.inputs[state.input].name}</button>`);
    $("crumbs").innerHTML = crumbs.join("");
    const body = $("card-body");
    const item = subject();
    const rows = table(item);
    const src = state.mode === "exports" ? item.exports : item;
    const srcLine = src ? `<p class="fine">${src.unit || ""} · ${src.year || ""} · <button type="button" class="ib" data-info="sources" aria-label="Sources" style="width:22px;min-height:22px">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.5"/>')}</button></p>` : "";

    if (!state.country) {
      body.innerHTML = `<div class="head">${svg(ICON[m.id])}<div><div class="t">${item.name}</div><div class="s">${state.mode === "exports" ? "Top exporters" : "Top producers"}</div></div></div>
        ${state.input ? "" : priceBlock(m)}
        ${rows.length ? bars(rows, color) : `<p class="empty">No ${state.mode === "exports" ? "export" : "production"} data yet.</p>`}
        ${srcLine}`;
    } else {
      const iso = state.country;
      const row = rows.find((r) => r.iso3 === iso);
      const big = !row ? "–" : fmtRow(row);
      const sub = !row ? `not among the listed ${state.mode === "exports" ? "exporters" : "producers"}` : row.share != null ? `of world ${state.mode === "exports" ? "exports" : "output"}` : unitOf(item);
      let inner = `<div class="head"><span class="chip">${iso}</span><div><div class="t">${nameOf(iso)}</div><div class="s">${item.name}</div></div></div>
        <div class="big ${state.mode === "exports" ? "ship" : "made"}"><b>${big}</b><span>${sub}</span></div>`;
      if (state.mode === "production") {
        const ins = (state.input ? [state.input] : m.inputs).map((id) => M.inputs[id]).filter(Boolean);
        inner += `<div class="inputs">${ins.map((inp) => {
          const ls = m.links.filter((l) => l.to === iso && l.input === inp.id).sort((a, b) => b.share - a.share);
          const chips = ls.length ? ls.slice(0, 6).map((l) => `<span class="chip ${l.from === iso ? "dom" : ""}" title="${l.basis || ""} (${l.year || ""})">${l.from} ${Math.round(l.share * 100)}%</span>`).join("")
            : `<span class="fine">No sourced supplier split</span>`;
          return `<div class="input"><div class="top"><span class="name"><span class="dot" style="background:${inp.color}"></span>${inp.name}</span>
            ${state.input || !(inp.producers.length || (inp.exports && inp.exports.list.length)) ? "" : `<button type="button" class="go" data-input="${inp.id}" aria-label="Show where ${inp.name} is produced">${svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3 3 15 0 18c-3-3-3-15 0-18z"/>')}</button>`}</div>
            <div class="chips">${chips}</div></div>`;
        }).join("")}</div>`;
        if (state.input) inner += `<p class="fine">Globe: who produces ${M.inputs[state.input].name.toLowerCase()} worldwide. Arcs: what reaches ${nameOf(iso)}.</p>`;
      } else {
        const flows = (item.flows || []).filter((f) => f.from === iso || f.to === iso);
        inner += flows.length ? `<div class="chips">${flows.map((f) => `<span class="chip">${f.from} → ${f.to}${f.value ? ` ${f.value}` : ""}</span>`).join("")}</div>`
          : `<p class="empty">No sourced flows for ${nameOf(iso)}.</p>`;
      }
      body.innerHTML = inner + srcLine;
    }
    body.querySelectorAll("[data-iso]").forEach((b) => b.addEventListener("click", () => pickCountry(b.dataset.iso)));
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
      return `<button type="button" class="mat" data-mat="${m.id}" aria-pressed="${m.id === state.mat}" title="${m.name}">${svg(ICON[m.id])}
        <span>${m.short || m.name}</span><span class="delta ${p ? "" : "none"}">${p ? pct(p.mean) : "?"}</span></button>`;
    }).join("");
    $("rail").querySelectorAll("[data-mat]").forEach((b) => b.addEventListener("click", () => {
      state.mat = b.dataset.mat; state.country = null; state.input = null; update(); flyToTop();
    }));
  }

  function pickCountry(iso) {
    state.country = iso;
    state.input = null;
    const w = where[iso];
    if (w) { controls.autoRotate = false; globe.pointOfView({ lat: w.lat, lng: w.lng, altitude: 2.3 }, 900); }
    update();
  }
  // Swing the globe to the biggest producer or exporter of whatever is now shown.
  function flyToTop() {
    const top = table(subject())[0];
    const w = top && where[top.iso3];
    if (w) globe.pointOfView({ lat: Math.max(-40, Math.min(55, w.lat)), lng: w.lng, altitude: 2.4 }, 1100);
  }

  function update() { paint(); render(); renderRail(); }

  // ---------------------------------------------------------------- info sheets
  function sourcesHtml() {
    const rows = [];
    for (const m of M.materials) {
      rows.push([m.name, "production", m.year, m.source]);
      if (m.exports) rows.push([m.name, "exports", m.exports.year, m.exports.source]);
      if (m.oil && m.oil.source) rows.push([m.name, "oil → price", m.oil.horizon || "", `${m.oil.series}. ${m.oil.source}`]);
    }
    for (const i of Object.values(M.inputs)) {
      rows.push([i.name, "production", i.year, i.source]);
      if (i.exports) rows.push([i.name, "exports", i.exports.year, i.exports.source]);
    }
    const link = (s) => String(s || "").split(/\s*;\s*/).map((u) => (u.startsWith("http") ? `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48)}</a>` : u)).join("<br>");
    return `<table><tr><th>Data</th><th>What</th><th>Year</th><th>Source</th></tr>${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2] || ""}</td><td>${link(r[3])}</td></tr>`).join("")}</table>
      <p>Supplier links (the arcs) cite their own source and year on hover. Collected ${M.generated}; full notes in <code>notes/materials/</code>.</p>`;
  }
  const INFO = {
    about: () => ({ title: "Materials Globe", html: `<p>Pick a material on the left. Countries rise and glow by their share of world output (<b>Made</b>) or exports (<b>Shipped</b>). Click a country to see where its ingredients come from, then the ${svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>')} button on an ingredient to see who makes that.</p>
      <p>The Brent slider scales each material's 12-month price response from the team's Bayesian pass-through model: rises use the +10% response and falls the −10% one, scaled in log terms, with the 90% interval. "?" means no fitted link yet. Supply-shock ranges come from past disruptions (OXH-4).</p>
      <p>Coastlines: ${C.source}. Every figure is from a published source with its year; nothing here is live.</p>` }),
    sources: () => ({ title: "Sources", html: sourcesHtml() }),
  };
  function bindInfo(b) {
    b.addEventListener("click", () => {
      const i = INFO[b.dataset.info]();
      $("sheet-title").textContent = i.title;
      $("sheet-body").innerHTML = i.html;
      $("sheet").hidden = false;
    });
  }
  document.querySelectorAll("[data-info]").forEach(bindInfo);
  $("sheet-close").addEventListener("click", () => { $("sheet").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("sheet").hidden = true; });

  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    state.mode = b.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    update();
    if (!state.country) flyToTop();
  }));
  $("brent").addEventListener("input", (e) => {
    state.brent = Number(e.target.value);
    $("brent-label").textContent = pct(state.brent);
    render(); renderRail();
  });

  update();
})();
