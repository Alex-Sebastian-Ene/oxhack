"""The stored macro_nn shuffled-target ablation (runs/macro/ablate-shuffled_targets-fold-*.json) against
the `full` variant's climatology, as docs/macro-ensemble.md cites it. For notes/verification.md.

    uv run --no-project --with numpy python notes/verification/nn_shuffle.py
"""

import json
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parents[2] / "runs" / "macro"
GROUPS = ("inflation", "unemployment", "rate", "cost")


def stack(variant, model, key="crps"):
    return np.vstack([np.array(json.loads((RUNS / f"ablate-{variant}-fold-{j}.json").read_text())["models"][model][key], float)
                      for j in range(8)])


groups = np.array(json.loads((RUNS / "ablate-full-fold-0.json").read_text())["groups"])
ref = np.nanmean(stack("full", "climatology"), 0)
for variant in ("full", "shuffled_targets"):
    print(variant)
    for m in ("ridge", "lstm_small", "tcn_transformer_small", "nn_mean", "stack", "climatology"):
        c = stack(variant, m)
        print(f"  {m:22s} " + " ".join(f"{g} {1 - np.nanmean(np.nanmean(c[:, groups == g], 0) / ref[groups == g]):+.3f}"
                                     for g in GROUPS))
