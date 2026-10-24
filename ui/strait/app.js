// Hormuz Flow: zoomable, animated map of tankers crossing the strait, with the flow estimate beside it.
// Data comes from data/scenarios.js, written by `uv run experiments/strait_flow.py`.
(() => {
  const D = window.STRAIT;
  const geo = D.geo;
  const KM_LAT = 111.32;
  const KX = KM_LAT * Math.cos(26.4 * Math.PI / 180);
  const COL = { seen: "#5cb8f0", oil: "#f0a23b", oilSoft: "#f5bd6e", sea: "#0b2236", land: "#2a3442",
    landEdge: "#3d4b5c", lane: "rgba(143,208,245,0.13)", text: "#c4cdd8", faint: "#7d8b9b", white: "#e7ecf2", other: "#7d8b9b" };
  const ISO = { Panama: "PA", Liberia: "LR", "Marshall Islands": "MH", Malta: "MT", Greece: "GR", Bahamas: "BS",
    Singapore: "SG", "Hong Kong": "HK", UAE: "AE", Iran: "IR", Comoros: "KM", Cameroon: "CM", Gabon: "GA",
    Guinea: "GN", "Netherlands Antilles": "AN", Guyana: "GY", Aruba: "AW", Oman: "OM", "Saudi Arabia": "SA",
    Qatar: "QA", Kuwait: "KW", India: "IN", China: "CN", Russia: "RU", "Cook Islands": "CK", Palau: "PW",
    "Sierra Leone": "SL", Tanzania: "TZ", Vanuatu: "VU", "St Kitts and Nevis": "KN", Cyprus: "CY" };
  // Commonly known symbols for each warning sign (stroke paths in a 24 x 24 box).
  const ICON = {
    radar_only: '<path d="M4 10l6-6 4 4-6 6z"/><path d="M14 14l6-6"/><path d="M12 16l4 4"/><path d="M3 21c2-4 4-6 7-7"/>',
    ais_gap: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><path d="M4 4l16 16"/>',
    spoofing: '<circle cx="12" cy="12" r="7"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    sanctioned: '<circle cx="12" cy="12" r="9"/><path d="M6 6l12 12"/>',
    false_flag: '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/><path d="M15 16l5 5M20 16l-5 5"/>',
    bad_imo: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h4M7 14h6"/><path d="M15 9l4 4M19 9l-4 4"/>',
    flag_mismatch: '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>',
    flag_hops: '<path d="M4 9h13l-3-3"/><path d="M20 15H7l3 3"/>',
    old: '<path d="M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9"/>',
    opaque_owner: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    sts: '<path d="M2 9h8l-2 3H4z"/><path d="M14 15h8l-2 3h-4z"/><path d="M10 12l4 2"/>',
    for_orders: '<path d="M9 9a3 3 0 1 1 4 3c-1 .5-1 1-1 2"/><path d="M12 18v.5"/>',
  };
  const svg = (paths) => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;

  // ---------------------------------------------------------------- lanes (same maths as Python)
  function makeLane(points) {
    const cum = [0];
    for (let i = 1; i < points.length; i++) {
      const [ax, ay] = points[i - 1], [bx, by] = points[i];
      cum.push(cum[i - 1] + Math.hypot((bx - ax) * KX, (by - ay) * KM_LAT));
    }
    const length = cum[cum.length - 1];
    function at(s) {
      s = Math.min(Math.max(s, 0), length);
      let i = 0;
      while (i < cum.length - 2 && cum[i + 1] < s) i++;
      const f = (s - cum[i]) / (cum[i + 1] - cum[i]);
      const [ax, ay] = points[i], [bx, by] = points[i + 1];
      return [ax + f * (bx - ax), ay + f * (by - ay)];
    }
    function sAtLon(lon) {
      for (let i = 0; i < points.length - 1; i++) {
        const a = points[i], b = points[i + 1];
        if (Math.min(a[0], b[0]) <= lon && lon <= Math.max(a[0], b[0]))
          return cum[i] + (lon - a[0]) / (b[0] - a[0]) * (cum[i + 1] - cum[i]);
      }
      return NaN;
    }
    return { points, length, at, sAtLon };
  }
  const lanes = { outbound: makeLane(geo.lanes.outbound), inbound: makeLane(geo.lanes.inbound.slice().reverse()) };
  const gateLon = geo.gate[0][0];

  // ---------------------------------------------------------------- state
  const $ = (id) => document.getElementById(id);
  const wrap = document.querySelector(".mapwrap");
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [B0, B1, B2, B3] = geo.bbox;
  const home = { z: 1, cx: (B0 + B2) / 2, cy: (B1 + B3) / 2 };
  const state = { key: "aug2026", view: "truth", t: 15, playing: !reduceMotion, speed: 1, selected: null, last: 0, ...home };
  let sc = null, ships = [], view = null;

  function load(key) {
    state.key = key;
    sc = D.scenarios[key];
    ships = sc.ships.map((v) => ({ ...v, laneObj: lanes[v.lane], tGate: v.t0 + lanes[v.lane].sAtLon(gateLon) / v.speed_kmh }));
    select(null);
    renderMetrics();
  }

  // ---------------------------------------------------------------- projection with zoom and pan
  function fit() {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    view = { w, h, s0: Math.min(w / ((B2 - B0) * KX), h / ((B3 - B1) * KM_LAT)) };
  }
  const scale = () => view.s0 * state.z;
  const P = (lon, lat) => [view.w / 2 + (lon - state.cx) * KX * scale(), view.h / 2 - (lat - state.cy) * KM_LAT * scale()];
  const unP = (x, y) => [state.cx + (x - view.w / 2) / (KX * scale()), state.cy - (y - view.h / 2) / (KM_LAT * scale())];
  function clampCenter() {
    state.cx = Math.min(Math.max(state.cx, B0), B2);
    state.cy = Math.min(Math.max(state.cy, B1), B3);
  }
  function zoomAt(factor, x = view.w / 2, y = view.h / 2) {
    const [lon, lat] = unP(x, y);
    state.z = Math.min(Math.max(state.z * factor, 1), 12);
    // keep the point under the cursor fixed
    state.cx = lon - (x - view.w / 2) / (KX * scale());
    state.cy = lat + (y - view.h / 2) / (KM_LAT * scale());
    clampCenter();
  }

  // ---------------------------------------------------------------- ship state at time t
  function shipAt(v, t) {
    const s = (t - v.t0) * v.speed_kmh;
    if (s < 0 || s > v.laneObj.length) return null;
    const [lon, lat] = v.laneObj.at(s);
    const [lon2, lat2] = v.laneObj.at(s + 2);
    const aisOn = v.ais_mode === "on" || v.ais_mode === "spoof" ||
      (v.ais_mode === "gap" && !(v.gap_km[0] <= s && s <= v.gap_km[1]));
    return { s, lon, lat, heading: Math.atan2(-(lat2 - lat) * KM_LAT, (lon2 - lon) * KX), aisOn };
  }

  // ---------------------------------------------------------------- drawing
  function path(points) {
    ctx.beginPath();
    points.forEach(([lon, lat], i) => (i ? ctx.lineTo(...P(lon, lat)) : ctx.moveTo(...P(lon, lat))));
  }
  function drawBase() {
    ctx.fillStyle = COL.sea;
    ctx.fillRect(0, 0, view.w, view.h);
    ctx.fillStyle = COL.land;
    ctx.strokeStyle = COL.landEdge;
    ctx.lineWidth = 1;
    for (const poly of geo.land.coordinates) {
      ctx.beginPath();
      for (const ring of poly) {
        ring.forEach(([lon, lat], i) => (i ? ctx.lineTo(...P(lon, lat)) : ctx.moveTo(...P(lon, lat))));
        ctx.closePath();
      }
      ctx.fill("evenodd");
      ctx.stroke();
    }
    ctx.strokeStyle = COL.lane;
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(5, 3.2 * scale());
    for (const lane of Object.values(lanes)) { path(lane.points); ctx.stroke(); }
    // direction arrows along each lane
    ctx.fillStyle = "rgba(143,208,245,0.35)";
    for (const lane of Object.values(lanes)) {
      for (let s = 30; s < lane.length; s += 70) {
        const [a, b] = lane.at(s), [c, d] = lane.at(s + 1);
        const [x, y] = P(a, b), [x2, y2] = P(c, d);
        ctx.save(); ctx.translate(x, y); ctx.rotate(Math.atan2(y2 - y, x2 - x));
        ctx.beginPath(); ctx.moveTo(5, 0); ctx.lineTo(-3, 4); ctx.lineTo(-3, -4); ctx.closePath(); ctx.fill();
        ctx.restore();
      }
    }
    ctx.setLineDash([6, 5]);
    ctx.strokeStyle = "rgba(231,236,242,0.55)";
    ctx.lineWidth = 1.5;
    path(geo.gate); ctx.stroke();
    ctx.setLineDash([]);
    for (const p of geo.places) {
      if (p.kind === "port" && state.z < 2) continue;
      const [x, y] = P(p.lon, p.lat);
      if (x < -50 || y < -20 || x > view.w + 50 || y > view.h + 20) continue;
      ctx.fillStyle = p.kind === "sea" ? COL.faint : COL.text;
      ctx.font = (p.kind === "country" ? "600 12px " : p.kind === "sea" ? "italic 12px " : "12px ") + "IBM Plex Sans, system-ui, sans-serif";
      if (p.kind === "port") { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 7); ctx.fill(); ctx.fillText(p.name, x + 5, y + 4); }
      else if (p.kind === "country" || state.z < 3) ctx.fillText(p.name.replace(" (Musandam)", ""), x, y);
    }
  }

  function tri(x, y, heading, size, fill, stroke, dashed) {
    ctx.save();
    ctx.translate(x, y); ctx.rotate(heading);
    ctx.beginPath(); ctx.moveTo(size, 0); ctx.lineTo(-size * 0.7, size * 0.55); ctx.lineTo(-size * 0.7, -size * 0.55); ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.setLineDash(dashed ? [3, 2] : []); ctx.strokeStyle = stroke; ctx.lineWidth = 1.6; ctx.stroke(); }
    ctx.restore();
  }

  const drawn = [];
  function drawShips(t) {
    drawn.length = 0;
    const truth = state.view === "truth";
    const zf = Math.min(1 + (state.z - 1) * 0.25, 2.2);
    for (const v of ships) {
      const p = shipAt(v, t);
      if (!p) continue;
      const [x, y] = P(p.lon, p.lat);
      if (x < -20 || y < -20 || x > view.w + 20 || y > view.h + 20) continue;
      if (v.kind !== "tanker") {
        if (!truth && !p.aisOn) continue;
        ctx.fillStyle = COL.other;
        ctx.beginPath(); ctx.arc(x, y, 2.2 * zf, 0, 7); ctx.fill();
        drawn.push({ v, x, y });
        continue;
      }
      const size = (v.class === "VLCC" ? 8 : v.class === "MR" ? 5.5 : 6.5) * zf;
      const [wl, wa] = v.laneObj.at(p.s - 10);
      ctx.strokeStyle = p.aisOn ? "rgba(92,184,240,0.35)" : "rgba(240,162,59,0.35)";
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(...P(wl, wa)); ctx.lineTo(x, y); ctx.stroke();
      if (p.aisOn) {
        tri(x, y, p.heading, size, v.laden ? COL.seen : null, v.laden ? null : COL.seen, false);
        drawn.push({ v, x, y });
      } else if (truth) {
        tri(x, y, p.heading, size, null, COL.oil, true);
        ctx.strokeStyle = "rgba(240,162,59,0.5)";
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.arc(x, y, size + 5, 0, 7); ctx.stroke();
        ctx.setLineDash([]);
        drawn.push({ v, x, y });
      }
      if (v.ghost.score >= 0.7 && truth) {   // warning dot on likely ghosts
        ctx.fillStyle = COL.oil;
        ctx.beginPath(); ctx.arc(x + size, y - size, 2.5 * zf, 0, 7); ctx.fill();
      }
      if (state.selected === v.id) {
        ctx.strokeStyle = COL.white; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(x, y, size + 9, 0, 7); ctx.stroke();
      }
    }
    ctx.strokeStyle = COL.oilSoft;
    ctx.lineWidth = 2;
    for (const v of ships) for (const [tp, lon, lat] of v.spoof_points || []) {
      if (Math.abs(tp - t) > 0.33) continue;
      const [x, y] = P(lon, lat);
      ctx.beginPath(); ctx.moveTo(x - 5, y - 5); ctx.lineTo(x + 5, y + 5); ctx.moveTo(x + 5, y - 5); ctx.lineTo(x - 5, y + 5); ctx.stroke();
    }
    let flag = null;
    sc.sar_passes_h.forEach((tp, i) => {
      const age = t - tp;
      if (age < 0 || age > 2) return;
      const a = 1 - age / 2;
      ctx.strokeStyle = `rgba(231,236,242,${a})`;
      ctx.lineWidth = 1.5;
      let n = 0;
      for (const v of ships) for (const h of v.sar_hits || []) {
        if (h.pass !== i) continue;
        n++;
        const [x, y] = P(h.lon, h.lat);
        ctx.strokeRect(x - 6 * zf, y - 6 * zf, 12 * zf, 12 * zf);
      }
      flag = `${n} · ${age.toFixed(1)} h ago`;
    });
    $("radar-flag").hidden = !flag;
    if (flag) $("radar-text").textContent = flag;
  }

  // ---------------------------------------------------------------- panels
  const fmt = (x) => x.toFixed(1);
  const MAXP = 22;
  function renderMetrics() {
    const e = sc.estimate;
    $("est-p50").textContent = fmt(e.total.p50);
    $("est-range").textContent = `${fmt(e.total.p5)}–${fmt(e.total.p95)} (90%)`;
    $("range-band").style.left = `${e.total.p5 / MAXP * 100}%`;
    $("range-band").style.width = `${(e.total.p95 - e.total.p5) / MAXP * 100}%`;
    $("range-mid").style.left = `${e.total.p50 / MAXP * 100}%`;
    $("est-seen").textContent = fmt(e.seen.p50);
    $("est-bridged").textContent = fmt(e.bridged.p50);
    $("est-hidden").textContent = fmt(e.hidden.p50);
    $("truth").textContent = fmt(sc.truth_mbd);
    $("g-world").textContent = `${(e.global.share_of_world_p50 * 100).toFixed(1)}%`;
    $("g-missing").textContent = `−${fmt(e.global.missing_vs_prewar_mbd.p50)}`;
    const short = { "EIA (pre-war baseline)": "EIA '24", "EIA quarterly chokepoint data": "EIA Q1", "Vortexa (via Argus)": "Vortexa",
      Argus: "Argus", "Windward (satellite)": "Windward", "US officials (via Argus)": "US gov" };
    const rows = sc.published.map((p) => `<div class="r" title="${p.who}, ${p.when}"><span>${short[p.who] || p.who}</span>
      <span class="track"><span class="bar" style="width:${p.mbd / MAXP * 100}%"></span></span><span class="v">${fmt(p.mbd)}</span></div>`);
    rows.push(`<div class="r" title="Our estimate, 90% range"><span class="ours">Ours</span><span class="track">
      <span class="band" style="left:${e.total.p5 / MAXP * 100}%;width:${(e.total.p95 - e.total.p5) / MAXP * 100}%"></span>
      <span class="mid" style="left:${e.total.p50 / MAXP * 100}%"></span></span><span class="v ours">${fmt(e.total.p50)}</span></div>`);
    $("published").innerHTML = rows.join("");
  }

  function renderCounters(t) {
    let all = 0, ais = 0, dark = 0;
    for (const v of ships) {
      if (v.kind !== "tanker" || v.lane !== "outbound" || !v.laden || v.tGate > t || v.tGate < 0) continue;
      all++;
      if (v.ais_mode === "on" || v.ais_mode === "spoof") ais++; else dark++;
    }
    $("c-all").textContent = all; $("c-ais").textContent = ais; $("c-dark").textContent = dark;
    const h = Math.floor(t), m = Math.floor((t - h) * 60);
    $("clock-label").textContent = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }

  // ---------------------------------------------------------------- ship popup
  const popup = $("popup");
  function select(id) {
    state.selected = id;
    const v = ships.find((s) => s.id === id);
    popup.hidden = !v;
    if (!v) return;
    $("p-flag").textContent = `${ISO[v.flag] || "??"} · ${v.class}`;
    $("p-flag").title = `Flag: ${v.flag}`;
    $("p-name").textContent = v.name;
    $("p-score").textContent = `${Math.round(v.ghost.score * 100)}%`;
    $("p-meter").style.width = `${v.ghost.score * 100}%`;
    const cargo = v.kind === "tanker" ? `<span title="${v.laden ? "Laden" : "Empty"}">${svg(v.laden
      ? '<path d="M12 3c3 4 6 7 6 11a6 6 0 0 1-12 0c0-4 3-7 6-11z" fill="currentColor"/>'
      : '<path d="M12 3c3 4 6 7 6 11a6 6 0 0 1-12 0c0-4 3-7 6-11z"/>')}</span>` : "";
    const warn = v.ghost.codes.map((c, i) => `<span class="warn" title="${v.ghost.reasons[i]}">${svg(ICON[c])}</span>`).join("");
    $("p-icons").innerHTML = cargo + (warn || `<span title="No warning signs">${svg('<path d="M5 12l5 5 9-10"/>')}</span>`);
    $("p-kv").innerHTML = [
      ["IMO", `${v.imo || "–"} ${v.imo_valid ? "✓" : "✗"}`], ["MMSI", `${v.mmsi} → ${ISO[v.mmsi_flag] || "?"}`],
      ["Flag", v.flag], ["Built", v.built || "–"], ["Cargo", v.kind === "tanker" ? (v.laden ? `${v.cargo_mbbl.toFixed(2)} M bbl` : "empty") : "–"],
      ["To", v.destination || "(blank)"]].map(([k, d]) => `<dt>${k}</dt><dd>${d}</dd>`).join("");
    $("p-reasons").innerHTML = v.ghost.reasons.map((r) => `<li>${r}</li>`).join("") + "<li>Synthetic identity</li>";
  }
  function placePopup(t) {
    if (popup.hidden) return;
    const v = ships.find((s) => s.id === state.selected);
    const p = v && shipAt(v, t);
    if (!p) { select(null); return; }
    const [x, y] = P(p.lon, p.lat);
    const pw = popup.offsetWidth, ph = popup.offsetHeight;
    let left = x + 16, top = y - ph / 2;
    if (left + pw > view.w - 60) left = x - pw - 16;
    top = Math.min(Math.max(top, 8), view.h - ph - 64);
    popup.style.left = `${Math.max(8, left)}px`;
    popup.style.top = `${top}px`;
  }
  $("p-close").addEventListener("click", () => select(null));
  $("p-more").addEventListener("click", () => {
    const d = $("p-detail"); d.hidden = !d.hidden; $("p-more").setAttribute("aria-expanded", String(!d.hidden));
  });

  // ---------------------------------------------------------------- info sheets
  function keyRow(draw, text) { return { draw, text }; }
  const INFO = {
    sim: () => ({ title: "Simulated data", html: `<p>Every ship, name, IMO number and radar pass here is <b>synthetic</b>. Each scenario is calibrated so the true flow matches a published figure, then the estimator sees only what AIS and two radar passes would show.</p>
      <p>Why not live: no free AIS receivers cover Hormuz, free radar passes are days apart, and the free ship-data services lag 3–5 days. Real collectors are in <code>experiments/strait_sources.py</code>.</p>
      <p class="mono">Generated ${sc.generated}</p>` }),
    estimate: () => {
      const a = sc.estimate.assumptions, c = sc.estimate.counts;
      return { title: "How the flow is estimated", html: `<ul>
        <li><b>Seen:</b> laden tankers whose AIS crosses the dashed gate (${c.seen_crossings}). Impossible jumps are dropped first (${c.spoofed_points_dropped} points).</li>
        <li><b>Bridged:</b> AIS off on one side of the gate, back on the other (${c.bridged_crossings}).</li>
        <li><b>Never on AIS:</b> radar ships with no AIS match. ${Object.values(c.unmatched_radar).join(" + ")} seen in a ${a.corridor_km_outbound} km corridor; Little's law turns a snapshot into a rate.</li></ul>
        <p>Ranges come from ${a.draws} random draws over load factor (${a.load_factor.join("–")}), radar recall (${a.sar_recall.join("–")}), false positives, laden share of dark ships (${a.laden_share_of_dark_outbound.join("–")}) and speed. Radar counts are treated as Poisson.</p>
        <p>The ✓ figure is the true value, shown only because the ships are simulated.</p>` };
    },
    global: () => ({ title: "Global figures", html: `<ul>
        <li>World oil demand 2026: 103.3 mb/d (IEA Oil Market Report, Aug 2026)</li>
        <li>Pre-war Hormuz flow: 20 mb/d, about 20% of world use (EIA, 2024 average)</li>
        <li>About 76% of oil moves by sea (EIA, 2023)</li>
        <li>Hormuz cargo is 72–75% crude, the rest products (EIA, IEA, 2025)</li></ul>
        <p>Published 2026 estimates (from search results; check before quoting):</p><ul>
        ${sc.published.map((p) => `<li>${p.who}, ${p.when}: ${fmt(p.mbd)} mb/d</li>`).join("")}</ul>
        <p>Sources and caveats: <code>docs/strait-live-data.md</code> in the repo.</p>` }),
    legend: () => ({ title: "Map key", key: [
        keyRow((c) => { c.fillStyle = COL.seen; c.beginPath(); c.moveTo(22, 10); c.lineTo(8, 4); c.lineTo(8, 16); c.fill(); }, "Tanker on AIS (filled = laden, outline = empty)"),
        keyRow((c) => { c.strokeStyle = COL.oil; c.setLineDash([3, 2]); c.lineWidth = 1.6; c.beginPath(); c.arc(14, 10, 8, 0, 7); c.stroke(); }, "Dark tanker: AIS off"),
        keyRow((c) => { c.fillStyle = COL.oil; c.beginPath(); c.arc(14, 10, 3, 0, 7); c.fill(); }, "Likely ghost ship (risk 70%+)"),
        keyRow((c) => { c.strokeStyle = COL.oilSoft; c.lineWidth = 2; c.beginPath(); c.moveTo(9, 5); c.lineTo(19, 15); c.moveTo(19, 5); c.lineTo(9, 15); c.stroke(); }, "Fake AIS position (spoofing or jamming)"),
        keyRow((c) => { c.strokeStyle = COL.white; c.lineWidth = 1.5; c.strokeRect(8, 4, 12, 12); }, "Radar detection (fades after 2 h)"),
        keyRow((c) => { c.fillStyle = COL.other; c.beginPath(); c.arc(14, 10, 2.5, 0, 7); c.fill(); }, "Other ship"),
        keyRow((c) => { c.strokeStyle = "rgba(231,236,242,0.7)"; c.setLineDash([4, 3]); c.lineWidth = 1.5; c.beginPath(); c.moveTo(14, 1); c.lineTo(14, 19); c.stroke(); }, "Counting gate"),
      ], html: `<p>Drag to pan · scroll, pinch or + / − to zoom · click a ship. Coastline: Natural Earth (public domain). Lanes approximate, not for navigation.</p>` }),
  };
  const sheet = $("sheet");
  document.querySelectorAll("[data-info]").forEach((b) => b.addEventListener("click", () => {
    const info = INFO[b.dataset.info]();
    $("sheet-title").textContent = info.title;
    const body = $("sheet-body");
    body.innerHTML = (info.key ? `<div class="key">${info.key.map((_, i) => `<canvas width="56" height="40" id="k${i}"></canvas><span>${info.key[i].text}</span>`).join("")}</div>` : "") + info.html;
    (info.key || []).forEach((k, i) => { const c = $(`k${i}`).getContext("2d"); c.scale(2, 2); k.draw(c); });
    sheet.hidden = false;
    $("sheet-close").focus();
  }));
  $("sheet-close").addEventListener("click", () => { sheet.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { sheet.hidden = true; select(null); } });

  // ---------------------------------------------------------------- controls
  const sel = $("scenario");
  const shortLabel = { prewar: "Pre-war", aug2026: "Aug 2026", sep2026: "Sep 2026" };
  for (const [k, s] of Object.entries(D.scenarios)) {
    const o = new Option(shortLabel[k] || k, k, false, k === state.key); o.title = s.label; sel.add(o);
  }
  sel.addEventListener("change", () => load(sel.value));
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view;
    document.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  function setPlaying(on) {
    state.playing = on;
    $("play-icon").innerHTML = on ? '<path d="M8 5v14M16 5v14"/>' : '<path d="M7 5l12 7-12 7z" fill="currentColor"/>';
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
  }
  $("play").addEventListener("click", () => setPlaying(!state.playing));
  $("clock").addEventListener("input", (e) => { state.t = Number(e.target.value); });
  const SPEEDS = [[1, "1×"], [3, "3×"], [0.25, "¼×"]];
  $("speed").addEventListener("click", () => {
    const i = (SPEEDS.findIndex(([s]) => s === state.speed) + 1) % SPEEDS.length;
    state.speed = SPEEDS[i][0]; $("speed").textContent = SPEEDS[i][1];
  });
  $("zin").addEventListener("click", () => zoomAt(1.6));
  $("zout").addEventListener("click", () => zoomAt(1 / 1.6));
  $("zreset").addEventListener("click", () => Object.assign(state, home));
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const step = 40 / scale();
    const k = { "+": () => zoomAt(1.4), "=": () => zoomAt(1.4), "-": () => zoomAt(1 / 1.4),
      ArrowLeft: () => { state.cx -= step / KX * 1; }, ArrowRight: () => { state.cx += step / KX; },
      ArrowUp: () => { state.cy += step / KM_LAT; }, ArrowDown: () => { state.cy -= step / KM_LAT; } }[e.key];
    if (k) { e.preventDefault(); k(); clampCenter(); }
  });
  // drag to pan, pinch to zoom, tap to select
  const pointers = new Map();
  let downAt = null, pinch = null;
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) downAt = { x: e.clientX, y: e.clientY, cx: state.cx, cy: state.cy, moved: false };
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), z: state.z };
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const r = canvas.getBoundingClientRect();
      const f = (Math.hypot(a.x - b.x, a.y - b.y) / pinch.d) * pinch.z / state.z;
      zoomAt(f, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
      downAt && (downAt.moved = true);
      return;
    }
    if (!downAt) return;
    const dx = e.clientX - downAt.x, dy = e.clientY - downAt.y;
    if (Math.hypot(dx, dy) > 4) { downAt.moved = true; canvas.classList.add("dragging"); }
    state.cx = downAt.cx - dx / (KX * scale());
    state.cy = downAt.cy + dy / (KM_LAT * scale());
    clampCenter();
  });
  function up(e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0 && downAt) {
      canvas.classList.remove("dragging");
      if (!downAt.moved) {
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        let best = null, bd = 16;
        for (const d of drawn) { const dd = Math.hypot(d.x - x, d.y - y); if (dd < bd) { bd = dd; best = d.v; } }
        select(best ? best.id : null);
      }
      downAt = null;
    }
  }
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  new ResizeObserver(fit).observe(wrap);

  function frame(now) {
    const dt = state.last ? Math.min((now - state.last) / 1000, 0.1) : 0;
    state.last = now;
    if (state.playing) { state.t = (state.t + dt * state.speed) % sc.window_h; $("clock").value = state.t; }
    drawBase();
    drawShips(state.t);
    renderCounters(state.t);
    placePopup(state.t);
    requestAnimationFrame(frame);
  }

  setPlaying(state.playing);
  fit();
  load(state.key);
  requestAnimationFrame(frame);
})();
