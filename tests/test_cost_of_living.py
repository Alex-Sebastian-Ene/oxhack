"""experiments/cost_of_living.py: the rest of the basket, the average link, the simulation's drift,
pass-through and supply-shock terms, sample CRPS, and the Brent path generators.

Synthetic data only, apart from the daily Lévy paths, which need the cached Brent file and the stored
Lévy fits (skipped otherwise). No MCMC. Needs jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("numpyro")
import cost_of_living as col  # noqa: E402

K = len(col.SERIES)
T = 80


def toy_data(y=None, x=None):
    months = pd.date_range("2000-01-01", periods=T, freq="MS")
    w = {k: 0.01 for k in [it.key for it in col.ITEMS]}
    for r in col.REGIONS:
        w[f"{r}_rest"] = 1 - sum(v for k, v in w.items() if k.startswith(f"{r}_"))
    return {"months": months, "x": np.zeros(T) if x is None else x, "g_us": np.zeros(T), "g_eu": np.zeros(T),
            "g_grain": np.zeros(T), "g_urea": np.zeros(T), "y": np.zeros((T, K)) if y is None else y,
            "D": np.zeros(T), "weights": {"w": w}}


def toy_post(n=2, a=0.0):
    z = np.zeros((n, K))
    return {"Bm": np.zeros((n, K, col.LAGS)), "Gm": np.zeros((n, K, col.LAGS)), "a": np.full((n, K), a),
            "S": np.zeros((n, K, 12)), "rho": z.copy(), "kappa": z.copy(), "phi": z.copy(), "psi": z.copy(),
            "sigma": np.full((n, K), 1e-12), "nu": np.full((n, K), 5.0)}


UNIT = SimpleNamespace(sd={c: 1.0 for c in col.CHANNELS}, xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))


def run(post, data, x0=0.0, D=0.0, regime=True):
    x = np.zeros((1, 1, col.H))
    x[..., 0] = x0
    return col.simulate(post, UNIT, data, np.array([30]), {"x": x}, np.full((1, col.H), D), np.zeros((5, K)),
                        np.random.default_rng(0), regime)[0, 0]  # [H, K], first draw


def test_driver_and_series_keys_do_not_clash():
    keys = [s.key for s in col.SERIES]
    assert len(set(keys)) == len(keys)
    assert not set(col.DRIVERS) & set(keys)


def test_lagmat_shifts_down():
    m = col.lagmat(np.arange(5.0), 2)
    assert m.shape == (5, 3)
    assert m[4].tolist() == [4.0, 3.0, 2.0]
    assert np.isnan(m[0, 1]) and np.isnan(m[1, 2])


def test_rest_makes_the_composite_equal_headline():
    rng = np.random.default_rng(1)
    keys = [it.key for it in col.ITEMS] + [f"{r}_all" for r in col.REGIONS]
    ch = pd.DataFrame(rng.normal(0, 1, (T, len(keys))), columns=keys)
    data = toy_data()
    ch = col.derive_rest(ch, data["weights"]["w"])
    S = ch[[s.key for s in col.SERIES]].values[None]  # one "draw"
    out = col.with_composites(S, data)[0]
    for i, r in enumerate(col.REGIONS):
        assert np.allclose(out[:, K + i], ch[f"{r}_all"].values)


def test_average_link_recovers_the_pass_through():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 0.08, T)
    k = [s.key for s in col.SERIES].index("us_fuel")  # oil lags 0..2, seasonally adjusted
    y = np.zeros((T, K))
    y[:, k] = 0.2 + 50 * x + 30 * np.r_[0, x[:-1]] + rng.normal(0, 0.01, T)
    b, sd, _ = col.ols_fit(toy_data(y, x), k, T - 1)
    assert b[1:4] == pytest.approx([50, 30, 0], abs=0.5)
    assert sd < 0.05


def test_drift_accumulates_month_by_month():
    out = run(toy_post(a=0.3), toy_data())
    assert out[:, 0] == pytest.approx(0.3 * np.arange(1, col.H + 1))


def test_oil_pass_through_and_the_supply_term():
    post = toy_post()
    post["Bm"][:, :, 0] = 2.0
    post["kappa"][:] = 1.0  # double pass-through in disruption months
    calm = run(post, toy_data(), x0=0.1, D=0.0)
    hit = run(post, toy_data(), x0=0.1, D=1.0)
    off = run(post, toy_data(), x0=0.1, D=1.0, regime=False)
    lagged = [s.lags for s in col.SERIES]
    k = int(np.argmax(lagged))  # a series with 12 lags: the shock enters at lag 0 only, B is zero beyond
    assert calm[-1, k] == pytest.approx(0.2)
    assert hit[-1, k] == pytest.approx(0.4)
    assert off[-1, k] == pytest.approx(0.2)


def test_driver_contributions_add_up_to_the_modelled_change():
    post = toy_post()
    post["Bm"][:, :, 0] = 2.0
    post["Gm"][:, :, 1] = -1.0
    post["rho"][:] = 0.3  # momentum carries each driver's effect on, but stays linear
    fut = {c: np.zeros((1, 1, col.H)) for c in col.CHANNELS}
    fut["x"][..., :3] = [0.1, -0.05, 0.02]
    fut["g_eu"][..., 0] = 0.2
    fut["g_us"][..., 0] = -0.1
    parts = col.decompose(post, UNIT, toy_data(), 30, fut, np.zeros((1, col.H)))
    total = np.array(parts["all_drivers"])
    groups = sum(np.array(parts[g]) for g in ("oil", "gas"))
    assert np.allclose(groups, total, atol=1e-3)
    assert np.abs(np.array(parts["gas"])).max() > 0.01


@pytest.mark.skipif(not (col.md.RAW / col.PINK_FILE).exists(), reason="needs the cached World Bank Pink Sheet")
def test_pinksheet_urea_parses_as_a_monthly_price():
    s = col.fetch_pinksheet("Urea")
    assert s.index.min() <= pd.Timestamp("2000-01-01")
    assert s.loc["2022-01-01":"2022-12-01"].notna().all()
    assert 50 < s.loc["2019-06-01"] < 1000  # $/t


def test_sample_crps_matches_the_normal_formula():
    rng = np.random.default_rng(3)
    S = rng.normal(1.0, 2.0, (200_000, 3))
    y = np.array([0.0, 1.0, 4.0])
    assert col.crps_samples(S, y) == pytest.approx(col.crps_normal(1.0, 2.0, y), rel=1e-2)


def test_scenario_shock_is_a_level_step_not_volatility():
    par = {"mu": 0.001, "omega": 0.0004, "alpha": 0.1, "beta": 0.8, "nu": 5.0, "s2_next": 0.005}
    shock = np.zeros(col.H)
    shock[:2] = [0.3, -0.1]
    base = col.garch_paths(par, 500, np.zeros(col.H), np.random.default_rng(4))
    hit = col.garch_paths(par, 500, shock, np.random.default_rng(4))
    assert np.allclose(hit - base, shock[None])


def test_monthly_garch_fit_finds_the_persistence():
    rng = np.random.default_rng(5)
    w, a, b, nu = 0.0002, 0.1, 0.85, 6.0
    r, s2 = np.zeros(1500), w / (1 - a - b)
    for i in range(1500):
        r[i] = np.sqrt(s2) * rng.standard_t(nu) * np.sqrt((nu - 2) / nu)
        s2 = w + a * r[i] ** 2 + b * s2
    fit = col.garch_fit(r)
    assert fit["alpha"] + fit["beta"] == pytest.approx(a + b, abs=0.06)


@pytest.mark.skipif(not (col.md.RAW / "fred_DCOILBRENTEU.csv").exists() or not (col.LEVY_RUNS / "rolling-2026.json").exists(),
                    reason="needs the cached daily Brent file and runs/levy/rolling-*.json")
def test_daily_levy_paths_shift_monthly_averages_by_the_shock():
    daily = col.daily_brent()
    month = pd.Timestamp("2026-01-01")
    shock = np.zeros(col.H)
    shock[0] = 0.25
    base = col.daily_paths("GARCH-CGMY", daily, month, 200, np.zeros(col.H), np.random.default_rng(6))
    hit = col.daily_paths("GARCH-CGMY", daily, month, 200, shock, np.random.default_rng(6))
    assert base.shape == (200, col.H)
    assert np.allclose(hit - base, shock[None], atol=1e-9)
    assert 0.02 < base[:, 0].std() < 0.3  # a month of Brent moves by a few to tens of percent
