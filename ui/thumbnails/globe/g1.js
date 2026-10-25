// 1. classic: the original globe layout, refined. Title left; the globe right, lit from the upper left so East Asia
// sits on the night side with its city lights, and every arc ends there glowing.
function draw() {
  const sk = sky("#02030d", "#0a1030", 3, 300);
  const G = globe({ cx: 356, cy: 138, r: 124, rot: [-84, -20, 0], light: [-0.82, -0.42, 0.4] });
  const atm = atmosphere(G, 0.085), lt = lights(G), A = arcs(G, flowArcs(14, 8), { lift: 0.2 });
  const hz = marker(G, HZ), bab = marker(G, BAB, "#ff8a5c", 4);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 30, 0.5); layer(atm, 8, 0.3);
  layer(G.b);
  layer(lt, 6, 0.9);
  glowOnly(A, 22, 0.75); layer(A, 6, 0.8);
  layer(hz.b, 10, 0.9); layer(bab.b, 6, 0.6);
  // the title, and nothing else
  txt("Hormuz", 120, 500, { size: 200, shadow: 10 });
  txt("Flow", 120, 690, { size: 200, color: P.oil, shadow: 10 });
}
still(draw);
