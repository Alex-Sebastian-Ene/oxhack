// Landing page: the night refinery, three headline numbers with their sources, sound, and "Open the valve",
// which turns the wheel, sounds the horn and wipes through to the app. #app in the address skips it.
window.HZIcons = {
  valve: ["...KKKKK...", ".KK..K..KK.", ".K...K...K.", "K....K....K", "K...KKK...K", "KKKKKGKKKKK", "K...KKK...K", "K....K....K", ".K...K...K.", ".KK..K..KK.", "...KKKKK..."],
  sound: ["....K......", "...KK...K..", "KKKKK.K..K.", "KKKKK..K.K.", "KKKKK..K.K.", "KKKKK.K..K.", "...KK...K..", "....K......"],
  mute: ["....K......", "...KK......", "KKKKK.K...K", "KKKKK..K.K.", "KKKKK...K..", "KKKKK..K.K.", "...KK.K...K", "....K......"],
  music: ["...KKKKKK", "...KKKKKK", "...K....K", "...K....K", "...K....K", ".KKK..KKK", "KKKK.KKKK", "KKKK.KKKK", ".KK...KK."],
  ship: ["...........K..", "..........KK..", "...K......KKK.", "KKKKKKKKKKKKKK", ".KKKKKKKKKKKK.", "..KKKKKKKKKK.."],
};
(() => {
  const $ = (id) => document.getElementById(id);
  const L = $("hz-landing"), scene = $("hz-scene"), wipeC = $("hz-wipe");
  if (!L) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const icon = (k, extra) => window.HZPixIcon(window.HZIcons[k], { K: "currentColor", G: "#ffe08a", ...extra });
  $("hz-l-go-i").innerHTML = icon("valve");
  const sb = $("hz-l-sound");
  function soundUI() {
    const on = window.HZSound.on;
    sb.setAttribute("aria-pressed", String(on));
    $("hz-l-sound-i").innerHTML = icon(on ? "sound" : "mute");
    $("hz-l-sound-t").textContent = on ? "Sound off" : "Sound on";
    if (window.HZShell) window.HZShell.sync();
  }
  soundUI();
  sb.addEventListener("click", (e) => {
    e.stopPropagation(); sb.classList.remove("hint");
    const on = window.HZSound.setSound(!window.HZSound.on);
    if (on && window.HZSound.musicWanted()) window.HZSound.setMusic(true);
    soundUI();
  });
  // the first click or key press on the landing brings in the harbour and the music, unless sound was turned off before
  const first = (e) => {
    if (e.target.closest && e.target.closest("#hz-l-sound")) return;
    if (window.HZSound.wanted() && !window.HZSound.on) { window.HZSound.setSound(true); if (window.HZSound.musicWanted()) window.HZSound.setMusic(true); sb.classList.remove("hint"); soundUI(); }
  };
  L.addEventListener("pointerdown", first, { once: true });
  L.addEventListener("keydown", first, { once: true });

  // ------------------------------------------------------------ the headline numbers, from the page's own data
  function stats() {
    const S = window.STRAIT, PW = window.PORTWATCH;
    if (!S || !PW) return;
    const sc = S.scenarios.aug2026 || Object.values(S.scenarios)[0], flow = sc.estimate.total.p50, lost = Math.round((1 - flow / 20) * 100);
    const i = PW.dates.length - 1, day = new Date(PW.dates[i] + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
    $("hz-l-tickets").innerHTML =
      `<span class="hz-l-ticket"><b>${flow.toFixed(1)}</b><span>mb/d getting through (est.)</span></span>` +
      `<span class="hz-l-ticket"><b class="lost">${lost}%</b><span>of normal flow lost</span></span>` +
      `<span class="hz-l-ticket"><b class="real">${PW.n_total[i]}</b><span>ships on ${day} (real)</span></span>`;
    $("hz-l-src").textContent = `Flow: our estimate, simulated ${sc.label.split(",")[0]} scenario, vs 20 mb/d pre-war (EIA 2024). ` +
      `Ships: IMF PortWatch, cached ${String(PW.collected_at).slice(0, 10)}. Not live.`;
    window.HZScene.setFlow(flow / 20);
  }

  // ------------------------------------------------------------ oil pours in, fills the screen, then drains away
  // Three pixel streams pour from the top and splash where they land; the pool rises with a lit, rolling surface.
  // When the screen is full, mid() swaps what is underneath; then the oil drains down, dripping from the top.
  function wipe(mid, done) {
    if (reduce) { mid(); if (done) done(); return; }
    const px = 6, W = Math.ceil(innerWidth / px), H = Math.ceil(innerHeight / px);
    wipeC.width = W; wipeC.height = H; wipeC.hidden = false;
    const c = wipeC.getContext("2d");
    const BODY = "#1a1108", DEEP = "#100a04", SHEEN = "#4a2f12", LIP = "#ffa424", LIP2 = "#ffd27a", DROP = "#2c1c0b";
    const streams = [0.2, 0.5, 0.8].map((f, i) => ({ x: Math.round(W * f + (Math.random() - 0.5) * W * 0.06), w: i === 1 ? 4 : 3, delay: [80, 0, 150][i] }));
    const drops = [], FILL = 1000, HOLD = 140, DRAIN = 700, END = FILL + HOLD + DRAIN;
    const t0 = performance.now();
    let last = t0, switched = false, level = H + 2;
    const ease = (k) => k * k * (3 - 2 * k);
    const surf = (x, t) => Math.round(Math.sin(x * 0.19 + t * 0.011) * 1.3 + Math.sin(x * 0.07 - t * 0.007) * 1.1);
    const splash = (x, y, n, up) => { for (let i = 0; i < n; i++) drops.push({ x, y, vx: (Math.random() - 0.5) * 1.8, vy: -(0.6 + Math.random() * up), lit: Math.random() < 0.5 }); };
    window.HZSound.play("pour");
    function frame(now) {
      const t = now - t0, dt = Math.min(48, now - last) / 16.7, draining = t > FILL + HOLD;
      last = now;
      if (t < FILL) level = H + 2 - (H + 8) * ease(t / FILL);
      else if (!draining) level = -6;
      else level = -6 + (H + 14) * Math.pow(Math.min(1, (t - FILL - HOLD) / DRAIN), 1.6);
      if (!switched && t >= FILL) { switched = true; mid(); }
      c.clearRect(0, 0, W, H);
      // the pour
      if (!draining) for (const s of streams) {
        if (t < s.delay) continue;
        const bottom = Math.max(0, Math.ceil(level));
        c.fillStyle = BODY; c.fillRect(s.x, 0, s.w, bottom);
        c.fillStyle = LIP; c.fillRect(s.x + 1, 0, 1, bottom);
        if (level > 3 && Math.random() < 0.7 * dt) splash(s.x + s.w / 2, level - 1, 3, 2.1);
      }
      // the pool: dark body, a lit lip that rolls, a few sheen pixels under it
      for (let x = 0; x < W; x++) {
        const y = Math.round(level + surf(x, t));
        if (y >= H) continue;
        const top = Math.max(0, y);
        c.fillStyle = BODY; c.fillRect(x, top, 1, H - top);
        if (y + 8 < H) { c.fillStyle = DEEP; c.fillRect(x, Math.max(0, y + 8), 1, H - Math.max(0, y + 8)); }
        if (y >= 0) { c.fillStyle = (x + Math.floor(t / 70)) % 11 === 0 ? LIP2 : LIP; c.fillRect(x, y, 1, 1); }
        if (y + 2 >= 0 && y + 2 < H && (x + Math.floor(t / 120)) % 14 < 5) { c.fillStyle = SHEEN; c.fillRect(x, y + 2, 1, 1); }
      }
      // drips off the top while it drains
      if (draining && level > 6 && level < H * 0.75 && Math.random() < 0.55 * dt) drops.push({ x: Math.random() * W, y: 0, vx: 0, vy: 0.4, lit: false });
      for (let i = drops.length - 1; i >= 0; i--) {
        const d = drops[i];
        d.vy += 0.13 * dt; d.x += d.vx * dt; d.y += d.vy * dt;
        if (d.y > level + 1 || d.y > H + 2) { drops.splice(i, 1); continue; }
        c.fillStyle = d.lit ? LIP : DROP; c.fillRect(Math.round(d.x), Math.round(d.y), 1, d.vy > 1.5 ? 2 : 1);
      }
      if (t >= END && (!drops.length || t > END + 700)) { c.clearRect(0, 0, W, H); wipeC.hidden = true; if (done) done(); return; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  let opening = false;
  function openApp(e) {
    if (opening || L.hidden) return;
    opening = true;
    const go = $("hz-l-go");
    go.classList.add("turning");
    window.HZScene.openValve();
    window.HZSound.play("valve");
    setTimeout(() => window.HZSound.play("horn"), 450);
    setTimeout(() => wipe(() => {
      L.hidden = true; document.body.classList.remove("hz-landing-open"); window.HZScene.stop();
      go.classList.remove("turning");
      window.dispatchEvent(new Event("resize"));   // the maps measure themselves once they can be seen
    }, () => { opening = false; const t = document.querySelector('[data-mode][aria-pressed="true"]'); if (t) t.focus({ preventScroll: true }); }), reduce ? 0 : 750);
  }
  function showLanding() {
    if (!L.hidden) return;
    wipe(() => {
      L.hidden = false; document.body.classList.add("hz-landing-open");
      window.HZScene.resume(); window.dispatchEvent(new Event("resize"));
    }, () => $("hz-l-go").focus({ preventScroll: true }));
  }
  $("hz-l-go").addEventListener("click", openApp);
  L.addEventListener("keydown", (e) => { if (e.key === "Escape" || e.key === "PageDown" || e.key === "ArrowDown") openApp(); });
  L.addEventListener("wheel", (e) => { if (e.deltaY > 20) openApp(); }, { passive: true });
  let ty = null;
  L.addEventListener("touchstart", (e) => { ty = e.touches[0].clientY; }, { passive: true });
  L.addEventListener("touchmove", (e) => { if (ty != null && ty - e.touches[0].clientY > 60) { ty = null; openApp(); } }, { passive: true });

  window.HZLanding = { show: showLanding, open: openApp, soundUI };
  if (location.hash === "#app") { L.hidden = true; }
  else { document.body.classList.add("hz-landing-open"); window.HZScene.start(scene); setTimeout(() => $("hz-l-go").focus({ preventScroll: true }), 50); }
  if (L.hidden) window.HZScene.start(scene), window.HZScene.stop();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", stats); else stats();
})();
