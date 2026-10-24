# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "scipy>=1.11", "pandas>=2.1"]
# ///
"""Check that the pieces of the oil-price work agree with each other, on the real results.

1. Same model, two scripts: levy_fourier's i.i.d. Gaussian, Student-t and CGMY against
   non_gaussian's, refitted on exactly the same training days.
2. Simulator against closed form: the simulated 5- and 21-day CRPS of the i.i.d. Gaussian model
   against the analytic Gaussian CRPS at the same forecast origins.
3. Laptop against Iridis: one rolling year re-run locally (pass its JSON with --laptop).
4. Fixed split against rolling: the 2009 refit (train before 2009-01-01) against the fixed fit
   (train before 2008-10-15), which share all but 2.5 months of training data.

    uv run experiments/validate_links.py [--laptop path/to/rolling-YEAR.json]   # writes notes/link-checks.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy import stats

import levy_fourier as lf
import non_gaussian as ng

OUT = lf.ROOT / "notes" / "link-checks.md"


def load(stem: str) -> dict:
    return json.loads((lf.RUNS / f"{stem}.json").read_text(encoding="utf-8"))


def gaussian_crps(mu, sd, y):
    z = (y - mu) / sd
    return sd * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / np.sqrt(np.pi))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--laptop", type=Path, help="a rolling-YEAR.json produced on this machine")
    args = p.parse_args()
    price, fetched = lf.load_brent()
    r = np.log(price).diff().dropna()
    fixed, fixed_iid = load("fixed"), load("fixed-iid")
    n_fit = int((r.index < lf.SPLIT).sum())
    train, test = r.values[:n_fit], r.values[n_fit:]
    rows = []

    # 1. Same model in both scripts, same training days.
    tr, te = ng.Data(train, ng.Cos(3.0, 4096)), ng.Data(test, ng.Cos(3.0, 4096))
    pairs = (("iid-Gaussian", ng.MODELS[0]), ("iid-Student-t", ng.MODELS[1]), ("iid-CGMY", ng.MODELS[6]))
    for lf_name, model in pairs:
        p_ng, _, _ = ng.fit(model, tr, float(train.mean()), float(train.std()))
        score_ng = ng.logpdf(model, p_ng, te, 1.0)[0].mean()
        score_lf = np.mean(fixed_iid["models"][lf_name]["lp"])
        gap = score_lf - score_ng
        rows.append(("Same model, two scripts", f"{lf_name} test log score: levy_fourier {score_lf:.5f}, "
                     f"non_gaussian {score_ng:.5f}", abs(gap) < 2e-3, f"gap {gap:+.5f} (pass < 0.002)"))

    # 2. Simulator against the analytic Gaussian CRPS at the same origins.
    g = fixed_iid["models"]["iid-Gaussian"]["params"]
    origins = np.array(fixed_iid["horizons"]["origins"])
    cum = np.concatenate([[0.0], np.cumsum(r.values)])
    for h in lf.HORIZONS:
        sim = np.array(fixed_iid["horizons"]["models"]["iid-Gaussian"][str(h)]["crps"])
        y = cum[origins + h] - cum[origins]
        exact = gaussian_crps(g["mu"] * h, g["sigma"] * np.sqrt(h), y)
        rel = abs(sim.mean() - exact.mean()) / exact.mean()
        rows.append(("Simulator vs closed form", f"{h}-day mean CRPS x100: simulated {100 * sim.mean():.4f}, "
                     f"exact {100 * exact.mean():.4f}", rel < 0.005, f"relative gap {rel:.2e} (pass < 0.5%)"))

    # 3. Laptop against Iridis for one rolling year.
    if args.laptop:
        mine = json.loads(args.laptop.read_text(encoding="utf-8"))
        theirs = load(f"rolling-{mine['name']}")
        for m in mine["models"]:
            gap = np.array(mine["models"][m]["lp"]) - np.array(theirs["models"][m]["lp"])
            d = np.abs(gap).max()
            c = np.abs(np.array(mine["horizons"]["models"][m]["21"]["crps"])
                       - np.array(theirs["horizons"]["models"][m]["21"]["crps"])).max()
            pa, pb = mine["models"][m]["params"], theirs["models"][m]["params"]
            par = max(abs(pa[k] - pb[k]) / max(abs(pb[k]), 1e-3) for k in pa)
            rows.append(("Laptop vs Iridis", f"{mine['name']} {m}: max daily log-score gap {d:.1e} "
                         f"(mean {gap.mean():+.1e}), max 21-day CRPS gap {c:.1e}", d < 1e-3 and c < 1e-3,
                         f"largest parameter gap {par:.1%}; tau {mine['tau']:g} vs {theirs['tau']:g} "
                         "(pass: both score gaps < 1e-3)"))

    # 4. Fixed split against the 2009 rolling refit.
    roll = load("rolling-2009")
    for m in ("GARCH-Student-t", "GARCH-CGMY"):
        a, b = fixed["models"][m]["params"], roll["models"][m]["params"]
        keys = [k for k in ("alpha", "beta", "nu", "Y") if k in a]
        worst = max(abs(a[k] - b[k]) / max(abs(a[k]), 1e-12) for k in keys)
        rows.append(("Fixed vs rolling 2009", f"{m}: " + ", ".join(f"{k} {a[k]:.4g} vs {b[k]:.4g}" for k in keys),
                     worst < 0.1, f"largest relative gap {worst:.1%} (pass < 10%)"))

    digest = hashlib.md5(lf.RAW.read_bytes()).hexdigest()
    out = [
        "# Link checks: do the pieces agree with each other?",
        "",
        f"_Generated by `experiments/validate_links.py` on {datetime.now(UTC).date().isoformat()} from "
        f"`runs/levy/` (Iridis job {fixed['meta'].get('slurm_job')}). Data: Brent spot, FRED DCOILBRENTEU, "
        f"fetched {fetched}, md5 {digest} (the same file was copied to Iridis)._",
        "",
        "| Check | What was compared | Result | Detail |",
        "|---|---|---|---|",
    ] + [f"| {kind} | {what} | {'PASS' if ok else '**FAIL**'} | {detail} |" for kind, what, ok, detail in rows] + [""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"{sum(ok for *_, ok, _ in rows)}/{len(rows)} checks passed")


if __name__ == "__main__":
    main()
