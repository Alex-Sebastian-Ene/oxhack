# /// script
# requires-python = ">=3.11"
# ///
"""Compile the sourced material tables into the globe's data bundle (ui/globe/data/materials.js).

Inputs, all in notes/materials/ and each citing its sources:
  <material>.json  production by country, inputs, supplier links (one file per material)
  exports.json     exporters and the biggest bilateral flows, per material and input

Oil -> price links come from Seb's Bayesian pass-through table (OXH-3 handoff, branch seb/macro-nn):
the 12-month response to a one-off +10% or -10% Brent move, with its 90% interval.

    uv run experiments/globe_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "notes" / "materials"
COUNTRIES = ROOT / "ui" / "globe" / "data" / "countries.js"
OUT = ROOT / "ui" / "globe" / "data" / "materials.js"

ORDER = ["steel", "jet_fuel", "aluminium", "fertiliser", "polyethylene"]
SHORT = {"steel": "Steel", "jet_fuel": "Jet fuel", "aluminium": "Alu", "fertiliser": "Fertiliser", "polyethylene": "Plastic"}
NAMES = {"steel": "Crude steel", "jet_fuel": "Jet fuel", "aluminium": "Primary aluminium",
         "fertiliser": "Nitrogen fertiliser", "polyethylene": "Polyethylene"}
INPUT_COLOR = {"iron_ore": "#e07a5f", "coking_coal": "#9aa5b1", "scrap": "#c9b37e", "crude_oil": "#f0a23b",
               "bauxite": "#d9822b", "alumina": "#f2c6a0", "natural_gas": "#5cb8f0", "lng": "#5cb8f0",
               "naphtha": "#b39ddb", "ethane": "#7fd3a8", "electricity": "#ffe08a"}

SEB = ("Seb's Bayesian pass-through model, notes/macro-bayes-responses.csv on seb/macro-nn "
       "(experiments/macro_bayes.py; FRED series fetched 2026-10-24)")
# % price change 12 months after a one-off Brent move of +10% (up) or -10% (down): posterior mean and
# 90% interval. Rises and falls differ, so the page uses the matching row and scales by
# ln(1+x)/ln(1.1) or ln(1+x)/ln(0.9).
OIL = {
    "jet_fuel": {"up": [8.17, 7.18, 9.12], "down": [-9.47, -10.47, -8.68], "series": "FRED DJFUELUSGULF (US Gulf jet)",
                 "validated": True, "horizon": "12 months", "source": SEB,
                 "disruption": {"lo": 13, "hi": 15, "note": "event-based range from past supply shocks (OXH-4)"}},
    "fertiliser": {"up": [6.30, 3.93, 8.86], "down": [-7.48, -9.80, -5.33], "series": "FRED PCU325311325311 (PPI nitrogen fertiliser)",
                   "validated": True, "horizon": "12 months", "source": SEB},
    "polyethylene": {"up": [2.32, 1.51, 3.14], "down": [-2.53, -3.27, -1.82], "series": "FRED PCU325211325211 (PPI plastics resin)",
                     "validated": True, "horizon": "12 months", "source": SEB},
    "steel": {"note": "requested from Seb (OXH-5)"},
    "aluminium": {"note": "requested from Seb (OXH-5)"},
}


def known_codes() -> set[str]:
    text = COUNTRIES.read_text()
    data = json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))
    return {f["properties"]["iso3"] for f in data["features"]} | set(data["points"])


def clean_rows(rows, codes, where, warn) -> list[dict]:
    out = []
    for r in rows or []:
        iso, share = r.get("iso3"), r.get("share")
        if iso not in codes:
            warn.append(f"{where}: unknown code {iso}")
            continue
        if share is None or share <= 0:
            continue
        out.append({"iso3": iso, "share": round(float(share), 4), **({"value": r["value"]} if r.get("value") is not None else {})})
    return sorted(out, key=lambda r: -r["share"])


def main() -> None:
    codes = known_codes()
    warn: list[str] = []
    exports = {e["id"]: e for e in json.loads((NOTES / "exports.json").read_text())} if (NOTES / "exports.json").exists() else {}

    def export_block(eid, where):
        e = exports.get(eid)
        if not e:
            return None, []
        flows = [f for f in e.get("flows", []) if f.get("from") in codes and f.get("to") in codes]
        return ({"unit": e.get("unit"), "year": e.get("year"), "source": e.get("source"), "note_2026": e.get("note_2026"),
                 "list": clean_rows(e.get("exporters"), codes, f"{where} exports", warn)}, flows)

    materials, inputs = [], {}
    for mid in ORDER:
        path = NOTES / f"{mid}.json"
        if not path.exists():
            warn.append(f"missing {path.relative_to(ROOT)}")
            continue
        d = json.loads(path.read_text())
        exp, flows = export_block(mid, mid)
        for inp in d.get("inputs", []):
            iid = inp["id"]
            if iid not in inputs:
                iexp, iflows = export_block(iid, iid)
                inputs[iid] = {"id": iid, "name": inp["name"], "color": INPUT_COLOR.get(iid, "#e7ecf2"),
                               "unit": inp.get("unit"), "year": inp.get("year"), "source": inp.get("source"),
                               "producers": clean_rows(inp.get("producers"), codes, iid, warn),
                               "exports": iexp, "flows": iflows}
        links = []
        for l in d.get("links", []):
            if l.get("to") in codes and l.get("from") in codes and l.get("share"):
                links.append({k: l.get(k) for k in ("to", "input", "from", "share", "basis", "year", "source")})
            else:
                warn.append(f"{mid} link skipped: {l.get('from')} -> {l.get('to')}")
        materials.append({"id": mid, "name": NAMES[mid], "short": SHORT[mid], "unit": d.get("unit"), "year": d.get("year"),
                          "source": d.get("source"), "producers": clean_rows(d.get("producers"), codes, mid, warn),
                          "exports": exp, "flows": flows, "inputs": [i["id"] for i in d.get("inputs", [])],
                          "links": links, "oil": OIL.get(mid), "oil_notes": d.get("oil_exposure")})
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    OUT.write_text("window.MATERIALS = " + json.dumps({"generated": generated, "materials": materials, "inputs": inputs},
                                                      separators=(",", ":")) + ";\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(materials)} materials, {len(inputs)} inputs, "
          f"{sum(len(m['links']) for m in materials)} supplier links")
    for w in warn:
        print("warning:", w, file=sys.stderr)


if __name__ == "__main__":
    main()
