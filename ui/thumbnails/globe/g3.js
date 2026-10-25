// 3. knock-on: the globe on the left; three glowing streams leave Hormuz and run into pixel icons of what the
// closure reaches (crude, fuel at the pump, prices), with the title beside them.
function bez(a, c1, c2, b, t) { const u = 1 - t; return [0, 1].map((k) => u * u * u * a[k] + 3 * u * u * t * c1[k] + 3 * u * t * t * c2[k] + t * t * t * b[k]); }
function icon(bf, x, y, rows, pal, k = 2) { rows.forEach((row, j) => [...row].forEach((ch, i) => { if (pal[ch]) fr(bf.x, pal[ch], x + i * k, y + j * k, k, k); })); }
const ICONS = {
  barrel: [" kkkkkk ", "kooooook", "kOOOOOOk", "kkkkkkkk", "kooooook", "kooooook", "kkkkkkkk", "kOOOOOOk", "kooooook", " kkkkkk "],
  pump: ["kkkkkk  ", "krrrrk  ", "kwwwwk k", "kwwwwkkk", "krrrrk k", "krrrrk k", "krrrrk k", "krrrrkkk", "krrrrk  ", "kkkkkkk "],
  tag: ["   kkkkk", "  kyyyyk", " kyykyyk", "kyyyyyyk", "kyyyyyyk", "kyyyyyk ", "kyyyyk  ", "kyyyk   ", "kyyk    ", "kkk     "],
};
const IPAL = { k: "#04060c", o: "#c26f12", O: "#ffa424", r: "#e0412e", w: "#f1e8d2", y: "#ffd27a" };
function draw() {
  const sk = sky("#02030d", "#0a1030", 13, 280);
  const G = globe({ cx: 120, cy: 150, r: 112, rot: [-62, -22, 0], light: [-0.72, -0.5, 0.48] });
  G.night = 0.2;
  const atm = atmosphere(G, 0.09), lt = lights(G, 4), A = arcs(G, flowArcs(10, 6, 5), { lift: 0.17 });
  const hz = marker(G, HZ, "#ff6a4d", 7);
  // three streams from the strait to the readouts
  const TS = 208, tiles = [{ y: 196, key: "barrel" }, { y: 436, key: "pump" }, { y: 676, key: "tag" }];
  const st = buf(LW, LH), hq = G.xy(G.at(HZ));
  tiles.forEach((tl, i) => {
    const a = [hq[0] + 2, hq[1]], b = [268, (tl.y + TS / 2) / S], c1 = [a[0] + 70, a[1] - 40 + i * 30], c2 = [b[0] - 70, b[1]];
    const head = 0.86 - i * 0.06;
    for (let k = 0; k <= 260; k++) {
      const t = k / 260, [x, y] = bez(a, c1, c2, b, t), tt = (t - (head - 0.35)) / 0.35;
      const col = tt < 0 || t > head ? "#7a4512" : tt > 0.93 ? "#fff1c9" : tt > 0.7 ? "#ffb547" : "#d9861f";
      fr(st.x, col, x, y, 2, 2);
    }
  });
  const ic = buf(LW, LH);
  tiles.forEach((tl) => icon(ic, 268 + (TS / S - 32) / 2, tl.y / S + (TS / S - 40) / 2, ICONS[tl.key], IPAL, 4));
  layer(sk.b); layer(sk.stars, 3, 0.5);
  glowOnly(atm, 28, 0.5); layer(atm, 8, 0.3);
  layer(G.b); layer(lt, 6, 0.9);
  glowOnly(A, 20, 0.7); layer(A, 6, 0.8);
  glowOnly(st, 24, 0.85); layer(st, 6, 0.8);
  layer(hz.b, 12, 1);
  // the icon plates the streams run into, and the title
  tiles.forEach((tl) => chip(1072, tl.y, TS, TS));
  layer(ic);
  txt("Hormuz", 1368, 520, { size: 140, shadow: 8 });
  txt("Flow", 1368, 680, { size: 140, color: P.oil, shadow: 8 });
}
still(draw);
