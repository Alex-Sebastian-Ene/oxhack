# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""Household cost of living over time: what people pay, what they earn, and the gap between them.

US, UK and euro area, monthly from 2000. Every row of the outputs names its source, series code and
fetch date. Nothing is synthetic, except the fixed shopping basket of the work-time table, which is
our own choice of quantities and is labelled as such.

    prices   CPI/HICP headline and the essentials: food, household energy (electricity, gas), motor
             fuel, rent or housing
    money    US average prices people pay (BLS, US city average): a gallon of petrol, a kWh, a therm
             of gas, eggs, milk, bread, beef, chicken, coffee, bananas
    pay      US average hourly earnings of production and nonsupervisory employees; UK average
             weekly earnings (total pay); euro-area wages and salaries (labour cost index, quarterly)
    housing  mortgage rates (US 30-year; UK 2- and 5-year fixed at 75% LTV, and the revert-to rate),
             US median house price
    buffers  US real disposable income per head and saving rate; consumer confidence (US, euro area)

Measures (notes/household-measures.csv):
    real pay           pay deflated by CPI, as an index (2019 = 100) and its 12-month change
    essentials vs pay  each essential's price in units of pay (2019 = 100): above 100, it takes
                       more work to buy than in 2019
    work-minutes       minutes of work at average US hourly pay for each everyday good
    mortgage           monthly payment per 100,000 borrowed (US 30-year; UK 2-year fixed over 25
                       years) as a share of monthly pay; US payment on the median house
    squeezes           runs of falling real pay: depth, length and recovery
    Hormuz scenarios   real pay over the year after Feb 2026 under the chain's scenarios
                       (notes/chain-scenarios-3m.csv), against what happened

    uv run experiments/household.py fetch     # download and cache every series (data/raw/macro/)
    uv run experiments/household.py report    # notes/household-*.csv and notes/household-costs.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import macro_data as md

ROOT = Path(__file__).resolve().parent.parent
NOTES, RAW = ROOT / "notes", md.RAW
START = "1999-01-01"  # one year before the tables start, so 2000 has a 12-month change
FIRST_YEAR = 2000
BASE_YEAR = 2019  # indices = 100 on the 2019 average, the last year before the pandemic and the 2021-23 surge
# ONS Household Costs Indices for UK household groups, April to June 2026 edition (released 2026-08-28;
# official statistics in development): indices by income decile, tenure, retirement and children
HCI_URL = ("https://www.ons.gov.uk/file?uri=/economy/inflationandpriceindices/datasets/"
           "householdcostsindicesforukhouseholdgroupsreferencetables/apriltojune2026/"
           "householdcostsindicesforukhouseholdgroupsaprtojun2026.xlsx")
HCI_FILE = "ons_hci_household_groups_2026q2.xlsx"
HCI_RELEASE = "ONS, Household Costs Indices for UK household groups: April to June 2026 (released 2026-08-28)"
HCI_INDEX = {"income decile": "Table 4", "tenure": "Table 9", "retirement": "Table 14", "children": "Table 19",
             "all": "Table 24"}
HCI_RATES = {"income decile": "Table 3", "tenure": "Table 8", "retirement": "Table 13", "children": "Table 18",
             "all": "Table 23"}  # the official 12-month rates (from unrounded indices)
# categories written to notes/household-groups.csv (the workbook has 25; `report` reads them all)
HCI_KEY_CODES = {"0": "All items", "01": "Food and non-alcoholic beverages", "04": "Housing, water, electricity, gas and "
                 "other fuels", "04.1a": "Private rentals", "04.1b": "Social and other rentals", "04.2a": "Mortgage interest "
                 "payments", "04.5": "Electricity, gas and other fuels", "07": "Transport", "07.2.2": "Motor fuels",
                 "11": "Restaurants and hotels", "12.6.9": "Interest on debt"}
HCI_WEIGHTS = {"income decile": "Table 5", "tenure": "Table 10", "retirement": "Table 15", "children": "Table 20",
               "all": "Table 25"}
# HM Land Registry UK House Price Index: average price, all property types, United Kingdom
UKHPI = ("https://landregistry.data.gov.uk/app/ukhpi/download/new.csv?from=1999-01-01&location="
         "http%3A%2F%2Flandregistry.data.gov.uk%2Fid%2Fregion%2Funited-kingdom&thm%5B%5D=property_type&in%5B%5D=avg")
ONS_PATH = {"mm23": "/economy/inflationandpriceindices/timeseries/{}/mm23",
            "lms": "/employmentandlabourmarket/peopleinwork/earningsandworkinghours/timeseries/{}/lms"}
BOE = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/1999"
       "&Dateto=now&SeriesCodes={}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")


@dataclass(frozen=True)
class Series:
    key: str
    region: str  # us | uk | ea
    kind: str  # cpi | item | price | pay | rate | house | income | saving | mood | debt
    source: str  # fred | ons | boe | eurostat
    code: str
    unit: str
    label: str
    title: str = ""  # ONS: words the official title must contain, so a wrong series code fails loudly
    freq: str = "M"  # M, Q or A (Q and A are carried forward to the months they cover)


