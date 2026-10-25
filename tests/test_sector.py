"""The sector runs: Eurostat JSON-stat decoding, the generated industry x country rows, the panel's
coverage rule, and experiments/sector_global.py's oil-free network and scaling.

Synthetic data only: no downloads. The sector_global tests need torch and numpyro (skipped otherwise).
"""

import numpy as np
import pandas as pd
import pytest

import macro_data as md

MONTHS = pd.date_range("1998-01-01", "2026-10-01", freq="MS")


def jsonstat(values: dict, geos=("DE", "FR"), naces=("B07", "C244"), times=("2020-01", "2020-02", "2020-03")) -> dict:
    """A Eurostat-shaped payload: dimension index as {code: position}, values keyed by flat position."""
    dims = {"freq": ["M"], "nace_r2": list(naces), "geo": list(geos), "time": list(times)}
    return {"id": list(dims), "size": [len(v) for v in dims.values()],
            # listed out of order, as nothing guarantees the order: positions are the values
            "dimension": {d: {"category": {"index": dict(reversed([(c, i) for i, c in enumerate(v)]))}}
                          for d, v in dims.items()},
            "value": {str(k): v for k, v in values.items()}}


def test_jsonstat_positions_are_row_major_over_the_dimensions():
    # size [1, 2, 2, 3]: position = ((nace * 2) + geo) * 3 + time
    pos = {(n, g, t): (n * 2 + g) * 3 + t for n in range(2) for g in range(2) for t in range(3)}
    values = {pos[(1, 0, 2)]: 105.0, pos[(0, 1, 0)]: 98.5}  # C244/DE/2020-03 and B07/FR/2020-01
    frame = md.jsonstat_frame(jsonstat(values))
    assert frame.loc["2020-03-01", ("DE", "C244")] == 105.0
    assert frame.loc["2020-01-01", ("FR", "B07")] == 98.5
    assert frame.notna().sum().sum() == 2


def test_sector_fetch_drops_zero_indices_and_unpublished_pairs(monkeypatch):
    x = pd.Series([0.0, 100.0, 101.0], index=pd.date_range("2020-01-01", periods=3, freq="MS"))
    frame = pd.DataFrame({("DE", "C241"): x, ("LT", "C241"): x * 0})
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["geo", "nace_r2"])
    monkeypatch.setattr(md, "_PANEL_FRAMES", {"price": frame})
    assert md.fetch_eurostat_panel("price:DE:C241").tolist() == [100.0, 101.0]
    for code in ("price:LT:C241", "price:FR:C241"):  # reported as all zeros; not in the data at all
        with pytest.raises(ValueError, match="not published"):
            md.fetch_eurostat_panel(code)


def test_sector_rows_cover_every_industry_and_country_once():
    rows = md.sector_series()
    keys = [s.key for s in rows]
    assert len(keys) == len(set(keys))
    assert {s.target for s in rows} == {"price", "output"}
    for nace, _, us_ppi, us_ip in md.SECTORS:
        for kind in ("price", "output"):
            assert all(f"{kind}_{g.lower()}_{nace.lower()}" in keys for g in md.COUNTRIES)
        assert (f"price_us_{nace.lower()}" in keys) == bool(us_ppi)
        assert (f"output_us_{nace.lower()}" in keys) == bool(us_ip)
    assert all(s.lag == 2 for s in rows if s.source == "eurostat_panel")
    assert all(s.geo and s.item for s in rows)


def test_goods_rows_cover_every_good_and_country_once():
    rows = md.goods_series()
    keys = [s.key for s in rows]
    assert len(keys) == len(set(keys))
    by = {(s.target, s.geo, s.item) for s in rows}
    for nace, _ in md.GOODS:
        for kind in ("price", "output"):
            assert all((kind, g, nace) in by for g in md.COUNTRIES)
    assert all(("price", "US", code) in by for code, _ in md.US_GOODS)
    assert all(("consumer", g, code) in by for code, _ in md.HOUSEHOLD for g in md.HOUSEHOLD_COUNTRIES)
    assert sum(s.target == "commodity" for s in rows) == len(md.WORLD)
    assert {s.block for s in rows} == set(md.GOODS_BLOCKS[1:])
    lags = {(s.block, s.target): s.lag for s in rows if s.source == "eurostat_panel"}
    assert lags == {("goods", "price"): 2, ("goods", "output"): 2, ("household", "consumer"): 1}


def test_every_registered_key_is_unique():
    keys = [s.key for s in md.registry(md.ALL_BLOCKS)]
    assert len(keys) == len(set(keys))


