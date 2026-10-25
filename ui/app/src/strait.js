// Strait view: each card's notes (dates, caveats, the simulation's true flow) move behind the card's blue info key
// and show at the end of its info panel, under "Dates and notes". The notes keep their ids, so the page still updates
// them as the scenario changes, and the panel reads them when it opens. A CACHED tag stays on its card, beside
// REAL DATA, so saved data never looks live.
(() => {
  const $ = (id) => document.getElementById(id);
  const NOTES = { "est-card": ["#est-when", ".truth"], "pw-card": [":scope > p.faint:not(.mono)"],
    "cap-card": [":scope > p.faint:not(.mono)"], "glob-card": [":scope > p.faint:not(.mono)"] };
  for (const [id, sels] of Object.entries(NOTES)) {
    const card = $(id), btn = card && card.querySelector("[data-info]");
    const notes = btn ? sels.flatMap((s) => [...card.querySelectorAll(s)]) : [];
    if (!notes.length) continue;
    notes.forEach((n) => n.classList.add("hz-tucked"));
    const cached = notes.map((n) => n.querySelector(".tagc")).find(Boolean);
    if (cached) {
      const t = cached.cloneNode(true);
      t.classList.add("hz-cached");
      (card.querySelector(".tag-real") || btn).after(t);
    }
    btn.setAttribute("aria-label", `${btn.getAttribute("aria-label")}, with dates and notes`);
    // runs after the page's own handler has filled the sheet for this key
    btn.addEventListener("click", () => {
      const body = $("sheet-body"), text = notes.map((n) => n.innerHTML.trim()).filter(Boolean);
      if (body && text.length) body.insertAdjacentHTML("beforeend", `<section class="hz-sec hz-notes"><h4>Dates and notes</h4>${text.map((t) => `<p>${t}</p>`).join("")}</section>`);
    });
  }
})();
