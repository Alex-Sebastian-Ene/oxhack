"""experiments/country_outlook.py: features, the backtest, bands and the forecast API. Synthetic data only: no downloads.

    uv run --no-project --with pytest --with numpy --with scipy --with pandas --with scikit-learn pytest -q tests/test_country_outlook.py
"""

import numpy as np
import pandas as pd
import pytest

import country_outlook as cl

MONTHS = pd.date_range("2000-01-01", "2026-06-01", freq="MS")
SEASON = np.array([0.6, 0.4, 0.2, 0.0, -0.2, -0.4, -0.6, -0.4, -0.2, 0.0, 0.2, 0.4])  # % a month, sums to zero


def brent_path(seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(70 * np.exp(np.cumsum(rng.normal(0, 0.08, len(MONTHS)))), index=MONTHS)


def synthetic_levels(n=30, seed=1, phi=0.85, noise=0.4):
    """Monthly inflation that reverts to each country's own mean (AR(1)), food with a seasonal pattern on top."""
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        mu = rng.uniform(1, 15) / 12  # % a month
        pi, x = np.empty(len(MONTHS)), mu
        for t in range(len(MONTHS)):
            x = mu + phi * (x - mu) + rng.normal(0, noise)
            pi[t] = x
        food = pi + SEASON[MONTHS.month - 1] + rng.normal(0, 0.2, len(MONTHS))
        out[f"C{i:02d}"] = {"all": pd.Series(100 * np.exp(np.cumsum(pi) / 100), index=MONTHS),
                            "food": pd.Series(100 * np.exp(np.cumsum(food) / 100), index=MONTHS)}
    return out


def test_zero_prediction_is_the_naive_rule_and_y_is_the_outcome():
    lv = synthetic_levels(n=3)
    s = lv["C00"]["all"]
    L = cl.log_wide(lv, "all")
    h = 3
    P = cl.panel(L, brent_path(), None, None, h)
    t = pd.Timestamp("2020-05-01")
    row = P.loc[(t, "C00")]
    naive = 100 * ((s[t] / s[t - pd.DateOffset(months=12)]) ** (h / 12) - 1)
    actual = 100 * (s[t + pd.DateOffset(months=h)] / s[t] - 1)
    assert cl.pct(h / 12 * row["r12"]) == pytest.approx(naive, abs=1e-9)
    assert cl.pct(h / 12 * (row["r12"] + row["y"])) == pytest.approx(actual, abs=1e-9)


def test_seasonal_feature_recovers_a_fixed_pattern():
    # steady 3% a year plus a fixed seasonal pattern: the seasonal feature is exactly the departure from naive
    pi = 3 / 12 + SEASON[MONTHS.month - 1]
    lv = {"X": {"food": pd.Series(100 * np.exp(np.cumsum(pi) / 100), index=MONTHS)}}
    P = cl.panel(cl.log_wide(lv, "food"), brent_path(), None, None, 2).loc["2010-01-01":"2020-12-01"]
    assert np.allclose(P["seas"], P["y"], atol=1e-8)
    assert P["seas"].abs().max() > 3  # and it is not trivially zero


def test_brent_changes_line_up_by_month():
    brent = brent_path()
    P = cl.panel(cl.log_wide(synthetic_levels(n=2), "all"), brent, None, None, 1)
    t = pd.Timestamp("2015-07-01")
    want = 100 * np.log(brent[t] / brent[t - pd.DateOffset(months=3)])
    assert P.loc[(t, "C00"), "b3"] == pytest.approx(want)
    assert P.loc[(t, "C01"), "b3"] == pytest.approx(want)


def test_fragile_and_hyperinflation_rows_are_kept_out_of_training():
    lv = synthetic_levels(n=3)
    lv["LBN"] = lv.pop("C02")
    hyper = lv["C01"]["all"].copy()
    hyper.loc["2010-01-01":] *= np.exp(np.arange((hyper.index >= "2010-01-01").sum()) * 0.05)  # ~80% a year
    lv["C01"]["all"] = hyper
    P = cl.panel(cl.log_wide(lv, "all"), brent_path(), None, None, 1)
    ok = cl.trainable(P)
    iso = P.index.get_level_values(1)
    assert not ok[iso == "LBN"].any()
    assert not ok[(iso == "C01") & (P.index.get_level_values(0) >= "2011-06-01")].any()
    assert ok[iso == "C00"].sum() > 250


@pytest.fixture(scope="module")
def bt():
    lv = synthetic_levels()
    origins = pd.date_range("2012-01-01", "2024-10-01", freq="3MS")
    B = cl.backtest(lv, brent_path(), horizons=(1, 12), origins=origins, rules=("ridge", "lad"), log=lambda *_: None)
    return lv, cl.add_bands(B, rules=("naive", "ridge", "lad"))


def test_pooled_model_beats_naive_when_inflation_reverts_to_its_mean(bt):
    _, B = bt
    S = cl.summarise(B, rules=("ridge", "lad"))
    for kind in ("food", "all"):
        for h in ("1", "12"):
            assert S[kind][h]["skill_vs_naive"] > 0.05, (kind, h, S[kind][h])
            assert S[kind][h]["model"] in ("ridge", "lad")
    # seasonality makes food's one-month naive rule much worse than the model
    assert S["food"]["1"]["skill_vs_naive"] > 0.3


def test_out_of_sample_band_covers_about_ninety_percent(bt):
    _, B = bt
    S = cl.summarise(B, rules=("ridge", "lad"))
    for kind in ("food", "all"):
        for h in ("1", "12"):
            assert 0.8 <= S[kind][h]["coverage90"] <= 0.97, (kind, h, S[kind][h]["coverage90"])


def test_backtest_only_trains_on_outcomes_known_at_the_origin(monkeypatch):
    lv = synthetic_levels(n=25)
    seen = []
    real = cl.fit_models

    def spy(D, *a, **k):
        seen.append(D.index.get_level_values(0).max())
        return real(D, *a, **k)

    monkeypatch.setattr(cl, "fit_models", spy)
    origins = pd.DatetimeIndex(["2016-01-01", "2020-07-01"])
    cl.backtest(lv, brent_path(), kinds=("all",), horizons=(6,), origins=origins, rules=("lad",), log=lambda *_: None)
    assert seen == [pd.Timestamp("2015-07-01"), pd.Timestamp("2020-01-01")]


def test_fit_and_forecast_any_index(bt):
    lv, B = bt
    S = cl.summarise(B, rules=("ridge", "lad"))
    lv = {k: v | {"transport": v["all"] * 1.0} for k, v in list(lv.items())[:25]}
    model = cl.fit(lv, brent_path(), S)
    assert model["kinds"]["transport"]["12"]["rule"] == S["all"]["12"]["model"]  # other kinds take "all"'s rule
    f = cl.forecast(lv["C03"]["food"], "food", brent_path(), model, pair=lv["C03"]["all"])
    assert f["from"] == "2026-06" and set(f["q"]) == {"1", "12"}
    for lo, mid, hi in f["q"].values():
        assert lo < mid < hi
    # a fragile country gets the naive rule: the median is the last 12 months' rate, scaled to h
    s = lv["C03"]["all"]
    g = cl.forecast(s, "all", brent_path(), model, iso="ZWE")
    assert g["rule"] == {"1": "naive", "12": "naive"}
    assert g["q"]["12"][1] == pytest.approx(round(100 * (s.iloc[-1] / s.iloc[-13] - 1), 2))
    # from an earlier month, and for a kind the backtest never saw
    h = cl.forecast(lv["C03"]["transport"], "transport", brent_path(), model, at="2024-03")
    assert h["from"] == "2024-03"


def test_gradient_boosting_runs_in_the_backtest():
    pytest.importorskip("sklearn")
    lv = synthetic_levels(n=25)
    origins = pd.date_range("2018-01-01", "2024-01-01", freq="12MS")
    B = cl.backtest(lv, brent_path(), kinds=("all",), horizons=(3,), origins=origins, log=lambda *_: None)
    assert {"gbm", "blend", "lad", "ridge", "naive"} <= set(B.columns)
    assert np.isfinite(B[["gbm", "blend"]]).all().all()
