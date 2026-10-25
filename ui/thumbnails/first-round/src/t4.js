// 4. globe: a pixel night globe turning under Hormuz, oil arcs (amber) and LNG arcs (violet) running out of the Gulf
LOOP = 4000;
const LW = 320, LH = 180, B = buf(LW, LH), X = B.x;
const G = buf(LW, LH);
const CXg = 222, CYg = 92, RG = 76;
const proj = d3.geoOrthographic().scale(RG).translate([CXg, CYg]).clipAngle(90).precision(0.3);
const path = d3.geoPath(proj, G.x), grat = d3.geoGraticule10();
const land = { type: "FeatureCollection", features: window.COUNTRIES.features };
const QUANT = ["#04060c", "#08183a", "#0b2240", "#0e2a50", "#2c3a60", "#34446c", "#56688f", "#5b6d95", "#11305a"].map((h) => [h, rgb(h)]);
const HZ = [56.4, 26.5], QA = [51.6, 25.9];
const OIL = [[121.5, 31], [139.8, 35.1], [129, 35.1], [72.8, 19], [103.8, 1.3], [4.3, 51.9], [120.3, 22.6]];
const LNG = [[119.5, 29.9], [72.6, 21.7], [126.6, 37], [12.3, 45.1], [67, 24.8]];
const arcs = [...OIL.map((b, i) => ({ a: HZ, b, c: "oil", o: i / OIL.length })), ...LNG.map((b, i) => ({ a: QA, b, c: "gas", o: 0.13 + i / LNG.length }))];
const r = rng(9);
const stars = Array.from({ length: 140 }, () => ({ x: r() * LW | 0, y: r() * LH | 0, b: r(), p: r() }));
function draw(t) {
  const p = ph(t);
  const lon = 62 + 22 * Math.sin(TAU * p), lat = 22 + 4 * Math.cos(TAU * p);
  proj.rotate([-lon, -lat]);
  // the globe, drawn smooth on its own buffer, then snapped to the palette so it stays pixel-crisp
  G.x.clearRect(0, 0, LW, LH);
  G.x.beginPath(); path({ type: "Sphere" }); G.x.fillStyle = "#0b2240"; G.x.fill();
  G.x.beginPath(); path(grat); G.x.strokeStyle = "#11305a"; G.x.lineWidth = 1; G.x.stroke();
  G.x.beginPath(); path(land); G.x.fillStyle = "#2c3a60"; G.x.fill(); G.x.strokeStyle = "#56688f"; G.x.lineWidth = 0.6; G.x.stroke();
  const img = G.x.getImageData(0, 0, LW, LH), d = img.data;
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const i = (y * LW + x) * 4; if (d[i + 3] < 100) { d[i + 3] = 0; continue; }
    let best = null, bd = 1e9; for (const [, c] of QUANT) { const dd = (c[0] - d[i]) ** 2 + (c[1] - d[i + 1]) ** 2 + (c[2] - d[i + 2]) ** 2; if (dd < bd) { bd = dd; best = c; } }
    // night side: dither the left limb darker
    const dx = (x - CXg) / RG, dy = (y - CYg) / RG, lit = dx * 0.75 - dy * 0.35;
    if (lit < -0.35 && dith(x, y, Math.min(1, (-0.35 - lit) * 1.6))) best = best === QUANT[4][1] || best === QUANT[5][1] ? QUANT[2][1] : QUANT[1][1];
    d[i] = best[0]; d[i + 1] = best[1]; d[i + 2] = best[2]; d[i + 3] = 255;
  }
  G.x.putImageData(img, 0, 0);
  // sky, stars, atmosphere
  X.fillStyle = "#03051a"; X.fillRect(0, 0, LW, LH);
  paint(B, (x, y) => { const v = y / LH; return dith(x, y, v * 0.8) ? "#070b26" : null; });
  for (const s of stars) { const v = Math.sin(TAU * (p * 3 + s.p)); if (s.b > 0.75 ? v > -0.5 : v > 0.6) fr(X, s.b > 0.9 ? "#f1e8d2" : "#5a6090", s.x, s.y); }
  paint(B, (x, y) => { const dd = Math.hypot(x - CXg, y - CYg) - RG; if (dd < 0 || dd > 9) return null; return dith(x, y, (1 - dd / 9) * 0.75) ? (dd < 3 ? "#2a5a9a" : "#16345e") : null; }, CXg - RG - 10, CYg - RG - 10, RG * 2 + 20, RG * 2 + 20);
  X.drawImage(G.c, 0, 0);
  // arcs: great circles lifted off the surface, each with a bright pulse running from the Gulf
  const ctr = [lon, lat];
  for (const A of arcs) {
    const ip = d3.geoInterpolate(A.a, A.b), dist = d3.geoDistance(A.a, A.b), n = Math.max(24, Math.round(dist * 60));
    const head = (p * 2 + A.o) % 1, col = A.c === "oil" ? ["#ffa424", "#fff3c4", "#b0671c"] : ["#b58cff", "#efe2ff", "#7a5cc0"];
    for (let k = 0; k <= n; k++) {
      const s = k / n, g = ip(s);
      if (d3.geoDistance(g, ctr) > Math.PI / 2 - 0.02) continue;
      const q = proj(g), lift = 1 + 0.22 * Math.sin(Math.PI * s) * Math.min(1, dist * 1.2);
      const x = CXg + (q[0] - CXg) * lift, y = CYg + (q[1] - CYg) * lift;
      const dh = (head - s + 1) % 1, glow = dh < 0.2 ? 1 - dh / 0.2 : 0;
      fr(X, col[2], x, y);
      if (glow > 0) { fr(X, glow > 0.85 ? col[1] : col[0], x, y); if (glow > 0.5) { fr(X, col[0], x + 1, y); fr(X, col[0], x, y + 1); } if (glow > 0.9) { fr(X, col[1], x + 1, y + 1); fr(X, col[0], x - 1, y); fr(X, col[0], x, y - 1); } }
    }
    const e = proj(A.b); if (d3.geoDistance(A.b, ctr) < Math.PI / 2 - 0.05) { fr(X, P.ink, e[0] - 1, e[1] - 1, 3, 3); fr(X, Math.sin(TAU * (p * 2 + A.o)) > 0 ? col[1] : col[0], e[0], e[1]); }
  }
  // Hormuz: a blinking red marker with an expanding ring
  const hq = proj(HZ);
  if (d3.geoDistance(HZ, ctr) < Math.PI / 2) {
    const rr = 2 + ph(t, 1000) * 9;
    for (let q = 0; q < 28; q++) { const a = q / 28 * TAU; if (dith(q, 2, 1 - ph(t, 1000))) fr(X, "#ff6a4d", hq[0] + Math.cos(a) * rr, hq[1] + Math.sin(a) * rr); }
    fr(X, "#04060c", hq[0] - 1, hq[1] - 1, 3, 3); fr(X, "#ff6a4d", hq[0], hq[1]);
  }
  up(B);
  txt("Hormuz", 70, 300, { size: 128, shadow: 7 });
  txt("Flow", 70, 420, { size: 128, color: P.oil, shadow: 7 });
  txt("Where the oil goes.", 74, 490, { size: 36, w: 400, color: P.text, shadow: 3 });
  ctx.fillStyle = P.ink; ctx.fillRect(74, 572, 24, 24); ctx.fillStyle = P.oil; ctx.fillRect(77, 575, 18, 18);
  txt("OIL", 110, 594, { font: "mono", w: 400, size: 34, color: P.oilSoft, shadow: 2 });
  ctx.fillStyle = P.ink; ctx.fillRect(184, 572, 24, 24); ctx.fillStyle = P.gas; ctx.fillRect(187, 575, 18, 18);
  txt("LNG", 220, 594, { font: "mono", w: 400, size: 34, color: "#d6c2ff", shadow: 2 });
  if (d3.geoDistance(HZ, ctr) < Math.PI / 2) txt("HORMUZ", hq[0] * 4 - 26, hq[1] * 4 - 44, { font: "mono", w: 400, size: 26, color: P.harm, align: "right", shadow: 2 });
}
boot(draw, 900);
