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

  // ------------------------------------------------------------ pixel wipe between the landing and the app
  function wipe(mid, done) {
    if (reduce) { mid(); if (done) done(); return; }
    const cell = 24, cols = Math.ceil(innerWidth / cell), rows = Math.ceil(innerHeight / cell);
    wipeC.width = cols; wipeC.height = rows; wipeC.hidden = false;
    const c = wipeC.getContext("2d"), order = [...Array(cols * rows).keys()].sort(() => Math.random() - 0.5);
    const run = (fill, ms, then) => {
      const t0 = performance.now();
      const stepF = (now) => {
        const k = Math.min(order.length, Math.round(((now - t0) / ms) * order.length));
        c.fillStyle = "#04060c";
        for (let n = 0; n < k; n++) { const j = order[n], x = j % cols, y = (j / cols) | 0; fill ? c.fillRect(x, y, 1, 1) : c.clearRect(x, y, 1, 1); }
        if (k < order.length) requestAnimationFrame(stepF); else then();
      };
      requestAnimationFrame(stepF);
    };
    c.clearRect(0, 0, cols, rows);
    run(true, 380, () => { mid(); c.fillStyle = "#04060c"; c.fillRect(0, 0, cols, rows); setTimeout(() => run(false, 420, () => { wipeC.hidden = true; if (done) done(); }), 60); });
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
