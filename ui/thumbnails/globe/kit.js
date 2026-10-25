// kit.js: the pixel globe, flow arcs and glow for the Hormuz Flow stills. Art is drawn at 480x270 and scaled x4
// to 1920x1080; text is drawn at full resolution. Needs d3, window.COUNTRIES (ui/globe/data/countries.js) and
// window.FLOWS (data.js: oil kb/d via Hormuz by destination, LNG Mt/yr from ui/app/data/gas.json).
const S = 4, LW = W / S, LH = H / S;
const HZ = [56.4, 26.5], BAB = [43.4, 12.6];
// major cities, for night lights only (lon, lat)
const CITIES = [[139.7, 35.7], [135.5, 34.7], [127, 37.6], [121.5, 31.2], [116.4, 39.9], [113.3, 23.1], [114.2, 22.3], [106.5, 29.5], [114.3, 30.6],
  [121.5, 25], [121, 14.6], [100.5, 13.8], [106.7, 10.8], [105.8, 21], [106.8, -6.2], [103.8, 1.35], [101.7, 3.1], [90.4, 23.8], [88.4, 22.6],
  [77.2, 28.6], [72.9, 19.1], [77.6, 13], [80.3, 13.1], [78.5, 17.4], [67, 24.9], [74.3, 31.5], [51.4, 35.7], [46.7, 24.7], [55.3, 25.2], [51.5, 25.3],
  [48, 29.4], [44.4, 33.3], [29, 41], [31.2, 30], [37.6, 55.8], [30.5, 50.5], [13.4, 52.5], [2.35, 48.85], [-0.1, 51.5], [-3.7, 40.4], [12.5, 41.9],
  [9.2, 45.5], [3.4, 6.5], [36.8, -1.3], [28, -26.2], [38.7, 9], [69.2, 41.3], [76.9, 43.2], [82.9, 55], [115.9, -32], [151.2, -33.9], [39.2, 21.5],
  [45, 12.8], [58.4, 23.6], [54.4, 24.5], [32.9, 39.9], [23.7, 38], [21, 52.2], [4.5, 51.9], [126.6, 45.8], [123.4, 41.8], [117.2, 39.1], [120.2, 30.3],
  [118.8, 32.1], [108.9, 34.3], [104.1, 30.7], [102.7, 25], [126.9, 35.2], [129, 35.1], [130.4, 33.6], [141.3, 43.1], [85.3, 27.7], [79.9, 6.9], [96.2, 16.8]];
const norm = (v) => { const l = Math.hypot(...v); return v.map((x) => x / l); };
function still(draw) {
  window.STILL_T = 0; window.renderAt = () => draw();
  Promise.all(['700 64px "Pixelify Sans"', '400 32px "Pixelify Sans"', '400 32px "VT323"'].map((f) => document.fonts.load(f))).then(() => { draw(); window.READY = true; });
}
function hex(c) { return "#" + c.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, "0")).join(""); }
function put(d, i, h) { const c = rgb(h); d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = 255; }

// sky: a dithered vertical gradient and seeded stars
function sky(top = "#02040f", bottom = "#08102a", seed = 3, n = 260) {
  const b = buf(LW, LH), img = b.x.createImageData(LW, LH), d = img.data, A = rgb(top), B2 = rgb(bottom), r = rng(seed);
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const v = y / LH, lv = Math.floor(v * 4), f = v * 4 - lv, k = (lv + (dith(x, y, f) ? 1 : 0)) / 4;
    put(d, (y * LW + x) * 4, hex(A.map((a, j) => a + (B2[j] - a) * k)));
  }
  b.x.putImageData(img, 0, 0);
  const stars = buf(LW, LH);
  for (let i = 0; i < n; i++) { const x = r() * LW | 0, y = r() * LH | 0, s = r(); fr(stars.x, s > 0.93 ? "#f1e8d2" : s > 0.7 ? "#8e93c0" : "#3e4472", x, y); if (s > 0.985) { fr(stars.x, "#8e93c0", x - 1, y); fr(stars.x, "#8e93c0", x + 1, y); fr(stars.x, "#8e93c0", x, y - 1); fr(stars.x, "#8e93c0", x, y + 1); } }
  return { b, stars };
}

