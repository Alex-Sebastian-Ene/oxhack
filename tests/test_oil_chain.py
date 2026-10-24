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


def test_taylor_rule_recovers_coefficients_and_skips_the_zero_lower_bound():
    rng = np.random.default_rng(2)
    pi = pd.Series(2 + np.cumsum(rng.normal(0, 0.1, len(MONTHS))), index=MONTHS)
    u = pd.Series(5 + np.cumsum(rng.normal(0, 0.05, len(MONTHS))), index=MONTHS)
    ff = 1.0 + 1.5 * pi.shift(1) - 0.5 * u.shift(1) + rng.normal(0, 0.05, len(MONTHS))
    ff[MONTHS < "1995-01-01"] = 0.1  # pretend these months sat at the lower bound
    r = oc.taylor(pi, u, ff, ("1991-01-01", "2026-12-31"))
    assert r["era"].startswith("1995") and r["b_pi"] == pytest.approx(1.5, abs=0.1)
    assert r["b_u"] == pytest.approx(-0.5, abs=0.15)
