// Picking a country focuses on it: the map eases up into a shorter band and zooms to the country, and its detail opens
// large below, the country card beside the shock and product cards. Closing the card (or clicking the country again)
// eases back to the whole map. The page's select() sends "hz-select"; HZZoomTo (world.py) does the zoom.
(() => {
  const stage = document.getElementById("world-stage");
  const map = stage && stage.querySelector(".mapwrap");
  if (!stage || !map) return;
  // the cards beside the country card (the shock card first) go in one column that can stay in place (focus.css);
  // it has no box of its own outside a picked country, so the side panel looks as before
  const hud = stage.querySelector(".hud"), cc = document.getElementById("country-card");
  if (hud && cc && !hud.querySelector(".hz-side")) {
    const side = document.createElement("div");
    side.className = "hz-side";
    [...hud.children].filter((x) => x !== cc).forEach((x) => side.appendChild(x));
    hud.appendChild(side);
  }
  // a picked country shows only what sets the closure beside it (focus.css): mark the shock card and the ranking
  const lost = document.getElementById("lost"), rank = document.getElementById("w-rank");
  if (lost && lost.closest(".card")) lost.closest(".card").classList.add("hz-shockcard");
  if (rank && rank.closest(".card")) rank.closest(".card").classList.add("hz-rankcard");
  const still = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let seq = 0;

  function focus(name) {
    const on = !!name, was = stage.classList.contains("hz-focus"), my = ++seq;
    let settled = Promise.resolve();
    if (on !== was) {
      // ease the map's height from where it is to where the new layout puts it (an animation, not inline styles,
      // which the page rewrites for the map's background)
      const from = map.getBoundingClientRect().height;
      stage.classList.toggle("hz-focus", on);
      const to = map.getBoundingClientRect().height;
      if (!still() && Math.abs(to - from) > 4 && map.animate)
        settled = map.animate([{ height: `${from}px` }, { height: `${to}px` }], { duration: 500, easing: "cubic-bezier(.2,.8,.2,1)" }).finished.catch(() => {});
      if (on) {
        stage.scrollTop = 0;
        const top = map.getBoundingClientRect().top;
        if (top < 0 || top > window.innerHeight / 3) window.scrollTo({ top: window.scrollY + top - 8, behavior: still() ? "auto" : "smooth" });
      }
    }
    // zoom once the map has settled at its new size: the page refits the map when its box changes, so a zoom made
    // earlier would land in the wrong place
    settled.then(() => requestAnimationFrame(() => requestAnimationFrame(() => {
      if (my === seq && window.HZZoomTo) window.HZZoomTo(name);
    })));
  }
  // how far the detail has slid over the map, 0 to 1, for the map's dimming and the cards' frosting (focus.css). The
  // stage scrolls on a wide screen, the page on a phone.
  function cover() {
    if (!stage.classList.contains("hz-focus")) { stage.style.removeProperty("--hz-cover"); return; }
    const hud = stage.querySelector(".hud"), m = map.getBoundingClientRect(), h = hud && hud.getBoundingClientRect();
    if (!h || !m.height) return;
    const over = Math.max(0, m.bottom - h.top);   // how much of the map the detail now covers
    stage.style.setProperty("--hz-cover", Math.min(1, over / (m.height * 0.7)).toFixed(3));
  }
  stage.addEventListener("scroll", cover, { passive: true });
  window.addEventListener("scroll", cover, { passive: true });
  document.addEventListener("hz-select", () => setTimeout(cover, 0));

  let current = null, again = 0;
  document.addEventListener("hz-select", (e) => { current = e.detail && e.detail.name; focus(current); });
  // the page refits the map whenever its box changes (a window resize, the phone's address bar), which leaves a zoom
  // behind: frame the picked country again once the size settles
  let last = "";
  new ResizeObserver(() => {
    const r = map.getBoundingClientRect(), key = `${Math.round(r.width)}x${Math.round(r.height)}`;
    if (key === last) return;
    last = key;
    clearTimeout(again);
    if (current && !map.getAnimations().length) again = setTimeout(() => window.HZZoomTo && current && window.HZZoomTo(current), 200);
  }).observe(map);
})();
