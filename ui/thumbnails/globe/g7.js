// 7. logo on the sea: the tanker rides a strip of dithered pixel waves under the title.

function draw() {
  const sk = sky("#02030d", "#0a1030", 3, 360);
  const G = globe({ cx: 372, cy: 162, r: 142, rot: [-84, -20, 0], light: [-0.82, -0.42, 0.4] });
  const atm = atmosphere(G, 0.085), lt = lights(G), A = arcs(G, flowArcs(14, 8), { lift: 0.2 });
  const hz = marker(G, HZ, "#ff6a4d", 7), bab = marker(G, BAB, "#ff8a5c", 5);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 34, 0.5); layer(atm, 8, 0.3);
  layer(G.b);
  layer(lt, 6, 0.9);
  glowOnly(A, 24, 0.75); layer(A, 6, 0.8);
  layer(hz.b, 10, 0.9); layer(bab.b, 6, 0.6);
  txt("Hormuz", 120, 540, { size: 200, shadow: 10 });
  txt("Flow", 120, 730, { size: 200, color: P.oil, shadow: 10 });
  // a strip of pixel sea, the tanker sitting in it
  const sx = 112, sw = 700, top = 900, px = 10;
  for (let j = 0; j < 6; j++) for (let i = 0; i < sw / px; i++) {
    const edge = Math.min(i, sw / px - 1 - i) / 10, fade = Math.min(1, edge) * (1 - j / 6);
    let c = null;
    if (j === 0) c = Math.sin(i * 0.7) > 0.35 ? "#8fbbe3" : dith(i, j, fade) ? "#3d8be0" : null;
    else if (dith(i, j, fade * 1.1)) c = j < 2 ? "#2460a8" : j < 4 ? "#163a6c" : "#0e2953";
    if (c) { ctx.fillStyle = c; ctx.fillRect(sx + i * px, top + j * px, px, px); }
  }
  const sp = 16; shipLogo(300, top - 5 * sp + 2, sp, P.oil, 6);
  for (let i = 0; i < 7; i++) { ctx.fillStyle = i % 2 ? "#5f86c4" : "#c8e0f5"; ctx.fillRect(300 - 24 - i * 22, top + 2 + (i % 2) * 8, 14, 6); }
}
still(draw);
