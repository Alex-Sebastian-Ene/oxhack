// 3. pour: a valve opens over the title and crude fills the letters, splashing where it lands
LOOP = 4000;
const B = buf(320, 180), X = B.x;
let M = null, OUT = null, glyph = null, mTop = 0, mBot = 0, nozX = 0;
const S = buf(320, 180);
// wall of riveted panels
paint(S, (x, y) => {
  const px = (x + (Math.floor(y / 30) % 2) * 20) % 40, py = y % 30;
  if (py === 0 || px === 0) return "#060914";
  if (py === 1 || px === 1) return "#151d33";
  if ((px === 4 || px === 36) && (py === 4 || py === 26)) return "#2a3550";
  const v = (y / 180) * 0.7;
  return dith(x, y, v) ? "#0b1020" : "#0e1428";
});
function prep() {
  const lines = [{ s: "HORMUZ", x: 160, y: 98, size: 60 }, { s: "FLOW", x: 160, y: 164, size: 66 }];
  M = textMask(320, 180, lines);
  const at = (x, y) => (x < 0 || y < 0 || x >= 320 || y >= 180) ? 0 : M[y * 320 + x];
  OUT = new Uint8Array(320 * 180); glyph = new Uint8Array(320 * 180);
  mTop = 999; mBot = 0;
  for (let y = 0; y < 180; y++) for (let x = 0; x < 320; x++) {
    const i = y * 320 + x;
    if (M[i]) { mTop = Math.min(mTop, y); mBot = Math.max(mBot, y); if (!at(x + 1, y) || !at(x - 1, y) || !at(x, y + 1) || !at(x, y - 1)) glyph[i] = 1; }
    else if (at(x + 1, y) || at(x - 1, y) || at(x, y + 1) || at(x, y - 1) || at(x + 1, y + 1) || at(x - 1, y - 1)) OUT[i] = 1;
  }
  // the nozzle sits over the O of HORMUZ
  X.font = FONT({ size: 60 }); const w = X.measureText("HORMUZ").width, h = X.measureText("H").width, o = X.measureText("O").width;
  nozX = Math.round(160 - w / 2 + h + o / 2);
}
const r = rng(4);
const drops = Array.from({ length: 28 }, () => ({ vx: (r() - 0.5) * 2.4, vy: 1.4 + r() * 2.2, ph: r(), lit: r() < 0.5 }));
function draw(t) {
  if (!M) prep();
  const p = ph(t);
  // fill for 85% of the loop, then a quick drain out of the bottom
  const f = p < 0.85 ? ease(p / 0.85) : 1 - ease((p - 0.85) / 0.15), pouring = p < 0.85;
  const level = mBot + 1 - f * (mBot - mTop + 3);
  X.drawImage(S.c, 0, 0);
  // shadow, rim and glass of the letters
  paint(B, (x, y) => {
    const i = y * 320 + x;
    if (M[i]) {
      const sv = Math.round(level + Math.sin(x * 0.27 + t * 0.006) * 1.2 + Math.sin(x * 0.09 - t * 0.004));
      if (glyph[i]) return y >= sv ? "#ffe7a8" : "#f1e8d2";
      const d = y - sv;
      if (d >= 0) {
        const bub = ((x * 7 + y * 13 + Math.floor(t / 60)) % 97) === 0 || (((x * 3 + Math.floor((y + t / 30) )) % 53) === 0 && d > 4);
        if (d < 1) return ((x + Math.floor(t / 70)) % 9 === 0) ? "#fff3c4" : "#ffd27a";
        if (bub) return "#ffe08a";
        if (d < 3) return "#ffa424";
        if (d < 9) return dith(x, y, (d - 3) / 6) ? "#e0831a" : "#ffa424";
        if (d < 26) return dith(x, y, (d - 9) / 17 * 0.6) ? "#c86a16" : "#e0831a";
        return dith(x, y, 0.6 + Math.min(0.4, (d - 26) / 40)) ? "#c86a16" : "#e0831a";
      }
      return ((x - y) % 11 === 0 || (x - y) % 11 === 1) ? "#1f2944" : "#141c32";
    }
    if (OUT[i]) return "#04060c";
    if (y > 1 && x > 1 && M[(y - 3) * 320 + x - 3]) return "#05070e";
    return null;
  });
  // the pipe, elbow and nozzle along the top
  const py = 12;
  fr(X, "#04060c", 0, py - 1, nozX + 6, 9); fr(X, P.steelLo, 0, py, nozX + 4, 7); fr(X, P.steel, 0, py + 1, nozX + 4, 4); fr(X, P.steelHi, 0, py + 1, nozX + 4, 1);
  for (let x = 14; x < nozX - 6; x += 26) { fr(X, "#04060c", x - 1, py - 2, 5, 11); fr(X, P.steelLo, x, py - 1, 3, 9); fr(X, P.steelHi, x, py - 1, 1, 9); }
  fr(X, "#04060c", nozX - 4, py, 9, 16); fr(X, P.steelLo, nozX - 3, py + 1, 7, 14); fr(X, P.steel, nozX - 2, py + 1, 4, 14); fr(X, P.steelHi, nozX - 2, py + 1, 1, 14);
  fr(X, "#04060c", nozX - 5, py + 14, 11, 4); fr(X, P.steelLo, nozX - 4, py + 15, 9, 2);
  // the red valve wheel on the pipe, turning while it pours
  const vx = 44, vy = py - 7, va = pouring ? p * TAU * 1.5 : 0;
  paint(B, (x, y) => {
    const dx = x - vx, dy = y - vy, d = Math.hypot(dx, dy); if (d > 8.6) return null;
    if (d > 7.4) return "#04060c";
    if (d > 5.6) return dx + dy < -2 ? "#ff6a4d" : dx + dy > 3 ? "#8a1f18" : "#e0412e";
    if (d < 1.6) return d < 0.8 ? "#f1e8d2" : P.steelHi;
    let aa = (Math.atan2(dy, dx) - va) % (Math.PI / 2); if (aa < 0) aa += Math.PI / 2;
    if (Math.min(aa, Math.PI / 2 - aa) * d < 0.9) return "#c2321f";
    return null;
  }, vx - 9, vy - 9, 19, 19);
  fr(X, "#04060c", vx - 1, vy + 8, 3, 3); fr(X, P.steelLo, vx, vy + 8, 1, 3);
  // the stream and the splash where it lands
  const sx = nozX - 1, sy0 = py + 18;
  if (pouring) {
    let land = sy0; while (land < 179 && !(M[land * 320 + sx] && land >= level - 1)) land++;
    fr(X, "#04060c", sx - 2, sy0, 6, land - sy0); fr(X, "#c26f12", sx - 1, sy0, 4, land - sy0); fr(X, "#ffa424", sx, sy0, 2, land - sy0); fr(X, "#fff3c4", sx, sy0, 1, land - sy0);
    for (let y = sy0; y < land; y += 4) if ((y + Math.floor(t / 40)) % 8 < 2) fr(X, "#ffd27a", sx, y, 1, 2);
    for (const d of drops) {
      const s = (p * 9 + d.ph) % 1, x = sx + d.vx * s * 14, y = land - (d.vy * s * 14 - 9 * s * s * 14 / 2.2);
      if (y < land + 1) fr(X, d.lit ? "#fff3c4" : "#ffbf5c", x, y, 1, s < 0.3 ? 2 : 1);
    }
  } else if (((t / 120) | 0) % 3 === 0) fr(X, "#ffa424", sx, sy0 + ((t / 8) % 20), 1, 2);
  up(B);
  txt("STRAIT OF HORMUZ · 2026", 1240, 70, { size: 24, color: P.oilSoft, align: "right", ls: 3, shadow: 3 });
  txt("FOLLOW THE OIL", 1240, 690, { font: "mono", w: 400, size: 40, color: P.muted, align: "right", shadow: 3, ls: 2 });
}
boot(draw, 2400);