REGISTRY = [
    # --- United States (BLS via FRED, seasonally adjusted CPI) ---
    Series("us_cpi", "us", "cpi", "fred", "CPIAUCSL", "index", "CPI, all items"),
    Series("us_food", "us", "item", "fred", "CUSR0000SAF11", "index", "Food at home"),
    Series("us_energy_home", "us", "item", "fred", "CUSR0000SAH21", "index", "Household energy"),
    Series("us_electricity", "us", "item", "fred", "CUSR0000SEHF01", "index", "Electricity"),
    Series("us_gas", "us", "item", "fred", "CUSR0000SEHF02", "index", "Utility (piped) gas"),
    Series("us_motor_fuel", "us", "item", "fred", "CUSR0000SETB01", "index", "Gasoline (all types)"),
    Series("us_rent", "us", "item", "fred", "CUSR0000SEHA", "index", "Rent of primary residence"),
    Series("us_shelter", "us", "item", "fred", "CUSR0000SAH1", "index", "Shelter"),
    Series("us_p_petrol", "us", "price", "fred", "APU000074714", "$ per gallon", "Gasoline, unleaded regular"),
    Series("us_p_electricity", "us", "price", "fred", "APU000072610", "$ per kWh", "Electricity"),
    Series("us_p_gas", "us", "price", "fred", "APU000072620", "$ per therm", "Utility (piped) gas"),
    Series("us_p_eggs", "us", "price", "fred", "APU0000708111", "$ per dozen", "Eggs, grade A, large"),
    Series("us_p_milk", "us", "price", "fred", "APU0000709112", "$ per gallon", "Milk, fresh, whole, fortified"),
    Series("us_p_bread", "us", "price", "fred", "APU0000702111", "$ per lb", "Bread, white, pan"),
    Series("us_p_beef", "us", "price", "fred", "APU0000703112", "$ per lb", "Ground beef, 100% beef"),
    Series("us_p_chicken", "us", "price", "fred", "APU0000706111", "$ per lb", "Chicken, fresh, whole"),
    Series("us_p_coffee", "us", "price", "fred", "APU0000717311", "$ per lb", "Coffee, 100%, ground roast"),
    Series("us_p_bananas", "us", "price", "fred", "APU0000711211", "$ per lb", "Bananas"),
    Series("us_pay", "us", "pay", "fred", "AHETPI", "$ per hour",
           "Average hourly earnings, production and nonsupervisory employees"),
    Series("us_pay_all", "us", "pay", "fred", "CES0500000003", "$ per hour", "Average hourly earnings, all employees"),
    Series("us_income", "us", "income", "fred", "A229RX0", "chained 2017 $ per person",
           "Real disposable personal income per head"),
    Series("us_median_income", "us", "income", "fred", "MEHOINUSA646N", "$ per year",
           "Median household income (annual, current $)", freq="A"),
    Series("us_saving", "us", "saving", "fred", "PSAVERT", "% of disposable income", "Personal saving rate"),
    Series("us_debt_service", "us", "debt", "fred", "TDSP", "% of disposable income",
           "Household debt service payments", freq="Q"),
    Series("us_mortgage", "us", "rate", "fred", "MORTGAGE30US", "% a year", "30-year fixed mortgage rate (Freddie Mac)"),
    Series("us_house", "us", "house", "fred", "MSPUS", "$", "Median sales price of houses sold", freq="Q"),
    Series("us_mood", "us", "mood", "fred", "UMCSENT", "index (1966 Q1 = 100)", "University of Michigan consumer sentiment"),
    # --- United Kingdom (ONS, CPI not seasonally adjusted; Bank of England) ---
    Series("uk_cpi", "uk", "cpi", "ons", "d7bt/mm23", "index", "CPI, all items", "ALL ITEMS"),
    Series("uk_cpih", "uk", "cpi", "ons", "l522/mm23", "index", "CPIH, all items (CPI plus owner occupiers' housing)", "CPIH INDEX 00"),
    Series("uk_food", "uk", "item", "ons", "d7c8/mm23", "index", "Food", "01.1 : FOOD"),
    Series("uk_energy_home", "uk", "item", "ons", "d7ch/mm23", "index", "Electricity, gas and other fuels", "ELECTRICITY, GAS AND OTHER FUELS"),
    Series("uk_electricity", "uk", "item", "ons", "d7dt/mm23", "index", "Electricity", "04.5.1 : ELECTRICITY"),
    Series("uk_gas", "uk", "item", "ons", "d7du/mm23", "index", "Gas", "04.5.2 : GAS"),
    Series("uk_motor_fuel", "uk", "item", "ons", "d7ec/mm23", "index", "Fuels and lubricants", "FUELS & LUBRICANTS"),
    Series("uk_housing", "uk", "item", "ons", "d7bx/mm23", "index", "Housing, water and fuels", "HOUSING, WATER AND FUELS"),
    Series("uk_pay", "uk", "pay", "ons", "kab9/lms", "£ per week", "Average weekly earnings, whole economy, total pay", "Total Pay"),
    Series("uk_mortgage_2y", "uk", "rate", "boe", "IUMBV34", "% a year", "2-year fixed mortgage, 75% LTV (quoted)"),
    Series("uk_mortgage_5y", "uk", "rate", "boe", "IUMBV42", "% a year", "5-year fixed mortgage, 75% LTV (quoted)"),
    Series("uk_mortgage_svr", "uk", "rate", "boe", "IUMTLMV", "% a year", "Revert-to-rate mortgage (quoted)"),
    Series("uk_house", "uk", "house", "landregistry", "ukhpi", "£", "Average house price, all property types (UK HPI)"),
    # --- Euro area (Eurostat HICP via FRED; Eurostat) ---
    Series("ea_cpi", "ea", "cpi", "fred", "CP0000EZ19M086NEST", "index", "HICP, all items"),
    Series("ea_food", "ea", "item", "fred", "CP0110EZ19M086NEST", "index", "Food"),
    Series("ea_energy_home", "ea", "item", "fred", "CP0450EZ19M086NEST", "index", "Electricity, gas and other fuels"),
    Series("ea_electricity", "ea", "item", "fred", "CP0451EZ19M086NEST", "index", "Electricity"),
    Series("ea_gas", "ea", "item", "fred", "CP0452EZ19M086NEST", "index", "Gas"),
    Series("ea_motor_fuel", "ea", "item", "fred", "CP0722EZ19M086NEST", "index", "Fuels and lubricants"),
    Series("ea_rent", "ea", "item", "fred", "CP0410EZ19M086NEST", "index", "Actual rentals for housing"),
    Series("ea_pay", "ea", "pay", "eurostat",
           "lc_lci_r2_q?geo=EA20&nace_r2=B-S&lcstruct=D11&unit=I20&s_adj=SCA", "index (2020 = 100)",
           "Labour cost index, wages and salaries (industry, construction, services)", freq="Q"),
    # EA21: the euro area with Bulgaria (joined 2026-01), back-cast by Eurostat; EA20 stops at 2025-12
    Series("ea_mood", "ea", "mood", "eurostat", "ei_bsco_m?geo=EA21&indic=BS-CSMCI&s_adj=SA&unit=BAL",
           "balance (%)", "Consumer confidence indicator (euro area, 21 countries)"),
]
# minutes of work per unit of each good; electricity and gas per 100 kWh and 10 therms, to read like a bill
MINUTE_UNITS = {"us_p_electricity": (100, "100 kWh"), "us_p_gas": (10, "10 therms")}
# A fixed weekly shop (our own choice of quantities, labelled as such) priced with the BLS averages
BASKET = {"us_p_milk": 1.0, "us_p_eggs": 1.0, "us_p_bread": 2.0, "us_p_beef": 1.0, "us_p_chicken": 2.0,
          "us_p_coffee": 0.5, "us_p_bananas": 2.0}
# 12-month HCI rates to June 2026 quoted in the ONS bulletin (read 2026-10-25), to check the parsing
HCI_BULLETIN = {"All Households": 2.8, "Decile 2": 2.7, "Decile 9": 2.8, "Private renter": 3.0,
                "Mortgagor and other owner occupier": 2.8, "Outright owner occupier": 2.6,
                "Social and other renter": 2.7, "Non-Retired": 2.9, "Retired": 2.5, "With Children": 2.8,
                "Without Children": 2.8}
EPISODES = (("2008 oil spike and crash", "2007-07", "2009-12"), ("2021-23 energy and inflation surge", "2021-01", "2023-12"),
            ("2026 Hormuz closure", "2026-02", "2026-09"))


# --- fetching (cached under data/raw/macro/) --------------------------------------------------

