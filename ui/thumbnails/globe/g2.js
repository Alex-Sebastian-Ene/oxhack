// 2. horizon: low orbit over the Gulf. The Earth's limb is a curve across the frame, Hormuz glows on it, and the
// arcs launch off over the horizon to the buyers. Title in the sky above.
function draw() {
  const sk = sky("#010209", "#0b1236", 7, 340);
  const G = globe({ cx: 240, cy: 470, r: 360, rot: [-56.4, 21, 0], light: [0.18, -0.62, -0.76] });
  G.night = 0.05;
  const atm = atmosphere(G, 0.05, ["#7fc0ff", "#3b7fd0", "#1b4a8a"]), lt = lights(G, 9);
  const A = arcs(G, flowArcs(14, 9, 21), { lift: 0.3, minZ: -0.6 });
  const hz = marker(G, HZ, "#ff6a4d", 9);
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 40, 0.7); layer(atm, 10, 0.5);
  layer(G.b);
  layer(lt, 6, 0.9);
  glowOnly(A, 26, 0.8); layer(A, 7, 0.85);
  layer(hz.b, 14, 1);
  // title, centred in the sky, on a soft dark pool so the arcs behind it stay quiet
  const vg = ctx.createRadialGradient(W / 2, 220, 60, W / 2, 220, 760); vg.addColorStop(0, "rgba(2,3,12,0.78)"); vg.addColorStop(1, "rgba(2,3,12,0)");
  ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);
  txt("Hormuz Flow", W / 2, 250, { size: 210, align: "center", shadow: 10 });
  const w1 = measure("Hormuz ", { size: 210 }), wAll = measure("Hormuz Flow", { size: 210 });
  txt("Flow", W / 2 - wAll / 2 + w1, 250, { size: 210, color: P.oil, shadow: 10 });
}
still(draw);
