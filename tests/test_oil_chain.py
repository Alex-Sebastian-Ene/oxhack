"""experiments/oil_chain.py: the regression machinery behind each knock-on link (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

import oil_chain as oc

MONTHS = pd.date_range("1991-01-01", "2026-09-01", freq="MS")


def test_ols_coefficients_match_lstsq_and_lag0_hac_is_white():
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(500), rng.normal(size=(500, 2))])
    y = X @ np.array([0.1, 0.5, -0.3]) + rng.normal(size=500) * (1 + np.abs(X[:, 1]))
    b, cov = oc.ols_hac(y, X, 0)
    np.testing.assert_allclose(b, np.linalg.lstsq(X, y, rcond=None)[0])
    e = y - X @ b
    inv = np.linalg.inv(X.T @ X)
    np.testing.assert_allclose(cov, inv @ (X.T * e ** 2) @ X @ inv)


def test_design_builds_shifted_lags():
    x = pd.Series(np.arange(10.0), index=MONTHS[:10])
    d = oc.design(x * 2, {"oil": x}, 2)
    assert list(d.columns) == ["y", "const", "oil_0", "oil_1", "oil_2"]
    assert d.index[0] == MONTHS[2] and (d["oil_0"] - d["oil_2"] == 2).all()


def test_link_recovers_a_known_distributed_lag_and_predicts_out_of_sample():
    rng = np.random.default_rng(1)
    oil = pd.Series(rng.normal(0, 0.08, len(MONTHS)), index=MONTHS)
    y = 0.5 * oil + 0.2 * oil.shift(1) + pd.Series(rng.normal(0, 0.02, len(MONTHS)), index=MONTHS)
    res = oc.link("synthetic", y, {"oil": oil}, 2, 6, 1.0, "elasticity")
    assert res["total"] == pytest.approx(0.7, abs=3 * res["se"])
    assert res["total_test"] == pytest.approx(0.7, abs=3 * res["se_test"])
    # Out of sample, the fitted link should do almost as well as the true coefficients would.
    te = oc.design(y, {"oil": oil}, 2).loc[oc.TEST[0]:]
    true = 1 - np.sum((te["y"] - 0.5 * te["oil_0"] - 0.2 * te["oil_1"]) ** 2) / np.sum((te["y"] - te["y"].mean()) ** 2)
    assert res["r2_oos"] == pytest.approx(true, abs=0.02)


@pytest.mark.parametrize("k", [8, 12, 16])
def test_blocked_folds_partition_the_rows_and_leave_a_gap(k):
    n, purge = 427, 3
    seen = np.zeros(n, int)
    for train, test in oc.blocked_folds(n, k, purge):
        seen += test
        assert not (train & test).any()
        lo, hi = np.flatnonzero(test)[[0, -1]]
        assert not train[max(0, lo - purge):hi + purge + 1].any()  # the gap either side
        assert train.sum() == n - test.sum() - min(purge, lo) - min(purge, n - 1 - hi)
    assert (seen == 1).all()


def synthetic_spec(seed=1):
    rng = np.random.default_rng(seed)
    oil = pd.Series(rng.normal(0, 0.08, len(MONTHS)), index=MONTHS)
    y = 0.5 * oil + 0.2 * oil.shift(1) + pd.Series(rng.normal(0, 0.02, len(MONTHS)), index=MONTHS)
    return dict(name="synthetic", y=y, regressors={"oil": oil}, lags=2, hac_lag=6, scale=1.0, unit="e")


@pytest.mark.parametrize("k", [8, 16])
def test_cross_validation_recovers_the_link_in_every_fold(k):
    spec = synthetic_spec()
    blocked, forward = oc.cv_link(spec, k), oc.cv_link(spec, k, forward=True)
    assert len(blocked["effects"]) == k and len(forward["effects"]) < k  # early blocks lack history
    assert np.all(np.abs(blocked["effects"] - 0.7) < 0.1) and np.all(blocked["r2"] > 0.5)
    assert 0.7 < blocked["pooled_r2"] < 0.9 and 0.7 < forward["pooled_r2"] < 0.9
    full, se = oc.full_window_effect(spec)
    assert full == pytest.approx(0.7, abs=3 * se)


def test_cross_validation_finds_nothing_when_there_is_no_link():
    spec = synthetic_spec()
    spec["y"] = pd.Series(np.random.default_rng(9).normal(0, 0.02, len(MONTHS)), index=MONTHS)
    res = oc.cv_link(spec, 12)
    assert res["pooled_r2"] < 0.02 and oc.verdict({12: res}, res["effects"], res["r2"], 1.0) != "**Holds** at every k"


def test_taylor_rule_recovers_coefficients_and_skips_the_zero_lower_bound():
    rng = np.random.default_rng(2)
    pi = pd.Series(2 + np.cumsum(rng.normal(0, 0.1, len(MONTHS))), index=MONTHS)
    u = pd.Series(5 + np.cumsum(rng.normal(0, 0.05, len(MONTHS))), index=MONTHS)
    ff = 1.0 + 1.5 * pi.shift(1) - 0.5 * u.shift(1) + rng.normal(0, 0.05, len(MONTHS))
    ff[MONTHS < "1995-01-01"] = 0.1  # pretend these months sat at the lower bound
    r = oc.taylor(pi, u, ff, ("1991-01-01", "2026-12-31"))
    assert r["era"].startswith("1995") and r["b_pi"] == pytest.approx(1.5, abs=0.1)
    assert r["b_u"] == pytest.approx(-0.5, abs=0.15)
    folds = oc.cv_taylor(pi, u, ff, 10)
    assert len(folds) == 10 and np.all(np.abs(folds - 1.5) < 0.15)
