// 6. arcade: a title screen. Striped oil-sun on the horizon, a perspective sea grid rolling in, a tanker crossing, PRESS START
LOOP = 4000;
const B = buf(320, 180), X = B.x, HZ = 118;
let M = null, EDGE = null;
const r = rng(31);
const stars = Array.from({ length: 120 }, () => ({ x: r() * 320 | 0, y: r() * 110 | 0, b: r(), p: r() }));
const SUN = ["#fff3c4", "#ffd27a", "#ffbf5c", "#ffa424", "#ff8a2e", "#ff6a4d", "#e0412e", "#b5301f"];
const LOGO = ["#fff3c4", "#fff3c4", "#ffe08a", "#ffd27a", "#ffbf5c", "#ffa424", "#ff8a2e", "#ff6a4d", "#e0412e"];
function prep() {
  M = textMask(320, 180, [{ s: "HORMUZ", x: 160, y: 46, size: 44 }, { s: "FLOW", x: 160, y: 84, size: 44 }]);
  EDGE = new Uint8Array(320 * 180);
  const at = (x, y) => (x < 0 || y < 0 || x >= 320 || y >= 180) ? 0 : M[y * 320 + x];
  for (let y = 0; y < 180; y++) for (let x = 0; x < 320; x++) if (!M[y * 320 + x]) { for (let dy = -2; dy <= 2 && !EDGE[y * 320 + x]; dy++) for (let dx = -2; dx <= 2; dx++) if (at(x + dx, y + dy)) { EDGE[y * 320 + x] = 1; break; } }
}
function draw(t) {
  if (!M) prep();
  const p = ph(t);
  // sky and stars
  paint(B, (x, y) => (y < HZ ? (dith(x, y, y / HZ * 0.9) ? "#0d0a26" : "#05051a") : null));
  for (const s of stars) if (Math.sin(TAU * (p * 4 + s.p)) > (s.b > 0.8 ? -0.6 : 0.5)) fr(X, s.b > 0.92 ? "#f1e8d2" : "#4a4a80", s.x, s.y);
  // the sun: striped, cut by widening gaps toward the horizon
  const SX = 160, SY = HZ + 2, SR = 48;
  paint(B, (x, y) => {
    const d = Math.hypot(x - SX, y - SY); if (d > SR || y >= HZ) return null;
    const v = (y - (SY - SR)) / SR; const band = clamp(Math.floor(v * SUN.length), 0, SUN.length - 1);
    if (y > SY - 30) { const k = y - (SY - 30), gap = 1 + Math.floor(k / 7); if ((k % 6) < gap * 0.9 + (k % 6 === 0 ? 1 : 0) && k > 2) return null; }
    return SUN[band];
  }, SX - SR, SY - SR, SR * 2 + 1, HZ - (SY - SR));
  // sun glow on the sky
  paint(B, (x, y) => { const d = Math.hypot(x - SX, y - SY); return d > SR && d < SR + 14 && y < HZ && dith(x, y, (SR + 14 - d) / 14 * 0.45) ? "#3a1030" : null; }, SX - SR - 15, SY - SR - 15, SR * 2 + 31, HZ - (SY - SR - 15));
  // sea: dark, with the sun's reflection broken into scanlines
  paint(B, (x, y) => {
    const k = y - HZ, ref = Math.abs(x - SX) < SR * (1 - k / 90) * 0.75 && Math.sin(y * 1.7 + TAU * p * 3 + x * 0.05) > 0.3;
    if (ref) return k < 14 ? "#ff8a2e" : k < 30 ? "#b5301f" : "#5a1a24";
    return dith(x, y, k / 62) ? "#080616" : "#0e0a24";
  }, 0, HZ, 320, 180 - HZ);
  // perspective grid rolling toward us; the line spacing repeats each loop
  for (let k = 0; k < 14; k++) { const y = Math.round(HZ + 2.2 * Math.pow(1.36, k + p)); if (y >= 180) break; for (let x = 0; x < 320; x++) if (y > HZ + 5) fr(X, y > 150 ? "#ff6a4d" : y > 130 ? "#b5301f" : "#6a1f2c", x, y); }
  for (let i = -16; i <= 16; i++) { const x0 = SX + i * 5, x1 = SX + i * 44; for (let y = HZ + 1; y < 180; y++) { const f = (y - HZ) / (180 - HZ); fr(X, f > 0.5 ? "#b5301f" : "#5a1a2c", Math.round(x0 + (x1 - x0) * f), y); } }
  fr(X, "#ffbf5c", 0, HZ, 320, 1);
  // a tanker crossing in front of the sun
  const tx = Math.round(-70 + p * 460), ty = HZ - 1;
  for (let y = 0; y < 6; y++) { const bow = Math.max(0, 5 - y), st = y > 4 ? 1 : 0; fr(X, "#04060c", tx + bow, ty - 6 + y, 58 - bow - st, 1); }
  fr(X, "#04060c", tx + 44, ty - 15, 10, 9); fr(X, "#04060c", tx + 47, ty - 21, 3, 6); for (let i = 0; i < 6; i++) fr(X, "#04060c", tx + 8 + i * 6, ty - 8, 3, 2);
  fr(X, "#ffd27a", tx + 46, ty - 12); fr(X, "#ffd27a", tx + 49, ty - 12); fr(X, Math.sin(TAU * p * 6) > 0 ? "#ff4d3a" : "#5a1a14", tx + 48, ty - 22);
  // the logo: banded fill, dark extrusion, ink rim, a glint sweeping across
  const glint = -60 + ph(t, 2000) * 460;
  paint(B, (x, y) => {
    const i = y * 320 + x;
    if (M[i]) {
      if (Math.abs((x + y * 0.6) - glint) < 2.2) return "#ffffff";
      const v = (y - 18) / 84, band = clamp(Math.floor(((y - 12) % 38) / 34 * LOGO.length), 0, LOGO.length - 1);
      return LOGO[band] + "";
    }
    for (let k = 1; k <= 4; k++) if (y - k >= 0 && M[(y - k) * 320 + x]) return k < 3 ? "#8a1f18" : "#4a1010";
    if (EDGE[i]) return "#04060c";
    return null;
  }, 0, 0, 320, 100);
  up(B);
  // hud and prompt
  txt("PRE-WAR 20.0", 40, 58, { font: "mono", w: 400, size: 40, color: P.text, shadow: 3 });
  txt("NOW 6.2 EST.", 1240, 58, { font: "mono", w: 400, size: 40, color: P.oil, align: "right", shadow: 3 });
  txt("MB/D THROUGH HORMUZ", 40, 88, { font: "mono", w: 400, size: 26, color: P.faint, shadow: 2 });
  txt("SIMULATED AUG 2026", 1240, 88, { font: "mono", w: 400, size: 26, color: P.faint, align: "right", shadow: 2 });
  if (ph(t, 1000) < 0.62) txt("PRESS START", 640, 628, { size: 56, color: P.text, align: "center", shadow: 5, ls: 4 });
  txt("OXHACK 2026", 640, 690, { font: "mono", w: 400, size: 28, color: P.faint, align: "center", shadow: 2, ls: 3 });
}
boot(draw, 1150);
