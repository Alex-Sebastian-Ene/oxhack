"""Leakage checks for notes/verification.md: index arithmetic of the folds, and perturbation tests
(overwrite what a forecaster could not have known and confirm nothing downstream changes; overwrite
what it could have known and confirm something does, so the test is not vacuous).

    uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch \
        --with jax --with numpyro python notes/verification/leak_checks.py
"""

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
import macro_bayes as mb  # noqa: E402
import macro_data as md  # noqa: E402
import macro_global as mg  # noqa: E402
import macro_nn as mn  # noqa: E402

BIG = 1e3


def month(data, m):
    return f"{mb.month_index(data)[m]:%Y-%m}"


def same(a, b):
    return all(np.array_equal(np.asarray(x), np.asarray(y), equal_nan=True) for x, y in zip(a, b))


def stats_tuple(st):
    return (st.xs, st.x2, st.vm, st.vs, st.ym, st.ys, st.um, st.us)


def main():
    data = mn.make_dataset(mn.V1_BLOCKS)
    dates, T = data["dates"], data["t"]
    info = mb.series_info(data)
    print("publication lags of the 22 targets:", dict(zip(info["keys"], info["pub_lag"].tolist())))

    print("\n== fold windows (macro_nn.fold_indices, macro_bayes.fold_window) ==")
    for j in range(mn.FOLDS):
        train, test = mn.fold_indices(dates, j)
        _, _, last = mb.fold_window(data, j)
        t_last, t0 = T[train[-1]], T[test[0]]
        cut = int(len(train) * 0.75)
        inner, val = train[:cut - 12], train[cut:]
        print(f"fold {j}: last training origin {month(data, t_last)}, its 12-month target ends {month(data, t_last + 12)}; "
              f"first test origin {month(data, t0)} (gap {t0 - t_last} origins); Bayes/global training months 13..{last} "
              f"= {month(data, 13)}..{month(data, last)}; macro_nn early stopping on origins "
              f"{month(data, T[val[0]])}..{month(data, T[val[-1]])} (inner ends {month(data, T[inner[-1]])}, "
              f"{T[val[0]] - T[inner[-1]]} origins apart)")
        assert t_last + 12 == t0 - 1 and last == t0 - 1 and T[val[-1]] < t0 and T[val[0]] - T[inner[-1]] > 12

    j = 7
    train, test, last = mb.fold_window(data, j)
    t0 = T[test[0]]

    print("\n== standardisation and training rows use training months only (fold 7) ==")
    st = mb.Stats(data, last)
    f = mg.features(data, st)
    rows = mg.training_rows(f, last)
    d = mb.design(data, st, last)
    late = copy.deepcopy(data)
    late["dM"][last + 1:] = BIG
    late["oil_m"][last + 1:] = BIG
    st2 = mb.Stats(late, last)
    print("  Stats unchanged when every month after", month(data, last), "is overwritten:", same(stats_tuple(st), stats_tuple(st2)))
    print("  macro_global training rows unchanged:", same(rows, mg.training_rows(mg.features(late, st2), last)))
    print("  macro_bayes design unchanged:", same(d.values(), mb.design(late, st2, last).values()))
    edge = copy.deepcopy(data)
    edge["dM"][last] += 1.0
    print("  positive control, month", month(data, last), "changed -> Stats change:",
          not same(stats_tuple(st), stats_tuple(mb.Stats(edge, last))))
    # macro_nn Scaler: only X rows inside the inner origins' windows and Y of inner origins
    cut = int(len(mn.fold_indices(dates, j)[0]) * 0.75)
    inner = mn.fold_indices(dates, j)[0][:cut - 12]
    sc = mn.Scaler(data, inner)
    late_nn = dict(data, X=data["X"].copy(), Y=data["Y"].copy(), OIL=data["OIL"].copy())
    late_nn["X"][T[inner[-1]] + 1:] = BIG
    late_nn["Y"][inner[-1] + 1:] = BIG
    late_nn["OIL"][inner[-1] + 1:] = BIG
    sc2 = mn.Scaler(late_nn, inner)
    print("  macro_nn Scaler unchanged when X after the last inner origin and Y/OIL of later origins are overwritten:",
          same((sc.xm, sc.xs, sc.ym, sc.ys, sc.os), (sc2.xm, sc2.xs, sc2.ym, sc2.ys, sc2.os)))

    print("\n== no input at month s contains y[s] ==")
    s_star = last - 5
    poke = copy.deepcopy(data)
    poke["dM"][s_star] += 5.0
    fp = mg.features(poke, st)
    print(f"  macro_global.features, y[{month(data, s_star)}] changed: inputs at s unchanged:",
          np.array_equal(f["own"][s_star], fp["own"][s_star], equal_nan=True) and np.array_equal(f["oil"][s_star], fp["oil"][s_star])
          and f["v"][s_star] == fp["v"][s_star], "| target at s changed:", not np.allclose(f["y"][s_star], fp["y"][s_star]),
          "| own lag at s+1 changed:", not np.allclose(np.nan_to_num(f["own"][s_star + 1]), np.nan_to_num(fp["own"][s_star + 1])))
    dp = mb.design(poke, st, last)
    r = s_star - 13
    print("  macro_bayes.design: yprev and own-vol u at s unchanged:",
          np.array_equal(d["yprev"][r], dp["yprev"][r], equal_nan=True) and np.array_equal(d["u"][r], dp["u"][r], equal_nan=True),
          "| u at s+1 changed:", not np.allclose(d["u"][r + 1], dp["u"][r + 1]))
    # macro_nn: the window of origin i ends at row t_i, and F is shifted by each series' publication lag
    F, L, _ = md.build_panel(mn.V1_BLOCKS)
    m = F.index.get_loc(pd.Timestamp("2024-06-01"))
    print("  macro_nn features: F['us_cpi_dlog'] at 2024-06 equals the true change of 2024-05 (lag 1):",
          np.isclose(F["us_cpi_dlog"].iloc[m], L["us_cpi"].iloc[m - 1] - L["us_cpi"].iloc[m - 2]),
          "| F['uk_unemp_d'] at 2024-06 equals the true change of 2024-04 (lag 2):",
          np.isclose(F["uk_unemp_d"].iloc[m], L["uk_unemp"].iloc[m - 2] - L["uk_unemp"].iloc[m - 3]))

    print("\n== the oil path starts the month after the origin (what-if) ==")
    oil = data["OIL"][test]
    print("  OIL[test][:, 0] == oil_m[t + 1]:", np.allclose(oil[:, 0], data["oil_m"][T[test] + 1]),
          "| OIL[test][:, 11] == oil_m[t + 12]:", np.allclose(oil[:, 11], data["oil_m"][T[test] + 12]))

    print("\n== simulators only use months published by the origin ==")
    post = mb.point_post(d, info, True, 20)
    post["psi"] = np.full_like(post["a"], 0.3)  # exercise the own-volatility path too
    ols = mg.OLS(rows[2], rows[1], rows[3], info["floor"])
    for i in (0, 7, len(test) - 1):
        t = T[test[i:i + 1]]
        fut = data["OIL"][test[i:i + 1]][None]
        hide = copy.deepcopy(data)
        for k, p in enumerate(info["pub_lag"]):
            hide["dM"][t[0] - p + 1:, k] = BIG  # months not yet published at the end of month t
        hide["oil_m"][t[0] + 1:] = BIG  # Brent after the origin (the what-if path comes from `fut`)
        show = copy.deepcopy(data)
        for k, p in enumerate(info["pub_lag"]):
            show["dM"][t[0] - p, k] += 1.0  # the last published month
        res = []
        for label, sim in (("macro_bayes.simulate", lambda dd: mb.simulate(post, st, info, dd, t, fut, np.random.default_rng(1))),
                           ("macro_global.simulate", lambda dd: mg.simulate([ols], st, info, dd, t, fut, np.random.default_rng(1), n=50))):
            base = sim(data)
            res.append(f"{label}: unpublished overwritten -> identical {np.array_equal(base, sim(hide))}, "
                       f"last published changed -> differs {not np.allclose(base, sim(show))}")
        print(f"  origin {month(data, t[0])}: " + "; ".join(res))

    print("\n== early stopping uses training months only (macro_global.train, fold 7) ==")
    months = rows[0]
    q = np.quantile(np.unique(months), 1 - mg.VAL_SHARE)
    print(f"  inner months {month(data, months.min())}..{month(data, int(np.floor(q)))}, validation months "
          f"{month(data, int(np.floor(q)) + 1)}..{month(data, months.max())}; first test origin {month(data, t0)}")


if __name__ == "__main__":
    main()
