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
  // highlighted countries (cfg.hi: Map iso3 -> "oil" | "gas"), one mask per kind
  const hiM = {};
  for (const kind of new Set(cfg.hi ? cfg.hi.values() : [])) { const fs = window.COUNTRIES.features.filter((f) => cfg.hi.get(f.properties.iso3) === kind);
    if (fs.length) hiM[kind] = mask((x, p) => { x.beginPath(); p({ type: "FeatureCollection", features: fs }); x.fillStyle = "#fff"; x.fill(); }); }
  const HI = cfg.hiRamps || { oil: ["#2c1706", "#5c300c", "#8c4c12", "#c06c18", "#e98c22", "#ffb547"], gas: ["#1d1338", "#362562", "#50388e", "#7050ba", "#9070e2", "#b69cf2"] };
  const hiLift = cfg.hiLift ?? 1, hiEdge = cfg.hiEdge ?? 1;
  const hb = buf(LW, LH), himg = hb.x.createImageData(LW, LH), hd = himg.data;
  const SEA = cfg.sea || ["#030716", "#05102b", "#0a1c40", "#0e2953", "#163a6c", "#204d88"];
  const LAND = cfg.land || ["#0a0d18", "#141a2c", "#222c47", "#324266", "#475a86", "#6177a5"];
  const out = buf(LW, LH), img = out.x.createImageData(LW, LH), d = img.data;
  const shade = (x, y) => { const dx = (x + 0.5 - cx) / r, dy = (y + 0.5 - cy) / r, rr = dx * dx + dy * dy; if (rr > 1) return null; const nz = Math.sqrt(1 - rr); return { s: dx * L[0] + dy * L[1] + nz * L[2], rr }; };
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const sh = shade(x, y); if (!sh) continue;
    const i = (y * LW + x) * 4, isL = land[i + 3] > 110;
    const v = clamp((sh.s + 0.18) / 1.05, 0, 1) * 5; let lv = Math.floor(v); if (dith(x, y, v - lv)) lv++; lv = clamp(lv, 0, 5);
    let hk = null; if (isL) for (const kk in hiM) if (hiM[kk][i + 3] > 110) { hk = kk; break; }
    const lvH = clamp(lv + hiLift, 1, 5);   // lit a step brighter than plain land, so they read on the night side too
    let col = hk ? HI[hk][lvH] : (isL ? LAND : SEA)[lv];
    if (isL && bord[i + 3] > 80) col = hk ? HI[hk][clamp(lvH + 1 + hiEdge, 2, 5)] : LAND[clamp(lv + 1, 1, 5)];
    if (hk) put(hd, i, HI[hk][clamp(lvH + 1, 2, 5)]);
    if (!isL && grat[i + 3] > 110 && lv >= 1 && dith(x, y, 0.55)) col = SEA[clamp(lv + 1, 0, 5)];
    if (sh.rr > 0.9 && sh.s > -0.1 && dith(x, y, (sh.rr - 0.9) * 8)) col = isL ? "#5f86c4" : "#2f6fb8";
    put(d, i, col);
  }
  out.x.putImageData(img, 0, 0); hb.x.putImageData(himg, 0, 0);
  const R = d3.geoRotation(rot);
  // view space position of a point at height h (in globe radii) above the ground
  const at = (ll, h = 0) => { const [l, p] = R(ll).map((v) => v * Math.PI / 180), c = Math.cos(p); return [c * Math.sin(l) * (1 + h), -Math.sin(p) * (1 + h), c * Math.cos(l) * (1 + h)]; };
  const seen = (q) => q[2] > 0 || q[0] * q[0] + q[1] * q[1] > 1;
  const xy = (q) => [cx + r * q[0], cy + r * q[1]];
  const lit = (ll) => { const q = at(ll); return q[0] * L[0] + q[1] * L[1] + q[2] * L[2]; };
  return { b: out, hiGlow: hb, proj, at, seen, xy, lit, L, cx, cy, r, land };
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
    const C = A.pal || ARC[A.kind], th = A.w > 0.55 ? 2 : 1, head = A.head ?? 0.75, tail = A.tail ?? 0.4, lift = (o.lift ?? 0.2) * (A.liftK ?? 1);
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
// the app's logo: the pixel tanker from the header (ui/app/src/landing.js, HZIcons.ship), drawn at full resolution
const SHIP = ["...........K..", "..........KK..", "...K......KKK.", "KKKKKKKKKKKKKK", ".KKKKKKKKKKKK.", "..KKKKKKKKKK.."];
function shipLogo(x, y, px, col = P.oil, shadow = Math.round(px / 2)) {
  ctx.save();
  for (const [dx, c] of [[shadow, P.ink], [0, col]]) {
    ctx.fillStyle = c;
    SHIP.forEach((row, j) => [...row].forEach((ch, i) => { if (ch === "K") ctx.fillRect(x + i * px + dx, y + j * px + dx, px, px); }));
  }
  ctx.restore();
  return { w: SHIP[0].length * px, h: SHIP.length * px };
}
// a pixel Z with straight bars and a stepped diagonal, sized to the font's Z, written into a text mask
function zGlyph(M, l) {
  const c = buf(8, 8).x; c.font = FONT({ size: l.size });
  const x0 = Math.round(l.x + c.measureText(l.s.slice(0, l.s.indexOf("Z"))).width), wZ = Math.round(c.measureText("Z").width * 0.92);
  const mH = c.measureText("H"), cap = Math.round(mH.actualBoundingBoxAscent), y1 = Math.round(l.y), y0 = y1 - cap;
  const t = Math.max(3, Math.round(l.size * 0.16)), inset = Math.round(wZ * 0.06);
  const set = (x, y) => { if (x >= 0 && y >= 0 && x < LW && y < LH) M[y * LW + x] = 1; };
  for (let y = y0; y < y1; y++) {
    if (y < y0 + t || y >= y1 - t) { for (let x = x0 + inset; x < x0 + wZ - inset; x++) set(x, y); continue; }
    const f = (y - y0 - t) / Math.max(1, (y1 - t) - (y0 + t)), xr = Math.round(x0 + wZ - inset - t * 1.15 - f * (wZ - 2 * inset - t * 1.15));
    for (let x = xr; x < xr + Math.round(t * 1.15); x++) set(x, y);
  }
}
// the "pour" lettering: the title as chunky low-res letters with a cream rim, black outline and drop shadow.
// fill: "cream" (solid, shaded) or "oil" (liquid oil with a lit surface and a few bubbles)
function pixelTitle(lines) {
  const b = buf(LW, LH), img = b.x.createImageData(LW, LH), d = img.data;
  for (const l of lines) {
    const zi = l.s.indexOf("Z"), head = zi < 0 ? l.s : l.s.slice(0, zi);
    const M = textMask(LW, LH, [{ s: head, x: l.x, y: l.y, size: l.size, align: "left", ls: l.ls }]);
    if (zi >= 0) zGlyph(M, l);
    const at = (x, y) => (x < 0 || y < 0 || x >= LW || y >= LH) ? 0 : M[y * LW + x];
    let top = LH, bot = 0;
    for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) if (M[y * LW + x]) { top = Math.min(top, y); bot = Math.max(bot, y); }
    for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
      const i = y * LW + x, j = i * 4; let c = null;
      if (M[i]) {
        const edge = !at(x + 1, y) || !at(x - 1, y) || !at(x, y + 1) || !at(x, y - 1), v = (y - top) / Math.max(1, bot - top);
        if (l.fill === "oil") {
          const sv = top + 2 + Math.round(Math.sin(x * 0.3) * 0.8), dd = y - sv;
          if (edge) c = "#ffe7a8";
          else if (dd < 0) c = "#141c32";
          else if (dd < 1) c = (x % 9 === 0) ? "#fff3c4" : "#ffd27a";
          else if (((x * 7 + y * 13) % 89) === 0) c = "#ffe08a";
          else if (dd < 3) c = "#ffa424";
          else c = dith(x, y, v * 0.9) ? "#c86a16" : dith(x, y, 0.2 + v * 0.6) ? "#e0831a" : "#ffa424";
        } else {
          c = edge ? "#fffaf0" : dith(x, y, v * 0.7) ? "#d8cdb2" : "#f1e8d2";
        }
      } else if (at(x + 1, y) || at(x - 1, y) || at(x, y + 1) || at(x, y - 1) || at(x + 1, y + 1) || at(x - 1, y - 1)) c = "#04060c";
      else if (at(x - 3, y - 3) || at(x - 2, y - 2)) c = "#05070e";
      if (c) put(d, j, c);
    }
  }
  b.x.putImageData(img, 0, 0);
  return b;
}
// a sea below the horizon (art row `top`) that reflects whatever is already on the canvas, with ripples,
// tinted by a palette; returns the water and a glow layer of its bright pixels
const WATER = {
  blue: { base: ["#0c2246", "#081a38", "#06122a", "#030a1c"], tint: [0.9, 0.95, 1.08], crest: ["#e4f1ff", "#8fbbe3", "#3d6aa8"], line: "#a9d2f5", refl: 0.6 },
  gold: { base: ["#b8741a", "#8f5612", "#663b0c", "#3e2207"], tint: [1.25, 0.95, 0.5], crest: ["#fff4cf", "#ffd27a", "#ffb547"], line: "#fff1c9", refl: 0.75, haze: "255,190,90" },
};
function sea(top, pal, o = {}) {
  const src = buf(LW, LH); src.x.imageSmoothingEnabled = true; src.x.drawImage(cv, 0, 0, LW, LH);
  const sd = src.x.getImageData(0, 0, LW, LH).data;
  const out = buf(LW, LH), img = out.x.createImageData(LW, LH), d = img.data, gl = buf(LW, LH), gimg = gl.x.createImageData(LW, LH), gd = gimg.data;
  const q = (v) => clamp(Math.round(v / 20) * 20, 0, 255);
  for (let y = top; y < LH; y++) {
    const depth = (y - top) / (LH - top);
    for (let x = 0; x < LW; x++) {
      const amp = 0.6 + depth * 7;
      const sx = clamp(Math.round(x + Math.sin(y * 0.9 + x * 0.05) * amp * 0.5 + Math.sin(y * 0.31 - x * 0.021) * amp), 0, LW - 1);
      const sy = clamp(Math.round(top - (y - top) * (o.squash ?? 1) - 1), 0, LH - 1);
      const i = (sy * LW + sx) * 4, j = (y * LW + x) * 4, src3 = [sd[i], sd[i + 1], sd[i + 2]];
      const n = pal.base.length, f = depth * (n - 1), lv = clamp(Math.floor(f) + (dith(x, y, f % 1) ? 1 : 0), 0, n - 1), base = rgb(pal.base[lv]);
      // bright things reflect strongly; the dark sky barely does, so the water keeps its own colour
      const sl = (src3[0] * 0.3 + src3[1] * 0.59 + src3[2] * 0.11) / 255;
      const k = pal.refl * (1 - depth * 0.55) * (dith(x, y, 0.85) ? 1 : 0.7) * clamp(0.15 + sl * 1.6, 0, 1);
      let c = base.map((b0, m) => b0 * (1 - k) + src3[m] * k * pal.tint[m]);
      // crests: short horizontal dashes, tiny and dense at the horizon, longer and sparser close up
      // and a glitter path under the light (o.glint: its x), where crests crowd and brighten
      const row = y - top, hsh = ((row * 2654435761) >>> 0), every = depth < 0.3 ? 2 : 3, gw = o.glint != null ? 6 + depth * 90 : 0;
      const inG = o.glint != null && Math.abs(x - o.glint) < gw, gk = inG ? 1 - Math.abs(x - o.glint) / gw : 0;
      const period = Math.round((14 + depth * 46 + (hsh % 13)) * (inG ? 0.45 + 0.4 * (1 - gk) : 1)), len = Math.round(1 + depth * 8 + (hsh % 3));
      const crest = row % every === 0 && (x + (hsh % period)) % period < len;
      if (crest) { const cc = rgb(inG && gk > 0.35 ? pal.crest[0] : depth < 0.45 || inG ? pal.crest[1] : pal.crest[2]), a = inG ? 0.85 : 0.5 + 0.3 * (1 - depth); c = cc.map((v, m) => v * a + c[m] * (1 - a)); }
      if (y === top) c = rgb(pal.line).map((v, m) => v * 0.7 + c[m] * 0.3);
      c = c.map(q);
      d[j] = c[0]; d[j + 1] = c[1]; d[j + 2] = c[2]; d[j + 3] = 255;
      const lum = (c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11) / 255;
      if (lum > 0.42 || y === top) { gd[j] = c[0]; gd[j + 1] = c[1]; gd[j + 2] = c[2]; gd[j + 3] = 255; }
    }
  }
  out.x.putImageData(img, 0, 0); gl.x.putImageData(gimg, 0, 0);
  return { b: out, glow: gl };
}
// a soft glow band along the horizon (gold water)
function horizonHaze(top, rgbs, alpha = 0.35, h = 260) {
  const y = top * S, g = ctx.createLinearGradient(0, y - h * 0.5, 0, y + h);
  g.addColorStop(0, `rgba(${rgbs},0)`); g.addColorStop(0.33, `rgba(${rgbs},${alpha})`); g.addColorStop(1, `rgba(${rgbs},0)`);
  ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = g; ctx.fillRect(0, y - h * 0.5, W, h * 1.5); ctx.restore();
}
// the logo as a dark silhouette with a lit rim along its top edges (for a bright sea behind it)
function shipSilhouette(x, y, px, body = "#0a0d18", rim = "#ffe7a8") {
  const on = (i, j) => j >= 0 && j < SHIP.length && i >= 0 && i < SHIP[0].length && SHIP[j][i] === "K";
  ctx.save(); ctx.fillStyle = body;
  SHIP.forEach((row, j) => [...row].forEach((ch, i) => { if (ch === "K") ctx.fillRect(x + i * px, y + j * px, px, px); }));
  ctx.fillStyle = rim; const t = Math.max(3, Math.round(px / 5));
  SHIP.forEach((row, j) => [...row].forEach((ch, i) => { if (ch !== "K") return; if (!on(i, j - 1)) ctx.fillRect(x + i * px, y + j * px, px, t); if (!on(i + 1, j)) ctx.fillRect(x + (i + 1) * px - t, y + j * px, t, px); }));
  ctx.restore();
}
// the logo with a strip of water on the same pixel grid: rows 5-7 under and around the hull, two cells wider
// than the ship each side. kind: "blue" or "gold"
const LOGO_SEA = {
  blue: { c: "#a9d2f5", w: "#2460a8", d: "#163a6c", f: "#e4f1ff" },
  gold: { c: "#fff6d6", w: "#f2bd2c", d: "#c88a16", f: "#fff1c9" },
};
// symmetric about the hull: 20 cells, three either side of the ship's 14
const SEA_ROWS = [
  ["cw.ff..........ff.wc", 5],
  [".wcwwdwwcwwcwwdwwcw.", 6],
  ["..dwwdwwcwwcwwdwwd..", 7],
];
function logoSea(x, y, px, kind = "blue", o = {}) {
  const pal = LOGO_SEA[kind], ship = o.ship || P.oil;
  const cells = [];
  SHIP.forEach((row, j) => [...row].forEach((ch, i) => { if (ch === "K") cells.push([i, j, ship]); }));
  for (const [row, j] of SEA_ROWS) [...row].forEach((ch, k) => { const i = k - 3; if (pal[ch] && !(SHIP[j] && SHIP[j][i] === "K")) cells.push([i, j, pal[ch]]); });
  const draw = (c2) => {
    if (o.outline) { c2.fillStyle = P.ink; for (const [i, j] of cells) c2.fillRect(x + i * px - o.outline, y + j * px - o.outline, px + 2 * o.outline, px + 2 * o.outline); }
    c2.fillStyle = P.ink; for (const [i, j] of cells) c2.fillRect(x + i * px + (o.shadow ?? 10), y + j * px + (o.shadow ?? 10), px, px);
    const shipCells = cells.filter((c3) => c3[2] === ship), waterCells = cells.filter((c3) => c3[2] !== ship);
    for (const [i, j, col] of waterCells) { c2.fillStyle = col; c2.fillRect(x + i * px, y + j * px, px, px); }
    if (o.shipLine) { c2.fillStyle = P.ink; for (const [i, j] of shipCells) c2.fillRect(x + i * px - o.shipLine, y + j * px - o.shipLine, px + 2 * o.shipLine, px + 2 * o.shipLine); }
    for (const [i, j, col] of shipCells) { c2.fillStyle = col; c2.fillRect(x + i * px, y + j * px, px, px); }
  };
  if (o.glow) { const off = document.createElement("canvas"); off.width = W; off.height = H; const ox = off.getContext("2d"); draw(ox);
    ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = o.glow; ctx.filter = "blur(22px)"; ctx.drawImage(off, 0, 0); ctx.restore(); ctx.drawImage(off, 0, 0); }
  else draw(ctx);
}
// the countries the arcs end in, as Map iso3 -> "oil" | "gas" (oil wins where both land). Only arcs whose end
// faces us (as arcs() draws them). Matched by name (oil: the app's country names) or ISO3 (LNG buyers); a buyer
// with no polygon at this scale (Singapore) is left unlit rather than guessed.
function destCountries(list, rot, minZ = 0.05) {
  const R = d3.geoRotation(rot), F = window.COUNTRIES.features, out = new Map();
  const faces = (ll) => { const [l, p] = R(ll).map((v) => v * Math.PI / 180); return Math.cos(p) * Math.cos(l) >= minZ; };
  for (const A of list) {
    if (!faces(A.b)) continue;
    const f = F.find((g) => g.properties.name === A.name || g.properties.iso3 === A.name);
    if (!f) continue;
    const iso = f.properties.iso3;
    if (A.kind === "oil" || !out.has(iso)) out.set(iso, A.kind);
  }
  return out;
}
// colour helpers for highlighted buyers: a 6-step ramp from the night land up to a hue, subtle or bright,
// and a 4-tone ramp for an arc in that hue
function hueRamp(hex, bright) {
  const ts = bright ? [0.34, 0.48, 0.62, 0.76, 0.9, 1] : [0.12, 0.19, 0.27, 0.36, 0.46, 0.58];
  return ts.map((t) => d3.color(d3.interpolateLab("#0b0f1c", hex)(t)).formatHex());
}
function arcRamp(hex) { const c = d3.color(hex); return [d3.interpolateLab("#0b0f1c", hex)(0.45), c.formatHex(), d3.interpolateLab(hex, "#ffffff")(0.35), d3.interpolateLab(hex, "#ffffff")(0.8)].map((v) => d3.color(v).formatHex()); }
// the buyer's ISO3 for an arc (name for oil, ISO3 for LNG), or null if it has no polygon here
function destIso(A) { const f = window.COUNTRIES.features.find((g) => g.properties.name === A.name || g.properties.iso3 === A.name); return f ? f.properties.iso3 : null; }
// one colour per buyer, picked to sit apart from each other and from the amber title
const BUYER = { CHN: "#ff5a5f", IND: "#ffb547", JPN: "#ff7ab8", KOR: "#8fd0f5", TWN: "#7ee0b0", THA: "#c49bff", VNM: "#5ad1c9", PHL: "#ffd166",
  IDN: "#9be15d", PAK: "#5aa9ff", NLD: "#ff9f5a", ITA: "#e07bff", BGD: "#4fe3a0", USA: "#8fb3ff", SGP: "#f1e8d2" };
