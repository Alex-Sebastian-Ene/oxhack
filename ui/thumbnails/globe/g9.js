// 9. logo with a wake: the tanker heads for the globe, trailing a glowing oil slick.

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
  // a glowing oil wake behind the tanker, tapering away from it
  const wk = buf(LW, LH), x1 = 140, x0 = 30, yW = Math.round((790 + 5 * 16) / S);
  for (let x = x0; x < x1; x++) {
    const t = (x - x0) / (x1 - x0), wob = Math.round(Math.sin(x * 0.35) * 0.7);
    if (dith(x, 0, 0.25 + 0.75 * t)) fr(wk.x, t > 0.85 ? "#fff1c9" : t > 0.55 ? "#ffd27a" : "#ffa424", x, yW + wob);
    if (t > 0.3 && dith(x, 1, (t - 0.3) * 1.2)) fr(wk.x, "#d9861f", x, yW - 1 + wob);
    if (dith(x, 2, 0.15 + 0.5 * t)) fr(wk.x, "#b0671c", x, yW + 1 + wob);
  }
  glowOnly(wk, 16, 0.9); layer(wk, 5, 0.6);
  shipLogo(x1 * S - 8, 790, 16);
}
still(draw);