def _get(url: str, path: Path, tries: int = 6) -> Path:
    """Download once to path; retry politely when rate-limited (the ONS answers 429 to bursts)."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=md.UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                path.write_bytes(resp.read())
            return path
        except urllib.error.HTTPError as err:
            if err.code != 429 or k == tries - 1:
                raise
            time.sleep(15 * (k + 1))
    return path


def fetch(s: Series) -> tuple[pd.Series, Path, str]:
    """(monthly series, cache file, official title or '') for one registry entry."""
    if s.source == "fred":
        path = md.RAW / f"fred_{s.code}.csv"
        x = md.fetch_fred(s.code)  # monthly mean of the observations (FRED's own caching via macro_data)
        return x, path, ""
    if s.source == "ons":
        cdid, ds = s.code.split("/")
        path = _get(md.ONS.format(ONS_PATH[ds].format(cdid)), RAW / f"ons_{cdid}_{ds}.csv")
        text = path.read_text(encoding="utf-8-sig")
        title = text.splitlines()[0].split('","')[-1].strip('"')
        vals = {}
        for line in text.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) == 2 and len(parts[0]) == 8 and parts[0][:4].isdigit() and parts[0][5:] in md.MONTHS:
                vals[pd.Timestamp(int(parts[0][:4]), md.MONTHS[parts[0][5:]], 1)] = float(parts[1])
        return pd.Series(vals).sort_index(), path, title
    if s.source == "boe":
        path = _get(BOE.format(s.code), RAW / f"boe_{s.code}.csv")
        df = pd.read_csv(path)
        idx = pd.to_datetime(df.iloc[:, 0], format="%d %b %Y").dt.to_period("M").dt.to_timestamp()
        return pd.Series(df.iloc[:, 1].astype(float).values, index=idx).sort_index(), path, ""
    if s.source == "eurostat":
        dataset, params = s.code.split("?", 1)
        since = "2000-Q1" if s.freq == "Q" else "2000-01"
        key = hashlib.sha1(s.code.encode()).hexdigest()[:10]
        path = _get(md.EUROSTAT.format(dataset, params + f"&sinceTimePeriod={since}"), RAW / f"eurostat_{dataset}_{key}.json")
        j = json.loads(path.read_text(encoding="utf-8"))
        times = list(j["dimension"]["time"]["category"]["index"])
        vals = {}
        for k, v in j["value"].items():
            t = times[int(k)]
            if "-Q" in t:  # a quarter's value is dated to its last month
                y, q = t.split("-Q")
                vals[pd.Timestamp(int(y), 3 * int(q), 1)] = v
            else:
                vals[pd.Timestamp(t + "-01")] = v
        return pd.Series(vals).sort_index(), path, j.get("label", "")
    if s.source == "landregistry":
        path = _get(UKHPI, RAW / "landregistry_ukhpi_uk.csv")
        df = pd.read_csv(path)
        idx = pd.to_datetime(df["Period"].astype(str) + "-01")
        return pd.Series(df["Average price All property types"].astype(float).values, index=idx).sort_index(), path, ""
    raise ValueError(s.source)


# --- the ONS Household Costs Indices (UK household groups) -----------------------------------

def _hci_sheet(path: Path, sheet: str, monthly: bool) -> pd.DataFrame:
    """One HCI table as tidy rows: (period, group, code, category, value). '[x]' (not available) is dropped."""
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    hdr = next(i for i in range(10) if str(df.iloc[i, 0]).strip() == "Description:")
    labels = [str(v).split("\n") for v in df.iloc[hdr, 1:].tolist()]
    rows = []
    for _, r in df.iloc[hdr + 1:].iterrows():
        lab = str(r.iloc[0]).strip().split()[0] if pd.notna(r.iloc[0]) else ""
        try:
            period = pd.to_datetime(lab, format="%b-%Y") if monthly else int(lab[:4])
        except (ValueError, TypeError):
            continue
        for (group, code, cat), v in zip(labels, r.iloc[1:].tolist()):
            try:
                rows.append((period, group.strip(), code.strip(), cat.strip(), float(v)))
            except (TypeError, ValueError):
                continue
    return pd.DataFrame(rows, columns=["period", "group", "code", "category", "value"])


def hci() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """(indices, weights, fetched): HCI indices (2015 = 100, measure "index") and official 12-month rates (%,
    measure "rate_12m") monthly from 2005-06, and spending weights (parts per thousand) yearly, for every household
    group, with the group type as a column."""
    path = _get(HCI_URL, RAW / HCI_FILE)
    idx = pd.concat([_hci_sheet(path, t, True).assign(group_type=g, measure="index") for g, t in HCI_INDEX.items()]
                    + [_hci_sheet(path, t, True).assign(group_type=g, measure="rate_12m") for g, t in HCI_RATES.items()])
    wts = pd.concat([_hci_sheet(path, t, False).assign(group_type=g) for g, t in HCI_WEIGHTS.items()])
    return idx, wts, fetched_on(path)


def hci_series(idx: pd.DataFrame, group: str, code: str = "0", measure: str = "index") -> pd.Series:
    x = idx[(idx["group"] == group) & (idx["code"] == code) & (idx["measure"] == measure)].set_index("period")["value"].sort_index()
    return x[~x.index.duplicated()]


def pct_change(x: pd.Series, a, b) -> float:
    """Simple % change from month a to month b (the ONS convention for HCI rates)."""
    try:
        return 100 * (x.loc[pd.Timestamp(b)] / x.loc[pd.Timestamp(a)] - 1)
    except KeyError:
        return np.nan


def fetched_on(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


def load(refresh: bool = False) -> tuple[pd.DataFrame, dict, list[str]]:
    """Monthly panel [months, keys] from START, provenance per key, and the series left out (with why).
    Quarterly and annual series are carried forward over the months they cover; the provenance says so."""
    idx = pd.date_range(START, pd.Timestamp.today().normalize(), freq="MS")
    cols, prov, dropped = {}, {}, []
    for s in REGISTRY:
        try:
            x, path, title = fetch(s)
        except Exception as err:  # a dead source should not take the panel down
            dropped.append(f"`{s.key}` ({s.source} {s.code}): {str(err)[:100]}")
            continue
        if s.title and s.title.lower() not in title.lower():
            dropped.append(f"`{s.key}` ({s.code}): official title '{title}' does not contain '{s.title}'")
            continue
        x = x[~x.index.duplicated()].reindex(idx)
        if s.freq in ("Q", "A"):
            x = x.ffill(limit=2 if s.freq == "Q" else 11)
        cols[s.key] = x
        prov[s.key] = {"source": s.source, "code": s.code, "unit": s.unit, "label": s.label, "region": s.region,
                       "kind": s.kind, "freq": s.freq, "fetched": fetched_on(path), "title": title,
                       "first": f"{x.first_valid_index():%Y-%m}" if x.notna().any() else "",
                       "last": f"{x.last_valid_index():%Y-%m}" if x.notna().any() else ""}
    panel = pd.DataFrame(cols, index=idx)
    return panel.loc[:panel.dropna(how="all").index.max()], prov, dropped


# --- measures ---------------------------------------------------------------------------------

def rebase(x: pd.Series, year: int = BASE_YEAR) -> pd.Series:
    """Index = 100 on the year's average."""
    return 100 * x / x[x.index.year == year].mean()


def yoy(x: pd.Series, periods: int = 12) -> pd.Series:
    """12-month change in % (log)."""
    return 100 * np.log(x / x.shift(periods))


def monthly_payment(principal: float, rate_pct, years: int):
    """Level monthly repayment of an amortising loan (rate_pct: % a year, compounded monthly)."""
    r = np.asarray(rate_pct, float) / 1200
    n = 12 * years
    with np.errstate(divide="ignore", invalid="ignore"):
        pay = np.where(r > 0, principal * r / (1 - (1 + r) ** -n), principal / n)
    return pay


def squeezes(real: pd.Series, min_months: int = 6) -> list[dict]:
    """Runs of falling real pay: from a peak (the highest real pay so far) to the trough before it is
    regained. Kept if the fall from peak lasts at least min_months. Reports depth, length and the
    month real pay was back at the peak (or None)."""
    x = real.dropna()
    out, peak_t, peak_v, trough_t, trough_v = [], x.index[0], x.iloc[0], None, None
    for t, v in x.items():
        if v >= peak_v:
            if trough_t is not None:
                months = (trough_t.year - peak_t.year) * 12 + trough_t.month - peak_t.month
                if months >= min_months:
                    out.append({"peak": peak_t, "trough": trough_t, "depth_pct": 100 * (trough_v / peak_v - 1),
                                "months_down": months, "recovered": t})
            peak_t, peak_v, trough_t, trough_v = t, v, None, None
        elif trough_v is None or v < trough_v:
            trough_t, trough_v = t, v
    if trough_t is not None:
        months = (trough_t.year - peak_t.year) * 12 + trough_t.month - peak_t.month
        if months >= min_months:
            out.append({"peak": peak_t, "trough": trough_t, "depth_pct": 100 * (trough_v / peak_v - 1),
                        "months_down": months, "recovered": None})
    return out


