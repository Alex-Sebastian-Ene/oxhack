// 7. spike: the price chart is a pipe; it runs flat, kinks up hard, and bursts at the top, spraying crude
LOOP = 3000;
const B = buf(320, 180), X = B.x;
const S = buf(320, 180);
const AX = 22, AY = 160;
paint(S, (x, y) => {
  if (x === AX && y < AY + 1 && y > 18) return "#3a4867";
  if (y === AY && x >= AX && x < 304) return "#3a4867";
  if ((x - AX) % 28 === 0 && x > AX && y % 2 === 0 && y < AY) return "#121a2d";
  if ((AY - y) % 24 === 0 && y < AY && x > AX && x % 2 === 0) return "#121a2d";
  return dith(x, y, y / 180 * 0.5) ? "#080b18" : "#0a0e1c";
});
for (let x = AX + 28; x < 304; x += 28) fr(S.x, "#3a4867", x, AY + 1, 1, 3);
// pipe path: flat, a small rise, then the spike; points in low-res pixels
const PTS = [[AX + 4, 140], [120, 139], [150, 136], [176, 132], [192, 126], [204, 112], [212, 92], [218, 72], [222, 60]];
const samp = []; { for (let i = 0; i < PTS.length - 1; i++) { const [a, b] = [PTS[i], PTS[i + 1]], n = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) * 2); for (let k = 0; k < n; k++) samp.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]); } }
let len = 0; const cum = [0]; for (let i = 1; i < samp.length; i++) { len += Math.hypot(samp[i][0] - samp[i - 1][0], samp[i][1] - samp[i - 1][1]); cum.push(len); }
const BREAK = samp.length - 1, [BX, BY] = samp[BREAK];
// draw the pipe body into the static layer: shade across its width
function pipe(b) {
  const R = 4.5;
  for (let i = 0; i < samp.length; i++) {
    const [x, y] = samp[i], j = Math.min(samp.length - 1, i + 1), k = Math.max(0, i - 1);
    const dx = samp[j][0] - samp[k][0], dy = samp[j][1] - samp[k][1], n = Math.hypot(dx, dy) || 1, nx = -dy / n, ny = dx / n;
    for (let o = -R - 1; o <= R + 1; o += 0.5) {
      const c = Math.abs(o) > R ? "#04060c" : o < -R + 1.5 ? P.steelHi : o > R - 2 ? P.steelLo : P.steel;
      fr(b.x, c, x + nx * o, y + ny * o);
    }
  }
  // flanges every 26 px along the run
  for (let i = 0; i < samp.length; i++) if (Math.round(cum[i]) % 26 === 0 && cum[i] > 8 && i < BREAK - 10) {
    const [x, y] = samp[i], j = Math.min(samp.length - 1, i + 1), dx = samp[j][0] - x, dy = samp[j][1] - y, n = Math.hypot(dx, dy) || 1, nx = -dy / n, ny = dx / n;
    for (let o = -7; o <= 7; o += 0.5) for (let w = -1.5; w <= 1.5; w += 0.5) fr(b.x, Math.abs(o) > 6 ? "#04060c" : w < -0.5 ? P.steelHi : P.steelLo, x + nx * o + dx / n * w, y + ny * o + dy / n * w);
  }
}
pipe(S);
// cracks near the top
const cracks = [[209, 100], [215, 82], [200, 118]];
const r = rng(12);
const spray = Array.from({ length: 190 }, () => ({ a: -Math.PI / 2 + (r() - 0.4) * 1.9, v: 1.8 + r() * 3.4, o: r(), lit: r() < 0.4, s: r() < 0.3 ? 3 : r() < 0.6 ? 2 : 1 }));
const puddle = Array.from({ length: 60 }, () => ({ x: 206 + r() * 96, w: 3 + r() * 10, h: r() < 0.5 ? 2 : 3 }));
function draw(t) {
  const p = ph(t);
  X.drawImage(S.c, 0, 0);
  // sight glasses on the flat run: oil slugs hurrying toward the spike
  for (const [x0, x1] of [[40, 90], [96, 140]]) { fr(X, "#04060c", x0, 137, x1 - x0, 4); fr(X, "#0b1020", x0 + 1, 138, x1 - x0 - 2, 2);
    for (let k = 0; k < 4; k++) { const sx = x0 + 1 + ((p * (x1 - x0) * 2 + k * (x1 - x0) / 4) % (x1 - x0 - 2)); fr(X, "#ffa424", sx, 138, 4, 2); fr(X, "#ffd27a", sx + 3, 138, 1, 2); } }
  // red heat along the spike, pulsing
  const heat = 0.55 + 0.45 * Math.sin(TAU * p * 3);
  for (let i = BREAK - 150; i < BREAK; i++) { if (i < 0) continue; const k = (i - (BREAK - 150)) / 150, [x, y] = samp[i]; const j = Math.min(samp.length - 1, i + 1), dx = samp[j][0] - x, dy = samp[j][1] - y, n = Math.hypot(dx, dy) || 1; for (let o = -3; o <= 3; o += 0.5) { const px = x - dy / n * o, py = y + dx / n * o; if (dith(Math.round(px), Math.round(py), k * heat * 0.8)) fr(X, o < -1.5 ? "#ff8a6d" : k > 0.6 ? "#e0412e" : "#8a2a2a", px, py); } }
  // jagged broken end
  for (let k = -6; k <= 6; k++) { const jag = (k * 7 + 3) % 3; fr(X, "#04060c", BX + k * 0.98, BY - 2 - jag, 1, 3); fr(X, "#1a1108", BX + k * 0.98, BY - 1 - jag, 1, 2); }
  // glow round the burst
  paint(B, (x, y) => { const d = Math.hypot(x - BX, y - BY + 4); return d < 26 && d > 3 && dith(x, y, (26 - d) / 26 * 0.4) ? (d < 12 ? "#7a3a1a" : "#3a1a14") : null; }, BX - 27, BY - 31, 55, 55);
  // the spray: crude arcs up and out of the break and rains down onto a puddle
  for (const d of spray) {
    const s = (p * 1.5 + d.o) % 1, tt = s * 60, vx = Math.cos(d.a) * d.v, vy = Math.sin(d.a) * d.v;
    const x = BX + vx * tt * 0.9, y = BY - 3 + vy * tt + 0.11 * tt * tt;
    if (y > AY - 2 || x > 318) continue;
    fr(X, d.lit ? (s < 0.3 ? "#fff3c4" : "#ffa424") : (s < 0.5 ? "#c26f12" : "#7a4a18"), x, y, d.s, d.s + (vy + 0.22 * tt > 1.5 ? 1 : 0));
  }
  // a fat jet straight up out of the pipe
  for (let k = 0; k < 34; k++) { const y = BY - 4 - k, w = 4 + Math.round(Math.sin(k * 0.6 - TAU * p * 6) * 1.5 + k / 6); fr(X, "#04060c", BX - w / 2 - 1, y, w + 2, 1); fr(X, k < 22 ? "#ffa424" : "#c26f12", BX - w / 2, y, w, 1); fr(X, "#ffd27a", BX - w / 2 + 1, y, 1, 1); if ((k + Math.floor(t / 50)) % 3 === 0) fr(X, "#fff3c4", BX + Math.round(Math.sin(k + TAU * p * 4)), y); }
  { const cy = BY - 40; for (let q = 0; q < 40; q++) { const a = q / 40 * TAU, rr = 6 + ((p * 4 + q * 0.37) % 1) * 12 + Math.sin(q * 2.1) * 2; fr(X, q % 3 ? "#ffa424" : "#fff3c4", BX + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.7, 2, 2); } }
  // spurts from the cracks
  cracks.forEach(([cx, cy], i) => { fr(X, "#04060c", cx - 1, cy, 3, 1); for (let k = 0; k < 8; k++) { const s = (p * 3 + k / 8 + i * 0.3) % 1; fr(X, "#ffa424", cx + 2 + s * 14, cy - 2 - s * 6 + s * s * 10, 1, 1); } });
  // the puddle, rippling
  for (const q of puddle) { fr(X, "#1a1108", q.x, AY - q.h, q.w, q.h); fr(X, "#4a2f12", q.x + 1, AY - q.h, q.w - 2, 1); }
  for (let x = 208; x < 302; x++) if (Math.sin(x * 0.6 - TAU * p * 3) > 0.75) fr(X, "#ffa424", x, AY - 3);
  up(B);
  txt("BRENT", AX * 4 + 14, 98, { font: "mono", w: 400, size: 30, color: P.faint, shadow: 2 });
  txt("2026", 1160, AY * 4 + 44, { font: "mono", w: 400, size: 30, color: P.faint, align: "right", shadow: 2 });
  txt("Hormuz Flow", 150, 250, { size: 100, shadow: 6 });
  parts([["Shut the strait. ", P.text], ["Watch the price.", P.oil]], 156, 312, { size: 34, w: 400, shadow: 3 });
}
boot(draw, 700);
