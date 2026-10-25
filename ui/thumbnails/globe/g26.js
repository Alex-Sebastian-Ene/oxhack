// 26. exposure heat, bright.
// LNG-only buyers, with lit borders, so the rays stay brighter than the land they land on.
function draw() {
  const sk = sky("#02030d", "#0a1030", 3, 360);
  const ROT = [-84, -20, 0], list = flowArcs(14, 8), BRIGHT = true;
  // each buyer by how much of its oil came via Hormuz before the war (h / c, ui/industry), teal at 15% or less, red at 60% or more
  const hi = new Map(), ramps = {};
  for (const [iso] of destCountries(list, ROT)) { const col = (() => { const o = window.FLOWS.oil.find((f) => destIso({ name: f.name }) === iso); const sh = o ? o.h / o.c : 0.3; return d3.interpolateRgbBasis(['#3ff0c8', '#ffd166', '#ff8a3d', '#ff3d4d'])(Math.max(0, Math.min(1, (sh - 0.15) / 0.45))); })(); if (!col) continue; hi.set(iso, iso); ramps[iso] = hueRamp(col, BRIGHT); }
  
  const G = globe({ cx: 392, cy: 162, r: 140, rot: ROT, light: [-0.82, -0.42, 0.4], hi, hiRamps: ramps, hiLift: BRIGHT ? 1 : 0, hiEdge: BRIGHT ? 1 : 2 });
  const atm = atmosphere(G, 0.085), lt = lights(G), A = arcs(G, list, { lift: 0.2 });
  const hz = marker(G, HZ, "#ff6a4d", 7), bab = marker(G, BAB, "#ff8a5c", 5);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 34, 0.5); layer(atm, 8, 0.3);
  layer(G.b); glowOnly(G.hiGlow, 14, 0.4); layer(lt, 6, 0.9);
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