def measures(panel: pd.DataFrame) -> dict[str, pd.Series]:
    """Every derived monthly measure, by name (region_measure)."""
    m: dict[str, pd.Series] = {}
    for r in ("us", "uk", "ea"):
        cpi, pay = panel.get(f"{r}_cpi"), panel.get(f"{r}_pay")
        if cpi is None:
            continue
        m[f"{r}_inflation"] = yoy(cpi)
        for item in ("food", "energy_home", "electricity", "gas", "motor_fuel", "rent", "housing", "shelter"):
            if f"{r}_{item}" in panel:
                m[f"{r}_{item}_inflation"] = yoy(panel[f"{r}_{item}"])
        if pay is None:
            continue
        if r == "ea":  # quarterly pay: compare with the quarter's average HICP, at the quarter's last month
            q = pay.dropna()
            q = q[q.index.month % 3 == 0]
            hicp = cpi.rolling(3).mean().reindex(q.index)
            real = rebase(q / hicp)
            m["ea_real_pay"] = real
            m["ea_pay_growth"] = yoy(q, 4)
            m["ea_real_pay_growth"] = yoy(q / hicp, 4)
            for item in ("food", "energy_home", "motor_fuel", "rent"):
                if f"ea_{item}" in panel:
                    m[f"ea_{item}_vs_pay"] = rebase(panel[f"ea_{item}"].rolling(3).mean().reindex(q.index) / q)
            continue
        real = pay / cpi
        m[f"{r}_real_pay"] = rebase(real)
        m[f"{r}_pay_growth"] = yoy(pay)
        m[f"{r}_real_pay_growth"] = yoy(real)
        for item in ("food", "energy_home", "electricity", "gas", "motor_fuel", "rent", "housing"):
            if f"{r}_{item}" in panel:
                m[f"{r}_{item}_vs_pay"] = rebase(panel[f"{r}_{item}"] / pay)
    if "us_pay" in panel:  # minutes of work at average hourly pay
        for key in [s.key for s in REGISTRY if s.kind == "price" and s.key in panel]:
            m[f"us_minutes_{key[5:]}"] = 60 * MINUTE_UNITS.get(key, (1, ""))[0] * panel[key] / panel["us_pay"]
        if all(k in panel for k in BASKET):
            shop = sum(q * panel[k] for k, q in BASKET.items())
            m["us_basket_cost"] = shop
            m["us_minutes_basket"] = 60 * shop / panel["us_pay"]
    if "us_mortgage" in panel and "us_pay" in panel:
        pay_month = panel["us_pay"] * 40 * 52 / 12  # full-time month at average hourly pay
        m["us_payment_per_100k"] = pd.Series(monthly_payment(100_000, panel["us_mortgage"], 30), index=panel.index)
        m["us_payment_share_pay"] = 100 * m["us_payment_per_100k"] / pay_month
        if "us_house" in panel:
            pay80 = pd.Series(monthly_payment(1.0, panel["us_mortgage"], 30), index=panel.index) * 0.8 * panel["us_house"]
            m["us_median_house_payment"] = pay80
            m["us_median_house_hours"] = pay80 / panel["us_pay"]
            if "us_median_income" in panel:
                m["us_median_house_share_income"] = 100 * pay80 / (panel["us_median_income"] / 12)
    if "uk_mortgage_2y" in panel and "uk_pay" in panel:
        pay_month = panel["uk_pay"] * 52 / 12
        for key in ("uk_mortgage_2y", "uk_mortgage_5y", "uk_mortgage_svr"):
            if key in panel:
                p = pd.Series(monthly_payment(100_000, panel[key], 25), index=panel.index)
                m[f"{key.replace('mortgage', 'payment')}_per_100k"] = p
                m[f"{key.replace('mortgage', 'payment')}_share_pay"] = 100 * p / pay_month
        if "uk_house" in panel:  # 75% of the average house at the 2-year fixed rate, repaid over 25 years
            p = pd.Series(monthly_payment(1.0, panel["uk_mortgage_2y"], 25), index=panel.index) * 0.75 * panel["uk_house"]
            m["uk_avg_house_payment"] = p
            m["uk_avg_house_share_pay"] = 100 * p / pay_month
    return m


MEASURE_DOC = {
    "inflation": ("% (12-month log change)", "CPI/HICP all items, 12-month change"),
    "real_pay": (f"index ({BASE_YEAR} = 100)", "pay deflated by CPI/HICP"),
    "pay_growth": ("% (12-month log change)", "nominal pay, 12-month change"),
    "real_pay_growth": ("% (12-month log change)", "real pay, 12-month change"),
    "vs_pay": (f"index ({BASE_YEAR} = 100)", "the item's price index divided by pay: above 100, it takes more work than in "
               f"{BASE_YEAR} to buy"),
    "minutes": ("minutes", "minutes of work at average hourly pay (production and nonsupervisory) to buy one unit"),
    "basket_cost": ("$", "a fixed weekly shop priced at BLS average prices (quantities are our own choice: 1 gal milk, "
                    "1 dozen eggs, 2 lb bread, 1 lb ground beef, 2 lb chicken, 0.5 lb coffee, 2 lb bananas)"),
    "per_100k": ("money per month", "level monthly repayment per 100,000 borrowed (US: 30-year fixed; UK: 25-year term at "
                 "the quoted rate)"),
    "share_pay": ("% of monthly pay", "that repayment as a share of one full-time month of average pay (US: hourly pay x "
                  "40 x 52 / 12; UK: weekly pay x 52 / 12)"),
    "median_house_payment": ("$ per month", "repayment on 80% of the median house price at the 30-year rate"),
    "median_house_hours": ("hours of work per month", "that repayment in hours at average hourly pay"),
    "median_house_share_income": ("% of monthly median household income", "that repayment as a share of median household "
                                  "income / 12 (annual figure carried forward)"),
    "avg_house_payment": ("£ per month", "repayment on 75% of the UK HPI average house price at the quoted 2-year fixed "
                          "rate over 25 years"),
    "avg_house_share_pay": ("% of monthly pay", "that repayment as a share of one month of average weekly earnings "
                            "(x 52 / 12): one full-time earner"),
}


def describe(name: str) -> tuple[str, str]:
    for k in sorted(MEASURE_DOC, key=len, reverse=True):
        if name.endswith(k) or f"_{k}_" in name or name.split("_", 1)[1].startswith(k):
            return MEASURE_DOC[k]
    return "", ""


# --- the Hormuz scenarios ---------------------------------------------------------------------

def scenarios(panel: pd.DataFrame, path: Path = NOTES / "chain-scenarios-3m.csv") -> pd.DataFrame:
    """Real pay over the 12 months after the chain's origin under each flow scenario.

    CPI paths come from the knock-on chain's replay table (equal-weight ensemble fitted
    on data to 2026-01). Nominal pay is assumed to keep growing at its pace over the 12 months to the
    origin (known at the origin; pay responses to the shock are not modelled), so the real-pay band
    is the CPI band. 'actual' is what happened, where published."""
    if not path.exists():
        return pd.DataFrame()
    sc = pd.read_csv(path)
    origin = pd.Timestamp(sc["origin"].iloc[0] + "-01")
    rows = []
    for r in ("us", "uk", "ea"):
        cpi_key, pay_key = f"{r}_cpi", f"{r}_pay"
        if pay_key not in panel or cpi_key not in panel:
            continue
        pay = panel[pay_key].dropna()
        pay = pay[pay.index <= origin]
        step = 4 if r == "ea" else 12
        pace = 100 * np.log(pay.iloc[-1] / pay.iloc[-1 - step]) * (12 / (3 * step) if r == "ea" else 1)  # % a year
        for (lost, h), g in sc[sc["series"] == cpi_key].groupby(["flow_drop_points", "months_ahead"]):
            g = g.iloc[0]
            wage = pace * h / 12
            act_cpi = g["actual"]
            act_pay = np.nan
            later = panel[pay_key].dropna()
            t1 = origin + pd.DateOffset(months=int(h))
            if r != "ea" and t1 in later.index and origin in later.index:
                act_pay = 100 * np.log(later[t1] / later[origin])
            rows.append({"region": r, "flow_drop_points": lost, "months_ahead": h, "pay_assumed": round(wage, 3),
                         "cpi_q05": g["q05"], "cpi_q50": g["q50"], "cpi_q95": g["q95"],
                         "real_pay_q05": round(wage - g["q95"], 3), "real_pay_q50": round(wage - g["q50"], 3),
                         "real_pay_q95": round(wage - g["q05"], 3), "cpi_actual": act_cpi,
                         "real_pay_actual": round(act_pay - act_cpi, 3) if np.isfinite(act_pay) and np.isfinite(act_cpi) else np.nan,
                         "origin": f"{origin:%Y-%m}", "source": f"{path.name} (CPI) and {pay_key} (pay)"})
    return pd.DataFrame(rows)


