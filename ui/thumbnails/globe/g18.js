// 18. the blue logo, centred: as 14, with the middle of the tanker at x = 474, under the title.
function draw() {
  const sk = sky("#02030d", "#0a1030", 3, 360);
  const G = globe({ cx: 392, cy: 162, r: 140, rot: [-84, -20, 0], light: [-0.82, -0.42, 0.4] });
  const atm = atmosphere(G, 0.085), lt = lights(G), A = arcs(G, flowArcs(14, 8), { lift: 0.2 });
  const hz = marker(G, HZ, "#ff6a4d", 7), bab = marker(G, BAB, "#ff8a5c", 5);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 34, 0.5); layer(atm, 8, 0.3);
  layer(G.b); layer(lt, 6, 0.9);
  glowOnly(A, 24, 0.75); layer(A, 6, 0.8);
  layer(hz.b, 10, 0.9); layer(bab.b, 6, 0.6);
  // the title in the pour lettering, then the logo: the tanker on its own strip of pixel water
  const T = pixelTitle([{ s: "HORMUZ", x: 28, y: 114, size: 52 }, { s: "FLOW", x: 28, y: 180, size: 60, fill: "oil" }]);
  layer(T); glowOnly(T, 10, 0.18);
  // the ship's middle at x = 474, a touch left of HORMUZ's middle (504), as chosen by eye
  const px = 26, mid = 474;
  logoSea(Math.round(mid - 7 * px), 790, px, "blue", {});
}
still(draw);
