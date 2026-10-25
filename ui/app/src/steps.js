// "The shock" card as an accordion: each numbered step opens on a click on its header and closes the one that was
// open. A closed step keeps its header and shows its headline number, so the card stays short without hiding the result.
(() => {
  const $ = (id) => document.getElementById(id);
  // headline shown on a closed step's header, read from the numbers the page already renders
  const SUMMARY = [
    () => ($("lost-v") ? `${$("lost-v").textContent.trim()} pts lost` : ""),
    () => ($("brent-v") ? $("brent-v").textContent.trim() : ""),
    () => ($("w-petrol") ? `fuel ${$("w-petrol").textContent.trim()}` : ""),
    () => "",
  ];
  let open = 0;

  function card() {
    const c = [...document.querySelectorAll("#world-stage .card")].find((x) => x.querySelector(".step .stephead"));
    return c || null;
  }
  function steps(c) { return [...c.querySelectorAll(":scope > .step")]; }

  function wrap(step, i) {
    const head = step.querySelector(":scope > .stephead");
    if (!head || step.dataset.acc) return;
    step.dataset.acc = "1";
    step.classList.add("acc-step");
    const body = document.createElement("div");
    body.className = "acc-body";
    body.id = `acc-body-${i}`;
    [...step.children].filter((x) => x !== head).forEach((x) => body.appendChild(x));
    step.appendChild(body);
    head.classList.add("acc-head");
    head.setAttribute("role", "button");
    head.tabIndex = 0;
    head.setAttribute("aria-controls", body.id);
    const sum = document.createElement("span");
    sum.className = "acc-sum";
    const chev = document.createElement("span");
    chev.className = "acc-chev";
    chev.setAttribute("aria-hidden", "true");
    chev.textContent = "▸";
    head.append(sum, chev);
    const toggle = () => { open = open === i ? -1 : i; render(); };
    head.addEventListener("click", (e) => { if (!e.target.closest("button, a, input")) toggle(); });
    head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  }

  function render() {
    const c = card();
    if (!c) return;
    steps(c).forEach((st, i) => {
      wrap(st, i);
      const on = i === open, head = st.querySelector(".acc-head"), body = st.querySelector(".acc-body");
      if (!head || !body) return;
      st.classList.toggle("acc-open", on);
      head.setAttribute("aria-expanded", String(on));
      body.hidden = !on;
      const s = head.querySelector(".acc-sum");
      const txt = on ? "" : (SUMMARY[i] || (() => ""))();
      if (s && s.textContent !== txt) s.textContent = txt;   // only on change, so the observer below doesn't loop
    });
  }

  function start() {
    const c = card();
    if (!c) return setTimeout(start, 300);
    render();
    // step 4 is added by the Households layer, and the numbers change with the slider: keep headers in step
    let busy = false;
    new MutationObserver(() => { if (busy) return; busy = true; requestAnimationFrame(() => { render(); busy = false; }); })
      .observe(c, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
