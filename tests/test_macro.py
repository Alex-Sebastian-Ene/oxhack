"""experiments/macro_data.py and macro_nn.py: publication lags, targets, folds, networks, ensembles.

Synthetic data only: no downloads. The network tests need torch (skipped if it is not installed).
"""

import numpy as np
import pandas as pd
import pytest

import macro_data as md

torch = pytest.importorskip("torch")
import macro_nn as mn  # noqa: E402

MONTHS = pd.date_range("1998-01-01", "2026-10-01", freq="MS")


@pytest.fixture
def toy_panel(monkeypatch):
    """Three series through build_panel: a market price (lag 0), a lag-1 macro level and an AIS flow."""
    rng = np.random.default_rng(0)
    price = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.05, len(MONTHS)))) * 50, index=MONTHS)
    unemp = pd.Series(5 + np.cumsum(rng.normal(0, 0.1, len(MONTHS))), index=MONTHS)
    flow = pd.Series(rng.uniform(0.8, 1.2, len(MONTHS)) * 1e6, index=MONTHS).loc["2019-01-01":]
    series = [md.Series("brent", "toy", "price", "oil", "dlog", 0, name="toy price"),
              md.Series("us_unemp", "toy", "unemp", "us", "level+diff", 1, "unemployment", "toy unemployment"),
              md.Series("hormuz_capacity", "toy", "flow", "ais", "share", 0, name="toy flow")]
    data = {"price": price, "unemp": unemp, "flow": flow}
    monkeypatch.setattr(md, "SERIES", series)
    monkeypatch.setattr(md, "FETCH", {"toy": lambda code: data[code]})
    return data


def test_publication_lag_and_transforms(toy_panel):
    F, L, prov = md.build_panel(blocks=("oil", "us", "ais"))
    t = pd.Timestamp("2010-06-01")
    # Market price: known the same month, as a log change.
    assert F.loc[t, "brent_dlog"] == pytest.approx(np.log(toy_panel["price"][t] / toy_panel["price"][t - pd.DateOffset(months=1)]))
    # Lag-1 series: at the end of June only May is public.
    assert F.loc[t, "us_unemp"] == pytest.approx(toy_panel["unemp"][t - pd.DateOffset(months=1)])
    assert F.loc[t, "us_unemp_d"] == pytest.approx(toy_panel["unemp"][t - pd.DateOffset(months=1)]
                                                   - toy_panel["unemp"][t - pd.DateOffset(months=2)])
    # Targets use the true (unlagged) level; prices are logged.
    assert L.loc[t, "us_unemp"] == pytest.approx(toy_panel["unemp"][t])
    assert L.loc[t, "brent"] == pytest.approx(np.log(toy_panel["price"][t]))
    # AIS: share of the 2019-2024 average, zero and flagged unavailable before it starts.
    base = toy_panel["flow"].loc[md.SHARE_BASE[0]:md.SHARE_BASE[1]].mean()
    assert F.loc["2021-03-01", "hormuz_capacity_share"] == pytest.approx(toy_panel["flow"]["2021-03-01"] / base)
    assert F.loc[:"2018-12-01", "hormuz_capacity_share"].eq(0).all()
    assert F.loc[:"2018-12-01", "ais_available"].eq(0).all() and F.loc["2019-02-01":, "ais_available"].eq(1).all()
    assert all("error" not in p for p in prov)


def test_short_gaps_are_filled_on_the_level_not_the_change(toy_panel):
    toy_panel["unemp"]["2015-04-01"] = np.nan  # a missing release, like October 2025
    F, _, _ = md.build_panel(blocks=("oil", "us"))
    # Published one month later: the gap shows at 2015-05 as an unchanged level (change 0)...
    assert F.loc["2015-05-01", "us_unemp"] == pytest.approx(toy_panel["unemp"]["2015-03-01"])
    assert F.loc["2015-05-01", "us_unemp_d"] == pytest.approx(0.0)
    # ...and the next month carries the full two-month change, not a repeat of an old one.
    assert F.loc["2015-06-01", "us_unemp_d"] == pytest.approx(toy_panel["unemp"]["2015-05-01"] - toy_panel["unemp"]["2015-03-01"])


def test_ignore_lags_only_moves_the_lagged_series(toy_panel):
    F, _, _ = md.build_panel(blocks=("oil", "us"))
    G, _, _ = md.build_panel(blocks=("oil", "us"), ignore_lags=True)
    assert np.allclose(F["brent_dlog"].dropna(), G["brent_dlog"].dropna())
    assert G.loc["2010-06-01", "us_unemp"] == pytest.approx(toy_panel["unemp"]["2010-06-01"])


