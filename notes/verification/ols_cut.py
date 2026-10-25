"""Publication-lag residual risk without training noise: the deterministic per-series least-squares
benchmark of experiments/macro_global.py (OLS on the networks' inputs), on all 8 folds, simulated
with the same random numbers, fitted on
    base   training months 13..last (as the folds; last = month before the first test origin)
    exact  only (month, series) rows published by the first test origin: s <= last + 1 - pub_lag[k]
    cut    training months 13..last - max(pub_lag) for every series (the conservative bound)

    uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch \
        --with jax --with numpyro python notes/verification/ols_cut.py
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
import macro_bayes as mb  # noqa: E402
import macro_global as mg  # noqa: E402
import macro_nn as mn  # noqa: E402

GROUPS = ("inflation", "unemployment", "rate", "cost")


def main():
    data = mn.make_dataset(mn.V1_BLOCKS)
    info = mb.series_info(data)
    lag = int(info["pub_lag"].max())
    groups = np.array(data["groups"])
    stored = json.loads((ROOT / "runs" / "macro" / "global-ols.json").read_text())["folds"]
    crps = {"base": [], "exact": [], "cut": []}
    clim = []
    for j in range(mn.FOLDS):
        _, test, last = mb.fold_window(data, j)
        t, Y, oil = data["t"][test], data["Y"][test], data["OIL"][test]
        for mode, fit_last in (("base", last), ("exact", last), ("cut", last - lag)):
            st = mb.Stats(data, fit_last)
            months, k, x, y = mg.training_rows(mg.features(data, st), fit_last)
            if mode == "exact":
                keep = months <= last + 1 - info["pub_lag"][k]
                months, k, x, y = months[keep], k[keep], x[keep], y[keep]
            S = mg.simulate([mg.OLS(x, k, y, info["floor"])], st, info, data, t, oil[None], np.random.default_rng(500 + j))
            crps[mode].append(np.array(mb.summarise(S, Y)["crps"], float))
        if j == 0 or j == 7:
            diff = np.nanmax(np.abs(crps["base"][-1] - np.array(stored[j]["crps"], float)))
            print(f"fold {j}: base run vs runs/macro/global-ols.json, max |CRPS difference| {diff:.2e}")
        clim.append(np.array(json.loads((ROOT / "runs" / "macro" / f"fold-{j}.json").read_text())["models"]["climatology"]["crps"], float))
    clim = np.vstack(clim)
    scale = np.nanmean(clim, 0)
    B = np.vstack(crps["base"])
    sizes = np.cumsum([0] + [len(c) for c in crps["base"]])
    for mode in ("exact", "cut"):
        C = np.vstack(crps[mode])
        print(f"OLS, same inputs, {mode} training window (all 8 folds, 214 origins):")
        for g in GROUPS:
            c = groups == g
            sb = 1 - np.nanmean(np.nanmean(B[:, c], 0) / scale[c])
            sc = 1 - np.nanmean(np.nanmean(C[:, c], 0) / scale[c])
            d = np.nanmean((C[:, c] - B[:, c]) / scale[c], 1)
            by_fold = [round(float(np.nanmean(d[sizes[f]:sizes[f + 1]])), 3) for f in range(mn.FOLDS)]
            print(f"  {g:12s} skill base {sb:+.3f}, {mode} {sc:+.3f}, {mode} minus base (scaled CRPS) "
                  f"{np.nanmean(d):+.4f} (t {mb.nw_t(d):+.2f}); by fold {by_fold}")


if __name__ == "__main__":
    main()
