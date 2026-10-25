// 1. skyline: the landing page's night refinery, wide, with the riveted title plate in the sky
LOOP = 3000;
const B = buf(320, 180), X = B.x, HZ = 124;
const r = rng(11);
const stars = Array.from({ length: 110 }, () => ({ x: r() * 320 | 0, y: r() * 108 | 0, b: r(), p: r() }));
// static layer: sky, moon, far city, refinery
const S = buf(320, 180);
const SKY = ["#03051a", "#070b26", "#0d1236", "#161843", "#231c4a", "#3a2148", "#4e2a52"];
paint(S, (x, y) => {
  if (y >= HZ) return null;
  let v = y / HZ; v = v * v * 0.6 + v * 0.4;
  const glow = Math.exp(-((x - 222) ** 2) / 1800) * Math.max(0, (y - 20) / 104) * 1.1 + Math.max(0, (y - 96) / 28) * 0.5;   // flare glow and horizon haze
  const k = clamp(v * (SKY.length - 2) + glow * 1.2, 0, SKY.length - 1.001), i = Math.floor(k);
  return dith(x, y, k - i) ? SKY[i + 1] : SKY[i];
});
// moon with a dithered halo
const MX = 262, MY = 34;
paint(S, (x, y) => {
  const d = Math.hypot(x - MX, y - MY);
  if (d <= 11) { const crater = (Math.hypot(x - MX + 3, y - MY + 2) < 3) || (Math.hypot(x - MX - 4, y - MY - 3) < 2) || (Math.hypot(x - MX - 2, y - MY + 5) < 1.6);
    const shade = x - MX + (y - MY) * 0.4 > 6; return crater ? "#c9bfa6" : shade ? "#ddd2b8" : "#f6eedb"; }
  if (d < 22 && dith(x, y, (22 - d) / 11 * 0.35)) return "#2a2a5a";
  return null;
}, MX - 24, MY - 24, 48, 48);
// far city
const city = []; { let cx = 0; const rr = rng(3); while (cx < 320) { const w = 5 + (rr() * 12 | 0), h = 5 + (rr() * 16 | 0); city.push({ x: cx, w, h }); cx += w + (rr() * 3 | 0); } }
for (const c of city) { fr(S.x, "#0f1530", c.x, HZ - 6 - c.h, c.w, c.h + 6); fr(S.x, "#151c3c", c.x, HZ - 6 - c.h, c.w, 1); }
const wins = []; { const rr = rng(5); for (const c of city) for (let i = 0; i < c.w * c.h / 14; i++) wins.push({ x: c.x + 1 + (rr() * (c.w - 2) | 0), y: HZ - 5 - c.h + 1 + (rr() * (c.h - 1) | 0), p: rr(), on: rr() < 0.55 }); }
// refinery silhouettes
const SIL = "#0c1326", EDGE = "#24325c", RING = "#17213e";
const lamps = [];
function column(x, w, h) { fr(S.x, SIL, x, HZ - h, w, h); fr(S.x, EDGE, x + w - 1, HZ - h, 1, h); for (let y = HZ - h + 4; y < HZ - 2; y += 6) fr(S.x, RING, x - 1, y, w + 2, 1); fr(S.x, SIL, x + 1, HZ - h - 3, w - 2, 3); lamps.push([x + (w >> 1), HZ - h - 4, "r"]); for (let y = HZ - h + 8; y < HZ - 4; y += 12) lamps.push([x - 1, y, "a"]); }
function tank(x, w, h) { fr(S.x, SIL, x, HZ - h, w, h); fr(S.x, EDGE, x + 1, HZ - h, w - 2, 1); fr(S.x, SIL, x + 2, HZ - h - 2, w - 4, 2); fr(S.x, RING, x, HZ - h + 4, w, 1); fr(S.x, RING, x, HZ - h + 9, w, 1);
  for (let y = HZ - h; y < HZ; y += 2) fr(S.x, EDGE, x + w - 4, y, 1, 1); lamps.push([x + 3, HZ - h - 1, "a"], [x + w - 4, HZ - h - 1, "a"]); }
