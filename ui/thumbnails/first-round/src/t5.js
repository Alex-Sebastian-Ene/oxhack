// 5. gauge: a big red valve wheel and a pressure gauge rattling in the red at 69% lost (the simulated Aug 2026 scenario)
LOOP = 3000;
const B = buf(320, 180), X = B.x;
const S = buf(320, 180);
// riveted steel wall
paint(S, (x, y) => {
  const px = x % 64, py = (y + 8) % 45;
  if (px === 0 || py === 0) return "#05070e";
  if (px === 1 || py === 1) return "#1c2640";
  if ((px === 4 || px === 60) && (py === 4 || py === 41)) return "#3a4867";
  if ((px === 5 || px === 61) && (py === 5 || py === 42)) return "#05070e";
  const g = Math.sin(x * 0.7 + y * 0.05) > 0.97;
  return g ? "#151d33" : dith(x, y, y / 180 * 0.6) ? "#0c1222" : "#10172b";
});
// pipes: one runs behind from the valve to the gauge, others leave the frame
function pipeH(x0, x1, y, w = 8) { fr(S.x, "#04060c", x0, y - 1, x1 - x0, w + 2); fr(S.x, P.steelLo, x0, y, x1 - x0, w); fr(S.x, P.steel, x0, y + 1, x1 - x0, w - 3); fr(S.x, P.steelHi, x0, y + 1, x1 - x0, 1);
  for (let x = x0 + 10; x < x1 - 4; x += 30) { fr(S.x, "#04060c", x - 1, y - 2, 6, w + 4); fr(S.x, P.steelLo, x, y - 1, 4, w + 2); fr(S.x, P.steelHi, x, y - 1, 1, w + 2); } }
function pipeV(x, y0, y1, w = 8) { fr(S.x, "#04060c", x - 1, y0, w + 2, y1 - y0); fr(S.x, P.steelLo, x, y0, w, y1 - y0); fr(S.x, P.steel, x + 1, y0, w - 3, y1 - y0); fr(S.x, P.steelHi, x + 1, y0, 1, y1 - y0);
  for (let y = y0 + 8; y < y1 - 4; y += 28) { fr(S.x, "#04060c", x - 2, y - 1, w + 4, 6); fr(S.x, P.steelLo, x - 1, y, w + 2, 4); fr(S.x, P.steelHi, x - 1, y, w + 2, 1); } }
