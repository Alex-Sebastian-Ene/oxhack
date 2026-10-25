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
    z = np.random.default_rng(0).standard_normal(1)  # the path's place in the band, drawn first
    prem = op.premium(op.LOST_2026, len(days), z)[0]
    last = days.month == 1  # month 12 after the origin is January 2021
    assert out[0, 0].sum() == pytest.approx(np.log(np.exp(prem[last]).mean()))


def test_premium_follows_the_curve_and_its_band():
    lo, mid, hi, _ = op.premium_curve()
    days = len(mid) + 10  # past the end of the curve
    e = op.premium(op.LOST_2026, days, np.array([0.0, op.Z90, -op.Z90]))
    assert e[0, :len(mid)] == pytest.approx(op.LOST_2026 * mid)  # the median path
    assert e[1, :len(mid)] == pytest.approx(op.LOST_2026 * hi)   # the band's edges at +-1.645
    assert e[2, :len(mid)] == pytest.approx(op.LOST_2026 * np.maximum(lo, 0))
    assert np.all(e[:, len(mid):] == e[:, [len(mid) - 1]])       # flat after the curve ends
    assert np.all(op.premium(0.0, days, np.array([1.0])) == 0)
    assert np.all(op.premium(op.LOST_2026, days, np.array([-10.0])) >= 0)  # never a negative premium


def test_a_lost_flow_path_takes_each_days_month():
    days = pd.bdate_range("2026-03-02", "2026-06-30")
    path = pd.Series([89.0, 84.0], index=pd.DatetimeIndex(["2026-03-01", "2026-04-01"]))
    lost = op.lost_on(path, days)
    assert set(lost[days.month == 3]) == {89.0} and set(lost[days.month == 4]) == {84.0}
    assert set(lost[days.month >= 5]) == {84.0}  # after the last month, the last month's loss holds
    assert op.lost_on(50.0, days).tolist() == [50.0] * len(days)
    z = np.array([0.0, 1.0])
    _, mid, _, _ = op.premium_curve()
    e = op.premium(lost, len(days), z)
    assert e[0] == pytest.approx(lost * mid[:len(days)])  # each day's loss times the curve
    held = op.premium(84.0, len(days), z)  # a held loss is the path of that one number
    assert np.array_equal(op.premium(np.full(len(days), 84.0), len(days), z), held)
    with pytest.raises(ValueError):
        op.premium(lost, len(days), z, "none")  # stock policies are fitted on a held loss


def test_iea_path_runs_from_march_2026():
    path = op.iea_lost_2026()
    assert path.index[0] == pd.Timestamp("2026-03-01") and path.is_monotonic_increasing is False
    assert path.iloc[0] == pytest.approx(100 * (1 - 2.27 / 20.66), abs=0.01)  # IEA: 2.27 mb/d against February's 20.66


def test_release_policy_scales_the_premium(monkeypatch):
    z = np.array([0.0, 1.0])
    base = op.premium(op.LOST_2026, 40, z)
    assert np.array_equal(op.premium(op.LOST_2026, 40, z, "2026"), base)  # the default is the fitted curve
    monkeypatch.setattr(op.rv, "factor", lambda lost, release, days: np.linspace(1.0, 2.0, days))
    assert op.premium(op.LOST_2026, 40, z, "none") == pytest.approx(base * np.linspace(1.0, 2.0, 40))
    assert np.all(op.premium(0.0, 40, z, "none") == 0)


def test_no_scenario_draws_nothing_extra():
    a = op.monthly_paths(prices(), MONTH, 50, np.random.default_rng(3))
    b = op.monthly_paths(prices(), MONTH, 50, np.random.default_rng(3), lost=0.0)
    assert np.array_equal(a, b)  # so the folds' levy mode is unchanged by the scenario code


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