# --- Hormuz scenarios by UK household group ------------------------------------------------------

# HCI spending categories -> basket items of the cost-of-living model (docs/cost-of-living.md,
# notes/cost-of-living-fans.csv). A category split over several items is split in proportion to their
# CPI weights there. Mortgage interest is not in that model and is held flat; everything else is its
# 'rest of the basket'.
GROUP_MAP = {"01": ("uk_bread", "uk_meat", "uk_dairy", "uk_oils_fats", "uk_fruit", "uk_vegetables", "uk_sugar"),
             "04.5": ("uk_electricity", "uk_gas"), "07.2.2": ("uk_fuel",), "11": ("uk_restaurants",)}
FLAT = ("04.2a",)  # mortgage interest payments


def group_scenarios(wts: pd.DataFrame, fans: pd.DataFrame, year: int | None = None) -> pd.DataFrame:
    """Each UK household group's cost change under each scenario of the item fans: sum over items of the
    group's spending share x the item's change since the origin (first-order: a weighted sum of item changes).
    Median from the items' medians. The band adds the items' 5% and 95% quantiles (as if all items moved
    together), so it is an upper bound on the band's width. Also the energy, motor fuel and food parts."""
    fans = fans[fans["region"] == "uk"]
    year = year or int(wts["period"].max())
    w_all = wts[wts["period"] == year]
    item_w = fans.drop_duplicates("series").set_index("series")["weight"]
    rows = []
    for group, w in w_all.groupby("group"):
        share = w.set_index("code")["value"] / 1000
        top = share[share.index.str.fullmatch(r"\d\d")].sum()  # the divisions add up to the whole basket
        alloc = {}
        for code, items in GROUP_MAP.items():
            s = share.get(code, 0.0)
            iw = item_w.reindex(list(items)).fillna(0)
            for it in items:
                alloc[it] = alloc.get(it, 0.0) + s * (iw[it] / iw.sum() if iw.sum() else 1 / len(items))
        flat = sum(share.get(c, 0.0) for c in FLAT)
        alloc["uk_rest"] = top - sum(alloc.values()) - flat
        for (scen, origin, h), g in fans.groupby(["scenario", "origin", "months_ahead"]):
            g = g.set_index("series")
            if not all(it in g.index for it in alloc):
                continue
            q = {c: sum(a * g.loc[it, c] for it, a in alloc.items()) / top for c in ("q05", "q50", "q95")}
            part = lambda items: sum(alloc.get(it, 0) * g.loc[it, "q50"] for it in items) / top  # noqa: E731
            rows.append({"group": group, "scenario": scen, "origin": origin, "months_ahead": h,
                         "cost_q50": round(q["q50"], 3), "cost_q05_bound": round(q["q05"], 3), "cost_q95_bound": round(q["q95"], 3),
                         "energy_part": round(part(GROUP_MAP["04.5"]), 3), "motor_fuel_part": round(part(GROUP_MAP["07.2.2"]), 3),
                         "food_part": round(part(GROUP_MAP["01"]), 3), "weights_year": year})
    return pd.DataFrame(rows)


# --- outputs ----------------------------------------------------------------------------------

def write_csvs(panel: pd.DataFrame, prov: dict, m: dict[str, pd.Series]) -> None:
    rows = []
    for key in panel:
        p = prov[key]
        for t, v in panel[key].dropna().items():
            rows.append((f"{t:%Y-%m}", p["region"], key, p["kind"], round(float(v), 6), p["unit"], p["label"],
                         p["source"], p["code"], p["freq"], p["fetched"]))
    pd.DataFrame(rows, columns=["month", "region", "series", "kind", "value", "unit", "label", "source", "code",
                                "frequency", "fetched"]).to_csv(NOTES / "household-panel.csv", index=False)
    rows = []
    for name, x in m.items():
        unit, definition = describe(name)
        for t, v in x.dropna().items():
            if np.isfinite(v):
                rows.append((f"{t:%Y-%m}", name.split("_")[0], name, round(float(v), 6), unit, definition))
    pd.DataFrame(rows, columns=["month", "region", "measure", "value", "unit", "definition"]).to_csv(
        NOTES / "household-measures.csv", index=False)


def annual(x: pd.Series) -> pd.Series:
    return x.groupby(x.index.year).mean()


def fmt(v, digits: int = 1, sign: bool = False) -> str:
    if v is None or not np.isfinite(v):
        return "–"
    return f"{v:+.{digits}f}" if sign else f"{v:.{digits}f}"