function stack(x, w, h) { fr(S.x, SIL, x, HZ - h, w, h); fr(S.x, EDGE, x + w - 1, HZ - h, 1, h); fr(S.x, "#2a1a20", x, HZ - h + 3, w, 2); fr(S.x, "#2a1a20", x, HZ - h + 10, w, 2); lamps.push([x + (w >> 1), HZ - h - 1, "r"]); }
// pipe rack and ground
fr(S.x, "#0a0f1d", 0, HZ - 2, 320, 8); fr(S.x, "#1e2a48", 0, HZ - 2, 320, 1);
for (let x = 40; x < 310; x += 9) fr(S.x, SIL, x, HZ - 10, 1, 9);
fr(S.x, EDGE, 40, HZ - 10, 270, 1); fr(S.x, SIL, 40, HZ - 8, 270, 2); fr(S.x, RING, 40, HZ - 6, 270, 1);
// flare stack lattice
const FX = 222, FH = 88;
for (let y = HZ - FH; y < HZ; y++) { const w = 1 + Math.floor((y - (HZ - FH)) / 26); fr(S.x, SIL, FX - w, y, 2 * w + 2, 1); if ((y + FX) % 6 === 0) fr(S.x, EDGE, FX - w, y, 2 * w + 2, 1); }
fr(S.x, EDGE, FX, HZ - FH - 2, 2, 2);
column(238, 7, 60); column(248, 5, 46); column(180, 6, 40);
tank(118, 30, 17); tank(152, 22, 13); tank(194, 16, 10); tank(60, 24, 12);
stack(268, 5, 70); stack(280, 4, 54);
// crane
fr(S.x, SIL, 304, HZ - 44, 3, 44); fr(S.x, SIL, 286, HZ - 44, 24, 2); fr(S.x, EDGE, 286, HZ - 44, 24, 1); fr(S.x, "#273150", 292, HZ - 42, 1, 12);
lamps.push([287, HZ - 45, "r"]);
// jetty
fr(S.x, SIL, 196, HZ + 4, 62, 2); for (let x = 198; x < 258; x += 8) fr(S.x, SIL, x, HZ + 6, 1, 5);
// the tanker
const T = { x: 96, y: 154, w: 92 };

