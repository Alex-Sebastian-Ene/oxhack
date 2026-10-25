"""experiments/reserves.py: the 2026 release path, the policies, the run-out day and the factor on the curve (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

import reserves as rv

TRANCHES = pd.DataFrame({"start": pd.to_datetime(["2026-03-14", "2026-05-01"]),
                         "end": pd.to_datetime(["2026-04-12", "2026-05-10"]), "volume_mb": [60.0, 20.0]})


def test_release_2026_spreads_each_tranche_over_its_window():
    r = rv.release_2026(120, TRANCHES)
    assert r[:10].sum() == 0 and r[10] == pytest.approx(2.0) and r[39] == pytest.approx(2.0) and r[40] == 0
    assert r.sum() == pytest.approx(80.0)
    assert rv.release_2026(30, TRANCHES).sum() == pytest.approx(40.0)  # a window cut by the horizon keeps its rate


def test_calendar_days_skip_weekends():
    cal = rv.calendar_days(10, pd.Timestamp("2026-03-04"))  # a Wednesday
    assert list(cal[:5]) == [1, 2, 5, 6, 7]


def test_policy_2026_leaves_the_curve_as_it_is():
    r26 = rv.release_2026(400, TRANCHES)
    for lost in (10, 50, 82, 100):
        sc = rv.scenario(lost, "2026", 262, stock=1e6, rate=5.0, r26=r26)
        assert np.allclose(sc["factor"], 1.0)


def test_no_release_raises_the_premium_while_2026_released():
    r26 = rv.release_2026(400, TRANCHES)
    sc = rv.scenario(82, "none", 262, stock=1e6, rate=5.0, r26=r26)
    on = sc["release"] == 0
    expect = rv.LOST_2026 / rv.net_points(rv.LOST_2026, r26[sc["cal"]])
    assert np.allclose(sc["factor"], expect) and (sc["factor"] >= 1).all()
    assert sc["factor"][sc["cal"] == 20][0] == pytest.approx(82 / (82 - 10))  # 2 mb/d = 10 points of 20 mb/d
    assert on.all() and sc["runout"] is None


def test_max_release_stops_when_the_stock_runs_out():
    r26 = np.zeros(400)
    sc = rv.scenario(50, "max", 262, stock=40.0, rate=4.0, r26=r26)  # 10 mb/d lost, 4 released, 10 days of stock
    assert sc["runout"] == 10 and sc["total_mb"] == pytest.approx(40.0)
    assert sc["release_cal"][9] == pytest.approx(4.0) and sc["release_cal"][10] == 0
    assert np.allclose(sc["factor"][sc["cal"] < 10], 30 / 50) and np.allclose(sc["factor"][sc["cal"] >= 10], 1.0)


def test_max_rate_holds_two_months_then_falls_to_nothing_by_six():
    rel = rv.release_path(100, "max", 250, stock=1e6, rate=25.0, r26=np.zeros(250))  # 20 mb/d lost
    assert np.allclose(rel[:rv.MAX_FULL + 1], 20.0)  # capped at the lost barrels while the rate is 25
    assert rel[121] == pytest.approx(25 * (rv.MAX_END - 121) / (rv.MAX_END - rv.MAX_FULL))
    assert np.all(rel[rv.MAX_END:] == 0) and rv.ends(rel) == rv.MAX_END
    assert rv.ends(np.ones(10)) is None and rv.ends(np.zeros(10)) is None


def test_release_never_exceeds_the_lost_barrels():
    rel = rv.release_path(10, "max", 30, stock=1e6, rate=8.0, r26=np.zeros(30))  # 2 mb/d lost
    assert np.allclose(rel, 2.0) and np.allclose(rv.net_points(10, rel), 0.0)


def test_stocks_in_each_unit_and_days_to_replace():
    # 1,000 kb/d of oil use, 80% imported net
    assert rv.stocks_kb(100, "days of net imports", 1000, 0.8) == pytest.approx(80_000)
    assert rv.stocks_kb(100, "days of demand", 1000, 0.8) == pytest.approx(100_000)
    assert rv.stocks_kb(1.5, "million barrels", 1000, 0.8) == pytest.approx(1_500)
    assert rv.stocks_kb(28, "days (official claim)", 1000, 0.8) is None
    assert rv.stocks_kb(100, "days of net imports", 1000, -0.5) == 0  # an exporter has no net imports
    # 80,000 kb of stocks, 400 kb/d via Hormuz, half of it lost: 80,000 / 200 = 400 days
    assert rv.days_to_replace(80_000, 400, 50) == pytest.approx(400)
    assert rv.days_to_replace(80_000, 400, 0) == np.inf and rv.days_to_replace(None, 400, 50) is None


def test_the_shipped_csvs_parse():
    tr, cv = rv.releases(), rv.cover()
    stock, rate = rv.buffer()
    assert stock > 0 and rate > 0 and tr["volume_mb"].sum() > 0 and len(cv)
