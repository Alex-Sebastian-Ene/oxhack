"""experiments/oil_paths.py: monthly means from daily paths, the GARCH variance along a path, unit-
variance innovations and the Hormuz scenario premium.

Synthetic data only: no downloads. Needs torch, jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import levy_fourier as lf  # noqa: E402
import oil_paths as op  # noqa: E402

FLAT = SimpleNamespace(table=lambda: (np.array([0.0, 1.0]), np.array([0.0, 0.0])))  # an innovation that is always 0
MONTH = pd.DatetimeIndex(["2020-01-01"])


def prices(start=100.0):
    return pd.Series(start, index=pd.bdate_range("2019-01-01", "2021-12-31"))


@pytest.fixture
def no_noise(monkeypatch):
    monkeypatch.setattr(op, "garch_levy", lambda year, innov="cgmy": (0.0, 1e-12, 0.0, 0.0, FLAT, "test"))


def test_flat_prices_give_no_change(no_noise):
    out = op.monthly_paths(prices(), MONTH, 3, np.random.default_rng(0))
    assert out.shape == (3, 1, 12)
    assert np.abs(out).max() < 1e-12


def test_month_zero_is_the_actual_monthly_mean(no_noise):
    p = prices()
    jan = (p.index >= "2020-01-01") & (p.index <= "2020-01-31")
    p[jan] = np.linspace(90, 110, jan.sum())  # rising through the origin month, closing at 110
    p[p.index > "2020-01-31"] = 110.0
    out = op.monthly_paths(p, MONTH, 1, np.random.default_rng(0))
    # February's mean is the last close; against January's mean that is a rise the bootstrap can't see
    assert out[0, 0, 0] == pytest.approx(np.log(110 / p[jan].mean()))
    assert np.abs(out[0, 0, 1:]).max() < 1e-12


def test_scenario_premium_reaches_the_monthly_means(no_noise):
    out = op.monthly_paths(prices(), MONTH, 1, np.random.default_rng(0), lost=op.LOST_2026)
    days = pd.bdate_range("2020-02-01", "2021-01-31")
    prem = op.premium(op.LOST_2026, len(days))
    last = days.month == 1  # month 12 after the origin is January 2021
    assert out[0, 0].sum() == pytest.approx(np.log(np.exp(prem[last]).mean()))


def test_premium_matches_the_event_study():
    e = op.premium(op.LOST_2026, 250)
    assert e[op.D_PEAK - 1] == pytest.approx(np.log(1.67))   # peak: +67%
    assert e[op.D_LATE - 1] == pytest.approx(np.log(1.222))  # 120 trading days: +22.2%
    assert e[-1] == pytest.approx(np.log(1.222))             # flat after the event study ends
    assert np.all(op.premium(0.0, 250) == 0)


def test_the_jump_widens_the_band_through_garch(monkeypatch):
    gauss = SimpleNamespace(table=lf.Gauss().table)
    monkeypatch.setattr(op, "garch_levy", lambda year, innov="cgmy": (0.0, 2e-6, 0.08, 0.9, gauss, "test"))
    calm = op.monthly_paths(prices(), MONTH, 2000, np.random.default_rng(1))
    shock = op.monthly_paths(prices(), MONTH, 2000, np.random.default_rng(1), lost=op.LOST_2026)
    assert shock[:, 0, 1].std() > 2 * calm[:, 0, 1].std()


@pytest.mark.parametrize("inn", [lf.Student(5.0), lf.Levy(1.0, 1.2, 0.9, np.zeros(lf.K), np.zeros(lf.K))])
def test_innovations_have_unit_variance(inn):
    cdf, x = inn.table()
    z = np.interp(np.random.default_rng(0).random(400_000), cdf, x)
    assert z.var() == pytest.approx(1.0, rel=0.03)
    assert abs(z.mean()) < 0.01
