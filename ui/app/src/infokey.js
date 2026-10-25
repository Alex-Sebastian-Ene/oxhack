// One behaviour for every info key in the app (World, Strait, Households, Models).
// Each view fills the shared #sheet with its own handler; this layer runs after them and makes the sheet act the same
// everywhere: it opens beside the key that opened it (below it, or above if there's no room, always inside the window),
// clicking the same key again closes it, and ×, Escape or a click outside closes it and returns focus to the key.
// On a phone-width window it stays a full-width sheet at the bottom of the screen.
(() => {
  const sheet = document.getElementById("sheet");
  if (!sheet) return;
  const KEYS = "[data-info], [data-winfo], [data-hsrc], [data-msrc], [data-mhow]";
  const GAP = 8, PAD = 12, NARROW = 560;
  let owner = null, wasOpenFor = null;

  function place() {
    if (sheet.hidden || !owner) return;
    const W = innerWidth, H = innerHeight;
    if (W < NARROW || !owner.isConnected || !owner.getClientRects().length) { clearPlace(); return; }
    const r = owner.getBoundingClientRect(), w = Math.min(420, W - 2 * PAD);
    Object.assign(sheet.style, { width: `${w}px`, right: "auto", bottom: "auto", maxHeight: `${Math.round(Math.min(H * 0.7, 560))}px` });
    const h = sheet.getBoundingClientRect().height;
    let top, left;
    if (r.bottom + GAP + h <= H - PAD) top = r.bottom + GAP;     // below the key
    else if (r.top - GAP - h >= PAD) top = r.top - GAP - h;     // or above it
    if (top != null) {
      left = r.right - w;                                       // right edges lined up with the key
      if (left < PAD) left = r.left;                            // a key near the left edge: left edges lined up
    } else {                                                    // no room above or below: beside it, on the roomier side
      left = r.left + r.width / 2 > W / 2 ? r.left - GAP - w : r.right + GAP;
      top = Math.min(Math.max(PAD, r.top - 24), H - PAD - h);
    }
    sheet.style.left = `${Math.round(Math.max(PAD, Math.min(left, W - w - PAD)))}px`;
    sheet.style.top = `${Math.round(top)}px`;
    sheet.classList.add("hz-placed");
  }
  function clearPlace() {
    ["width", "right", "bottom", "left", "top", "maxHeight"].forEach((k) => (sheet.style[k] = ""));
    sheet.classList.remove("hz-placed");
  }
  function close(focusKey) {
    const k = owner;
    sheet.hidden = true;
    if (k) k.setAttribute("aria-expanded", "false");
    owner = null; clearPlace();
    if (focusKey && k && k.isConnected) k.focus({ preventScroll: true });
  }

  // before the views' handlers: remember whether this key's sheet was already open
  document.addEventListener("click", (e) => {
    const k = e.target.closest(KEYS);
    wasOpenFor = k && !sheet.hidden && owner === k ? k : null;
  }, true);

  // after them: toggle, place, or close on a click outside
  document.addEventListener("click", (e) => {
    const k = e.target.closest(KEYS);
    if (k) {
      if (wasOpenFor === k) { close(true); return; }
      if (sheet.hidden) return;                                 // this key didn't open the sheet
      if (owner && owner !== k) owner.setAttribute("aria-expanded", "false");
      owner = k; k.setAttribute("aria-expanded", "true");
      sheet.scrollTop = 0;
      place();
      return;
    }
    if (e.target.closest("#sheet-close")) { close(true); return; }
    if (!sheet.hidden && owner && !sheet.contains(e.target) && e.isTrusted) close(false);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && owner) close(true); });

  // keep it beside its key while the page or a panel scrolls, or the window resizes
  let raf = 0;
  const follow = () => { if (!raf && owner) raf = requestAnimationFrame(() => { raf = 0; place(); }); };
  addEventListener("resize", follow);
  document.addEventListener("scroll", (e) => { if (!sheet.contains(e.target)) follow(); }, true);
  // a view switch hides the key: close rather than float over the new view
  document.addEventListener("click", (e) => { if (e.target.closest("[data-mode], [data-hmode]") && owner) close(false); }, true);

  document.querySelectorAll(KEYS).forEach((k) => { k.setAttribute("aria-haspopup", "dialog"); k.setAttribute("aria-expanded", "false"); });
})();
