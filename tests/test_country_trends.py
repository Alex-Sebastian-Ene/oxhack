"""experiments/country_trends.py: annual rates, rebasing, packing for the page, and the sector run's
per-series skill and responses. Synthetic data only: no downloads."""

import numpy as np
import pandas as pd
import pytest

import country_trends as ct

MONTHS = pd.date_range("2005-01-01", "2026-09-01", freq="MS")


def test_yoy_is_the_change_on_the_same_month_a_year_earlier():
    level = pd.Series(100 * 1.02 ** (np.arange(len(MONTHS)) / 12), index=MONTHS)  # 2% a year, smoothly
    r = ct.yoy(level)
    assert r.iloc[:12].isna().all()
    assert np.allclose(r.iloc[12:], 2.0)


def test_rebase_puts_the_year_average_at_100():
    level = pd.Series(np.linspace(50, 80, len(MONTHS)), index=MONTHS)
    assert ct.rebase(level).loc["2021"].mean() == pytest.approx(100)


def test_pack_trims_gaps_at_the_ends_keeps_them_inside_and_starts_at_start():
    x = pd.Series(np.nan, index=MONTHS)
    x.loc["2010-03-01":"2010-08-01"] = [1.04, 2.0, np.nan, 3.0, 4.0, 5.0]
    p = ct.pack(x, start="2007-01")
    assert p == {"from": "2010-03", "v": [1.0, 2.0, None, 3.0, 4.0, 5.0]}
    assert ct.pack(pd.Series(np.nan, index=MONTHS)) is None
    assert ct.pack(pd.Series(1.0, index=MONTHS), start="2026-08")["from"] == "2026-08"


def fold(crps_a, crps_clim, resp, scored=(True, True, True, True)):
    """A sector-fold-shaped result with one series "a" at horizons 1 and 12 and one series "b" at 1 and 12."""
    names = ["a@1", "a@12", "b@1", "b@12"]
    return {"names": names, "scored": [list(scored)],
            "models": {"global_lin": {"crps": [crps_a], "response_up10": [resp]}, "climatology": {"crps": [crps_clim]}}}


def test_run_results_skill_is_one_minus_the_mean_ratio_over_horizons():
    # a: ratios 0.8 and 0.6 -> skill 0.3; b: ratios 1.2 and 1.0 -> skill -0.1
    folds = [fold([0.8, 0.6, 1.2, 1.0], [1, 1, 1, 1], [0.1, 1.0, 0.2, 2.0])]
    r = ct.run_results(folds)
    assert r["a"]["skill"] == pytest.approx(0.3)
    assert r["b"]["skill"] == pytest.approx(-0.1)
    assert r["a"]["resp"] == {1: pytest.approx(0.1), 12: pytest.approx(1.0)}
    g = ct.group_skill(r, ["a", "b"])
    assert g == {"skill": pytest.approx(0.1), "beats": 1, "of": 2}


def test_run_results_averages_crps_over_folds_and_responses_only_where_scored():
    f1 = fold([0.5, 0.5, 1, 1], [1, 1, 1, 1], [1.0, 1.0, 1.0, 1.0])
    f2 = fold([1.0, 1.0, 1, 1], [1, 1, 1, 1], [9.0, 9.0, 3.0, 3.0], scored=(False, False, True, True))
    f2["models"]["global_lin"]["crps"][0][:2] = [np.nan, np.nan]  # not scored: no CRPS either
    f2["models"]["climatology"]["crps"][0][:2] = [np.nan, np.nan]
    r = ct.run_results([f1, f2])
    assert r["a"]["skill"] == pytest.approx(0.5)  # only fold 1 scored "a"
    assert r["a"]["resp"][1] == pytest.approx(1.0)  # fold 2's 9.0 is ignored
    assert r["b"]["resp"][12] == pytest.approx(2.0)  # mean of 1 and 3
