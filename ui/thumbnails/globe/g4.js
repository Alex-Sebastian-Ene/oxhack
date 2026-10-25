// 4. control room: the globe on a CRT in a riveted steel wall, fed by a pipe with a valve wheel and a sight
// glass; a pressure gauge reads the app's 69% lost (simulated Aug 2026 scenario).
function draw() {
  // the wall: steel panels, seams and rivets
  const wall = buf(LW, LH), wi = wall.x.createImageData(LW, LH), wd = wi.data;
  for (let y = 0; y < LH; y++) for (let x = 0; x < LW; x++) {
    const px = x % 96, py = y % 68, seam = px === 0 || py === 0, hi = px === 1 || py === 1;
    const v = 0.35 + 0.25 * (y / LH);
    let c = dith(x, y, v) ? "#111829" : "#0c1220";
    if (seam) c = "#05080f"; else if (hi) c = "#1b2438";
    if ((px === 6 || px === 89) && (py === 6 || py === 61)) c = "#3a4867";
    if ((px === 7 || px === 90) && (py === 7 || py === 62)) c = "#5b6d95";
    put(wd, (y * LW + x) * 4, c);
  }
  wall.x.putImageData(wi, 0, 0);
  // the monitor: bezel, screen, globe inside
  const MX = 196, MY = 18, MW = 270, MH = 236, scr = { x: MX + 10, y: MY + 10, w: MW - 20, h: MH - 34 };
  const mon = buf(LW, LH);
  fr(mon.x, "rgba(0,0,0,0.6)", MX + 4, MY + 4, MW, MH);
  fr(mon.x, P.ink, MX - 2, MY - 2, MW + 4, MH + 4); fr(mon.x, "#3a4867", MX, MY, MW, MH); fr(mon.x, "#5b6d95", MX, MY, MW, 2); fr(mon.x, "#273250", MX, MY + MH - 2, MW, 2);
  fr(mon.x, P.ink, scr.x - 2, scr.y - 2, scr.w + 4, scr.h + 4); fr(mon.x, "#02050f", scr.x, scr.y, scr.w, scr.h);
  for (let i = 0; i < 4; i++) { fr(mon.x, P.ink, MX + 18 + i * 14, MY + MH - 18, 8, 8); fr(mon.x, i === 0 ? "#ff6a4d" : i === 1 ? P.oil : "#5b6d95", MX + 20 + i * 14, MY + MH - 16, 4, 4); }
  for (const [rx, ry] of [[MX + 4, MY + 4], [MX + MW - 7, MY + 4], [MX + 4, MY + MH - 7], [MX + MW - 7, MY + MH - 7]]) { fr(mon.x, P.ink, rx - 1, ry - 1, 4, 4); fr(mon.x, P.oil, rx, ry, 2, 2); }
  const G = globe({ cx: scr.x + scr.w / 2 + 6, cy: scr.y + scr.h / 2 + 4, r: 86, rot: [-70, -22, 0], light: [-0.75, -0.45, 0.5] });
  G.night = 0.22;
  const atm = atmosphere(G, 0.1), lt = lights(G, 8), A = arcs(G, flowArcs(10, 7, 31), { lift: 0.2 }), hz = marker(G, HZ, "#ff6a4d", 6);
  // the pipe into the monitor, with a sight glass and a valve wheel
  const pipe = buf(LW, LH), PY = 196;
  fr(pipe.x, P.ink, 0, PY - 9, MX + 2, 18); fr(pipe.x, "#323e5c", 0, PY - 7, MX, 14); fr(pipe.x, "#5b6d95", 0, PY - 6, MX, 3); fr(pipe.x, "#8b9bc0", 0, PY - 5, MX, 1); fr(pipe.x, "#232c44", 0, PY + 4, MX, 3);
  for (const cx of [22, 150]) { fr(pipe.x, P.ink, cx - 2, PY - 11, 9, 22); fr(pipe.x, "#5b6d95", cx, PY - 10, 5, 20); fr(pipe.x, "#8b9bc0", cx + 1, PY - 10, 1, 20); }
  // sight glass: oil at 31% of the pipe, the flow still getting through
  fr(pipe.x, P.ink, 52, PY - 8, 60, 16); fr(pipe.x, "#0a0f1c", 54, PY - 6, 56, 12);
  for (let x = 54; x < 110; x++) { const lvl = PY + 6 - Math.round(12 * 0.31) + (x % 9 < 4 ? 0 : 1); fr(pipe.x, "#ffa424", x, lvl, 1, PY + 6 - lvl); fr(pipe.x, "#ffd27a", x, lvl, 1, 1); }
  fr(pipe.x, "rgba(241,232,210,0.35)", 56, PY - 5, 50, 1);
  // a slimmer LNG pipe along the bottom, its glass violet
  const QY = 238;
  fr(pipe.x, P.ink, 0, QY - 6, MX + 2, 12); fr(pipe.x, "#323e5c", 0, QY - 4, MX, 8); fr(pipe.x, "#5b6d95", 0, QY - 3, MX, 2); fr(pipe.x, "#232c44", 0, QY + 2, MX, 2);
  for (const cx of [40, 170]) { fr(pipe.x, P.ink, cx - 2, QY - 8, 8, 16); fr(pipe.x, "#5b6d95", cx, QY - 7, 4, 14); }
  fr(pipe.x, P.ink, 72, QY - 5, 70, 10); fr(pipe.x, "#0a0f1c", 74, QY - 3, 66, 6);
  for (let x = 74; x < 140; x++) { fr(pipe.x, "#8f6ee0", x, QY - 1 + (x % 7 < 3 ? 0 : 1), 1, 3); if (x % 7 === 0) fr(pipe.x, "#c4a8ff", x, QY - 1, 1, 1); }
  // valve wheel
  const VX = 132, VY = PY - 26;
  fr(pipe.x, P.ink, VX - 2, VY, 5, 22); fr(pipe.x, "#5b6d95", VX - 1, VY, 3, 20);
  for (let k = 0; k < 72; k++) { const a = k / 72 * TAU; for (const rr of [15, 16, 17]) fr(pipe.x, rr === 17 ? P.ink : rr === 16 ? "#e0412e" : "#ff6a4d", VX + Math.cos(a) * rr, VY + Math.sin(a) * rr * 0.96); }
  for (let s2 = 0; s2 < 6; s2++) { const a = s2 / 6 * TAU + 0.3; for (let rr = 3; rr < 15; rr++) fr(pipe.x, "#b5241a", VX + Math.cos(a) * rr, VY + Math.sin(a) * rr, 2, 2); }
  fr(pipe.x, P.ink, VX - 3, VY - 3, 7, 7); fr(pipe.x, "#8b9bc0", VX - 2, VY - 2, 5, 5);
  // pressure gauge
  const gg = buf(LW, LH), GX = 70, GY = 128, GR = 26;
  for (let y = -GR - 3; y <= GR + 3; y++) for (let x = -GR - 3; x <= GR + 3; x++) { const d = Math.hypot(x, y); if (d > GR + 3) continue; fr(gg.x, d > GR + 1.5 ? P.ink : d > GR - 1 ? "#5b6d95" : "#f1e8d2", GX + x, GY + y); }
  const a0 = Math.PI * 0.75, a1 = Math.PI * 2.25, at = (f) => a0 + (a1 - a0) * f;
  for (let k = 0; k <= 60; k++) { const f = k / 60, a = at(f); for (const rr of [GR - 3, GR - 4]) fr(gg.x, f > 0.6 ? "#e0412e" : "#323e5c", GX + Math.cos(a) * rr, GY + Math.sin(a) * rr); }
  for (let k = 0; k <= 10; k++) { const a = at(k / 10); for (let rr = GR - 8; rr < GR - 5; rr++) fr(gg.x, P.ink, GX + Math.cos(a) * rr, GY + Math.sin(a) * rr); }
  const na = at(0.69); for (let rr = 0; rr < GR - 6; rr++) fr(gg.x, "#b5241a", GX + Math.cos(na) * rr, GY + Math.sin(na) * rr, 2, 2);
  fr(gg.x, P.ink, GX - 3, GY - 3, 7, 7); fr(gg.x, "#8b9bc0", GX - 2, GY - 2, 4, 4);
  fr(gg.x, P.ink, GX - 3, GY + GR + 2, 7, PY - GY - GR - 9); fr(gg.x, "#5b6d95", GX - 2, GY + GR + 2, 5, PY - GY - GR - 9);
  // scanlines over the screen
  const scan = buf(LW, LH); for (let y = scr.y; y < scr.y + scr.h; y += 2) fr(scan.x, "rgba(0,0,0,0.28)", scr.x, y, scr.w, 1);
  // compose
  layer(wall); layer(pipe); layer(gg); layer(mon);
  ctx.save(); ctx.beginPath(); ctx.rect(scr.x * S, scr.y * S, scr.w * S, scr.h * S); ctx.clip();
  const sk = sky("#02040f", "#071030", 17, 160); layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 22, 0.5); layer(atm, 6, 0.3); layer(G.b); layer(lt, 5, 0.9);
  glowOnly(A, 18, 0.75); layer(A, 5, 0.8); layer(hz.b, 10, 1);
  layer(scan);
  const vg = ctx.createRadialGradient((scr.x + scr.w / 2) * S, (scr.y + scr.h / 2) * S, 200, (scr.x + scr.w / 2) * S, (scr.y + scr.h / 2) * S, 640);
  vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,0.5)"); ctx.fillStyle = vg; ctx.fillRect(scr.x * S, scr.y * S, scr.w * S, scr.h * S);
  ctx.restore();
  glowOnly(pipe, 10, 0.25);
  // title plate and gauge label
  plate(84, 128, 660, 150);
  txt("Hormuz", 124, 240, { size: 96, shadow: 6 });
  txt("Flow", 124 + measure("Hormuz ", { size: 96 }), 240, { size: 96, color: P.oil, shadow: 6 });
}
still(draw);
