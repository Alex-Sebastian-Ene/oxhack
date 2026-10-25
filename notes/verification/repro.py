"""Independent recomputation of the knock-on skill scores and the DM test from runs/macro/*.json.

Written for notes/verification.md; uses no report() function from the experiments.

    uv run --no-project --with numpy python notes/verification/repro.py
"""

import json
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parents[2] / "runs" / "macro"
GROUPS = ("inflation", "unemployment", "rate", "cost")


def load(stem):
    return json.loads((RUNS / f"{stem}.json").read_text())


def stacked(stem, path):
    """CRPS [origins, outputs] over the 8 folds, following `path` (keys) inside each fold file."""
    out = []
    for j in range(8):
        d = load(f"{stem}-{j}" if stem != "fold" else f"fold-{j}")
        for k in path:
            d = d[k]
        out.append(np.array(d, dtype=float))
    return np.vstack(out)


def newey_west_t(d, lags=12):
    d = d[np.isfinite(d)]
    n, e = len(d), d - d.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return d.mean() / np.sqrt(s / n)


def main():
    f0 = load("fold-0")
    names, groups = f0["names"], np.array(f0["groups"])
    # targets and origins must be identical across every file
    ys = {}
    for stem in ("fold", "global-fold", "bayes-own-fold", "bayes-fold"):
        ys[stem] = np.vstack([np.array(load(f"{stem}-{j}" if stem != "fold" else f"fold-{j}")["y"], float)
                              for j in range(8)])
    for stem, y in ys.items():
        same = np.array_equal(np.isnan(y), np.isnan(ys["fold"])) and np.allclose(np.nan_to_num(y), np.nan_to_num(ys["fold"]))
        print(f"targets in {stem}-*.json identical to fold-*.json: {same}; shape {y.shape}")
    clim = stacked("fold", ["models", "climatology", "crps"])
    scale = np.nanmean(clim, 0)  # mean over origins of climatology CRPS, per output
    M = {
        "global": stacked("global-fold", ["models", "global", "crps"]),
        "global_lin": stacked("global-fold", ["models", "global_lin", "crps"]),
        "bayes_own": stacked("bayes-own-fold", ["modes", "whatif", "crps"]),
        "bayes_oil": stacked("bayes-fold", ["modes", "whatif", "crps"]),
        "bayes_own_forecast": stacked("bayes-own-fold", ["modes", "forecast", "crps"]),
        "v1_nn_mean": stacked("fold", ["models", "nn_mean", "crps"]),
        "v1_climatology": clim,
        "v1_no_change": stacked("fold", ["models", "no_change", "crps"]),
    }
    for name, c in M.items():  # NaN pattern must match the targets'
        assert np.array_equal(np.isnan(c), np.isnan(ys["fold"])), name
    print(f"\n{clim.shape[0]} origins, {clim.shape[1]} outputs")
    print("skill = 1 - mean_c[ mean_origins CRPS_c / mean_origins CRPS_clim,c ], all horizons")
    print(f"{'model':20s} " + " ".join(f"{g:>12s}" for g in GROUPS))
    for name, c in M.items():
        sk = [1 - np.nanmean(np.nanmean(c[:, groups == g], 0) / scale[groups == g]) for g in GROUPS]
        print(f"{name:20s} " + " ".join(f"{s:+12.3f}" for s in sk))

    print("\nDiebold-Mariano, per-origin mean of climatology-scaled CRPS differences, NW 12 lags")
    for a, b in (("global_lin", "bayes_own"), ("global", "bayes_own"), ("global_lin", "bayes_oil"),
                 ("global_lin", "global"), ("bayes_own", "bayes_oil")):
        cells = []
        for g in GROUPS:
            c = groups == g
            d = np.nanmean((M[a][:, c] - M[b][:, c]) / scale[c], 1)
            cells.append(f"{np.nanmean(d):+.3f} (t {newey_west_t(d):+.2f})")
        print(f"{a} vs {b}: " + " | ".join(cells))

    # 90% band coverage: share of finite targets inside [q05, q95]
    y = ys["fold"]
    print("\n90% band coverage")
    for name, stem, path in (("global", "global-fold", ["models", "global"]), ("global_lin", "global-fold", ["models", "global_lin"]),
                             ("bayes_own", "bayes-own-fold", ["modes", "whatif"]), ("bayes_oil", "bayes-fold", ["modes", "whatif"])):
        lo, hi = stacked(stem, path + ["q05"]), stacked(stem, path + ["q95"])
        cells = []
        for g in GROUPS:
            c = groups == g
            ok = np.isfinite(y[:, c])
            cells.append(f"{g} {np.mean(((y[:, c] >= lo[:, c]) & (y[:, c] <= hi[:, c]))[ok]):.1%}")
        print(f"  {name:12s} " + " ".join(cells))

    # skill by fold, each fold against its own climatology CRPS
    sizes = [len(load(f"fold-{j}")["test_dates"]) for j in range(8)]
    edges = np.cumsum([0] + sizes)
    print("\nskill by fold (against that fold's v1 climatology), inflation | cost")
    for name in ("global_lin", "global", "bayes_own", "bayes_own_forecast", "v1_nn_mean"):
        cells = []
        for j in range(8):
            r = slice(edges[j], edges[j + 1])
            sc = np.nanmean(clim[r], 0)
            s = [1 - np.nanmean(np.nanmean(M[name][r][:, groups == g], 0) / sc[groups == g]) for g in ("inflation", "cost")]
            cells.append(f"{s[0]:+.2f}|{s[1]:+.2f}")
        print(f"  {name:20s} " + "  ".join(cells))

    # robustness of the inflation DM t: lag length, and dropping one fold at a time
    c = groups == "inflation"
    d = np.nanmean((M["global_lin"][:, c] - M["bayes_own"][:, c]) / scale[c], 1)
    print("\nglobal_lin vs bayes_own, inflation: t by NW lags",
          {L: round(newey_west_t(d, L), 2) for L in (0, 6, 12, 18, 24)})
    sizes = [len(load(f"fold-{j}")["test_dates"]) for j in range(8)]
    edges = np.cumsum([0] + sizes)
    drop = {j: round(newey_west_t(np.delete(d, np.arange(edges[j], edges[j + 1]))), 2) for j in range(8)}
    print("  dropping fold j:", drop)
    per_fold = {j: round(float(np.nanmean(d[edges[j]:edges[j + 1]])), 3) for j in range(8)}
    print("  mean difference by fold:", per_fold)
    # by inflation series and by horizon
    H = np.array([int(n.split("@")[1]) for n in names])
    for key in ("us_cpi", "uk_cpi", "ea_cpi"):
        cc = np.array([n.startswith(key + "@") for n in names])
        dd = np.nanmean((M["global_lin"][:, cc] - M["bayes_own"][:, cc]) / scale[cc], 1)
        print(f"  {key}: diff {np.nanmean(dd):+.3f} t {newey_west_t(dd):+.2f}")
    for h in (1, 3, 6, 12):
        cc = c & (H == h)
        dd = np.nanmean((M["global_lin"][:, cc] - M["bayes_own"][:, cc]) / scale[cc], 1)
        print(f"  h={h}: diff {np.nanmean(dd):+.3f} t {newey_west_t(dd):+.2f}")


if __name__ == "__main__":
    main()
