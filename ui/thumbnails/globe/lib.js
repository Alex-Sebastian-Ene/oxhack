// shared helpers for the Hormuz Flow thumbnails: palette, seeded random, low-res buffers, dither, text
const W = window.STILL_W || 1920, H = window.STILL_H || 1080, TAU = Math.PI * 2;
const P = { bg: "#0a0e1c", panel: "#121a2d", panel2: "#1a2439", line: "#27324c", line2: "#3a4867", text: "#f1e8d2", muted: "#c4baa3",
  faint: "#a0978a", oil: "#ffa424", oilSoft: "#ffbf5c", oilHi: "#ffd27a", oilDeep: "#c26f12", harm: "#ff6a4d", red: "#e0412e", redLo: "#8a1f18",
  sea: "#0b2240", gas: "#b58cff", ais: "#5aa9ff", ink: "#04060c", steel: "#5b6d95", steelHi: "#8b9bc0", steelLo: "#323e5c", crude: "#1a1108", crude2: "#100a04", sheen: "#4a2f12" };
let LOOP = 3000;
function rng(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const cv = document.getElementById("c"), ctx = cv.getContext("2d");
function buf(w, h) { const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d"); x.imageSmoothingEnabled = false; return { c, x, w, h }; }
function fr(x, col, X, Y, w = 1, h = 1) { x.fillStyle = col; x.fillRect(Math.round(X), Math.round(Y), w, h); }
const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
const dith = (x, y, v) => v * 16 > BAYER[y & 3][x & 3] + 0.5;
const ph = (t, period = LOOP) => (((t % period) + period) % period) / period;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = (k) => k * k * (3 - 2 * k);
const RGB = {};
function rgb(h) { if (!RGB[h]) RGB[h] = [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; return RGB[h]; }
// per-pixel painter into a buffer: fn(x, y) returns a hex colour or null
function paint(b, fn, x0 = 0, y0 = 0, w = b.w, h = b.h) {
  const img = b.x.getImageData(x0, y0, w, h), d = img.data;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const c = fn(x0 + x, y0 + y); if (!c) continue;
    const [r, g, bl] = rgb(c), i = (y * w + x) * 4; d[i] = r; d[i + 1] = g; d[i + 2] = bl; d[i + 3] = 255;
  }
  b.x.putImageData(img, x0, y0);
}
function disc(x, col, cx, cy, r) { for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + r * 0.6) fr(x, col, cx + dx, cy + dy); }
function up(b) { ctx.imageSmoothingEnabled = false; ctx.drawImage(b.c, 0, 0, W, H); }
const FONT = (o) => `${o.w || 700} ${o.size || 64}px ${o.font === "mono" ? '"VT323"' : '"Pixelify Sans"'}, monospace`;
function txt(s, x, y, o = {}) {
  ctx.save();
  ctx.font = FONT(o); ctx.textAlign = o.align || "left"; ctx.textBaseline = o.base || "alphabetic";
  if (o.ls) ctx.letterSpacing = `${o.ls}px`;
  if (o.alpha != null) ctx.globalAlpha = o.alpha;
  const sh = o.shadow ?? Math.max(2, Math.round((o.size || 64) / 18));
  if (o.outline) { ctx.lineJoin = "round"; ctx.lineWidth = o.outline; ctx.strokeStyle = P.ink; ctx.strokeText(s, x, y); }
  if (sh) { ctx.fillStyle = o.shColor || P.ink; ctx.fillText(s, x + sh, y + sh); }
  ctx.fillStyle = o.color || P.text; ctx.fillText(s, x, y);
  ctx.restore();
}
function measure(s, o = {}) { ctx.save(); ctx.font = FONT(o); if (o.ls) ctx.letterSpacing = `${o.ls}px`; const m = ctx.measureText(s).width; ctx.restore(); return m; }
// a run of differently coloured words on one baseline
function parts(list, x, y, o = {}) { let cx = x; for (const [s, col] of list) { txt(s, cx, y, { ...o, color: col }); cx += measure(s, o); } return cx; }
// the landing page's riveted title plate, at full resolution
function plate(x, y, w, h) {
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(x + 12, y + 12, w + 6, h + 6);
  ctx.fillStyle = P.ink; ctx.fillRect(x - 9, y - 9, w + 18, h + 18);
  ctx.fillStyle = P.text; ctx.fillRect(x - 6, y - 6, w + 12, h + 12);
  ctx.fillStyle = P.ink; ctx.fillRect(x - 3, y - 3, w + 6, h + 6);
  ctx.fillStyle = P.line2; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#10182b"; ctx.fillRect(x + 4, y + 4, w - 8, h - 8);
  for (const [rx, ry] of [[x + 12, y + h / 2], [x + w - 20, y + h / 2], [x + 12, y + 12], [x + w - 20, y + 12], [x + 12, y + h - 20], [x + w - 20, y + h - 20]]) {
    ctx.fillStyle = P.ink; ctx.fillRect(rx - 2, ry - 2, 12, 12); ctx.fillStyle = P.oil; ctx.fillRect(rx, ry, 8, 8); ctx.fillStyle = P.oilHi; ctx.fillRect(rx, ry, 3, 3);
  }
  ctx.restore();
}
// a text mask drawn at low resolution (1 inside the letters), for pixel-art lettering
function textMask(w, h, lines) {
  const b = buf(w, h); b.x.fillStyle = "#fff";
  for (const l of lines) { b.x.font = FONT(l); b.x.textAlign = l.align || "center"; b.x.textBaseline = "alphabetic"; if (l.ls) b.x.letterSpacing = `${l.ls}px`; b.x.fillText(l.s, l.x, l.y); }
  const d = b.x.getImageData(0, 0, w, h).data, m = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) m[i] = d[i * 4 + 3] > 110 ? 1 : 0;
  return m;
}
function boot(draw, still) {
  window.STILL_T = still; window.LOOP_MS = LOOP; window.renderAt = (t) => draw(t);
  Promise.all(['700 64px "Pixelify Sans"', '400 32px "Pixelify Sans"', '400 32px "VT323"'].map((f) => document.fonts.load(f))).then(() => {
    draw(still); window.READY = true;
    if (!window.__capture) { const t0 = performance.now(); const f = (now) => { draw(now - t0 + still); requestAnimationFrame(f); }; requestAnimationFrame(f); }
  });
}
