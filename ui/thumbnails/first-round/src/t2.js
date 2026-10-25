// 2. radar: the strait from above at night; lit tankers with AIS halos, one dark tanker caught by the radar sweep
LOOP = 3000;
const B = buf(320, 180), X = B.x;
const sm = (a, b, x) => ease(clamp((x - a) / (b - a), 0, 1));
const yTop = (x) => 52 + 5 * Math.sin(x * 0.05) + 2.5 * Math.sin(x * 0.17 + 1) + 12 * Math.exp(-(((x - 196) / 26) ** 2)) - 26 * sm(232, 320, x);
const yBot = (x) => 168 - 66 * Math.exp(-(((x - 212) / 17) ** 2)) - 8 * Math.exp(-(((x - 120) / 50) ** 2)) + 2.5 * Math.sin(x * 0.21) + 30 * sm(236, 300, x) - 26 * sm(250, 320, x) * 0;
const isles = [[150, 66, 22, 3.2], [118, 70, 5, 2], [182, 72, 4, 2.2], [248, 70, 3, 1.6]];
const isLand = (x, y) => y < yTop(x) || y > yBot(x) || isles.some(([cx, cy, a, b]) => ((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 < 1);
const r = rng(21);
const towns = Array.from({ length: 70 }, () => { let x, y; do { x = r() * 320; y = r() * 180; } while (!isLand(x, y)); return { x: x | 0, y: y | 0, p: r() }; });
// static map
const S = buf(320, 180);
paint(S, (x, y) => {
  if (isLand(x, y)) {
    const coast = !isLand(x + 1, y) || !isLand(x - 1, y) || !isLand(x, y + 1) || !isLand(x, y - 1);
    if (coast) return "#46557a";
    const near = !isLand(x + 2, y) || !isLand(x - 2, y) || !isLand(x, y + 2) || !isLand(x, y - 2);
    if (near) return "#262d47";
    const n = Math.sin(x * 0.31 + y * 0.17) + Math.sin(x * 0.11 - y * 0.29) + Math.sin(x * 0.53 + y * 0.61) * 0.5;
    return n > 1.1 ? "#1d2238" : dith(x, y, 0.25) && n > 0.2 ? "#181c30" : "#14182a";
  }
  const dc = Math.min(Math.abs(y - yTop(x)), Math.abs(y - yBot(x)));
  if ((x % 20 === 0 && y % 2 === 0) || (y % 20 === 0 && x % 2 === 0)) return "#0c2747";
  return dc < 4 ? "#0b2240" : dith(x, y, clamp((dc - 4) / 14, 0, 1)) ? "#06142a" : "#0a1d38";
});
// lanes: two dotted tracks through the narrows
const mid = (x) => (Math.max(yTop(x), 40) + Math.min(yBot(x), 170)) / 2;
const laneY = (x, k) => mid(x) + k * 5;
for (let x = 0; x < 320; x += 3) { fr(S.x, "#1d3a5c", x, laneY(x, 1)); fr(S.x, "#1d3a5c", x, laneY(x, -1)); }
// ships: outbound (east, lower lane) and inbound (west, upper lane); spacing = one loop of travel, so the GIF loops
const SP = 64;
const CX = 132, CY = 90;    // radar centre, west of the narrows
const ghost = { x: 204, k: 1 };
function ship(x, y, dir, lit) {
  const hull = lit ? "#a8b4cc" : "#1b2133", deck = lit ? "#6b7896" : "#121726";
  for (let i = 0; i < 9; i++) fr(X, i === 0 || i === 8 ? deck : hull, x + dir * (i - 4), y, 1, 1);
  for (let i = 1; i < 7; i++) fr(X, hull, x + dir * (i - 4), y - 1); for (let i = 1; i < 7; i++) fr(X, hull, x + dir * (i - 4), y + 1);
  fr(X, lit ? "#f1e8d2" : "#232a40", x - dir * 3, y);
  if (lit) { fr(X, P.oil, x + dir * 1, y); fr(X, P.oil, x, y); }
}
function draw(t) {
  const p = ph(t), a = p * TAU;
  X.drawImage(S.c, 0, 0);
  // town lights on land
  for (const w of towns) if (Math.sin(TAU * (p * 2 + w.p)) > -0.6) fr(X, w.p > 0.8 ? "#ffd27a" : "#a8742e", w.x, w.y);
  // the sweep: a fading wedge behind the beam, and range rings
  paint(B, (x, y) => {
    const dx = x - CX, dy = y - CY, d = Math.hypot(dx, dy);
    if (d > 190) return null;
    const ring = [36, 72, 108, 144].some((rr) => Math.abs(d - rr) < 0.5) && (Math.round(Math.atan2(dy, dx) * rr4(d)) % 2 === 0);
    let ang = Math.atan2(dy, dx); let dd = (a - ang) % TAU; if (dd < 0) dd += TAU;
    const land = isLand(x, y);
    if (dd < 0.035 && d > 2) return land ? "#7a6a3a" : "#ffbf5c";
    if (dd < 0.9 && dith(x, y, (1 - dd / 0.9) * (land ? 0.35 : 0.55))) return land ? "#2e3048" : (dd < 0.25 ? "#3d4a2a" : "#173226");
    if (ring) return land ? "#2a3150" : "#16406a";
    return null;
  });
  // ships
  for (const [k, dir] of [[1, 1], [-1, -1]]) for (let i = -1; i < 6; i++) {
    const x0 = i * SP + (k === 1 ? 10 : 40), x = ((x0 + dir * p * SP) % (SP * 6) + SP * 6) % (SP * 6) - 20;
    if (Math.abs(x - ghost.x) < 26) continue;
    if (x < -10 || x > 330) continue;
    const y = Math.round(laneY(x, k));
    for (let w = 1; w < 6; w++) if ((w + Math.floor(p * 30)) % 2) fr(X, "#2c4a74", x - dir * (5 + w), y + ((w % 2) ? 1 : -1));
    ship(Math.round(x), y, dir, true);
    // AIS halo
    const ar = 4 + Math.round((p * 6 + i) % 2);
    for (let q = 0; q < 12; q++) { const qa = q / 12 * TAU; if (q % 2 === 0) fr(X, "#3f7fd0", Math.round(x + Math.cos(qa) * ar), Math.round(y + Math.sin(qa) * ar * 0.8)); }
  }
  // the dark tanker, drifting slowly in the outbound lane
  const gx = Math.round(ghost.x + Math.sin(TAU * p) * 2), gy = Math.round(laneY(ghost.x, ghost.k));
  ship(gx, gy, 1, false);
  // how long since the beam crossed it
  const ga = Math.atan2(gy - CY, gx - CX); let since = (a - ga) % TAU; if (since < 0) since += TAU; since = since / TAU * LOOP;
  const hit = Math.exp(-since / 1100);
  if (hit > 0.08) { const rr = 3 + since / 60; for (let q = 0; q < 20; q++) { const qa = q / 20 * TAU; if (dith(q, 0, hit)) fr(X, "#ff6a4d", Math.round(gx + Math.cos(qa) * rr), Math.round(gy + Math.sin(qa) * rr)); }
    ship(gx, gy, 1, false); for (let i = -4; i <= 4; i++) { fr(X, dith(i + 4, 1, hit) ? "#7a3a34" : "#2a2030", gx + i, gy - 1); fr(X, dith(i + 4, 3, hit) ? "#7a3a34" : "#2a2030", gx + i, gy + 1); } fr(X, hit > 0.5 ? "#ff6a4d" : "#a0403a", gx, gy); }
  // radar site
  fr(X, "#ffbf5c", CX, CY); fr(X, "#04060c", CX - 1, CY); fr(X, "#04060c", CX + 1, CY);
  up(B);
  // hud
  ctx.save(); ctx.strokeStyle = "rgba(255,191,92,.75)"; ctx.lineWidth = 4;
  for (const [cx, cy, sx, sy] of [[24, 24, 1, 1], [1256, 24, -1, 1], [24, 696, 1, -1], [1256, 696, -1, -1]]) { ctx.beginPath(); ctx.moveTo(cx, cy + sy * 40); ctx.lineTo(cx, cy); ctx.lineTo(cx + sx * 40, cy); ctx.stroke(); }
  ctx.restore();
  if (hit > 0.08) {
    const bx = gx * 4, by = gy * 4, al = clamp(hit * 1.6, 0, 1);
    ctx.save(); ctx.globalAlpha = al; ctx.strokeStyle = P.harm; ctx.lineWidth = 4; const s = 36;
    for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { ctx.beginPath(); ctx.moveTo(bx + sx * s, by + sy * (s - 14)); ctx.lineTo(bx + sx * s, by + sy * s); ctx.lineTo(bx + sx * (s - 14), by + sy * s); ctx.stroke(); }
    ctx.restore();
    txt("DARK SHIP · NO AIS", bx + 48, by + 52, { font: "mono", w: 400, size: 34, color: P.harm, alpha: al, shadow: 3 });
  }
  txt("Hormuz Flow", 60, 118, { size: 96, shadow: 6 });
  parts([["AIS off. ", P.muted], ["Still on radar.", P.oil]], 64, 172, { size: 32, w: 400, shadow: 3 });
  txt("26.5N 56.4E", 1220, 668, { font: "mono", w: 400, size: 30, color: P.oilSoft, align: "right", shadow: 2 });
  txt("SIMULATED SHIPS", 1220, 636, { font: "mono", w: 400, size: 26, color: P.faint, align: "right", shadow: 2 });
}
function rr4(d) { return Math.max(6, Math.round(d / 2)); }
boot(draw, 170);
