"""experiments/household.py: mortgage arithmetic, real pay and work-minutes, squeezes, the HCI table
parser, and the real-pay scenarios.

Synthetic data only, except the last test, which checks the cached ONS workbook against the rates its
bulletin quotes (skipped when the file is not downloaded).
"""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("openpyxl")
import household as hh  # noqa: E402


def test_mortgage_payment_matches_the_textbook_value():
    assert float(hh.monthly_payment(100_000, 6.0, 30)) == pytest.approx(599.55, abs=0.01)
    assert float(hh.monthly_payment(120_000, 0.0, 10)) == pytest.approx(1000.0)


def test_real_pay_and_work_minutes():
    idx = pd.date_range("2018-01-01", "2021-12-01", freq="MS")
    t = np.arange(len(idx))
    panel = pd.DataFrame({"us_cpi": 100 * 1.002 ** t, "us_pay": 20 * 1.003 ** t,
                          "us_p_petrol": np.full(len(idx), 3.0), "us_p_electricity": np.full(len(idx), 0.15)}, index=idx)
    m = hh.measures(panel)
    assert m["us_real_pay"][idx.year == 2019].mean() == pytest.approx(100.0)
    assert m["us_minutes_petrol"].iloc[0] == pytest.approx(60 * 3.0 / 20)
    assert m["us_minutes_electricity"].iloc[0] == pytest.approx(60 * 100 * 0.15 / 20)  # per 100 kWh
    growth = 100 * np.log(1.003 ** 12 / 1.002 ** 12)
    assert m["us_real_pay_growth"].dropna().iloc[0] == pytest.approx(growth)


def test_quarterly_pay_uses_quarter_months_and_quarter_average_prices():
    idx = pd.date_range("2018-01-01", "2020-12-01", freq="MS")
    pay = pd.Series(np.nan, index=idx)
    pay[idx.month % 3 == 0] = 100.0
    panel = pd.DataFrame({"ea_cpi": np.linspace(100, 110, len(idx)), "ea_pay": pay.ffill(limit=2)}, index=idx)
    real = hh.measures(panel)["ea_real_pay"].dropna()
    assert set(real.index.month) == {3, 6, 9, 12}
    assert real.is_monotonic_decreasing  # flat pay, rising prices


def test_squeezes_find_depth_length_and_recovery():
    idx = pd.date_range("2010-01-01", periods=40, freq="MS")
    x = np.r_[np.linspace(100, 104, 10), np.linspace(103, 96, 12), np.linspace(97, 105, 18)]
    out = hh.squeezes(pd.Series(x, index=idx))
    assert len(out) == 1
    s = out[0]
    assert s["peak"] == idx[9] and s["trough"] == idx[21]
    assert s["depth_pct"] == pytest.approx(100 * (96 / 104 - 1))
    assert s["recovered"] is not None and s["recovered"] > s["trough"]
    short = pd.Series(np.r_[100, 99, 98, 101], index=idx[:4])  # 2 months down: too short to count
    assert hh.squeezes(short) == []
    open_ = pd.Series(np.r_[np.linspace(100, 105, 5), np.linspace(104, 95, 10)], index=idx[:15])
    assert hh.squeezes(open_)[0]["recovered"] is None


def test_hci_sheet_parser(tmp_path):
    rows = [["Household Costs Indices, test table", None, None, None], [None] * 4, [None] * 4,
            ["Description:", "Decile 1\n0\nAll items", "Decile 1\n04.5\nElectricity, gas and other fuels", "Decile 10\n0\nAll items"],
            ["Jan-2005", 73.4, "[x]", 80.0], ["Feb-2005", 73.7, 50.0, 80.5], ["Jun-2026 [p]", 148.2, 160.0, 150.0]]
    path = tmp_path / "hci.xlsx"
    pd.DataFrame(rows).to_excel(path, sheet_name="Table 4", header=False, index=False)
    df = hh._hci_sheet(path, "Table 4", monthly=True)
    assert len(df) == 8  # the [x] cell is dropped
    one = df[(df["group"] == "Decile 1") & (df["code"] == "04.5")]
    assert one["category"].iloc[0] == "Electricity, gas and other fuels" and one["value"].tolist() == [50.0, 160.0]
    assert df["period"].max() == pd.Timestamp("2026-06-01")  # the [p] (provisional) flag is read past


