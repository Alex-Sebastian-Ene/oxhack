"""The shuffled-target global_lin (notes/verification/retrain.py shuffle j, all 8 folds) as a second
zero point: it knows each series' distribution of monthly changes and nothing about the current
state. For notes/verification.md.

    uv run --no-project --with numpy python notes/verification/shuffle_all.py DIR
"""

import json
import sys
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parents[2] / "runs" / "macro"
GROUPS = ("inflation", "unemployment", "rate", "cost")


def nw_t(d, lags=12):
    d = d[np.isfinite(d)]
    n, e = len(d), d - d.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return d.mean() / np.sqrt(s / n)


def stack(stem, path):
    out = []
    for j in range(8):
        d = json.loads((RUNS / f"{stem}{j}.json").read_text())
        for key in path:
            d = d[key]
        out.append(np.array(d, float))
    return np.vstack(out)


def main(folder: Path):
    shuf = [json.loads((folder / f"shuffle-{j}.json").read_text()) for j in range(8)]
    groups = np.array(json.loads((RUNS / "fold-0.json").read_text())["groups"])
    S = np.vstack([np.array(s["crps"], float) for s in shuf])
    M = {"global_lin": stack("global-fold-", ["models", "global_lin", "crps"]),
         "global": stack("global-fold-", ["models", "global", "crps"]),
         "bayes_own": stack("bayes-own-fold-", ["modes", "whatif", "crps"]),
         "bayes_own_forecast": stack("bayes-own-fold-", ["modes", "forecast", "crps"]),
         "v1_climatology": stack("fold-", ["models", "climatology", "crps"])}
    clim = np.nanmean(M["v1_climatology"], 0)
    sizes = np.cumsum([0] + [len(s["test_dates"]) for s in shuf])
    print("shuffled-target global_lin, skill against the v1 climatology (all 214 origins):",
          " ".join(f"{g} {1 - np.nanmean(np.nanmean(S[:, groups == g], 0) / clim[groups == g]):+.3f}" for g in GROUPS))
    for j in range(8):
        r = slice(sizes[j], sizes[j + 1])
        sc = np.nanmean(M["v1_climatology"][r], 0)
        print(f"  fold {j} ({shuf[j]['test_dates'][0]}..{shuf[j]['test_dates'][-1]}): " + " ".join(
            f"{g} {1 - np.nanmean(np.nanmean(S[r][:, groups == g], 0) / sc[groups == g]):+.3f}" for g in GROUPS)
            + f"; best epochs {[t['best_epoch'] for t in shuf[j]['training']]}")
    zero = np.nanmean(S, 0)
    print("\nskill with the shuffled-target model as the zero point, and DM t against it (scaled by the v1 climatology)")
    for name, c in M.items():
        cells = []
        for g in GROUPS:
            cc = groups == g
            sk = 1 - np.nanmean(np.nanmean(c[:, cc], 0) / zero[cc])
            d = np.nanmean((c[:, cc] - S[:, cc]) / clim[cc], 1)
            cells.append(f"{g} {sk:+.3f} (t {nw_t(d):+.1f})")
        print(f"  {name:20s} " + " | ".join(cells))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
