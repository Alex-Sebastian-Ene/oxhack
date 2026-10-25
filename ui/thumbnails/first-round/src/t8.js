// 8. maze: the name built out of pipework, oil pulsing through every letter, valves on the dead ends
LOOP = 3000;
const B = buf(320, 180), X = B.x, C = 12, OX = 10, OY = 0;
const GL = {
  H: ["101", "101", "111", "101", "101"], O: ["111", "101", "101", "101", "111"], R: ["111", "101", "111", "110", "101"],
  M: ["11111", "10101", "10101", "10001", "10001"], U: ["101", "101", "101", "101", "111"], Z: ["111", "001", "111", "100", "111"],
  F: ["111", "100", "110", "100", "100"], L: ["100", "100", "100", "100", "111"], W: ["10001", "10001", "10101", "10101", "11111"],
};
// lay the words out on the cell grid
const cells = new Map(); const key = (c, r) => c + "," + r;
function word(s, row0) {
  const width = [...s].reduce((a, ch) => a + GL[ch][0].length, 0) + s.length - 1; let c0 = Math.round((25 - width) / 2);
  for (const ch of s) { const g = GL[ch]; g.forEach((line, r) => [...line].forEach((v, c) => { if (v === "1") cells.set(key(c0 + c, row0 + r), { c: c0 + c, r: row0 + r, word: s }); })); c0 += g[0].length + 1; }
}
word("HORMUZ", 2); word("FLOW", 8);
const has = (c, r) => cells.has(key(c, r));
const S = buf(320, 180);
// back wall with dim pipes behind
paint(S, (x, y) => {
  if (x % 10 === 0 && y % 10 === 0) return "#111829";
  const bg = dith(x, y, y / 180 * 0.6) ? "#060912" : "#080c18";
  for (const [y0, h] of [[16, 6], [162, 7]]) if (y >= y0 && y < y0 + h) return y === y0 ? "#1a2238" : y === y0 + h - 1 ? "#05070e" : (x % 40 < 3 ? "#0a0e1a" : "#121a2d");
  return bg;
});
function drawCell(b, cell) {
  const { c, r } = cell, x0 = OX + c * C, y0 = OY + r * C;
  const n = has(c, r - 1), s = has(c, r + 1), w = has(c - 1, r), e = has(c + 1, r), deg = n + s + w + e;
  const seg = (x, y, ww, hh, horiz) => { fr(b.x, "#04060c", x - 1, y - 1, ww + 2, hh + 2); fr(b.x, P.steel, x, y, ww, hh);
    if (horiz) { fr(b.x, P.steelHi, x, y, ww, 1); fr(b.x, "#7d8db3", x, y + 1, ww, 1); fr(b.x, P.steelLo, x, y + hh - 1, ww, 1); }
    else { fr(b.x, P.steelHi, x, y, 1, hh); fr(b.x, "#7d8db3", x + 1, y, 1, hh); fr(b.x, P.steelLo, x + ww - 1, y, 1, hh); } };
  // outline pass first, then fills, so joins are seamless
  const parts = [[x0 + 2, y0 + 2, 8, 8, !(n || s)]];
  if (n) parts.push([x0 + 2, y0, 8, 6, false]); if (s) parts.push([x0 + 2, y0 + 6, 8, 6, false]);
  if (w) parts.push([x0, y0 + 2, 6, 8, true]); if (e) parts.push([x0 + 6, y0 + 2, 6, 8, true]);
  for (const [x, y, ww, hh] of parts) fr(b.x, "#04060c", x - 1, y - 1, ww + 2, hh + 2);
  for (const [x, y, ww, hh, hz] of parts) { fr(b.x, P.steel, x, y, ww, hh); if (hz) { fr(b.x, P.steelHi, x, y, ww, 1); fr(b.x, "#7d8db3", x, y + 1, ww, 1); fr(b.x, P.steelLo, x, y + hh - 1, ww, 1); } else { fr(b.x, P.steelHi, x, y, 1, hh); fr(b.x, "#7d8db3", x + 1, y, 1, hh); fr(b.x, P.steelLo, x + ww - 1, y, 1, hh); } }
  // collars where pipes turn or branch; bolted caps on the ends
  if (deg >= 3 || (deg === 2 && !((n && s) || (w && e)))) { fr(b.x, "#04060c", x0 + 1, y0 + 1, 10, 10); fr(b.x, P.steelLo, x0 + 2, y0 + 2, 8, 8); fr(b.x, P.steel, x0 + 3, y0 + 3, 6, 6); for (const [bx, by] of [[2, 2], [9, 2], [2, 9], [9, 9]]) fr(b.x, P.steelHi, x0 + bx, y0 + by); }
  if (deg <= 1) { fr(b.x, "#04060c", x0 + 1, y0 + 1, 10, 10); fr(b.x, P.steelLo, x0 + 2, y0 + 2, 8, 8); fr(b.x, "#7d8db3", x0 + 3, y0 + 3, 6, 6); fr(b.x, P.steelHi, x0 + 3, y0 + 3, 6, 1); }
  cell.deg = deg; cell.n = n; cell.s = s; cell.w = w; cell.e = e;
}
for (const cell of cells.values()) drawCell(S, cell);
const ends = [...cells.values()].filter((c) => c.deg <= 1).filter((c, i) => i % 3 === 0);
const r = rng(17);
function draw(t) {
  const p = ph(t);
  X.drawImage(S.c, 0, 0);
  // the gas line along the bottom: violet dashes moving the other way
  for (let x = 0; x < 300; x++) if (((x + Math.floor(p * 40)) % 10) < 4) fr(X, "#b58cff", x, 165); else fr(X, "#3a2f5a", x, 165);
  // oil pulses: a wave runs left to right through every pipe's sight line
  for (const cell of cells.values()) {
    const { c } = cell, x0 = OX + c * C, y0 = OY + cell.r * C;
    const ph0 = (p * 2 - c / 32 - (cell.word === "FLOW" ? 0.15 : 0) + 4) % 1, on = ph0 < 0.5, hot = ph0 < 0.12;
    const col = hot ? "#fff3c4" : on ? "#ffa424" : "#3a2410";
    const line = (x, y, ww, hh) => fr(X, col, x, y, ww, hh);
    if (cell.deg > 1 || true) line(x0 + 5, y0 + 5, 2, 2);
    if (cell.n) line(x0 + 5, y0, 2, 5); if (cell.s) line(x0 + 5, y0 + 7, 2, 5); if (cell.w) line(x0, y0 + 5, 5, 2); if (cell.e) line(x0 + 7, y0 + 5, 5, 2);
  }
  // valve wheels on the dead ends, each turning
  ends.forEach((cell, i) => {
    const cx = OX + cell.c * C + 6, cy = OY + cell.r * C + 6, a = TAU * (p + i * 0.13);
    for (let q = 0; q < 24; q++) { const qa = q / 24 * TAU; fr(X, "#04060c", cx + Math.round(Math.cos(qa) * 6), cy + Math.round(Math.sin(qa) * 6)); fr(X, q < 8 ? "#ff6a4d" : "#e0412e", cx + Math.round(Math.cos(qa) * 5), cy + Math.round(Math.sin(qa) * 5)); }
    for (let k = 0; k < 2; k++) { const qa = a + k * Math.PI / 2; for (let d = -4; d <= 4; d++) fr(X, "#c2321f", cx + Math.round(Math.cos(qa) * d), cy + Math.round(Math.sin(qa) * d)); }
    fr(X, P.steelHi, cx, cy);
  });
  // a drip from under the R and steam off the W
  const dr = ph(t, 1500), dx = 6 * C + 5 + 6 * 0, dy0 = 8 * C;
  const rc = [...cells.values()].find((c) => c.word === "HORMUZ" && c.r === 6 && c.c > 6 && c.c < 10) || [...cells.values()][10];
  fr(X, "#ffa424", OX + rc.c * C + 6, OY + rc.r * C + 12 + dr * 40, 1, 2);
  const wc = [...cells.values()].filter((c) => c.word === "FLOW").sort((a, b) => b.c - a.c)[0];
  for (let k = 0; k < 6; k++) { const s = (p * 2 + k / 6) % 1, cx = OX + wc.c * C + 10 + s * 10, cy = OY + wc.r * C - s * 22, rr2 = 1 + s * 4;
    for (let yy = -rr2; yy <= rr2; yy++) for (let xx = -rr2; xx <= rr2; xx++) if (xx * xx + yy * yy <= rr2 * rr2 && dith(Math.round(cx + xx), Math.round(cy + yy), (1 - s) * 0.6)) fr(X, s < 0.4 ? "#c4baa3" : "#5b6d95", cx + xx, cy + yy); }
  up(B);
  txt("STRAIT OF HORMUZ · 2026", 640, 74, { font: "mono", w: 400, size: 34, color: P.oilSoft, align: "center", shadow: 3, ls: 4 });
  txt("Follow the oil.", 640, 690, { size: 36, w: 400, color: P.text, align: "center", shadow: 3 });
}
boot(draw, 300);