// the globe: shaded by a light in view space (x right, y down, z toward us), land and sea snapped to two ramps
function globe(cfg) {
  const { cx, cy, r } = cfg, rot = cfg.rot, L = norm(cfg.light || [-0.55, -0.45, 0.7]);
  const proj = d3.geoOrthographic().scale(r).translate([cx, cy]).clipAngle(90).rotate(rot).precision(0.1);
  const feats = { type: "FeatureCollection", features: window.COUNTRIES.features };
  const mask = (fn) => { const b = buf(LW, LH); fn(b.x, d3.geoPath(proj, b.x)); return b.x.getImageData(0, 0, LW, LH).data; };
  const land = mask((x, p) => { x.beginPath(); p(feats); x.fillStyle = "#fff"; x.fill(); });
  const bord = mask((x, p) => { x.beginPath(); p(feats); x.strokeStyle = "#fff"; x.lineWidth = 0.55; x.stroke(); });
  const grat = mask((x, p) => { x.beginPath(); p(d3.geoGraticule().step([15, 15])()); x.strokeStyle = "#fff"; x.lineWidth = 0.5; x.stroke(); });
  const SEA = cfg.sea || ["#030716", "#05102b", "#0a1c40", "#0e2953", "#163a6c", "#204d88"];
  const LAND = cfg.land || ["#0a0d18", "#141a2c", "#222c47", "#324266", "#475a86", "#6177a5"];
  const out = buf(LW, LH), img = out.x.createImageData(LW, LH), d = img.data;
  const shade = (x, y) => { const dx = (x + 0.5 - cx) / r, dy = (y + 0.5 - cy) / r, rr = dx * dx + dy * dy; if (rr > 1) return null; const nz = Math.sqrt(1 - rr); return { s: dx * L[0] + dy * L[1] + nz * L[2], rr }; };
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const sh = shade(x, y); if (!sh) continue;
    const i = (y * LW + x) * 4, isL = land[i + 3] > 110;
    const v = clamp((sh.s + 0.18) / 1.05, 0, 1) * 5; let lv = Math.floor(v); if (dith(x, y, v - lv)) lv++; lv = clamp(lv, 0, 5);
    let col = (isL ? LAND : SEA)[lv];
    if (isL && bord[i + 3] > 80) col = LAND[clamp(lv + 1, 1, 5)];
    if (!isL && grat[i + 3] > 110 && lv >= 1 && dith(x, y, 0.55)) col = SEA[clamp(lv + 1, 0, 5)];
    if (sh.rr > 0.9 && sh.s > -0.1 && dith(x, y, (sh.rr - 0.9) * 8)) col = isL ? "#5f86c4" : "#2f6fb8";
    put(d, i, col);
  }
  out.x.putImageData(img, 0, 0);
  const R = d3.geoRotation(rot);
  // view space position of a point at height h (in globe radii) above the ground
  const at = (ll, h = 0) => { const [l, p] = R(ll).map((v) => v * Math.PI / 180), c = Math.cos(p); return [c * Math.sin(l) * (1 + h), -Math.sin(p) * (1 + h), c * Math.cos(l) * (1 + h)]; };
  const seen = (q) => q[2] > 0 || q[0] * q[0] + q[1] * q[1] > 1;
  const xy = (q) => [cx + r * q[0], cy + r * q[1]];
  const lit = (ll) => { const q = at(ll); return q[0] * L[0] + q[1] * L[1] + q[2] * L[2]; };
  return { b: out, proj, at, seen, xy, lit, L, cx, cy, r, land };
}
// atmosphere: a dithered halo, stronger on the lit side
function atmosphere(G, w = 0.1, cols = ["#3d8be0", "#2460a8", "#143a6a"]) {
  const b = buf(LW, LH), img = b.x.createImageData(LW, LH), d = img.data, ww = G.r * w;
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const dx = x + 0.5 - G.cx, dy = y + 0.5 - G.cy, dist = Math.hypot(dx, dy) - G.r;
    if (dist < -1 || dist > ww) continue;
    const side = (dx * G.L[0] + dy * G.L[1]) / (Math.hypot(dx, dy) || 1), a = (1 - dist / ww) * (0.3 + 0.7 * clamp(side * 0.8 + 0.4, 0, 1));
    if (!dith(x, y, a * 0.9)) continue;
    put(d, (y * LW + x) * 4, dist < ww * 0.25 ? cols[0] : dist < ww * 0.6 ? cols[1] : cols[2]);
  }
  b.x.putImageData(img, 0, 0); return b;
}
// city lights on the night side
function lights(G, seed = 5) {
  const b = buf(LW, LH), r = rng(seed);
  for (const c of CITIES) {
    const q = G.at(c); if (q[2] < 0.08) continue;
    const s = G.lit(c); if (s > (G.night ?? 0.3)) continue;
    const [x, y] = G.xy(q), k = clamp(((G.night ?? 0.3) - s) * 2.5 + 0.25, 0, 1);
    fr(b.x, k > 0.5 ? "#ffd27a" : "#c98a3a", x, y);
    for (let n = 0; n < 4; n++) if (r() < k * 0.8) fr(b.x, "#a8692a", x + (r() * 3 - 1.5), y + (r() * 3 - 1.5));
  }
  return b;
}
// flow arcs: great circles lifted off the ground, a dim line with a bright comet heading to the buyer
const ARC = { oil: ["#7a4512", "#d9861f", "#ffb547", "#fff1c9"], gas: ["#4a3a86", "#8f6ee0", "#c4a8ff", "#f3ecff"] };
function arcs(G, list, o = {}) {
  const b = buf(LW, LH), ends = [];
  for (const A of list) {
    if (G.at(A.b)[2] < (o.minZ ?? 0.05)) continue;
    const ip = d3.geoInterpolate(A.a, A.b), dist = d3.geoDistance(A.a, A.b), n = Math.max(60, Math.round(dist * G.r * 2.2));
    const C = ARC[A.kind], th = A.w > 0.55 ? 2 : 1, head = A.head ?? 0.75, tail = A.tail ?? 0.4, lift = (o.lift ?? 0.2) * (A.liftK ?? 1);
    for (let k = 0; k <= n; k++) {
      const s = k / n, q = G.at(ip(s), lift * Math.sin(Math.PI * s) * Math.min(1, dist * 1.15));
      if (!G.seen(q)) continue;
      const [x, y] = G.xy(q), t = s <= head && s >= head - tail ? (s - (head - tail)) / tail : -1;
      const col = t < 0 ? (s > head ? C[0] : C[0]) : t > 0.93 ? C[3] : t > 0.7 ? C[2] : C[1];
      fr(b.x, col, x, y, th, th);
      if (t > 0.9 && A.w > 0.25) fr(b.x, C[2], x - 1, y, th + 2, th);
    }
    const qe = G.at(A.b); if (G.seen(qe) && qe[2] > 0) ends.push({ xy: G.xy(qe), C, w: A.w });
  }
  for (const e of ends) { const [x, y] = e.xy; fr(b.x, P.ink, x - 1, y - 1, 3, 3); fr(b.x, e.C[3], x, y); if (e.w > 0.4) { fr(b.x, e.C[2], x - 2, y); fr(b.x, e.C[2], x + 2, y); fr(b.x, e.C[2], x, y - 2); fr(b.x, e.C[2], x, y + 2); } }
  return b;
}
// the real flows, as arc lists: oil by kb/d via Hormuz (top n), LNG by Mt/yr from Qatar and the UAE
function flowArcs(nOil = 12, nGas = 8, seed = 11) {
  const r = rng(seed), F = window.FLOWS;
  const oil = [...F.oil].sort((a, b) => b.h - a.h).slice(0, nOil), om = oil[0].h;
  const gas = [...F.gas].sort((a, b) => b.value - a.value).slice(0, nGas), gm = gas[0].value;
  return [...oil.map((f) => ({ a: HZ, b: f.end, kind: "oil", w: Math.sqrt(f.h / om), head: 0.62 + r() * 0.3, name: f.name })),
          ...gas.map((f) => ({ a: f.start, b: f.end, kind: "gas", w: Math.sqrt(f.value / gm), head: 0.55 + r() * 0.35, liftK: 1.35, name: f.to }))];
}
// a strait marker: dark core, red ring, dithered outer ring
function marker(G, ll, col = "#ff6a4d", rr = 6) {
  const b = buf(LW, LH), q = G.at(ll); if (!G.seen(q) || q[2] < 0) return { b, xy: null };
  const [x, y] = G.xy(q);
  for (let k = 0; k < 48; k++) { const a = k / 48 * TAU; fr(b.x, col, x + Math.cos(a) * rr, y + Math.sin(a) * rr * 0.92); if (dith(k, 1, 0.5)) fr(b.x, "#8a2a1e", x + Math.cos(a) * (rr + 4), y + Math.sin(a) * (rr + 4) * 0.92); }
  fr(b.x, P.ink, x - 2, y - 2, 5, 5); fr(b.x, col, x - 1, y - 1, 3, 3); fr(b.x, "#ffd2c4", x, y);
  return { b, xy: [x * S, y * S] };
}
// draw a low-res buffer crisp, and optionally its glow
function layer(b, glow = 0, alpha = 0.9, blend = "lighter") {
  ctx.imageSmoothingEnabled = false; ctx.drawImage(b.c, 0, 0, W, H);
  if (!glow) return;
  ctx.save(); ctx.globalCompositeOperation = blend; ctx.globalAlpha = alpha; ctx.filter = `blur(${glow}px)`; ctx.imageSmoothingEnabled = true; ctx.drawImage(b.c, 0, 0, W, H); ctx.restore();
}
function glowOnly(b, glow, alpha) { ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = alpha; ctx.filter = `blur(${glow}px)`; ctx.imageSmoothingEnabled = true; ctx.drawImage(b.c, 0, 0, W, H); ctx.restore(); }
// a full-resolution pixel chip: dark frame, inner line, text
function chip(x, y, w, h, o = {}) {
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,.45)"; ctx.fillRect(x + 8, y + 8, w, h);
  ctx.fillStyle = P.ink; ctx.fillRect(x - 4, y - 4, w + 8, h + 8);
  ctx.fillStyle = o.edge || P.line2; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = o.fill || "#0f1628"; ctx.fillRect(x + 4, y + 4, w - 8, h - 8);
  ctx.restore();
}
function legendKey(x, y, col, label, labCol) { ctx.fillStyle = P.ink; ctx.fillRect(x, y - 24, 28, 28); ctx.fillStyle = col; ctx.fillRect(x + 4, y - 20, 20, 20); txt(label, x + 42, y, { font: "mono", w: 400, size: 40, color: labCol, shadow: 2 }); }