def test_targets_and_oil_path_line_up_with_the_origin(toy_panel, monkeypatch):
    monkeypatch.setattr(md, "registry", lambda blocks=md.BLOCKS: [s for s in md.SERIES if s.block in blocks])
    data = mn.make_dataset(blocks=("oil", "us"))
    i = 100
    t = data["t"][i]
    L = md.build_panel(blocks=("oil", "us"))[1]
    for h in mn.HORIZONS:
        col = data["names"].index(f"us_unemp@{h}")
        assert data["Y"][i, col] == pytest.approx(L["us_unemp"].iloc[t + h] - L["us_unemp"].iloc[t])
    oil = L["brent"].diff().values
    assert np.allclose(data["OIL"][i], oil[t + 1:t + 1 + mn.OIL_AHEAD])
    assert data["groups"].count("unemployment") == len(mn.HORIZONS)


def test_folds_leave_a_12_month_gap_before_every_test_block():
    dates = pd.date_range("2001-12-01", "2025-10-01", freq="MS")
    seen = []
    for j in range(mn.FOLDS):
        train, test = mn.fold_indices(dates, j)
        assert train.max() + max(mn.HORIZONS) < test.min()  # no training target reaches the test block
        seen += list(test)
    assert seen == list(np.flatnonzero(dates >= mn.TEST_START))


def test_scaler_uses_training_rows_only():
    rng = np.random.default_rng(1)
    T = 120
    data = {"X": rng.normal(size=(T, 4)), "t": np.arange(mn.WINDOW - 1, T - 12), "Y": rng.normal(size=(T - 12 - mn.WINDOW + 1, 3)),
            "OIL": rng.normal(size=(T - 12 - mn.WINDOW + 1, mn.OIL_AHEAD))}
    train = np.arange(40)
    a = mn.Scaler(data, train)
    data["X"][80:] += 100.0  # rows only test windows can see
    data["Y"][60:] += 100.0
    b = mn.Scaler(data, train)
    assert np.allclose(a.xm, b.xm) and np.allclose(a.ym, b.ym)


@pytest.mark.parametrize("arch", list(mn.ARCHS) + ["lstm_skip", "tcn_transformer_skip"])
def test_every_network_maps_a_batch_to_gaussian_outputs(arch):
    net = mn.Net(arch, n_in=7, n_out=5, d=16, layers=1, dropout=0.0)
    mu, logvar = net(torch.randn(3, mn.WINDOW, 7), torch.randn(3, mn.OIL_AHEAD))
    assert mu.shape == (3, 5) and logvar.shape == (3, 5) and torch.isfinite(mu).all()
    assert (net.skip is not None) == arch.endswith("_skip")


def test_tcn_is_causal():
    tcn = mn.TCN(n_in=3, d=8, layers=1, dropout=0.0, sequence=True).eval()
    x = torch.randn(1, mn.WINDOW, 3)
    y = x.clone()
    y[:, 15:] += 5.0  # change only the later months
    with torch.no_grad():
        a, b = tcn(x), tcn(y)
    assert torch.allclose(a[:, :15], b[:, :15], atol=1e-6) and not torch.allclose(a[:, 15:], b[:, 15:])


def test_skip_path_is_trained_without_weight_decay(monkeypatch):
    monkeypatch.setattr(mn, "QUICK", True)
    rng = np.random.default_rng(2)
    b = [torch.tensor(rng.normal(size=s), dtype=torch.float32) for s in ((40, mn.WINDOW, 5), (40, mn.OIL_AHEAD), (40, 3))]
    net, _, _ = mn.train_net("lstm_skip", "small", 0, b, b, 5, 3)
    assert net.skip is not None and torch.isfinite(net.skip.weight).all()


def test_nll_ignores_missing_targets_and_mixture_moments():
    mu, logvar = torch.zeros(2, 2), torch.zeros(2, 2)
    y = torch.tensor([[1.0, float("nan")], [float("nan"), -1.0]])
    assert mn.nll(mu, logvar, y).item() == pytest.approx(0.5)  # 0.5 * (0 + 1) on the two observed cells
    m, v = mn.mixture([(np.array([0.0]), np.array([1.0])), (np.array([2.0]), np.array([1.0]))])
    assert m[0] == pytest.approx(1.0) and v[0] == pytest.approx(2.0)  # within 1 + between 1


