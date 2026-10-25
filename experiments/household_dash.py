"""Build the cost-of-living dashboard's datasets (runs/dash/*.csv) from the household notes, and wrap
its page (experiments/household_dash.html) as runs/dash/page.json, the dashboard's files/index.html.

Every file is a cut of a committed notes/household-*.csv (no new numbers), so the sources and fetch
dates are those of notes/household-panel.csv; sources.csv lists them. Run after `household.py report`:

    uv run --no-project --with numpy --with pandas --with scipy --with openpyxl python experiments/household_dash.py
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "experiments")
import household as hh  # noqa: E402

OUT = "runs/dash/"
PUBLISHER = {"fred": "FRED, St. Louis Fed", "ons": "ONS", "boe": "Bank of England", "landregistry": "HM Land Registry",
             "eurostat": "Eurostat"}
os.makedirs(OUT, exist_ok=True)
REG = {"us": "US", "uk": "UK", "ea": "Euro area"}

me = pd.read_csv("notes/household-measures.csv")
me = me[me["month"] >= "2000-01"]


def long(names, label):
    d = me[me["measure"].isin(names)].copy()
    d["region"] = d["region"].map(REG)
    d[label] = d["measure"].str.split("_", n=1).str[1]
    return d


# 1. real pay (2019 = 100) and inflation (12-month %), long by region
rp = me[me["measure"].str.fullmatch(r"(us|uk|ea)_(real_pay|inflation|real_pay_growth|pay_growth)")].copy()
rp = rp.pivot_table(index=["month", "region"], columns=rp["measure"].str[3:], values="value").reset_index()
rp["region"] = rp["region"].map(REG)
rp.round(2).sort_values(["region", "month"]).to_csv(OUT + "real_pay.csv", index=False)

# 2. essentials in units of pay (2019 = 100)
items = {"food": "Food", "energy_home": "Household energy", "electricity": "Electricity", "gas": "Gas",
         "motor_fuel": "Motor fuel", "rent": "Rent", "housing": "Housing, water and fuels"}
ess = me[me["measure"].str.endswith("_vs_pay")].copy()
ess["item"] = ess["measure"].str[3:].str.replace("_vs_pay", "", regex=False).map(items)
ess["region"] = ess["region"].map(REG)
ess[["month", "region", "item", "value"]].round(2).to_csv(OUT + "essentials.csv", index=False)

# 3. US minutes of work for everyday items
goods = {"petrol": "Gallon of petrol", "electricity": "100 kWh of electricity", "gas": "10 therms of gas",
         "eggs": "Dozen eggs", "milk": "Gallon of milk", "bread": "Pound of white bread", "beef": "Pound of ground beef",
         "chicken": "Pound of chicken", "coffee": "Pound of coffee", "bananas": "Pound of bananas",
         "basket": "Fixed weekly shop (our choice of quantities)"}
mins = me[me["measure"].str.startswith("us_minutes_")].copy()
mins["item"] = mins["measure"].str.replace("us_minutes_", "", regex=False).map(goods)
mins[["month", "item", "value"]].rename(columns={"value": "minutes"}).round(2).to_csv(OUT + "minutes.csv", index=False)

# 4. mortgage burden: repayment per 100k as a share of pay, and a typical home as a share of income
mg_names = {"us_payment_share_pay": "US 30-year fixed, per $100k, share of pay",
            "uk_payment_2y_share_pay": "UK 2-year fixed, per £100k, share of pay",
            "uk_payment_5y_share_pay": "UK 5-year fixed, per £100k, share of pay",
            "uk_payment_svr_share_pay": "UK revert-to rate, per £100k, share of pay",
            "us_median_house_share_income": "US median home (80% loan), share of median household income",
            "uk_avg_house_share_pay": "UK average home (75% loan), share of one average earner's pay"}
mg = me[me["measure"].isin(mg_names)].copy()
mg["measure_label"] = mg["measure"].map(mg_names)
mg["region"] = mg["region"].map(REG)
mg[["month", "region", "measure", "measure_label", "value"]].round(2).to_csv(OUT + "mortgage.csv", index=False)

# 5. UK household groups: official 12-month HCI rates and indices, all items and key categories
g = pd.read_csv("notes/household-groups.csv", dtype={"code": str})
cats = {"0": "All items", "01": "Food and non-alcoholic beverages", "04.5": "Electricity, gas and other fuels",
        "07.2.2": "Motor fuels", "04.1a": "Private rentals", "04.1b": "Social and other rentals",
        "04.2a": "Mortgage interest payments"}
g = g[g["code"].isin(cats)].copy()
g["category"] = g["code"].map(cats)
g[["month", "group_type", "group", "category", "index", "rate_12m"]].to_csv(OUT + "uk_groups.csv", index=False)

# 6. UK spending shares by group, latest weights year
w = pd.read_csv("notes/household-group-weights.csv", dtype={"code": str})
wy = int(w["year"].max())
share_cats = {"01": "Food", "04.5": "Electricity, gas, fuels", "07.2.2": "Motor fuels", "04.1a": "Private rent",
              "04.1b": "Social rent", "04.2a": "Mortgage interest", "11": "Restaurants and hotels"}
w = w[(w["year"] == wy) & w["code"].isin(share_cats)].copy()
w["category"] = w["code"].map(share_cats)
w["share_pct"] = (w["parts_per_thousand"] / 10).round(2)
w[["year", "group_type", "group", "category", "share_pct"]].to_csv(OUT + "uk_shares.csv", index=False)

# 7. Hormuz: real pay under the chain's CPI scenarios, against what happened
s = pd.read_csv("notes/household-scenarios.csv")
s["region"] = s["region"].map(REG)
s.drop(columns=["source"]).to_csv(OUT + "hormuz_pay.csv", index=False)

# 8. Hormuz closures and the year ahead, by UK household group
gs = pd.read_csv("notes/household-group-scenarios.csv")
gs = gs[gs["scenario"] != "whatif"]
gs.drop(columns=["source"]).to_csv(OUT + "hormuz_groups.csv", index=False)

# 9. squeezes: runs of falling real pay lasting 6 months or more
rows = []
for r, name in REG.items():
    d = me[me["measure"] == f"{r}_real_pay"]
    x = pd.Series(d["value"].values, index=pd.to_datetime(d["month"] + "-01")).sort_index().dropna()
    for q in hh.squeezes(x):
        rows.append({"region": name, "peak": f"{q['peak']:%Y-%m}", "trough": f"{q['trough']:%Y-%m}",
                     "fall_pct": round(q["depth_pct"], 1), "months_falling": q["months_down"],
                     "back_at_peak": "not yet" if q["recovered"] is None else f"{q['recovered']:%Y-%m}"})
pd.DataFrame(rows).to_csv(OUT + "squeezes.csv", index=False)

# 10. sources and fetch dates: one row per series, plus the ONS workbook and the two model outputs
pan = pd.read_csv("notes/household-panel.csv")
src = pan.groupby("series").agg(region=("region", "first"), label=("label", "first"), publisher=("source", "first"),
                                code=("code", "first"), frequency=("frequency", "first"), first=("month", "min"),
                                last=("month", "max"), fetched=("fetched", "max")).reset_index()
src["region"] = src["region"].map(REG)
src["publisher"] = src["publisher"].map(PUBLISHER)
src["kind"] = "data"


def period(month: str, freq: str, end: bool) -> str:
    """The panel carries quarterly and annual values forward over the months they cover; name the period itself."""
    t = pd.Timestamp(month + "-01") - pd.DateOffset(months=(2 if freq == "Q" else 11 if freq == "A" else 0) if end else 0)
    return f"{t.year}-Q{(t.month - 1) // 3 + 1}" if freq == "Q" else str(t.year) if freq == "A" else month


src["first"] = [period(m, f, False) for m, f in zip(src["first"], src["frequency"])]
src["last"] = [period(m, f, True) for m, f in zip(src["last"], src["frequency"])]
_, _, hci_fetched = hh.hci()
chain = pd.read_csv("notes/chain-scenarios-3m.csv")
gw = pd.read_csv("notes/household-groups.csv")
extra = [{"series": "uk_hci", "region": "UK", "label": "Household Costs Indices by household group (indices, 12-month rates, "
          "spending weights; official statistics in development)", "publisher": "ONS", "code": hh.HCI_FILE,
          "frequency": "M", "first": gw["month"].min(), "last": gw["month"].max(), "fetched": hci_fetched, "kind": "data"},
         {"series": "chain_cpi_scenarios", "region": "US, UK, euro area", "label": "CPI fans under Hormuz flow scenarios "
          "from 2026-02 (knock-on chain, notes/chain-scenarios-3m.csv on seb/levy-chain)", "publisher": "Model output (ours)",
          "code": "chain-scenarios-3m.csv", "frequency": "M", "first": "2026-03", "last": "2027-02",
          "fetched": chain["generated"].max(), "kind": "model"},
         {"series": "basket_item_fans", "region": "UK", "label": "Item price fans under closures from 2026-02 and the outlook "
          "from 2026-09 (basket-item model, notes/cost-of-living-fans.csv; see docs/cost-of-living.md)",
          "publisher": "Model output (ours)", "code": "cost-of-living-fans.csv", "frequency": "M", "first": "2026-03",
          "last": "2027-09", "fetched": "2026-10-25", "kind": "model"}]  # the date the fans were committed
src = pd.concat([src, pd.DataFrame(extra)], ignore_index=True)
src[["series", "region", "label", "publisher", "code", "frequency", "first", "last", "fetched", "kind"]].to_csv(
    OUT + "sources.csv", index=False)

# the page, as the document the dashboard stores it in
page = Path("experiments/household_dash.html").read_text(encoding="utf-8")
Path(OUT + "page.json").write_text(json.dumps({"text": page}), encoding="utf-8")

for f in sorted(os.listdir(OUT)):
    with open(OUT + f, encoding="utf-8") as fh:
        print(f, os.path.getsize(OUT + f), sum(1 for _ in fh) - 1)
