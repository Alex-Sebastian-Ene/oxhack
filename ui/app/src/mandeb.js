// Which strait the Strait view shows. Runs before the industry page's scripts: its strait block reads
// window.HZStrait.data() once at load, so switching reloads the page on #mandeb (or back on #app).
// Bab el-Mandeb data: window.STRAITS.mandeb, ui/strait/data/mandeb-scenarios.js (synthetic ships, calibrated
// to published figures; see notes/strait-flow-mandeb.md).
window.HZStrait = (() => {
  const has = () => !!(window.STRAITS && window.STRAITS.mandeb);
  const id = location.hash === "#mandeb" && has() ? "mandeb" : "hormuz";
  // pre-crisis Bab el-Mandeb flow: 8.7 mb/d, EIA Today in Energy (Vortexa data), 2023 average
  const PREWAR = { hormuz: 20, mandeb: 8.7 };
  const NAME = { hormuz: "Hormuz", mandeb: "Bab el-Mandeb" };
  function go(to) {
    if (to === id) return;
    location.hash = to === "mandeb" ? "mandeb" : "app";
    location.reload();
  }
  function mount() {
    if (id === "mandeb") document.body.classList.add("hz-mandeb");
    const sel = document.getElementById("scenario");
    if (!sel || !has()) return;
    const seg = document.createElement("div");
    seg.className = "seg hz-straitseg"; seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Which strait");
    seg.innerHTML = ["hormuz", "mandeb"].map((k) => `<button type="button" data-strait="${k}" aria-pressed="${k === id}">${NAME[k]}</button>`).join("");
    sel.before(seg);
    seg.addEventListener("click", (e) => { const b = e.target.closest("[data-strait]"); if (b) go(b.dataset.strait); });
    if (id === "mandeb") {
      const g = document.querySelector('#glob-card [title^="Missing compared"]');
      if (g) g.title = "Missing compared with 8.7 mb/d in 2023 (EIA)";
      const strait = document.querySelector('[data-mode="strait"]');
      if (strait) strait.click();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else setTimeout(mount, 0);
  return { id, name: NAME[id], prewar: PREWAR[id], go, data: () => (id === "mandeb" ? window.STRAITS.mandeb : window.STRAIT) };
})();
