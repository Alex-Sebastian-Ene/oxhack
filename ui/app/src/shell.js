// App shell: the pipe strip under the header (its oil runs at the share of Hormuz flow getting through),
// the brand as the home button, the sound keys, interface sounds, and the lost-flow slider driving the music's tension.
window.HZShell = (() => {
  const $ = (id) => document.getElementById(id);
  const icon = (k) => window.HZPixIcon(window.HZIcons[k], { K: "currentColor", G: "#ffe08a" });
  const bar = document.querySelector(".app > header.bar");
  if (!bar) return { sync() {} };
  // brand mark: a pixel tanker in place of the line logo
  const brand = bar.querySelector(".brand");
  const mark = document.createElement("span"); mark.className = "hz-brand"; mark.innerHTML = icon("ship");
  brand.prepend(mark);
  // the brand is the home button: back to the landing page
  brand.classList.add("hz-home"); brand.setAttribute("role", "button"); brand.tabIndex = 0; brand.title = "Home"; brand.setAttribute("aria-label", "Home");
  const home = () => window.HZLanding && window.HZLanding.show();
  brand.addEventListener("click", (e) => { if (!e.target.closest("button")) home(); });   // the SIMULATED pill keeps its own sheet
  brand.addEventListener("keydown", (e) => { if (e.target === brand && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); home(); } });
  // sound and music keys at the right of the header
  const keys = document.createElement("div"); keys.className = "hz-keys";
  keys.innerHTML = `<button type="button" class="hz-key" id="hz-snd" aria-pressed="false" title="Sound" aria-label="Sound"></button>
    <button type="button" class="hz-key" id="hz-mus" aria-pressed="false" title="Music" aria-label="Music">${icon("music")}</button>`;
  bar.querySelector(".tools").append(keys);
  // the pipe strip
  const pipe = document.createElement("div"); pipe.className = "hz-pipe";
  pipe.innerHTML = `<div class="hz-tube" aria-hidden="true"><span class="hz-oil"></span></div><span class="hz-read" id="hz-read"></span>`;
  bar.after(pipe);

  function sync() {
    const S = window.HZSound;
    $("hz-snd").setAttribute("aria-pressed", String(S.on)); $("hz-snd").innerHTML = icon(S.on ? "sound" : "mute");
    $("hz-mus").setAttribute("aria-pressed", String(S.on && S.music));
    $("hz-mus").disabled = !S.on;
  }
  $("hz-snd").addEventListener("click", () => {
    const on = window.HZSound.setSound(!window.HZSound.on);
    if (on && window.HZSound.musicWanted() && !window.HZSound.music) window.HZSound.setMusic(true);
    sync(); if (window.HZLanding) window.HZLanding.soundUI();
  });
  $("hz-mus").addEventListener("click", () => { window.HZSound.setMusic(!window.HZSound.music); sync(); });

  // flow readout: the lost-flow slider sets it in the World view; the scenario menu sets it in the Strait view
  function flow() {
    const lostEl = $("lost");
    const lost = lostEl ? Number(lostEl.value) : 69, got = 20 * (1 - lost / 100);
    $("hz-read").innerHTML = `FLOW <b>${got.toFixed(1)}</b>/20 mb/d · <span class="lost">LOST ${lost}%</span>`;
    pipe.style.setProperty("--flow-dur", `${(0.45 / Math.max(0.04, got / 20)).toFixed(2)}s`);
    window.HZSound.setTension(lost / 100);
    if (window.HZScene) window.HZScene.setFlow(got / 20);
  }
  const lostEl = $("lost");
  if (lostEl) lostEl.addEventListener("input", () => { flow(); window.HZSound.play("tick", Number(lostEl.value) / 100); });
  document.querySelectorAll("[data-lost]").forEach((b) => b.addEventListener("click", () => setTimeout(flow, 0)));
  const scen = $("scenario");
  if (scen) scen.addEventListener("change", () => { setTimeout(flow, 0); window.HZSound.play("clank"); });
  flow();

  // interface sounds, by what was pressed
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button, [data-c], #world .ctry, #world .dot");
    if (!b || b.disabled || b.closest("#hz-landing") || b.id === "hz-snd") return;
    const d = b.dataset || {};
    const kind = d.mode != null ? "clank" : d.lost != null ? "clank" : d.mat != null || d.pick != null || d.goto != null ? "select"
      : b.matches("#world .ctry, #world .dot") || d.c != null ? "select"
      : d.wview != null || d.mmode != null || d.eco != null || d.ctab != null || d.view != null || b.id === "hz-mus" ? "toggle"
      : d.info != null || d.winfo != null ? "paper" : "blip";
    window.HZSound.play(kind);
  }, true);
  const day = $("pw-day");
  if (day) day.addEventListener("input", () => window.HZSound.play("tick", Number(day.value) / Math.max(1, Number(day.max))));
  sync();
  return { sync, flow };
})();