def test_world_bank_sheet_is_read_by_column_name(tmp_path, monkeypatch):
    head = [None, "Crude oil, Brent", "Urea ", "Beef **"]
    rows = [["World Bank Commodity Price Data (The Pink Sheet)", None, None, None], *[[None] * 4] * 3, head,
            [None, "($/bbl)", "($/mt)", "($/kg)"],
            ["2020M01", 64.0, 250.0, "…"], ["2020M02", 55.0, 260.5, 4.5], ["Notes", None, None, None]]
    pd.DataFrame(rows).to_excel(tmp_path / "worldbank_cmo_monthly.xlsx", sheet_name="Monthly Prices", header=False,
                                index=False)
    monkeypatch.setattr(md, "RAW", tmp_path)
    urea = md.fetch_worldbank("Urea")
    assert urea.tolist() == [250.0, 260.5] and urea.index[1] == pd.Timestamp("2020-02-01")
    assert md.fetch_worldbank("Beef **").tolist() == [4.5]  # "..." marks a missing month


def test_nation_rows_cover_every_measure_and_country_once():
    rows = md.nation_series()
    assert len({s.key for s in rows}) == len(rows) == len(md.NATION_MEASURES) * len(md.NATIONS)
    assert {s.target for s in rows} == {g for _, g, _ in md.NATION_MEASURES}
    assert all(s.block == "nations" and s.lag == 1 and s.geo in md.NATIONS for s in rows)


def test_inflation_database_splits_energy_from_its_housing_proxy_and_keeps_the_longest_source(tmp_path, monkeypatch):
    months = [200001 + 100 * (i // 12) + i % 12 for i in range(300)]  # 2000-01 .. 2024-12 as yyyymm
    def row(iso, note, n, value):
        return {"Country Code": iso, "Country": iso, "Note": note} | {m: (value if i < n else None) for i, m in enumerate(months)}
    energy = pd.DataFrame([row("AAA", "Energy price", 150, 100.0), row("AAA", "Energy price (estimated)", 280, 101.0),
                           row("AAA", "Housing, Water, Electricity, Gas & Other Fuel", 300, 102.0),
                           row("BBB", "Housing, Water, Electricity, Gas & Other Fuel", 300, 103.0)])
    headline = pd.DataFrame([row("AAA", "", 300, 104.0)])
    with pd.ExcelWriter(tmp_path / "worldbank_inflation.xlsx") as xl:
        energy.to_excel(xl, sheet_name="ecpi_m", index=False)
        headline.to_excel(xl, sheet_name="hcpi_m", index=False)
    monkeypatch.setattr(md, "RAW", tmp_path)
    monkeypatch.setattr(md, "_INFL_SHEETS", {})
    real = md.fetch_wb_inflation("ecpi_m:AAA")
    assert real.size == 280 and set(real) == {101.0}  # the longer of the two real energy rows
    assert set(md.fetch_wb_inflation("ecpi_m_housing:AAA")) == {102.0}
    assert set(md.fetch_wb_inflation("ecpi_m_housing:BBB")) == {103.0}
    with pytest.raises(ValueError, match="not published"):
        md.fetch_wb_inflation("ecpi_m:BBB")  # only the housing proxy: no energy row
    assert md.fetch_wb_inflation("hcpi_m:AAA").index[0] == pd.Timestamp("2000-01-01")


def test_market_and_oil_flow_rows():
    kinds = {k for k, _ in md.KINDS}
    world = [s for s in md.goods_series() if s.block == "world"]
    assert {s.item for s in world} <= kinds and {s.item for s in md.market_series()} <= kinds
    markets = md.market_series()
    assert len({s.key for s in markets}) == len(markets) == len(md.MARKETS)
    assert all(s.lag == 0 for s in markets if s.source == "fred" and s.code.startswith("D"))  # daily EIA spot prices
    flows = md.oilflow_series()
    assert len({s.key for s in flows}) == len(flows) == len(md.JODI_FLOWS) * len(md.JODI_COUNTRIES)
    assert {s.target for s in flows} == {"production", "imports", "exports", "refining", "demand"}
    assert all(len(s.geo) == 3 and s.lag == 2 for s in flows)


def test_fao_indices_are_read_by_column(tmp_path, monkeypatch):
    text = "\n".join(["FAO Food Price Index,,,", "2014-2016=100,,,", "Date,Food Price Index,Meat,Sugar", ",,,",
                      "1990-01,64.4,74.3,87.9", "1990-02,64.0,,85.0", ""])
    (tmp_path / "fao_food_price_indices.csv").write_text(text, encoding="utf-8")
    monkeypatch.setattr(md, "RAW", tmp_path)
    assert md.fetch_fao("Food Price Index").tolist() == [64.4, 64.0]
    assert md.fetch_fao("Meat").index.tolist() == [pd.Timestamp("1990-01-01")]


def test_jodi_flows_drop_zeros_and_give_each_country_its_oil_trade_position(monkeypatch):
    rows = []
    for month in pd.date_range("2015-01-01", "2024-12-01", freq="MS"):
        for area, crude_in, crude_out in (("JP", 3000.0, 0.0), ("SA", 0.0, 7000.0)):
            rows += [(area, month, "TOTCRUDE", "TOTIMPSB", crude_in), (area, month, "TOTCRUDE", "TOTEXPSB", crude_out),
                     (area, month, "TOTPRODS", "TOTIMPSB", 500.0), (area, month, "TOTPRODS", "TOTEXPSB", 400.0)]
    df = pd.DataFrame(rows, columns=["REF_AREA", "month", "ENERGY_PRODUCT", "FLOW_BREAKDOWN", "value"])
    monkeypatch.setattr(md, "_JODI", {"kbd": df})
    assert md.oil_trade_position() == {"JPN": "net importer", "SAU": "net exporter"}
    assert md.fetch_jodi("TOTCRUDE:TOTEXPSB:SA").size == 120
    with pytest.raises(ValueError, match="not published"):  # Japan exports no crude: all zeros
        md.fetch_jodi("TOTCRUDE:TOTEXPSB:JP")


def test_country_codes_map_to_iso3():
    classes = {"GRC": {"iso2": "GR"}, "GBR": {"iso2": "GB"}, "DEU": {"iso2": "DE"}}
    assert [md.iso3(g, classes) for g in ("EL", "UK", "DE", "DEU", "ZZ")] == ["GRC", "GBR", "DEU", "DEU", None]


def test_short_or_dead_sector_series_are_skipped(monkeypatch):
    rng = np.random.default_rng(0)
    price = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.05, len(MONTHS)))) * 50, index=MONTHS)
    data = {"brent": price, "long": price * 2, "short": price.loc["2020-01-01":], "dead": price.loc[:"2019-12-01"]}
    rows = [md.Series(f"price_xx_{k}", "toy", k, "sectors", "dlog", 2, "price", k) for k in ("long", "short", "dead")]
    monkeypatch.setattr(md, "SERIES", [md.Series("brent", "toy", "brent", "oil", "dlog", 0, name="toy price")])
    monkeypatch.setattr(md, "sector_series", lambda: rows)
    monkeypatch.setattr(md, "FETCH", {"toy": lambda code: data[code]})
    _, L, prov = md.build_panel(blocks=("oil", "sectors"))
    assert "price_xx_long" in L and "price_xx_short" not in L and "price_xx_dead" not in L
    skipped = {p["series"].key: p["error"] for p in prov if "error" in p}
    assert set(skipped) == {"price_xx_short", "price_xx_dead"}
    assert all(e.startswith("skipped") for e in skipped.values())


