"""notes/trade-stats.json (experiments/trade_stats.py): every map country, every number sourced and dated."""

import json

import trade_stats as ts

DATA = json.loads(ts.OUT.read_text(encoding="utf-8"))


def test_every_map_country_is_there():
    assert set(DATA["countries"]) == set(ts.map_countries())


def test_every_number_has_its_source_indicator_year_and_date():
    codes = {k: code for k, code, _ in ts.INDICATORS}
    for iso, c in DATA["countries"].items():
        for k, v in c["stats"].items():
            assert v["indicator"] == codes[k] and v["source"] == "World Bank WDI", (iso, k)
            assert v["year"] >= int(DATA["generated"][:4]) - ts.MAX_AGE and len(v["collected"]) == 10, (iso, k)
        assert not set(c.get("too_old", {})) & set(c["stats"]), iso
        for flow, x in c["partners"].items():
            assert flow in ("exports", "imports") and x["source"] == "UN Comtrade" and len(x["collected"]) == 10, (iso, flow)
            assert 0 < len(x["top"]) <= ts.TOP and all(0 < t["share"] <= 1 for t in x["top"]), (iso, flow)
            assert [t["value"] for t in x["top"]] == sorted((t["value"] for t in x["top"]), reverse=True), (iso, flow)
            assert all(t["named"] or t["iso3"] is None for t in x["top"]), (iso, flow)  # no flag for "..., nes" areas
            assert 0 <= x["unnamed_share"] <= 1, (iso, flow)


def test_countries_without_figures_say_so():
    for c in DATA["countries"].values():
        assert ("note" in c) == (not c["stats"] and not c["partners"]), c["name"]


def test_shares_are_percentages_and_gdp_ratios_plausible():
    for c in DATA["countries"].values():
        st = c["stats"]
        for k in ("fuel_exp", "fuel_imp"):
            if k in st:
                assert 0 <= st[k]["value"] <= 100, (c["name"], k)
        for k in ("exp_gdp", "imp_gdp"):
            if k in st:
                assert 0 < st[k]["value"] < 400, (c["name"], k)
