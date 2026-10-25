"""experiments/metal_links.py: macro_nn's folds on the panel calendar and the summed lag effects (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

import metal_links as ml

MONTHS = pd.date_range("2000-01-01", "2026-10-01", freq="MS")  # the macro panel's calendar in OXH-3


def test_folds_match_the_oxh3_test_blocks():
    ends = ml.fold_ends(MONTHS)
    assert len(ends) == ml.FOLDS
    starts = [f"{t0:%Y-%m}" for _, t0, _ in ends]
    assert starts == ["2008-01", "2010-04", "2012-07", "2014-10", "2017-01", "2019-04", "2021-07", "2023-09"]
    assert f"{ends[-1][2]:%Y-%m}" == "2025-10"
    # Each fold fits on every month before its test block, and the blocks tile the test years.
    for (last, t0, _), (_, nxt, _) in zip(ends, ends[1:] + [(None, pd.Timestamp("2025-11-01"), None)]):
        assert MONTHS[last + 1] == t0
        assert t0 < nxt


def test_fit_recovers_known_lag_sums():
    rng = np.random.default_rng(0)
    oil = rng.normal(0, 0.08, len(MONTHS))
    oil[0] = np.nan  # a first difference
    beta = np.zeros(ml.LAGS + 1)
    beta[[0, 1, 2, 12]] = [30.0, 20.0, 10.0, -5.0]
    y = ml.lagged(oil) @ beta + 0.5 + rng.normal(0, 0.5, len(MONTHS))
    f = ml.fit(y, oil, len(MONTHS) - 1)
    assert f["total"] == pytest.approx(55.0, abs=4 * f["se"])
    assert f["after"][3][0] == pytest.approx(ml.SHOCK * 60.0, abs=4 * f["after"][3][1])
    assert f["after"][12][0] == pytest.approx(ml.SHOCK * 60.0, abs=4 * f["after"][12][1])
    assert f["clears"] and f["months"] == len(MONTHS) - 1 - ml.LAGS


def test_control_and_dropped_months_leave_the_oil_sums_in_place():
    rng = np.random.default_rng(1)
    demand = rng.normal(0, 1, len(MONTHS))
    oil = 0.05 * demand + rng.normal(0, 0.05, len(MONTHS))
    y = 40.0 * oil + 5.0 * demand + rng.normal(0, 0.5, len(MONTHS))
    drop = (MONTHS >= "2008-07-01") & (MONTHS <= "2009-12-01")
    plain, held = ml.fit(y, oil, len(MONTHS) - 1, drop=drop), ml.fit(y, oil, len(MONTHS) - 1, control=demand)
    assert plain["months"] == len(MONTHS) - ml.LAGS - drop.sum()
    # Leaving demand out loads its effect onto oil; holding it fixed recovers the true 40.
    assert plain["total"] > held["total"]
    assert held["total"] == pytest.approx(40.0, abs=4 * held["se"])
