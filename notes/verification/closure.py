"""The 2026 Hormuz closure in the last fold: 12-month forecasts from 2025-03, 2025-06 and 2025-09
(mean, 90% band, actual) from runs/macro/bayes-own-fold-7.json and global-fold-7.json.

    uv run --no-project --with numpy python notes/verification/closure.py
"""

import json
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parents[2] / "runs" / "macro"
OUTPUTS = {"us_cpi@12": "US CPI", "uk_cpi@12": "UK CPI", "ea_cpi@12": "Euro-area HICP",
           "ind_gasdesw@12": "Diesel (US retail, GASDESW)", "ind_djfuelusgulf@12": "Jet fuel (US Gulf, DJFUELUSGULF)"}


def main():
    b = json.loads((RUNS / "bayes-own-fold-7.json").read_text())
    g = json.loads((RUNS / "global-fold-7.json").read_text())
    assert b["test_dates"] == g["test_dates"] and b["names"] == g["names"]
    sources = {"Bayes own-vol what-if": b["modes"]["whatif"], "Bayes own-vol forecast": b["modes"]["forecast"],
               "global what-if": g["models"]["global"], "global_lin what-if": g["models"]["global_lin"]}
    inside = {k: [] for k in sources}
    print("| Origin | Output | Actual | " + " | ".join(f"{k} mean (90%)" for k in sources) + " |")
    print("|---|---|---|" + "---|" * len(sources))
    for t in ("2025-03", "2025-06", "2025-09"):
        i = b["test_dates"].index(t)
        for nm, label in OUTPUTS.items():
            k = b["names"].index(nm)
            y = b["y"][i][k]
            assert np.isclose(y, g["y"][i][k])
            cells = []
            for name, m in sources.items():
                lo, hi, mu = m["q05"][i][k], m["q95"][i][k], m["mu"][i][k]
                ok = lo <= y <= hi
                inside[name].append(ok)
                cells.append(f"{mu:+.1f} ({lo:+.1f}..{hi:+.1f}){'' if ok else ' **out**'}")
            print(f"| {t} | {label} | {y:+.1f} | " + " | ".join(cells) + " |")
    print()
    for name, v in inside.items():
        print(f"{name}: {sum(v)}/{len(v)} actuals inside the 90% band")


if __name__ == "__main__":
    main()
