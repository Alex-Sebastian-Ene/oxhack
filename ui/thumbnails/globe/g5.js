// 5. classic at 3:2 (1920x1280): the same picture as 1, recomposed for the taller frame. The globe grows to
// fill the height, and the title sits at its vertical centre.
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
  // the title, and nothing else
  txt("Hormuz", 120, 600, { size: 200, shadow: 10 });
  txt("Flow", 120, 790, { size: 200, color: P.oil, shadow: 10 });
}
still(draw);