function draw(t) {
  const p = ph(t);
  X.drawImage(S.c, 0, 0);
  // stars twinkle
  for (const s of stars) { const v = 0.5 + 0.5 * Math.sin(TAU * (p * 2 + s.p)); if (s.b > 0.7) fr(X, v > 0.4 ? "#f1e8d2" : "#8a8fb0", s.x, s.y); else if (v > 0.55) fr(X, "#5a6090", s.x, s.y); }
  // city windows
  for (const w of wins) if (w.on && Math.sin(TAU * (p + w.p)) > -0.8) fr(X, w.p > 0.85 ? "#ffd27a" : "#c98a3a", w.x, w.y);
  // sea, per pixel: depth bands, moving wave glints, moon and flare reflections
  paint(B, (x, y) => {
    const d = (y - HZ - 6) / 50;
    let c = d < 0.15 ? "#0b2240" : d < 0.5 ? (dith(x, y, (d - 0.15) / 0.35) ? "#081a36" : "#0b2240") : (dith(x, y, (d - 0.5) / 0.5) ? "#06122a" : "#081a36");
    const wv = Math.sin(x * 0.21 + y * 1.9 - TAU * p * 2) + Math.sin(x * 0.07 - y * 0.8 + TAU * p);
    if (wv > 1.55) c = "#16345e";
    const mr = Math.abs(x - MX + (y - HZ) * 0.05);
    if (mr < 6 - d * 3 && Math.sin(y * 2.3 + x * 0.6 - TAU * p * 3) > 0.35) c = mr < 2 ? "#f1e8d2" : "#8f8a9a";
    const fx = Math.abs(x - FX - 1);
    if (fx < 4 && Math.sin(y * 2.1 - TAU * p * 4 + x) > 0.5 && y < HZ + 34) c = fx < 1.5 ? "#ffbf5c" : "#c26f12";
    return c;
  }, 0, HZ + 6, 320, 180 - HZ - 6);
  // lamps on the plant, and their wobbling reflections
  for (const [lx, ly, k] of lamps) {
    const on = k === "r" ? Math.sin(TAU * (p * 2 + lx * 0.013)) > -0.2 : true;
    if (on) fr(X, k === "r" ? "#ff4d3a" : "#ffbf5c", lx, ly);
    if (k === "a" && ly > HZ - 30 && Math.sin(TAU * (p * 3 + lx * 0.1)) > 0) fr(X, "#7a5222", lx + Math.round(Math.sin(TAU * p * 2 + lx)), HZ + 8 + ((lx * 7) % 14));
  }
  // flare flame and glow
  const fl = Math.sin(TAU * p * 4) * 1.5 + Math.sin(TAU * p * 7 + 1) * 1.2, top = HZ - FH - 3;
  paint(B, (x, y) => {
    const dx = x - FX - 1, dy = top - y; if (dy < -1) return null;
    const hgt = 16 + fl * 1.4, wdt = 4.2 * (1 - dy / (hgt + 1)) + Math.sin(dy * 0.9 + TAU * p * 6) * 0.6;
    if (dy <= hgt && Math.abs(dx) <= wdt) { const k = dy / hgt; return Math.abs(dx) < wdt * 0.45 && k < 0.6 ? "#fff3c4" : k < 0.75 ? "#ffa424" : "#ff6a4d"; }
    const g = Math.hypot(dx, dy - 7); if (g < 20 && dith(x, y, (20 - g) / 20 * 0.38)) return g < 9 ? "#7a3a2a" : "#5a2a30";
    return null;
  }, FX - 22, top - 30, 46, 40);
  // smoke from the stacks
  for (const [sx, sy] of [[270, HZ - 71], [282, HZ - 55]]) for (let k = 0; k < 6; k++) {
    const s = (p + k / 6) % 1, cx = sx + s * 22 + Math.sin(TAU * s * 2 + k) * 2, cy = sy - s * 34, rr = 1.5 + s * 5;
    for (let dy = -rr; dy <= rr; dy++) for (let dx = -rr; dx <= rr; dx++) if (dx * dx + dy * dy <= rr * rr && dith(Math.round(cx + dx), Math.round(cy + dy), (1 - s) * 0.7)) fr(X, s < 0.4 ? "#3a4867" : "#273150", cx + dx, cy + dy);
  }
  // a dark tanker far out: no lights, AIS off
  { const gx = 262 - Math.round(p * 6), gy = 138 + Math.round(Math.sin(TAU * p + 1) * 0.5);
    for (let y = 0; y < 4; y++) fr(X, "#070d1c", gx + Math.max(0, 3 - y), gy + y, 40 - Math.max(0, 3 - y), 1);
    fr(X, "#070d1c", gx + 32, gy - 5, 6, 5); fr(X, "#070d1c", gx + 34, gy - 8, 2, 3); }
  // the tanker, bobbing, with its wake
  const bob = Math.round(Math.sin(TAU * p) * 0.8), ty = T.y + bob, tx = T.x;
  for (let i = 0; i < 14; i++) { const wx = tx + T.w + 1 + i * 3 + ((p * 18) % 3), wy = ty + (i % 2); if (Math.sin(i * 1.7 + TAU * p * 2) > -0.3) fr(X, i < 6 ? "#8fa4c8" : "#3a5480", wx, wy, 2, 1); }
  for (let y = 0; y < 9; y++) { const bow = Math.max(0, 7 - y * 1.4) | 0, stern = y > 6 ? (y - 6) : 0; fr(X, y >= 7 ? "#7a2f22" : y === 0 ? "#2a3450" : "#151b2e", tx + bow, ty + y - 7, T.w - bow - stern, 1); }
  for (let i = 0; i < 9; i++) { fr(X, "#2f3a58", tx + 10 + i * 7, ty - 9, 4, 2); fr(X, "#1f2840", tx + 10 + i * 7, ty - 7, 4, 1); }
  fr(X, "#3a4867", tx + 8, ty - 10, T.w - 26, 1);
  fr(X, "#1c2338", tx + T.w - 18, ty - 20, 14, 13); fr(X, "#2f3a58", tx + T.w - 18, ty - 20, 14, 1); fr(X, "#1c2338", tx + T.w - 13, ty - 27, 3, 7); fr(X, "#7a2f22", tx + T.w - 13, ty - 27, 3, 2);
  for (let i = 0; i < 5; i++) { fr(X, "#ffbf5c", tx + T.w - 17 + i * 2.6, ty - 17, 1, 1); fr(X, Math.sin(TAU * p + i) > 0 ? "#ffd27a" : "#c98a3a", tx + T.w - 17 + i * 2.6, ty - 13, 1, 1); }
  fr(X, "#f1e8d2", tx + T.w - 12, ty - 28); fr(X, Math.sin(TAU * p * 2) > 0 ? "#ff4d3a" : "#5a1a14", tx + 3, ty - 9); fr(X, "#7fe08a", tx + T.w - 4, ty - 8);
  for (let i = 0; i < T.w; i += 3) if (Math.sin(i * 0.9 + TAU * p * 2) > 0.2) fr(X, "#1d3a66", tx + i, ty + 2, 2, 1);
  up(B);
  // title
  const kx = 76;
  txt("STRAIT OF HORMUZ · 2026", kx, 128, { size: 26, w: 700, color: P.oilSoft, ls: 3 });
  const tw = measure("Hormuz Flow", { size: 112 });
  plate(kx - 6, 152, tw + 72, 150);
  parts([["Hormuz ", P.text], ["Flow", P.oil]], kx + 30, 266, { size: 112, shadow: 6 });
  txt("The strait is closing. Follow the oil.", kx, 362, { size: 34, w: 400, color: P.text, shadow: 3 });
}
boot(draw, 900);
