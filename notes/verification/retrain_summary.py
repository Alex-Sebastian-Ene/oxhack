"""Summarise notes/verification/retrain.py outputs against the stored fold files, for notes/verification.md.

    uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch \
        python notes/verification/retrain_summary.py DIR
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
import macro_nn as mn  # noqa: E402

RUNS = ROOT / "runs" / "macro"
GROUPS = ("inflation", "unemployment", "rate", "cost")


def nw_t(d, lags=12):
    d = d[np.isfinite(d)]
    n, e = len(d), d - d.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return d.mean() / np.sqrt(s / n) if s > 0 else float("nan")


def gcrps(mu, sd, y):
    from scipy.stats import norm
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def main(out: Path):
    data = mn.make_dataset(mn.V1_BLOCKS)
    for j in sorted({int(p.stem.split("-")[-1]) for p in out.glob("*-*.json")}):
        g = json.loads((RUNS / f"global-fold-{j}.json").read_text())
        v1 = json.loads((RUNS / f"fold-{j}.json").read_text())
        groups = np.array(g["groups"])
        scale = np.nanmean(np.array(v1["models"]["climatology"]["crps"], float), 0)  # this fold's climatology
        stored = np.array(g["models"]["global_lin"]["crps"], float)
        runs = {"stored": stored}
        for p in sorted(out.glob(f"*-{j}.json")):
            r = json.loads(p.read_text())
            assert r["test_dates"] == g["test_dates"]
            runs[r["mode"]] = np.array(r["crps"], float)
        print(f"fold {j} ({g['test_dates'][0]}..{g['test_dates'][-1]}), global_lin")
        if "base" in runs:
            print(f"  base re-run vs stored: max |CRPS difference| {np.nanmax(np.abs(runs['base'] - stored)):.2e}")
        # a second yardstick: Gaussian climatology on every training origin of the fold
        train, _ = mn.fold_indices(data["dates"], j)
        y = np.array(g["y"], float)
        full = np.where(np.isnan(y), np.nan, gcrps(np.nanmean(data["Y"][train], 0), np.nanstd(data["Y"][train], 0),
                                                   np.nan_to_num(y)))
        for label, sc in (("this fold's v1 climatology", scale), ("Gaussian climatology on all training origins", np.nanmean(full, 0))):
            print(f"  skill against {label}")
            for name, c in runs.items():
                sk = [1 - np.nanmean(np.nanmean(c[:, groups == gg], 0) / sc[groups == gg]) for gg in GROUPS]
                print(f"    {name:8s} " + " ".join(f"{gg} {s:+.3f}" for gg, s in zip(GROUPS, sk)))
        ref = runs.get("base", stored)
        for name in ("cut", "exact", "reseed", "shuffle"):
            if name not in runs:
                continue
            cells = []
            for gg in GROUPS:
                cc = groups == gg
                d = np.nanmean((runs[name][:, cc] - ref[:, cc]) / scale[cc], 1)
                cells.append(f"{gg} {np.nanmean(d):+.3f} (t {nw_t(d):+.1f})")
            print(f"  {name} minus base, scaled CRPS: " + " | ".join(cells))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