torch = pytest.importorskip("torch")
pytest.importorskip("numpyro")
import macro_global as mg  # noqa: E402
import sector_global as sg  # noqa: E402


def test_no_oil_network_ignores_the_oil_inputs():
    net = mg.Net(3, mg.OWN + 13 + 1, np.full(3, 0.05), linear=True).eval()
    with torch.no_grad():
        net.lin.normal_()
    x = torch.randn(5, mg.OWN + 14)
    before = x.clone()
    k = torch.tensor([0, 1, 2, 0, 1])
    shocked = x.clone()
    shocked[:, mg.OWN:] += 3.0  # every oil lag and the volatility state
    with torch.no_grad():
        a, b = sg.NoOil(net)(x, k), sg.NoOil(net)(shocked, k)
        assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])
        assert not torch.allclose(net(x, k)[0], net(shocked, k)[0])  # the plain network does see oil
        assert torch.equal(x, before)  # the caller's inputs are left alone


def test_small_ols_uses_only_the_last_change_and_brent_lags_0_to_2():
    rng = np.random.default_rng(0)
    n_in = mg.OWN + 14
    x = rng.normal(size=(600, n_in))
    k = np.repeat([0, 1], 300)
    y = 0.5 * x[:, 0] + 0.8 * x[:, mg.OWN + 2] + 0.9 * x[:, 5] + 0.01 * rng.normal(size=600)  # lag 6 is left out
    m = sg.SmallOLS(x, k, y, np.full(2, 0.05))
    W = m.ols.W.numpy()
    assert np.allclose(W[:, [0, mg.OWN + 2]], [[0.5, 0.8]] * 2, atol=0.1)
    assert np.all(W[:, 5] == 0) and np.all(W[:, mg.OWN + 3:-1] == 0)
    shifted = torch.as_tensor(x[:5], dtype=torch.float32)
    moved = shifted.clone()
    moved[:, 5] += 10.0
    assert torch.allclose(m(shifted, torch.zeros(5, dtype=torch.long))[0], m(moved, torch.zeros(5, dtype=torch.long))[0])


def test_series_without_training_months_are_left_unscaled():
    rng = np.random.default_rng(0)
    M = 80
    dM = rng.normal(size=(M, 3))
    dM[:60, 1] = np.nan  # starts after the training months
    dM[:, 2] = 0.0  # never moves
    s = sg.stats({"oil_m": rng.normal(size=M), "dM": dM}, 50)
    assert np.isfinite(s.ym).all() and np.isfinite(s.ys).all()
    assert (s.ym[1], s.ys[1]) == (0.0, 1.0) and s.ys[2] == 1.0
    assert s.ys[0] == pytest.approx(np.std(dM[13:51, 0]), rel=1e-6)
