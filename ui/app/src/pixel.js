// Hormuz Flow landing scene: a night-shift refinery and tanker jetty, drawn as pixel art on a canvas.
// Everything is drawn in code at a low resolution and scaled up with crisp edges: the sky, stars and moon,
// the refinery (columns, tanks, stacks, a flare), the water, the tankers (one lit, one running dark) and the
// pipeline across the front with its valve. Nothing is loaded from outside the page.
window.HZScene = (() => {
  const P = {
    sky: ["#05081a", "#080d24", "#0d1430", "#141a3c", "#1e1f46", "#2c2450", "#43294f"],
    star: "#f3ecd8", starDim: "#8f8fb3", moon: "#efe7cf", moonShade: "#c9c1a8",
    far: "#0f1530", farLit: "#f6c35a",
    steel: "#1a2136", steelLit: "#2c3757", steelDark: "#10152a", rail: "#39466a",
    tank: "#1f283f", tankLit: "#35425f",
    sea: "#060d22", wave: "#123056", waveLit: "#1e4a7a",
    hull: "#1c2236", hullLit: "#2e3854", boot: "#6b2027", deck: "#46526f", cabin: "#2a3350", window: "#ffd27a",
    red: "#ff3b30", green: "#38e07b", white: "#fff6e0",
    pipe: "#2b3550", pipeTop: "#4a5a80", pipeLow: "#141a2c", flange: "#56688f", rust: "#7a4a2a",
    oil: "#ffb020", oilHot: "#ffe08a", valve: "#d83b2b", valveLit: "#ff6a4d",
    smoke: "#262c44", gauge: "#e8dfc6",
    flame: ["#fff4cc", "#ffd34d", "#ff9a1f", "#ff5a1a", "#c22a12"],
  };
  const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  let cv, ctx, bg, W = 0, H = 0, S = 4, horizon = 0, raf = 0, last = 0, t = 0, running = false;
  let layout = null, stars = [], windows = [], puffs = [], flowSpeed = 0.3, valveAngle = 0, valveSpin = 0, rush = 0;
  const reduce = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296); }

  // ------------------------------------------------------------ static layer, drawn once per size into an image
  function buildStatic() {
    const img = new ImageData(W, H), d = img.data;
    const put = (x, y, c) => { x |= 0; y |= 0; if (x < 0 || y < 0 || x >= W || y >= H) return; const i = (y * W + x) * 4, [r, g, b] = c; d[i] = r; d[i + 1] = g; d[i + 2] = b; d[i + 3] = 255; };
    const rect = (x, y, w, h, c) => { for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) put(x + i, y + j, c); };
    const sky = P.sky.map(hex);
    // sky: bands of night blue to a warm haze over the refinery, blended with an ordered dither
    for (let y = 0; y < horizon; y++) {
      const v = (y / horizon) * (sky.length - 1), i = Math.floor(v), f = v - i;
      for (let x = 0; x < W; x++) put(x, y, f * 16 > BAYER[y % 4][x % 4] ? sky[Math.min(i + 1, sky.length - 1)] : sky[i]);
    }
    // moon with a few craters
    const m = layout.moon, mo = hex(P.moon), ms = hex(P.moonShade);
    for (let y = -m.r; y <= m.r; y++) for (let x = -m.r; x <= m.r; x++) {
      const r2 = x * x + y * y;
      if (r2 <= m.r * m.r + m.r * 0.6) put(m.x + x, m.y + y, (x - 1) * (x - 1) + (y + 1) * (y + 1) > m.r * m.r * 0.72 && x > 0 ? ms : mo);
    }
    [[-2, -1, 1], [2, 2, 1], [-1, 3, 0], [3, -2, 0]].forEach(([cx, cy, big]) => { put(m.x + cx, m.y + cy, ms); if (big) put(m.x + cx + 1, m.y + cy, ms); });
    // far shore: a low skyline along the whole horizon
    const far = hex(P.far), r = rng(7);
    for (let x = 0; x < W;) {
      const w = 3 + Math.floor(r() * 9), h = 2 + Math.floor(r() * (x > layout.plant.x0 - 20 ? 5 : 9));
      rect(x, horizon - h, w, h, far);
      for (let k = 0; k < w * h / 9; k++) if (r() < 0.5) windows.push({ x: x + Math.floor(r() * w), y: horizon - 1 - Math.floor(r() * (h - 1)), p: r() });
      x += w + Math.floor(r() * 3);
    }
    // the refinery stands on a strip of shore
    const pl = layout.plant, steel = hex(P.steel), lit = hex(P.steelLit), dark = hex(P.steelDark), rail = hex(P.rail);
    rect(pl.x0, horizon - 2, W - pl.x0, 3, dark);
    const column = (x, w, h) => {
      rect(x, horizon - h, w, h, steel); rect(x, horizon - h, 1, h, lit);
      rect(x - 1, horizon - h - 1, w + 2, 1, rail);
      for (let y = horizon - h + 5; y < horizon - 2; y += 7) rect(x - 1, y, w + 2, 1, rail);       // platforms
      for (let y = horizon - h + 2; y < horizon - 2; y += 2) put(x + w, y, rail);               // ladder
    };
    const tank = (x, w, h) => {
      for (let y = 0; y < h; y++) {
        const inset = y === 0 ? 2 : y === 1 ? 1 : 0;
        rect(x + inset, horizon - h + y, w - inset * 2, 1, y < 2 ? hex(P.tankLit) : hex(P.tank));
      }
      for (let i = 0; i < h - 2; i++) put(x + 2 + i, horizon - 2 - i, rail);                   // stair
      rect(x, horizon - Math.floor(h / 2), w, 1, dark);
    };
    const stack = (x, h) => {
      rect(x, horizon - h, 2, h, steel); put(x, horizon - h, lit);
      for (let y = horizon - h; y < horizon - h + 6; y += 2) rect(x, y, 2, 1, hex("#8a2a2a"));    // red bands near the top
    };
    pl.columns.forEach(([x, w, h]) => column(x, w, h));
    pl.tanks.forEach(([x, w, h]) => tank(x, w, h));
    pl.stacks.forEach(([x, h]) => stack(x, h));
    // pipe rack joining the units
    for (const y of [horizon - 6, horizon - 9]) for (let x = pl.x0 + 2; x < W; x++) if ((x + y) % 23) put(x, y, rail);
    // flare tower: a lattice
    const f = pl.flare;
    for (let y = f.y; y < horizon; y++) { put(f.x, y, steel); put(f.x + 2, y, steel); if ((y - f.y) % 3 === 0) put(f.x + 1, y, rail); }
    // crane over the jetty
    const c = pl.crane;
    for (let y = c.y; y < horizon; y++) { put(c.x, y, steel); if ((y - c.y) % 3 === 0) put(c.x + 1, y, rail); put(c.x + 2, y, steel); }
    for (let x = c.x - c.boom; x <= c.x + 4; x++) { put(x, c.y, steel); if (x % 2) put(x, c.y + 1, rail); }
    for (let i = 0; i < 4; i++) put(c.x - c.boom + 3 + i, c.y + 2 + i * 0, dark);
    // jetty reaching out over the water
    const j = pl.jetty;
    rect(j.x, horizon, j.w, 2, dark); for (let x = j.x + 2; x < j.x + j.w; x += 6) rect(x, horizon + 2, 1, 3, steel);
    // sea
    const sea = hex(P.sea);
    for (let y = horizon; y < H; y++) for (let x = 0; x < W; x++) if (!(y < horizon + 2 && x >= j.x && x < j.x + j.w)) put(x, y, sea);
    // the pipeline across the front, with flanges and supports down to the bottom edge
    const pp = layout.pipe, top = hex(P.pipeTop), body = hex(P.pipe), low = hex(P.pipeLow), fl = hex(P.flange), rust = hex(P.rust);
    for (let x = 0; x < W; x++) {
      put(x, pp.y, top); rect(x, pp.y + 1, 1, pp.h - 2, body); put(x, pp.y + pp.h - 1, low);
      if (x % 29 === 5) { rect(x, pp.y - 1, 2, pp.h + 2, fl); }
      if (x % 29 === 15) { rect(x, pp.y + pp.h, 2, H - pp.y - pp.h, low); rect(x - 1, H - 2, 4, 2, body); }
      if (x % 41 === 9) put(x, pp.y + pp.h - 2, rust);
    }
    // sight glass where the oil shows through
    rect(pp.glass, pp.y + 2, pp.glassW, pp.h - 4, hex("#0b0f1c"));
    bg = img;
  }

  // ------------------------------------------------------------ layout from the screen size
  function measure() {
    const vw = window.innerWidth, vh = window.innerHeight;
    S = Math.max(2, Math.min(6, Math.floor(Math.min(vw, vh * 1.25) / 170)));
    W = Math.ceil(vw / S); H = Math.ceil(vh / S);
    const portrait = vh > vw * 1.05;
    horizon = Math.round(H * (portrait ? 0.7 : 0.64));
    const x0 = portrait ? Math.round(W * 0.05) : Math.round(W * 0.5);
    const span = W - x0, r = rng(11);
    const columns = [], tanks = [], stacks = [];
    const at = (f) => x0 + Math.round(span * f);
    columns.push([at(0.18), 5, Math.round(H * 0.28)], [at(0.26), 4, Math.round(H * 0.22)], [at(0.62), 6, Math.round(H * 0.31)]);
    tanks.push([at(0.34), 18, 10], [at(0.47), 14, 8], [at(0.72), 20, 11], [at(0.86), 13, 7]);
    stacks.push([at(0.42), Math.round(H * 0.34)], [at(0.56), Math.round(H * 0.27)]);
    layout = {
      portrait,
      moon: { x: portrait ? Math.round(W * 0.82) : Math.round(W * 0.7), y: Math.round(H * (portrait ? 0.6 : 0.14)), r: Math.max(5, Math.round(Math.min(H * 0.035, W * 0.05))) },
      plant: { x0, columns, tanks, stacks,
        flare: { x: at(0.94), y: horizon - Math.round(H * 0.36) },
        crane: { x: at(0.06), y: horizon - Math.round(H * 0.22), boom: Math.round(span * 0.12) },
        jetty: { x: at(0.0) - Math.round(span * 0.2), w: Math.round(span * 0.24) } },
      pipe: { y: H - 12, h: 7, glass: Math.round(W * (portrait ? 0.15 : 0.08)), glassW: Math.round(W * (portrait ? 0.55 : 0.34)) },
      valve: { x: Math.round(W * (portrait ? 0.82 : 0.47)), y: H - 9 },
      gauge: { x: Math.round(W * (portrait ? 0.68 : 0.535)), y: H - 18 },
      ships: [
        { len: Math.round(Math.min(64, W * 0.2)), y: horizon + Math.round((H - horizon) * 0.38), x: W * 0.78, v: -1.1, lit: true },
        { len: Math.round(Math.min(40, W * 0.12)), y: horizon + Math.round((H - horizon) * 0.12), x: W * 0.2, v: 0.45, lit: false },
      ],
    };
    stars = []; windows = []; puffs = [];
    for (let i = 0; i < Math.round(W * horizon / 160); i++) stars.push({ x: Math.floor(r() * W), y: Math.floor(r() * horizon * 0.8), p: r() * 6.28, s: r() < 0.12 });
    cv.width = W; cv.height = H;
    ctx.imageSmoothingEnabled = false;
    buildStatic();
  }

  // ------------------------------------------------------------ animated layer
  const dot = (x, y, c, w = 1, h = 1) => { ctx.fillStyle = c; ctx.fillRect(x | 0, y | 0, w, h); };
  function drawStars() {
    for (const s of stars) {
      const tw = Math.sin(t * (s.s ? 2.2 : 1.1) + s.p);
      if (tw < -0.75) continue;
      dot(s.x, s.y, tw > 0.4 ? P.star : P.starDim);
      if (s.s && tw > 0.85) { dot(s.x - 1, s.y, P.starDim); dot(s.x + 1, s.y, P.starDim); dot(s.x, s.y - 1, P.starDim); dot(s.x, s.y + 1, P.starDim); }
    }
  }
  function drawWindows() {
    for (const w of windows) if (Math.sin(t * 0.3 + w.p * 40) > -0.6 || w.p < 0.2) dot(w.x, w.y, P.farLit);
  }
  function blink(x, y, period, phase) {
    if (((t + phase) % period) > period * 0.35) return;
    dot(x, y, P.red); ctx.globalAlpha = 0.45; dot(x - 1, y, P.red); dot(x + 1, y, P.red); dot(x, y - 1, P.red); ctx.globalAlpha = 1;
  }
  function drawFlare() {
    const f = layout.plant.flare, cx = f.x + 1, top = f.y - 1, r = rng(Math.floor(t * 10) + 3);
    // glow on the sky behind the flame, dithered
    ctx.fillStyle = "rgba(255,140,40,0.10)";
    for (let y = -14; y <= 10; y++) for (let x = -14; x <= 14; x++) if (x * x + y * y < 190 && (x + y + Math.floor(t * 6)) % 2 === 0) ctx.fillRect(cx + x, top - 6 + y, 1, 1);
    const h = 8 + Math.floor(r() * 4);
    for (let i = 0; i < h; i++) {
      const w = Math.max(1, Math.round((1 - i / h) * 3 + (i < 3 ? 1 : 0))), jx = Math.round((r() - 0.5) * (i / h) * 3);
      for (let k = -w; k <= w; k++) {
        const edge = Math.abs(k) / (w + 0.01), heat = Math.min(4, Math.floor(edge * 2.4 + (i / h) * 2.6));
        dot(cx + k + jx, top - i, P.flame[heat]);
      }
    }
  }
  function drawSmoke(dt) {
    for (const [x, h] of layout.plant.stacks) if (Math.random() < dt * 1.4) puffs.push({ x: x + 1, y: horizon - h - 1, a: 1, s: 1 + Math.random() });
    for (const p of puffs) { p.y -= dt * 4 * p.s; p.x += dt * 2.5; p.a -= dt * 0.18; }
    puffs = puffs.filter((p) => p.a > 0);
    for (const p of puffs) {
      const sz = p.a > 0.6 ? 2 : 3;
      ctx.globalAlpha = Math.max(0, p.a) * 0.8; dot(p.x, p.y, P.smoke, sz, sz); ctx.globalAlpha = 1;
    }
  }
  function drawWater() {
    for (let y = horizon + 2, k = 0; y < layout.pipe.y - 1; y += 3, k++) {
      const depth = (y - horizon) / (H - horizon), seg = 4 + Math.round(depth * 10), gap = 9 + Math.round(depth * 14);
      const off = Math.floor((t * (4 + depth * 10) + k * 17) % (seg + gap));
      for (let x = -off; x < W; x += seg + gap) dot(x, y, k % 3 ? P.wave : P.waveLit, seg, 1);
    }
    // reflections of the moon and the flare: shimmering dashes straight down from them
    const refl = (sx, col, width, alpha) => {
      for (let y = horizon + 2; y < layout.pipe.y - 1; y += 2) {
        const w = Math.max(1, Math.round(width * (0.5 + 0.5 * Math.sin(y * 0.7 + t * 3)))), jx = Math.round(Math.sin(y * 1.3 + t * 2) * 2);
        ctx.globalAlpha = alpha * (1 - (y - horizon) / (H - horizon)); dot(sx - (w >> 1) + jx, y, col, w, 1);
      }
      ctx.globalAlpha = 1;
    };
    refl(layout.moon.x, P.moon, 5, 0.55);
    refl(layout.plant.flare.x + 1, P.flame[2], 4, 0.6);
  }
  function drawShip(s) {
    const L = s.len, x0 = Math.round(s.x), bob = Math.round(Math.sin(t * 1.6 + L) * 0.6), y0 = s.y + bob, faceLeft = s.v < 0;
    const X = (i) => (faceLeft ? x0 + i : x0 + L - 1 - i);   // i runs from the bow
    const dim = !s.lit;
    for (let r = 0; r < 5; r++) {
      const a = r <= 2 ? 3 - r : 0, b = r >= 3 ? 1 : 0;      // raked bow, nearly square stern
      for (let i = a; i < L - b; i++) dot(X(i), y0 + r, r === 4 ? (dim ? P.steelDark : P.boot) : r === 0 ? (dim ? P.steel : P.hullLit) : (dim ? P.steelDark : P.hull));
    }
    // deck pipes and a manifold
    for (let i = 5; i < L - 13; i++) if (i % 2) dot(X(i), y0 - 1, dim ? P.steel : P.deck);
    dot(X(Math.floor(L * 0.45)), y0 - 2, dim ? P.steel : P.deck); dot(X(Math.floor(L * 0.45)), y0 - 3, dim ? P.steel : P.deck);
    // accommodation block and funnel at the stern
    for (let r = 1; r <= 7; r++) for (let i = L - 12; i < L - 3; i++) dot(X(i), y0 - r, dim ? P.steelDark : P.cabin);
    for (let i = L - 12; i < L - 3; i++) dot(X(i), y0 - 8, dim ? P.steel : P.hullLit);
    for (let r = 8; r <= 11; r++) { dot(X(L - 5), y0 - r, dim ? P.steel : P.deck); dot(X(L - 4), y0 - r, dim ? P.steel : P.deck); }
    if (!dim) {
      dot(X(L - 5), y0 - 10, P.boot); dot(X(L - 4), y0 - 10, P.boot);
      for (let i = L - 11; i < L - 4; i += 2) if (Math.sin(t * 0.5 + i) > -0.7) dot(X(i), y0 - 5, P.window);
      for (let i = L - 10; i < L - 4; i += 3) dot(X(i), y0 - 3, P.window);
      dot(X(1), y0 - 3, P.white); dot(X(L - 8), y0 - 10, P.white);                   // masthead lights
      dot(X(3), y0 + 1, faceLeft ? P.red : P.green);                                    // sidelight
      // lights reflected under the hull
      ctx.globalAlpha = 0.5; dot(X(L - 8), y0 + 7, P.window, 2, 1); dot(X(L - 6), y0 + 9, P.window, 1, 1); ctx.globalAlpha = 1;
    }
    // the bow wave
    ctx.globalAlpha = 0.7; dot(faceLeft ? x0 - 1 : x0 + L, y0 + 4, P.waveLit, 2, 1); ctx.globalAlpha = 1;
  }
  function drawPipe(dt) {
    const pp = layout.pipe, speed = (flowSpeed + rush) * 26;
    // oil in the sight glass: amber slugs moving left to right, faster when the valve opens
    const off = (t * speed) % 9;
    for (let x = pp.glass - 9 + off; x < pp.glass + pp.glassW; x += 9) {
      const a = Math.max(pp.glass, Math.round(x)), b = Math.min(pp.glass + pp.glassW, Math.round(x) + 5);
      if (b > a) { dot(a, pp.y + 2, rush > 0.5 ? P.oilHot : P.oil, b - a, pp.h - 4); }
    }
    // valve hand-wheel: a red ring with four spokes, turned by its angle
    const v = layout.valve; valveAngle += (0.15 + valveSpin) * dt * 6; valveSpin = Math.max(0, valveSpin - dt * 3);
    dot(v.x - 1, v.y - 2, P.flange, 3, 6);                                              // stem
    for (let y = -7; y <= 7; y++) for (let x = -7; x <= 7; x++) {
      const d = Math.hypot(x, y); let c = null;
      if (d >= 5 && d <= 6.6) c = (x + y) < 0 ? P.valveLit : P.valve;
      else if (d < 5) {
        for (const a of [valveAngle, valveAngle + Math.PI / 2]) if (Math.abs(x * Math.sin(a) - y * Math.cos(a)) < 0.75) c = P.valve;
        if (d < 1.6) c = P.flange;
      }
      if (c) dot(v.x + x, v.y - 10 + y, c);
    }
    // pressure gauge: the needle follows the flow
    const g = layout.gauge, ang = Math.PI * (0.85 + Math.min(1.3, (flowSpeed + rush) * 1.1)) + Math.sin(t * 7) * 0.04;
    for (let y = -5; y <= 5; y++) for (let x = -5; x <= 5; x++) { const d = Math.hypot(x, y); if (d <= 5.4) dot(g.x + x, g.y + y, d > 4.3 ? P.flange : P.gauge); }
    for (let i = 0; i <= 3; i++) dot(g.x + Math.round(Math.cos(ang) * i), g.y + Math.round(Math.sin(ang) * i), P.valve);
    dot(g.x, g.y + 6, P.flange, 1, layout.pipe.y - g.y - 6);
  }

  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    const step = 1 / 12;                       // 12 frames a second, for a pixel-animation feel
    if (now - last < step * 1000 - 1) return;
    const dt = Math.min(0.25, (now - last) / 1000 || step); last = now; t += dt;
    rush = Math.max(0, rush - dt * 0.35);
    draw(dt);
  }
  function draw(dt) {
    ctx.putImageData(bg, 0, 0);
    drawStars(); drawWindows(); drawSmoke(dt); drawFlare();
    for (const [x, h] of layout.plant.stacks) blink(x, horizon - h - 1, 1.6, x * 0.01);
    for (const [x, , h] of layout.plant.columns) blink(x + 1, horizon - h - 2, 2.2, x * 0.03);
    blink(layout.plant.crane.x + 1, layout.plant.crane.y - 1, 1.9, 0.4);
    drawWater();
    for (const s of layout.ships) {
      s.x += s.v * dt * 6 * (1 + rush * 3);
      if (s.v < 0 && s.x < -s.len - 4) s.x = W + 4; if (s.v > 0 && s.x > W + 4) s.x = -s.len - 4;
      drawShip(s);
    }
    drawPipe(dt);
  }

  function start(canvas) {
    cv = canvas; ctx = cv.getContext("2d");
    measure();
    running = true; last = 0;
    if (reduce()) { t = 3; draw(0); running = false; return; }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  let rs = 0;
  window.addEventListener("resize", () => { if (!cv) return; clearTimeout(rs); rs = setTimeout(() => { measure(); if (!running) draw(0); }, 120); });
  return {
    start,
    stop() { running = false; cancelAnimationFrame(raf); },
    resume() { if (cv && !running && !reduce()) { running = true; last = 0; raf = requestAnimationFrame(frame); } },
    setFlow(f) { flowSpeed = Math.max(0.05, Math.min(1, f)); },   // share of pre-war flow getting through
    openValve() { valveSpin = 4; rush = 2.2; },
    palette: P,
  };
})();

// Small pixel icons for buttons, from character grids: one rect per lit cell, drawn with crisp edges.
window.HZPixIcon = (rows, colors, label) => {
  const h = rows.length, w = rows[0].length;
  let r = "";
  rows.forEach((row, y) => [...row].forEach((ch, x) => { if (colors[ch]) r += `<rect x="${x}" y="${y}" width="1" height="1" fill="${colors[ch]}"/>`; }));
  return `<svg class="pxi" viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges" ${label ? `role="img" aria-label="${label}"` : 'aria-hidden="true"'}>${r}</svg>`;
};
