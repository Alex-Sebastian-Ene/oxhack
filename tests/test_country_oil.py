"""experiments/country_oil.py: the fuel pass-through fit and the trade shares. Synthetic data only: no downloads."""

import numpy as np
import pandas as pd
import pytest

import country_oil as co

MONTHS = pd.date_range("2005-01-01", "2026-06-01", freq="MS")


def brent_path(seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(70 * np.exp(np.cumsum(rng.normal(0, 0.08, len(MONTHS)))), index=MONTHS)


def test_passthrough_recovers_a_known_slope_from_annual_rates():
    brent = brent_path()
    fuel = np.exp(0.3 * np.log(brent) + np.random.default_rng(1).normal(0, 0.01, len(MONTHS)))
    yoy = 100 * (fuel / fuel.shift(12) - 1)  # annual % change, as notes/country-trends.json packs it
    fit = co.passthrough(yoy, brent)
    assert fit["e"] == pytest.approx(0.3, abs=0.02)
    assert fit["lo"] < fit["e"] < fit["hi"]
    assert fit["from"] == "2009-01" and fit["to"] == "2025-12"


def test_passthrough_needs_five_years():
    brent = brent_path()
    yoy = pd.Series(np.nan, index=MONTHS)
    yoy.loc["2020-01-01":"2023-12-01"] = 5.0
    assert co.passthrough(yoy, brent) is None


def test_yoy_series_reads_the_packed_format():
    s = co.yoy_series({"from": "2007-01", "v": [1.0, None, 2.5]})
    assert list(s.index.strftime("%Y-%m")) == ["2007-01", "2007-02", "2007-03"]
    assert s.iloc[0] == 1.0 and np.isnan(s.iloc[1])


def test_trade_profile_shares_and_import_dependence():
    p = co.trade_profile(imp=200.0, exp=50.0, gulf_by={"Saudi Arabia": 60.0, "Iraq": 40.0, "Qatar": 0.0})
    assert p["gulf_share"] == 0.5
    assert p["m"] == 0.75
    assert list(p["by"]) == ["Saudi Arabia", "Iraq"]  # largest first, zeros dropped


def test_ridge_update_pulls_noisy_slopes_to_the_prior_more_than_precise_ones():
    fits = {"A": {"b": 0.10, "se": 0.001}, "B": {"b": 0.10, "se": 0.05}, "C": {"b": -0.02, "se": 0.01}, "D": {"b": 0.05, "se": 0.02}}
    out, prior = co.partial_pool(fits, prior=0.03)
    assert prior["b"] == 0.03
    assert out["A"]["b"] == pytest.approx(0.10, abs=0.005)        # precise: keeps its own slope
    assert abs(out["B"]["b"] - 0.03) < abs(0.10 - 0.03)            # noisy: pulled towards the model
    assert all(out[k]["se"] <= fits[k]["se"] for k in fits)


def test_latest_yoy_now_and_at_a_month():
    level = pd.Series(100 * 1.01 ** np.arange(len(MONTHS)), index=MONTHS)  # 1% a month
    assert co.latest_yoy(level)["month"] == "2026-06"
    assert co.latest_yoy(level, "2026-02")["v"] == pytest.approx(100 * (1.01 ** 12 - 1), abs=0.05)
    assert co.latest_yoy(level, "1999-01") is None


def test_naive_outlook_continues_the_latest_rate_with_a_band():
    level = pd.Series(100 * 1.005 ** np.arange(len(MONTHS)), index=MONTHS)  # about 6.2% a year
    brent = pd.Series(70.0, index=pd.date_range("2005-01-01", "2026-09-01", freq="MS"))  # flat: no oil move
    o = co.naive_outlook(level, brent, link=None, misses=list(np.linspace(-2, 2, 20)))
    lo, mid, hi, oil = o["q"]["12"]
    assert mid == pytest.approx(100 * (1.005 ** 12 - 1), abs=0.01) and oil == 0
    assert lo < mid < hi
    assert o["q"]["3"][2] - o["q"]["3"][0] < hi - lo                # the band widens with the horizon
    assert co.naive_outlook(level, brent, None, misses=[0.1] * 3) is None  # too few past misses


def test_trade_profile_net_exporter_and_caps():
    assert co.trade_profile(imp=10.0, exp=50.0, gulf_by={})["m"] == -4.0
    assert co.trade_profile(imp=1.0, exp=1000.0, gulf_by={})["m"] == -20.0
    assert co.trade_profile(imp=0.0, exp=5.0, gulf_by={})["gulf_share"] is None
    assert co.trade_profile(imp=10.0, exp=0.0, gulf_by={"Iraq": 12.0})["gulf_share"] == 1.0  # CIF/FOB mismatch capped