pipeH(0, 320, 150, 9); pipeV(70, 112, 180, 10); pipeV(250, 120, 180, 8); pipeH(104, 214, 118, 8);
const VX = 72, VY = 108, VR = 44, GX = 250, GY = 104, GR = 46;
const GSTART = Math.PI * 0.75, GSWEEP = Math.PI * 1.5;   // 0% at bottom left, 100% at bottom right, clockwise
const r = rng(8);
function draw(t) {
  const p = ph(t);
  X.drawImage(S.c, 0, 0);
  // sight glass on the cross pipe: a few slugs of oil, sparse, since most of the flow is gone
  fr(X, "#04060c", 132, 117, 56, 10); fr(X, "#0b1020", 133, 119, 54, 6);
  for (let k = 0; k < 3; k++) { const sx = 133 + ((p * 54 + k * 18) % 54); for (let i = 0; i < 5; i++) if (sx + i < 187) fr(X, i === 4 ? "#ffd27a" : "#ffa424", sx + i, 120, 1, 4); }
  fr(X, "#3a4867", 133, 119, 54, 1);
  // valve wheel, turning a sixth of a turn per loop (six spokes, so the GIF loops)
  const va = p * TAU / 6;
  paint(B, (x, y) => {
    const dx = x - VX, dy = y - VY, d = Math.hypot(dx, dy); if (d > VR + 2) return null;
    const ang = Math.atan2(dy, dx), light = -(dx + dy) / (d + 0.01);
    if (d > VR) return "#04060c";
    if (d > VR - 8) { const grip = Math.sin((ang - va) * 18) > 0.6 && d > VR - 3; const c = light > 0.45 ? "#ff6a4d" : light < -0.45 ? "#8a1f18" : "#e0412e"; return grip ? "#b5301f" : (d > VR - 1.2 || d < VR - 7) ? "#5a140e" : c; }
    if (d < 10) { if (d > 8.8) return "#04060c"; return d < 3 ? "#f1e8d2" : light > 0.3 ? P.steelHi : light < -0.3 ? P.steelLo : P.steel; }
    let a = (ang - va) % (TAU / 6); if (a < 0) a += TAU / 6;
    const off = Math.min(a, TAU / 6 - a) * d;
    if (off < 3.2) return off > 2.3 ? "#5a140e" : light > 0.2 ? "#ff6a4d" : "#c2321f";
    return null;
  }, VX - VR - 3, VY - VR - 3, VR * 2 + 6, VR * 2 + 6);
  // gauge
  const val = 0.69 + 0.012 * Math.sin(TAU * p * 6) + 0.007 * Math.sin(TAU * p * 15);
  paint(B, (x, y) => {
    const dx = x - GX, dy = y - GY, d = Math.hypot(dx, dy); if (d > GR + 2) return null;
    if (d > GR) return "#04060c";
    const light = -(dx + dy) / (d + 0.01);
    if (d > GR - 6) return light > 0.4 ? P.steelHi : light < -0.4 ? "#1f2840" : P.steel;
    if (d > GR - 7) return "#04060c";
    let a = Math.atan2(dy, dx) - GSTART; while (a < 0) a += TAU; const f = a / GSWEEP;
    if (f <= 1 && d > GR - 15 && d < GR - 10) { if (f > 0.6) return "#e0412e"; if (f > 0.4) return "#ffa424"; }
    if (f <= 1 && d > GR - 11 && d < GR - 7) { const tk = f * 10, near = Math.abs(tk - Math.round(tk)); if (near < 0.05 * (GR / d)) return "#04060c"; const tk2 = f * 50; if (Math.abs(tk2 - Math.round(tk2)) < 0.08 && d > GR - 9) return "#4a4436"; }
    return dith(x, y, Math.max(0, (d - (GR - 18)) / 14) * 0.5) ? "#e2d6bc" : "#f1e8d2";
  }, GX - GR - 3, GY - GR - 3, GR * 2 + 6, GR * 2 + 6);
  // needle
  const na = GSTART + val * GSWEEP;
  for (let k = -6; k <= GR - 12; k++) { const x = GX + Math.cos(na) * k, y = GY + Math.sin(na) * k; fr(X, k > GR - 22 ? "#e0412e" : "#04060c", x, y, 2, 2); }
  disc(X, "#04060c", GX, GY, 5); disc(X, P.steelLo, GX, GY, 4); fr(X, P.steelHi, GX - 1, GY - 2, 2, 1);
  // red warning lamp on top of the gauge
  const on = Math.sin(TAU * p * 3) > 0;
  fr(X, "#04060c", GX - 5, GY - GR - 9, 11, 8); disc(X, on ? "#ff4d3a" : "#5a1a14", GX, GY - GR - 6, 3);
  if (on) paint(B, (x, y) => { const d = Math.hypot(x - GX, y - (GY - GR - 6)); return d > 4 && d < 13 && dith(x, y, (13 - d) / 9 * 0.5) ? "#7a2a2a" : null; }, GX - 14, GY - GR - 20, 29, 28);
  // steam from the joint between them
  for (const [sx0, sy0, dir] of [[150, 146, 1], [178, 146, -1]]) for (let k = 0; k < 7; k++) {
    const s = (p * 2 + k / 7) % 1, cx = sx0 + dir * s * 12 + Math.sin(TAU * s * 2 + k) * 2, cy = sy0 - 2 - s * 18, rr = 2 + s * 7;
    for (let dy = -rr; dy <= rr; dy++) for (let dx = -rr; dx <= rr; dx++) if (dx * dx + dy * dy <= rr * rr && dith(Math.round(cx + dx), Math.round(cy + dy), (1 - s) * 0.7)) fr(X, s < 0.3 ? "#f1e8d2" : s < 0.6 ? "#c4baa3" : "#5b6d95", cx + dx, cy + dy);
  }
  up(B);
  // gauge face text
  const gx = GX * 4, gy = GY * 4;
  txt("LOST", gx, gy + 62, { font: "mono", w: 400, size: 34, color: "#3a3426", align: "center", shadow: 0 });
  txt("69%", gx, gy + 128, { font: "mono", w: 400, size: 76, color: "#b5301f", align: "center", shadow: 0 });
  txt("0", gx - 84, gy + 100, { font: "mono", w: 400, size: 30, color: "#3a3426", align: "center", shadow: 0 });
  txt("100", gx + 80, gy + 100, { font: "mono", w: 400, size: 30, color: "#3a3426", align: "center", shadow: 0 });
  txt("SIMULATED · AUG 2026 SCENARIO", 640, 214, { font: "mono", w: 400, size: 26, color: P.muted, align: "center", shadow: 2 });
  // title plate
  const tw = measure("Hormuz Flow", { size: 96 });
  plate(640 - tw / 2 - 36, 40, tw + 72, 128);
  parts([["Hormuz ", P.text], ["Flow", P.oil]], 640 - tw / 2, 140, { size: 96, shadow: 5 });
}
boot(draw, 400);
