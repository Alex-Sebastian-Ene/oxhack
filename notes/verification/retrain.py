"""Re-train `global_lin` (experiments/macro_global.py) on one fold, unchanged or with one thing changed,
for notes/verification.md. The model code is imported, not edited; this re-does run_fold's steps.

    base      as run_fold: training months 13..last (last = month before the first test origin)
    cut       training months 13..last - max(pub_lag): what was published at the first test origin
    exact     only (month, series) rows published by the first test origin: s <= last + 1 - pub_lag[k]
    shuffle   y permuted within each series' training rows (a leakage control: skill should vanish)
    reseed    as base with other seeds (how much a re-training moves the score on its own)

    uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch \
        --with jax --with numpyro python notes/verification/retrain.py base 7 OUT.json
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
import macro_bayes as mb  # noqa: E402
import macro_global as mg  # noqa: E402
import macro_nn as mn  # noqa: E402


def main(mode: str, j: int, out: str, variant: str = "global_lin") -> None:
    data = mn.make_dataset(mn.V1_BLOCKS)
    _, test, last = mb.fold_window(data, j)
    info = mb.series_info(data)
    lag = int(info["pub_lag"].max()) if mode == "cut" else 0
    fit_last = last - lag
    st = mb.Stats(data, fit_last)
    months, k, x, y = mg.training_rows(mg.features(data, st), fit_last)
    if mode == "exact":
        keep = months <= last + 1 - info["pub_lag"][k]
        months, k, x, y = months[keep], k[keep], x[keep], y[keep]
    if mode == "shuffle":
        rng = np.random.default_rng(12345 + j)
        for kk in np.unique(k):
            rows = np.flatnonzero(k == kk)
            y[rows] = y[rng.permutation(rows)]
    vi = mg.VARIANTS.index(variant)
    t0 = time.time()
    offset = 50 if mode == "reseed" else 0
    fitted = [mg.train(x, k, y, months, info["floor"], variant == "global_lin", seed=1000 * j + 100 * vi + s + offset)
              for s in range(mg.SEEDS)]
    t, Y, oil = data["t"][test], data["Y"][test], data["OIL"][test]
    S = mg.simulate([f[0] for f in fitted], st, info, data, t, oil[None], np.random.default_rng(300 + j))
    res = mb.summarise(S, Y) | {"mode": mode, "fold": j, "variant": variant, "train_months_to": int(fit_last),
                                "pub_lag_max": lag, "training": [f[1] for f in fitted],
                                "seconds": round(time.time() - t0, 1), "y": Y.tolist(),
                                "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]]}
    Path(out).write_text(json.dumps(res))
    print(f"{mode} fold {j} {variant}: months to {fit_last}, rows {len(y)}, CRPS {np.nanmean(res['crps']):.4f}, "
          f"{res['seconds']}s, best epochs {[f[1]['best_epoch'] for f in fitted]}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3], *(sys.argv[4:5]))
