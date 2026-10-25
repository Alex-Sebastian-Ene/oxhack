// Long explanations in the World view's side panel fold into a dropdown: past two lines, a note shows its start and a
// "More" toggle that drops the rest down. The panel redraws its text often (every slider move, every country), so new
// text is folded as it appears, and a note the reader opened stays open when it is redrawn.
(() => {
  const hud = document.querySelector("#world-stage .hud");
  if (!hud || !window.MutationObserver || !window.ResizeObserver) return;
  // the explanation lines under each row, source notes and the longer card notes; headlines stay as they are
  const SEL = ".why, p.faint, p.sub, p.explain, p.eco-head";
  const LONG = 180;   // characters: shorter text is never folded
  const opened = new Set();
  const key = (el) => { const li = el.closest("li"), nm = li && li.querySelector(".nm"); return [el.id, el.className.replace(/\bfold\S*/g, "").trim(), nm ? nm.textContent : ""].join("|"); };
  // the toggle shows only while the folded text is actually cut (a hidden tab measures 0, so check again when it shows)
  const sync = (el) => {
    const t = el.nextElementSibling;
    if (t && t.classList.contains("fold-t")) t.hidden = !el.classList.contains("fold-open") && el.scrollHeight <= el.clientHeight + 1;
  };
  const ro = new ResizeObserver((es) => es.forEach((e) => sync(e.target)));

  function fold(el) {
    // a note that is already a dropdown of its own (<details>, as the Cost of living rows are) stays as it is
    if (el.classList.contains("fold") || el.textContent.length < LONG || el.closest("details")) return;
    const k = key(el), t = document.createElement("button");
    t.type = "button";
    t.className = "fold-t";
    const set = (open) => {
      el.classList.toggle("fold-open", open);
      t.textContent = open ? "Less ▴" : "More ▾";
      t.setAttribute("aria-expanded", String(open));
    };
    el.classList.add("fold");
    set(opened.has(k));
    // its own click only: a row in the Cost of living list charts itself when clicked
    t.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const open = !el.classList.contains("fold-open");
      set(open);
      if (open) opened.add(k); else opened.delete(k);
      sync(el);
    });
    el.after(t);
    ro.observe(el);
  }
  const scan = (n) => {
    if (n.nodeType !== 1) return;
    if (n.matches(SEL)) fold(n);
    n.querySelectorAll(SEL).forEach(fold);
  };
  scan(hud);
  // text replaced inside a note (innerHTML or textContent) refolds it, so its toggle matches the new length
  new MutationObserver((ms) => ms.forEach((m) => {
    m.addedNodes.forEach(scan);
    if (m.target.nodeType !== 1) return;
    if (m.target.matches(SEL)) fold(m.target);   // a short note that has grown long
    const el = m.target.closest(".fold");
    if (el) sync(el);
  })).observe(hud, { childList: true, subtree: true });
})();