def report() -> None:
    panel, prov, dropped = load()
    m = measures(panel)
    write_csvs(panel, prov, m)
    sc = scenarios(panel)
    if len(sc):
        sc.to_csv(NOTES / "household-scenarios.csv", index=False)
    try:
        h_idx, h_wts, h_fetched = hci()
    except Exception as err:  # the ONS workbook is optional for the rest of the report
        h_idx, h_wts, h_fetched = None, None, ""
        dropped.append(f"ONS Household Costs Indices: {str(err)[:100]}")
    if h_idx is not None:
        keep = h_idx[h_idx["code"].isin(HCI_KEY_CODES)]
        wide = keep.pivot_table(index=["period", "group_type", "group", "code"], columns="measure", values="value").reset_index()
        wide.insert(0, "month", wide.pop("period").dt.strftime("%Y-%m"))
        wide.round(2).to_csv(NOTES / "household-groups.csv", index=False)
        h_wts.rename(columns={"period": "year", "value": "parts_per_thousand"})[
            ["year", "group_type", "group", "code", "category", "parts_per_thousand"]].to_csv(
            NOTES / "household-group-weights.csv", index=False)
    gen = datetime.now(UTC).date().isoformat()
    last = {r: max((prov[k]["last"] for k in prov if prov[k]["region"] == r and prov[k]["kind"] == "cpi"), default="")
            for r in ("us", "uk", "ea")}
    years = list(range(FIRST_YEAR, int(panel.index.max().year) + 1))
    regions = (("us", "US"), ("uk", "UK"), ("ea", "Euro area"))
    out = ["# Household cost of living over time: what people pay and what they earn", "",
           f"_Generated by `experiments/household.py report` on {gen}. US, UK and euro area, monthly from {FIRST_YEAR}. "
           "Sources: BLS via FRED, ONS, Bank of England, HM Land Registry, Eurostat (some via FRED); fetch dates per series "
           f"in `notes/household-panel.csv` and the table at the end. Latest CPI month: US {last['us']}, UK {last['uk']}, "
           f"euro area {last['ea']}. Nothing is synthetic except the fixed weekly shop of the work-time table, whose "
           "quantities are our own choice. Revised data (not real-time vintages)._", "",
           f"Index = 100 on the {BASE_YEAR} average. Changes are 12-month log changes in % unless marked. Real pay = pay ÷ "
           "CPI (US: hourly earnings of production and nonsupervisory workers ÷ CPI; UK: average weekly earnings ÷ CPI; "
           "euro area: the quarterly labour cost index of wages and salaries ÷ HICP).", ""]

    # 0. the main points, computed from the tables below
    pts = []
    for r, name in regions:
        if f"{r}_real_pay" not in m:
            continue
        rp = m[f"{r}_real_pay"].dropna()
        w = rp[(rp.index >= "2021-01-01") & (rp.index <= "2024-12-01")]
        pts.append(f"**{name}:** real pay hit its 2021-24 low of {w.min():.1f} ({BASE_YEAR} = 100) in {w.idxmin():%Y-%m} and is "
                   f"{rp.iloc[-1]:.1f} in {rp.index[-1]:%Y-%m}"
                   + (": still below its 2019 level." if rp.iloc[-1] < 100 else "."))
    if h_idx is not None:
        d1, d10 = hci_series(h_idx, "Decile 1"), hci_series(h_idx, "Decile 10")
        a, b = "2021-01-01", f"{d1.index.max():%Y-%m}-01"
        r1, r10 = hci_series(h_idx, "Decile 1", measure="rate_12m"), hci_series(h_idx, "Decile 10", measure="rate_12m")
        pts.append(f"**UK income groups:** household costs rose {pct_change(d1, a, b):.1f}% for the lowest-income tenth "
                   f"and {pct_change(d10, a, b):.1f}% for the highest from 2021-01 to {d1.index.max():%Y-%m} (ONS Household "
                   f"Costs Indices). The poorest were hit first: {r1.get(pd.Timestamp('2022-10-01'), np.nan):.1f}% against "
                   f"{r10.get(pd.Timestamp('2022-10-01'), np.nan):.1f}% in the year to 2022-10, as energy and food dominate "
                   "their budgets. The richest caught up as mortgage rates rose: "
                   f"{r1.get(pd.Timestamp('2024-06-01'), np.nan):.1f}% against {r10.get(pd.Timestamp('2024-06-01'), np.nan):.1f}% "
                   "in the year to 2024-06.")
    if "us_minutes_petrol" in m:
        x = m["us_minutes_petrol"].dropna()
        pts.append(f"**A gallon of US petrol** took {x[x.index.year == BASE_YEAR].mean():.1f} minutes of work in {BASE_YEAR}, "
                   f"{x[x.index.year == 2022].max():.1f} at the 2022 peak and {x.iloc[-1]:.1f} in {x.index[-1]:%Y-%m}.")
    if len(sc):
        g = sc[(sc["region"] == "uk") & (sc["months_ahead"] == 6)].set_index("flow_drop_points")
        if 82.0 in g.index:
            pts.append(f"**The 2026 Hormuz closure:** for the UK, the chain's 82-points-lost scenario gives real pay "
                       f"{g.loc[82.0, 'real_pay_q50']:+.1f}% after 6 months ({g.loc[82.0, 'real_pay_q05']:+.1f} to "
                       f"{g.loc[82.0, 'real_pay_q95']:+.1f}); it was {g.loc[82.0, 'real_pay_actual']:+.1f}%.")
    out += ["## Main points", ""] + [f"- {p}" for p in pts] + [""]

    # 1. real pay, year by year
    out += ["## Real pay: is pay keeping up with prices?", "",
            f"Average of each year (index, {BASE_YEAR} = 100). The latest year is the average to date. The US jump in 2020 "
            "is a composition effect: low-paid jobs were lost first, which raised average pay.", "",
            "| Year | US real pay | UK real pay | Euro-area real pay | US inflation | UK inflation | Euro-area inflation |",
            "|---|---|---|---|---|---|---|"]
    A = {k: annual(m[k]) for k in ("us_real_pay", "uk_real_pay", "ea_real_pay", "us_inflation", "uk_inflation",
                                    "ea_inflation") if k in m}
    for y in years:
        cells = [fmt(A[k].get(y, np.nan)) if k in A else "–" for k in ("us_real_pay", "uk_real_pay", "ea_real_pay")]
        cells += [fmt(A[k].get(y, np.nan), sign=True) if k in A else "–" for k in ("us_inflation", "uk_inflation", "ea_inflation")]
        out.append(f"| {y} | " + " | ".join(cells) + " |")

    # 2. squeezes
    out += ["", "## Squeezes: runs of falling real pay", "",
            "From a peak in real pay to the lowest point before the peak was regained (falls lasting 6 months or more). "
            "The US peak of 2020-04 is the composition effect above.", "",
            "| Region | Peak | Trough | Fall | Months falling | Back at the peak |", "|---|---|---|---|---|---|"]
    for r, name in regions:
        if f"{r}_real_pay" not in m:
            continue
        for s in squeezes(m[f"{r}_real_pay"][m[f"{r}_real_pay"].index.year >= FIRST_YEAR]):
            out.append(f"| {name} | {s['peak']:%Y-%m} | {s['trough']:%Y-%m} | {s['depth_pct']:+.1f}% | {s['months_down']} | "
                       f"{'not yet' if s['recovered'] is None else format(s['recovered'], '%Y-%m')} |")

    # 3. essentials against pay
    out += ["", "## Essentials in units of pay", "",
            f"Each essential's price ÷ pay, index ({BASE_YEAR} = 100): above 100, buying it takes more work than in "
            f"{BASE_YEAR}.", "",
            "| Region | Essential | 2000 | 2019 | 2022 peak | Latest | Latest month |", "|---|---|---|---|---|---|---|"]
    for r, name in regions:
        for item, label in (("food", "food"), ("energy_home", "household energy"), ("electricity", "electricity"),
                            ("gas", "gas"), ("motor_fuel", "motor fuel"), ("rent", "rent"), ("housing", "housing, water, fuels")):
            k = f"{r}_{item}_vs_pay"
            if k not in m:
                continue
            x = m[k].dropna()
            y22 = x[x.index.year == 2022]
            out.append(f"| {name} | {label} | {fmt(x[x.index.year == 2000].mean())} | {fmt(x[x.index.year == 2019].mean())} | "
                       f"{fmt(y22.max() if len(y22) else np.nan)} | {fmt(x.iloc[-1])} | {x.index[-1]:%Y-%m} |")

    # 4. UK household groups
    if h_idx is not None:
        groups = ["All Households", "Decile 1", "Decile 2", "Decile 5", "Decile 9", "Decile 10", "Private renter",
                  "Mortgagor and other owner occupier", "Outright owner occupier", "Social and other renter", "Retired",
                  "Non-Retired", "With Children", "Without Children"]
        latest = hci_series(h_idx, "All Households").index.max()
        dates = [pd.Timestamp(d) for d in ("2019-12-01", "2021-12-01", "2022-10-01", "2023-06-01", "2024-06-01", "2025-06-01")]
        dates.append(latest)
        cpi = panel["uk_cpi"].dropna() if "uk_cpi" in panel else pd.Series(dtype=float)
        out += ["", "## Who feels it: UK household groups", "",
                f"{HCI_RELEASE}; official statistics in development, file `data/raw/macro/{HCI_FILE}` fetched {h_fetched}. "
                "The Household Costs Indices (HCIs) weight each group's basket by the average household's spending in it "
                "('democratic' weights) and include mortgage interest and other owner-occupier costs, unlike the CPI. "
                "12-month change in % (simple, as the ONS reports it), all items. Tables: `notes/household-groups.csv` "
                "(index and official 12-month rate by month, group and key category) and `notes/household-group-weights.csv` "
                "(spending weights, all 25 categories).", "",
                "| Group | " + " | ".join(f"{d:%Y-%m}" for d in dates) + " | Rise 2021-01 to latest |", "|---|" + "---|" * (len(dates) + 1)]
        for g in groups:
            x, rate = hci_series(h_idx, g), hci_series(h_idx, g, measure="rate_12m")
            if x.empty:
                continue
            cells = [fmt(rate.get(d, np.nan), sign=True) for d in dates]
            out.append(f"| {g} | " + " | ".join(cells) + f" | {fmt(pct_change(x, '2021-01-01', latest), sign=True)} |")
        out.append("| CPI (for comparison) | " + " | ".join(fmt(pct_change(cpi, d - pd.DateOffset(years=1), d), sign=True)
                                                       for d in dates) + f" | {fmt(pct_change(cpi, '2021-01-01', latest), sign=True)} |")
        bad = []
        for g, rate in HCI_BULLETIN.items():
            got = hci_series(h_idx, g, measure="rate_12m").get(latest, np.nan)
            if not (np.isfinite(got) and abs(got - rate) < 0.051):
                bad.append(f"{g} {got:.2f} vs {rate}")
        out += ["", f"**Check against the ONS bulletin** (12-month rates to {latest:%Y-%m} quoted in the release): "
                + ("every group matches to 0.05 points." if not bad else "MISMATCH: " + "; ".join(bad) + ".")]
        cats = (("01", "food and drink"), ("04.5", "electricity, gas, fuels"), ("07.2.2", "motor fuels"),
                ("04.1a", "private rent"), ("04.1b", "social rent"), ("04.2a", "mortgage interest"))
        wy = int(h_wts["period"].max())
        out += ["", f"**Where the money goes** ({wy} weights, % of each group's spending):", "",
                "| Group | " + " | ".join(c[1] for c in cats) + " |", "|---|" + "---|" * len(cats)]
        for g in groups:
            w = h_wts[(h_wts["group"] == g) & (h_wts["period"] == wy)].set_index("code")["value"]
            if w.empty:
                continue
            out.append(f"| {g} | " + " | ".join(fmt(w.get(c, np.nan) / 10) for c, _ in cats) + " |")
        a = pd.Timestamp("2026-02-01")
        out += ["", f"**The 2026 energy and fuel shock by group** (approximate first-round cost: each group's {wy} spending share "
                f"× the change in its own category index from {a:%Y-%m} to {latest:%Y-%m}, in % of total spending). UK "
                "household energy follows the Ofgem price cap, reset each quarter: the April 2026 reset lowered it, and the "
                f"July reset that followed the closure is after the latest HCI month ({latest:%Y-%m}); the CPI shows it "
                "(table 'Three shocks').", "",
                "| Group | Electricity, gas, fuels | Motor fuels | Both | All-items change, same months |", "|---|---|---|---|---|"]
        for g in groups:
            w = h_wts[(h_wts["group"] == g) & (h_wts["period"] == wy)].set_index("code")["value"] / 1000
            if w.empty:
                continue
            e = w.get("04.5", np.nan) * pct_change(hci_series(h_idx, g, "04.5"), a, latest)
            f = w.get("07.2.2", np.nan) * pct_change(hci_series(h_idx, g, "07.2.2"), a, latest)
            out.append(f"| {g} | {fmt(e, 2, True)} | {fmt(f, 2, True)} | {fmt(e + f, 2, True)} | "
                       f"{fmt(pct_change(hci_series(h_idx, g), a, latest), 1, True)} |")

    # 4b. the Hormuz scenarios and the outlook, by UK household group
    fans_path = NOTES / "cost-of-living-fans.csv"
    if h_idx is not None and fans_path.exists():
        fans = pd.read_csv(fans_path)
        gs = group_scenarios(h_wts, fans)
        src = fans_path.relative_to(ROOT).as_posix()
        gs.assign(source=f"item fans: {src}; spending shares: {HCI_RELEASE}").to_csv(NOTES / "household-group-scenarios.csv", index=False)
        show = ["Decile 1", "Decile 2", "Decile 5", "Decile 9", "Decile 10", "Private renter", "Mortgagor and other owner occupier",
                "Outright owner occupier", "Social and other renter", "Retired", "With Children"]
        out += ["", "## A Hormuz closure by UK household group", "",
                f"Item price fans of the cost-of-living model (`{src}`: the Bayesian basket-item model, Lévy Brent paths, "
                "closures scaled to the 2026 one) weighted by each group's spending shares (HCI weights, "
                f"{int(h_wts['period'].max())}). Change in each group's costs since 2026-02, % (median; first-order "
                "weighted sum of item changes). Mortgage interest is held flat, as the price model has no rates. 'Extra' "
                "is the closure's cost above no closure.", "",
                "| Group | Energy share | Motor fuel share | 6 months, no closure | 6 months, 50% closure | 6 months, full closure | "
                "Extra from a full closure (6 m) | of which motor fuel | 12 months, full closure |",
                "|---|---|---|---|---|---|---|---|---|"]
        wy = int(h_wts["period"].max())
        for g in show:
            x = gs[(gs["group"] == g) & (gs["origin"] == "2026-02")].set_index(["scenario", "months_ahead"])
            if x.empty:
                continue
            w = h_wts[(h_wts["group"] == g) & (h_wts["period"] == wy)].set_index("code")["value"]
            c = lambda s, h: x.loc[(s, h), "cost_q50"] if (s, h) in x.index else np.nan  # noqa: E731
            extra = c("closure_100", 6) - c("none", 6)
            fuel = x.loc[("closure_100", 6), "motor_fuel_part"] - x.loc[("none", 6), "motor_fuel_part"] if ("none", 6) in x.index else np.nan
            out.append(f"| {g} | {fmt(w.get('04.5', np.nan) / 10)}% | {fmt(w.get('07.2.2', np.nan) / 10)}% | {fmt(c('none', 6), 2, True)} | "
                       f"{fmt(c('closure_50', 6), 2, True)} | {fmt(c('closure_100', 6), 2, True)} | {fmt(extra, 2, True)} | "
                       f"{fmt(fuel, 2, True)} | {fmt(c('closure_100', 12), 2, True)} |")
        ol = gs[gs["scenario"] == "outlook"]
        if len(ol):
            o0 = ol["origin"].iloc[0]
            out += ["", f"**The year ahead from {o0}** (a forecast: the item model's Brent paths from {o0}, no scenario; "
                    "median and the comonotone bound):", "", "| Group | 3 months | 6 months | 12 months |", "|---|---|---|---|"]
            for g in show:
                x = ol[ol["group"] == g].set_index("months_ahead")
                if x.empty:
                    continue
                cells = [f"{x.loc[h, 'cost_q50']:+.1f} ({x.loc[h, 'cost_q05_bound']:+.1f}..{x.loc[h, 'cost_q95_bound']:+.1f})" if h in x.index else "–"
                         for h in (3, 6, 12)]
                out.append(f"| {g} | " + " | ".join(cells) + " |")

    # 5. minutes of work
    minutes = [k for k in m if k.startswith("us_minutes_")]
    if minutes:
        out += ["", "## Minutes of work for everyday goods (US)", "",
                "At average hourly pay of production and nonsupervisory employees (FRED AHETPI), BLS US city average "
                "prices. The weekly shop is a fixed basket of our own choosing (see the measures CSV).", "",
                "| Good | 2000 | 2008 peak | 2019 | 2022 peak | Latest | Latest month |", "|---|---|---|---|---|---|---|"]
        for k in minutes:
            x = m[k].dropna()
            key = "us_p_" + k[11:]
            s = next((s for s in REGISTRY if s.key == key), None)
            label = f"{s.label} (per {MINUTE_UNITS[key][1] if key in MINUTE_UNITS else s.unit.split(' per ')[-1]})" if s else "Weekly shop"
            pk = lambda yy: x[x.index.year == yy].max() if (x.index.year == yy).any() else np.nan  # noqa: E731
            out.append(f"| {label} | {fmt(x[x.index.year == 2000].mean())} | {fmt(pk(2008))} | {fmt(x[x.index.year == 2019].mean())} | "
                       f"{fmt(pk(2022))} | {fmt(x.iloc[-1])} | {x.index[-1]:%Y-%m} |")

    # 6. housing
    out += ["", "## Mortgage costs against pay", "",
            "Monthly repayment as a share of one full-time month of average pay. Per 100,000: US 30-year fixed (Freddie "
            "Mac); UK quoted 2-year fixed (75% LTV) and revert-to rate over 25 years (Bank of England; methodology changed "
            "in 2008, applied back to 2005). Typical home: US, 80% of the median sales price at the 30-year rate, against "
            "median household income; UK, 75% of the UK HPI average price at the 2-year fixed rate, against one average "
            "weekly earner.", "",
            "| Year | US rate | US per 100k: share of pay | US median house: share of median income | UK 2-year rate | "
            "UK per 100k: share of pay | UK average house: share of one earner's pay |", "|---|---|---|---|---|---|---|"]
    keys = ("us_mortgage", "us_payment_share_pay", "us_median_house_share_income", "uk_mortgage_2y", "uk_payment_2y_share_pay",
            "uk_avg_house_share_pay")
    AA = {k: annual(m[k] if k in m else panel[k]) for k in keys if k in m or k in panel}
    for y in years:
        out.append(f"| {y} | " + " | ".join(fmt(AA[k].get(y, np.nan)) if k in AA else "–" for k in keys) + " |")

    # 7. episodes, over the months both pay and prices cover
    out += ["", "## Three shocks, side by side", "",
            "Change over each window in %, first to last month; pay and CPI over the months both cover (euro-area pay "
            "is quarterly).", "",
            "| Episode | Region | Window | CPI | Pay | Real pay | Household energy | Motor fuel | Food |", "|---|---|---|---|---|---|---|---|---|"]
    for title, a, b in EPISODES:
        for r, name in regions:
            def span(key, a=a, b=b):
                x = panel[key].dropna() if key in panel else pd.Series(dtype=float)
                if key.endswith("_pay") and r == "ea":
                    x = x[x.index.month % 3 == 0]
                return x[(x.index >= a) & (x.index <= pd.Timestamp(b))]

            def ch(x):
                return 100 * np.log(x.iloc[-1] / x.iloc[0]) if len(x) > 1 else np.nan
            pay = span(f"{r}_pay")
            cpi_x = span(f"{r}_cpi")
            if len(pay) > 1 and pay.index[0] > pd.Timestamp(a) + pd.DateOffset(months=3):
                pay = pd.Series(dtype=float)  # pay starts too late to cover the episode
            if len(pay) > 1:
                cpi_x = cpi_x[(cpi_x.index >= pay.index[0]) & (cpi_x.index <= pay.index[-1])]
            window = f"{pay.index[0]:%Y-%m}..{pay.index[-1]:%Y-%m}" if len(pay) > 1 else f"{a}..{b}"
            out.append(f"| {title} | {name} | {window} | {fmt(ch(cpi_x), sign=True)} | {fmt(ch(pay), sign=True)} | "
                       f"{fmt(ch(pay) - ch(cpi_x), sign=True)} | {fmt(ch(span(f'{r}_energy_home')), sign=True)} | "
                       f"{fmt(ch(span(f'{r}_motor_fuel')), sign=True)} | {fmt(ch(span(f'{r}_food')), sign=True)} |")

    # 8. buffers and mood
    out += ["", "## Buffers and mood", "", "| Year | US real disposable income per head ($, 2017 prices) | US saving rate (%) | "
            "US debt service (% of income) | US consumer sentiment | Euro-area consumer confidence |", "|---|---|---|---|---|---|"]
    BB = {k: annual(panel[k]) for k in ("us_income", "us_saving", "us_debt_service", "us_mood", "ea_mood") if k in panel}
    for y in years:
        out.append(f"| {y} | " + " | ".join(fmt(BB[k].get(y, np.nan), 0 if k == "us_income" else 1) if k in BB else "–"
                                           for k in ("us_income", "us_saving", "us_debt_service", "us_mood", "ea_mood")) + " |")

    # 9. Hormuz scenarios
    if len(sc):
        out += ["", "## The 2026 Hormuz closure: real pay under the chain's scenarios", "",
                f"From {sc['origin'].iloc[0]}: CPI from the knock-on chain's replay (`notes/chain-scenarios-3m.csv`: the "
                "3-member ensemble fitted on data to 2026-01, the flow premium of `notes/flow-premium.csv`), and nominal pay "
                "assumed to keep its pace of the 12 months before (pay's response to the shock is not modelled). Real pay "
                "change in % with the 90% band; 'actual' is what happened, where published (US and UK). Lost flow is in "
                "points of normal Hormuz tanker flow; 2026 lost about 82.", "",
                "| Region | Months ahead | Pay (assumed) | No closure | 25 lost | 50 lost | 82 lost (as in 2026) | 100 lost | Actual |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r, name in regions:
            g = sc[sc["region"] == r]
            for h in (3, 6, 12):
                gh = g[g["months_ahead"] == h].set_index("flow_drop_points")
                if gh.empty:
                    continue
                cell = lambda lost: (f"{gh.loc[lost, 'real_pay_q50']:+.1f} ({gh.loc[lost, 'real_pay_q05']:+.1f}..{gh.loc[lost, 'real_pay_q95']:+.1f})"  # noqa: E731
                                     if lost in gh.index else "–")
                act = gh["real_pay_actual"].iloc[0]
                out.append(f"| {name} | {h} | {gh['pay_assumed'].iloc[0]:+.1f} | {cell(0.0)} | {cell(25.0)} | {cell(50.0)} | "
                           f"{cell(82.0)} | {cell(100.0)} | {fmt(act, sign=True)} |")

    # 10. sources
    out += ["", "## Series and sources", "", "| Series | Region | What | Unit | Source | Code | Months | Fetched |",
            "|---|---|---|---|---|---|---|---|"]
    names = {"fred": "FRED", "ons": "ONS", "boe": "Bank of England", "eurostat": "Eurostat", "landregistry": "HM Land Registry"}
    for k, p in prov.items():
        out.append(f"| `{k}` | {p['region'].upper()} | {p['label']} | {p['unit']} | {names[p['source']]} | `{p['code']}` | "
                   f"{p['first']}..{p['last']} | {p['fetched']} |")
    if h_idx is not None:
        out.append(f"| `household-groups.csv` | UK | Household Costs Indices by group and category | index (2015 = 100) | "
                   f"ONS | `{HCI_FILE}` | 2005-01..{h_idx['period'].max():%Y-%m} | {h_fetched} |")
    if dropped:
        out += ["", "**Left out:** " + "; ".join(dropped) + "."]
    (NOTES / "household-costs.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'household-costs.md'}, household-panel.csv, household-measures.csv"
          + (", household-scenarios.csv" if len(sc) else "") + (", household-groups.csv" if h_idx is not None else ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("fetch", "report"))
    a = p.parse_args()
    if a.cmd == "fetch":
        panel, prov, dropped = load()
        print(f"{panel.shape[1]} series, {panel.index.min():%Y-%m}..{panel.index.max():%Y-%m}")
        for k, v in prov.items():
            print(f"  {k:22s} {v['first']}..{v['last']}  {v['source']} {v['code']}")
        for d in dropped:
            print("  DROPPED", d)
        return
    report()


if __name__ == "__main__":
    main()