def test_real_pay_scenarios(tmp_path):
    idx = pd.date_range("2024-01-01", "2026-12-01", freq="MS")
    pay = pd.Series(1000 * np.exp(0.03 * np.arange(len(idx)) / 12), index=idx)  # 3% a year
    panel = pd.DataFrame({"uk_cpi": 100.0, "uk_pay": pay}, index=idx)
    csv = tmp_path / "sc.csv"
    pd.DataFrame([{"series": "uk_cpi", "flow_drop_points": 82.0, "months_ahead": 6, "mean": 2.0, "q05": 1.0,
                   "q50": 2.0, "q95": 3.5, "actual": 2.5, "origin": "2026-02"}]).to_csv(csv, index=False)
    sc = hh.scenarios(panel, csv)
    r = sc.iloc[0]
    assert r["pay_assumed"] == pytest.approx(1.5, abs=1e-3)  # half a year at 3% a year
    assert r["real_pay_q50"] == pytest.approx(1.5 - 2.0, abs=1e-3)
    assert r["real_pay_q05"] == pytest.approx(1.5 - 3.5, abs=1e-3) and r["real_pay_q95"] == pytest.approx(1.5 - 1.0, abs=1e-3)
    assert r["real_pay_actual"] == pytest.approx(1.5 - 2.5, abs=1e-3)


def test_group_scenarios_weight_items_by_spending_shares():
    # one group spending 20% on food, 10% on energy, 5% on motor fuel, 5% on mortgage interest (held flat), 65% on the rest
    w = pd.DataFrame([(2026, "G", c, "", v) for c, v in (("01", 200), ("04", 150), ("04.5", 100), ("07", 100), ("07.2.2", 50),
                                                         ("04.2a", 50), ("12", 550))],  # divisions 01+04+07+12 = 1000
                     columns=["period", "group", "code", "category", "value"])
    items = {"uk_bread": 0.02, "uk_meat": 0.02, "uk_dairy": 0.01, "uk_oils_fats": 0.0, "uk_fruit": 0.01, "uk_vegetables": 0.01,
             "uk_sugar": 0.01, "uk_electricity": 0.02, "uk_gas": 0.02, "uk_fuel": 0.03, "uk_restaurants": 0.1, "uk_rest": 0.7}
    change = {k: 10.0 if k in ("uk_electricity", "uk_gas") else 20.0 if k == "uk_fuel" else 0.0 for k in items}
    fans = pd.DataFrame([{"origin": "2026-02", "scenario": "s", "series": k, "region": "uk", "months_ahead": 6, "weight": v,
                          "q05": change[k], "q50": change[k], "q95": change[k]} for k, v in items.items()])
    g = hh.group_scenarios(w, fans).iloc[0]
    assert g["energy_part"] == pytest.approx(0.10 * 10.0)  # energy share x its change, over a whole basket of 1
    assert g["motor_fuel_part"] == pytest.approx(0.05 * 20.0)
    assert g["cost_q50"] == pytest.approx(1.0 + 1.0)  # food and rest unchanged; mortgage interest held flat


@pytest.mark.skipif(not (hh.RAW / hh.HCI_FILE).exists(), reason="ONS HCI workbook not downloaded")
def test_hci_workbook_reproduces_the_bulletin():
    idx, wts, _ = hh.hci()
    latest = hh.hci_series(idx, "All Households").index.max()
    for group, rate in hh.HCI_BULLETIN.items():
        assert hh.hci_series(idx, group, measure="rate_12m")[latest] == pytest.approx(rate, abs=0.051), group
    w = wts[(wts["group"] == "Decile 1") & (wts["period"] == wts["period"].max())]
    assert 900 < w[w["code"].str.fullmatch(r"\d\d")]["value"].sum() < 1100  # divisions add up to about 1000 per mille
