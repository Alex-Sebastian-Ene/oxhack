// 12. globe-set, blue: the globe sinks into a night sea like a setting sun; the tanker sails under the title.
function draw() {
  const TOP = 236;   // the horizon, in art rows
  const sk = sky("#02030d", "#0c1336", 3, 360);
  const G = globe({ cx: 394, cy: 150, r: 130, rot: [-84, -20, 0], light: [-0.82, -0.42, 0.4] });
  const atm = atmosphere(G, 0.085), lt = lights(G), A = arcs(G, flowArcs(14, 8), { lift: 0.2 });
  const hz = marker(G, HZ, "#ff6a4d", 7);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 34, 0.5); layer(atm, 8, 0.3);
  layer(G.b); layer(lt, 6, 0.9);
  glowOnly(A, 24, 0.75); layer(A, 6, 0.8);
  layer(hz.b, 10, 0.9);
  // the tanker logo on the horizon, right below where the title goes
  const px = 26; shipLogo(116, TOP * S - 5 * px + 2, px, P.oil, 10);
  // the sea reflects everything drawn so far
  const W2 = sea(TOP, WATER.blue, { glint: G.cx });
  layer(W2.b); glowOnly(W2.glow, 14, 0.45);
  // the title in the pour lettering, drawn after the sea so the water does not mirror it
  const T = pixelTitle([{ s: "HORMUZ", x: 28, y: 118, size: 58 }, { s: "FLOW", x: 28, y: 188, size: 66, fill: "oil" }]);
  layer(T); glowOnly(T, 10, 0.18);
}
still(draw);
