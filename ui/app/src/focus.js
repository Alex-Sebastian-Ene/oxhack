// Picking a country focuses on it: the map eases up into a shorter band and zooms to the country, and its detail opens
// large below, the country card beside the shock and product cards. Closing the card (or clicking the country again)
// eases back to the whole map. The page's select() sends "hz-select"; HZZoomTo (world.py) does the zoom.
(() => {
  const stage = document.getElementById("world-stage");
  const map = stage && stage.querySelector(".mapwrap");
  if (!stage || !map) return;
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