def test_gaussian_crps_matches_numerical_integration():
    from scipy import integrate, stats
    mu, sd, y = 0.3, 1.7, -0.4
    num = integrate.quad(lambda x: (stats.norm.cdf(x, mu, sd) - (x >= y)) ** 2, -30, 30, points=[y], limit=200)[0]
    assert mn.gaussian_crps(np.array([mu]), np.array([sd ** 2]), np.array([y]))[0] == pytest.approx(num, rel=1e-6)


def test_stacker_returns_a_convex_combination_of_the_means():
    st = mn.Stacker(n_models=3, n_out=4, n_feat=6)
    mus = torch.tensor([[0.0, 1.0, 2.0]] * 5)
    mu, logvar = st(mus, torch.zeros(5, 3), torch.randn(5, 6), torch.arange(5) % 4)
    assert torch.all(mu >= 0.0) and torch.all(mu <= 2.0) and torch.isfinite(logvar).all()


def synthetic_anchor_data(seed=0, T=300, beta=(0.3, 0.2, 0.1)):
    """Monthly oil changes and two targets: one with a known 0-2 lag pass-through, one with none."""
    rng = np.random.default_rng(seed)
    oil = rng.normal(0, 0.08, T)
    oil[0] = np.nan  # a log change has no first month, as in the panel
    o = np.nan_to_num(oil)
    linked = sum(b * np.concatenate([np.zeros(l), o[:T - l]]) for l, b in enumerate(beta)) * 100 + rng.normal(0, 0.2, T)
    t = np.arange(23, T - 12)
    OIL = np.stack([o[i + 1:i + 13] for i in t])
    return {"oil_m": oil, "dM": np.column_stack([linked, rng.normal(0, 0.2, T)]), "target_keys": ["linked", "none"],
            "target_lags": [2, 2], "t": t, "OIL": OIL, "names": [f"{k}@{h}" for k in ("linked", "none") for h in mn.HORIZONS],
            "dates": pd.date_range("2000-01-01", periods=len(t), freq="MS"), "Y": np.zeros((len(t), 8))}


def test_anchor_recovers_the_pass_through_and_drops_links_that_fail_validation():
    data = synthetic_anchor_data()
    anchor = mn.Anchor(data, last_month=250)
    np.testing.assert_allclose(anchor.beta[0], [30, 20, 10], atol=1.5)  # target units: x100 log points
    assert anchor.info[0]["anchored"] and not anchor.info[1]["anchored"]
    assert np.all(anchor.beta[1] == 0)


def test_anchor_uses_training_months_only_and_sums_lags_over_the_horizon():
    data = synthetic_anchor_data()
    a = mn.Anchor(data, last_month=200)
    data["dM"][201:] += 1000.0  # months after the training window must not matter
    b = mn.Anchor(data, last_month=200)
    np.testing.assert_allclose(a.beta[0], b.beta[0])
    i = 50
    t, beta = data["t"][i], a.beta[0]
    path = {s: data["oil_m"][s] for s in range(t - 2, t + 1)} | {t + 1 + j: data["OIL"][i, j] for j in range(12)}
    manual = [sum(sum(beta[l] * path[m - l] for l in range(3)) for m in range(t + 1, t + h + 1)) for h in mn.HORIZONS]
    np.testing.assert_allclose(a.predict(data, np.array([i]))[0, :4], manual, rtol=1e-10)


def test_residual_data_removes_the_anchor_and_the_oil_path():
    data = synthetic_anchor_data()
    anchor = mn.Anchor(data, last_month=250)
    res = mn.residual_data(data, anchor)
    assert np.all(res["OIL"] == 0)
    np.testing.assert_allclose(res["Y"] + anchor.predict(data, np.arange(len(data["dates"]))), data["Y"])


def test_calibration_rescales_variances_that_are_too_narrow():
    rng = np.random.default_rng(3)
    y = rng.normal(0, 2, (400, 8))  # true variance 4 everywhere
    b_val = (None, None, torch.tensor(y, dtype=torch.float32))
    names = [f"s{k}@{h}" for k in range(2) for h in mn.HORIZONS]
    scales = mn.calibrate({"narrow": lambda b: (np.zeros((400, 8)), np.ones((400, 8)))}, b_val, names)
    np.testing.assert_allclose(scales["narrow"], 4.0, rtol=0.15)
