"""Are fold-*.json's `climatology` and `no_change` what they claim to be? And how much does the
choice of climatology move the skill scores? For notes/verification.md.

    uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch \
        python notes/verification/baselines.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
import macro_nn as mn  # noqa: E402

RUNS = ROOT / "runs" / "macro"
GROUPS = ("inflation", "unemployment", "rate", "cost")


def gcrps(mu, sd, y):
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def sample_crps(S, y):
    """CRPS of the empirical distribution of the sample S [N] at each y [O]."""
    S = np.sort(S[np.isfinite(S)])
    N = len(S)
    i = np.arange(1, N + 1)
    return np.mean(np.abs(S[:, None] - y[None]), 0) - np.sum((2 * i - N - 1) * S) / N ** 2


def main():
    data = mn.make_dataset(mn.V1_BLOCKS)
    Y, dates = data["Y"], data["dates"]
    groups = np.array(data["groups"])
    worst = {"y": 0.0, "clim_mu": 0.0, "clim_sd": 0.0, "nc_mu": 0.0, "nc_sd": 0.0, "crps": 0.0}
    alt = {"full_gauss": [], "full_empirical": []}
    for j in range(mn.FOLDS):
        f = json.loads((RUNS / f"fold-{j}.json").read_text())
        train, test = mn.fold_indices(dates, j)
        inner = train[:int(len(train) * 0.75) - max(mn.HORIZONS)]  # as fit_all
        y = np.array(f["y"], float)
        assert f["test_dates"] == [f"{d:%Y-%m}" for d in dates[test]]
        worst["y"] = max(worst["y"], np.nanmax(np.abs(y - Y[test])))
        ym, ys = np.nanmean(Y[inner], 0), np.nanstd(Y[inner], 0) + 1e-8
        c, nc = f["models"]["climatology"], f["models"]["no_change"]
        cm, cv = np.array(c["mu"]), np.array(c["var"])
        worst["clim_mu"] = max(worst["clim_mu"], np.abs(cm - ym).max())
        worst["clim_sd"] = max(worst["clim_sd"], np.abs(np.sqrt(cv) - ys).max())
        worst["nc_mu"] = max(worst["nc_mu"], np.abs(np.array(nc["mu"])).max())
        worst["nc_sd"] = max(worst["nc_sd"], np.abs(np.sqrt(np.array(nc["var"])) - ys).max())
        rec = np.where(np.isnan(y), np.nan, gcrps(cm, np.sqrt(cv), np.nan_to_num(y)))
        worst["crps"] = max(worst["crps"], np.nanmax(np.abs(rec - np.array(c["crps"], float))))
        print(f"fold {j}: train origins {dates[train[0]]:%Y-%m}..{dates[train[-1]]:%Y-%m} ({len(train)}), "
              f"climatology/no-change fitted on {dates[inner[0]]:%Y-%m}..{dates[inner[-1]]:%Y-%m} ({len(inner)}), "
              f"test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}")
        # alternatives on every training origin (the same months the Bayes and global models see)
        fm, fs = np.nanmean(Y[train], 0), np.nanstd(Y[train], 0)
        alt["full_gauss"].append(np.where(np.isnan(y), np.nan, gcrps(fm, fs, np.nan_to_num(y))))
        emp = np.full(y.shape, np.nan)
        for col in range(y.shape[1]):
            ok = np.isfinite(y[:, col])
            if ok.any():
                emp[ok, col] = sample_crps(Y[train, col], y[ok, col])
        alt["full_empirical"].append(emp)
    print("max |difference|:", {k: float(f"{v:.2e}") for k, v in worst.items()})

    def stack(stem, path):
        out = []
        for j in range(mn.FOLDS):
            d = json.loads((RUNS / f"{stem}{j}.json").read_text())
            for key in path:
                d = d[key]
            out.append(np.array(d, float))
        return np.vstack(out)

    M = {"global_lin": stack("global-fold-", ["models", "global_lin", "crps"]),
         "global": stack("global-fold-", ["models", "global", "crps"]),
         "bayes_own": stack("bayes-own-fold-", ["modes", "whatif", "crps"]),
         "bayes_own_forecast": stack("bayes-own-fold-", ["modes", "forecast", "crps"]),
         "v1_climatology": stack("fold-", ["models", "climatology", "crps"])}
    scales = {"v1 (inner 75% of training origins, Gaussian)": np.nanmean(M["v1_climatology"], 0),
              "all training origins, Gaussian": np.nanmean(np.vstack(alt["full_gauss"]), 0),
              "all training origins, empirical": np.nanmean(np.vstack(alt["full_empirical"]), 0)}
    for label, scale in scales.items():
        print(f"\nskill against climatology on {label}")
        for name, c in M.items():
            sk = [1 - np.nanmean(np.nanmean(c[:, groups == g], 0) / scale[groups == g]) for g in GROUPS]
            print(f"  {name:20s} " + " ".join(f"{g} {s:+.3f}" for g, s in zip(GROUPS, sk)))


if __name__ == "__main__":
    main()
