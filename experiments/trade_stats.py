# /// script
# requires-python = ">=3.11"
# ///
"""Exports and imports for every country on the World map (notes/trade-stats.json), for the app's Trade tab.

  World Bank, World Development Indicators (api.worldbank.org/v2, no key): each country's latest year with a
  value, per indicator:
    NE.EXP.GNFS.CD, NE.IMP.GNFS.CD         exports, imports of goods and services, current US$
    NE.EXP.GNFS.ZS, NE.IMP.GNFS.ZS         the same as % of GDP
    TX.VAL.MRCH.CD.WT, TM.VAL.MRCH.CD.WT   merchandise (goods) exports, imports, current US$ (WTO's figures;
                                           the older .WD codes are no longer served)
    TX.VAL.FUEL.ZS.UN, TM.VAL.FUEL.ZS.UN   fuels' share of merchandise exports, imports, %
  UN Comtrade (public preview API, no key): the five largest partners for goods exports and imports, all
  commodities (HS TOTAL), in the latest year the country reported each flow.

Figures more than MAX_AGE years old (Nigeria's latest goods-and-services totals are from 1960) are left out;
their year is kept under "too_old" so the app can say so.

Countries come from the map itself (ui/globe/data/countries.js: Natural Earth 1:110m, keyed by iso3). Every
number carries its source, indicator, year and the date it was collected. Raw responses are cached in
data/raw/trade/ (git-ignored); the collection date is the day the cached file was fetched. Delete the
folder to fetch again.

    uv run experiments/trade_stats.py      # writes notes/trade-stats.json
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data" / "raw" / "trade", ROOT / "notes" / "trade-stats.json"
MAP = ROOT / "ui" / "globe" / "data" / "countries.js"
UA = {"User-Agent": "oxhack26-research (github.com/Alex-Sebastian-Ene/oxhack)"}

WDI = "https://api.worldbank.org/v2/country/all/indicator/{}?format=json&source=2&mrnev=1&per_page=1000"
INDICATORS = [  # key, WDI code, what it measures
    ("exp", "NE.EXP.GNFS.CD", "Exports of goods and services, current US$"),
    ("imp", "NE.IMP.GNFS.CD", "Imports of goods and services, current US$"),
    ("exp_gdp", "NE.EXP.GNFS.ZS", "Exports of goods and services, % of GDP"),
    ("imp_gdp", "NE.IMP.GNFS.ZS", "Imports of goods and services, % of GDP"),
    ("goods_exp", "TX.VAL.MRCH.CD.WT", "Merchandise exports, current US$"),
    ("goods_imp", "TM.VAL.MRCH.CD.WT", "Merchandise imports, current US$"),
    ("fuel_exp", "TX.VAL.FUEL.ZS.UN", "Fuel exports, % of merchandise exports"),
    ("fuel_imp", "TM.VAL.FUEL.ZS.UN", "Fuel imports, % of merchandise imports"),
]
WB_CODE = {"KOS": "XKX"}  # the map's code where the World Bank's differs
MAX_AGE = 10  # years: older "latest" figures describe another economy

CT = "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode={}&period={}&flowCode={}&partnerCode={}&cmdCode=TOTAL"
CT_REF = "https://comtradeapi.un.org/files/v1/app/reference/{}.json"
FLOWS = {"X": "exports", "M": "imports"}
# World, bunkers, free zones, special categories, areas not specified: not partners to rank
NOT_PARTNERS = {0, 837, 838, 839, 899}
TOP = 5

# Said in the app for map countries the sources don't cover
NOTES = {
    "TWN": "The World Bank and UN Comtrade publish no figures for Taiwan; its partners record trade with it as "
           "\"Other Asia, nes\".",
    "CYN": "Northern Cyprus has no figures of its own in the World Bank or UN Comtrade data.",
    "SOL": "Somaliland has no figures of its own in the World Bank or UN Comtrade data.",
    "ESH": "Western Sahara has no figures of its own in the World Bank or UN Comtrade data.",
    "ATA": "Antarctica has no economy to report.",
    "ATF": "The French Southern and Antarctic Lands have no figures of their own.",
}


def collected(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


class QuotaError(RuntimeError):
    """Comtrade's public preview is out of calls until its quota refills (about an hour)."""


def get_json(url: str, path: Path, ok=lambda d: True, tries: int = 6) -> tuple[object, str]:
    """The parsed response, cached at `path`, and the day it was fetched. Retries (with back-off) on errors
    and on answers `ok` rejects, such as Comtrade's rate-limit notes."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        for k in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as resp:
                    body = resp.read()
                if ok(json.loads(body)):
                    path.write_bytes(body)
                    break
                why = body[:200]
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    raise QuotaError(f"{url}: {e.read()[:200]!r}") from e
                why = e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                why = e
            if k == tries - 1:
                raise RuntimeError(f"{url}: {why}")
            time.sleep(2 ** (k + 1))
        time.sleep(1.2)  # Comtrade's public preview takes about one call a second
    return json.loads(path.read_text(encoding="utf-8")), collected(path)


def map_countries() -> dict[str, str]:
    """iso3 -> name for every country on the World map."""
    text = MAP.read_text(encoding="utf-8")
    geo = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return {f["properties"]["iso3"]: f["properties"]["name"] for f in geo["features"]}


def wdi(countries: dict[str, str]) -> tuple[dict, dict, dict]:
    """{iso3: {key: number with provenance}}, {iso3: {key: year}} for figures too old to show, and the
    indicators' metadata."""
    stats, old, meta = {iso: {} for iso in countries}, {iso: {} for iso in countries}, {}
    wb_to_map = {WB_CODE.get(iso, iso): iso for iso in countries}
    for key, code, what in INDICATORS:
        (head, rows), day = get_json(WDI.format(code), RAW / f"wdi_{code}.json", ok=lambda d: isinstance(d, list) and len(d) == 2)
        assert head["pages"] == 1, f"{code}: more than one page"
        meta[key] = {"code": code, "name": rows[0]["indicator"]["value"], "what": what, "source": "wdi",
                     "updated": head["lastupdated"], "collected": day,
                     "url": f"https://data.worldbank.org/indicator/{code}"}
        for r in rows:
            iso = wb_to_map.get(r["countryiso3code"])
            if iso and r["value"] is not None and int(r["date"]) < date.today().year - MAX_AGE:
                old[iso][key] = int(r["date"])
            elif iso and r["value"] is not None:
                stats[iso][key] = {"value": r["value"], "year": int(r["date"]), "indicator": code,
                                   "source": "World Bank WDI", "collected": day}
    return stats, old, meta


def comtrade(countries: dict[str, str]) -> tuple[dict, dict]:
    """{iso3: {"exports"|"imports": {year, total, top partners}}} for map countries that report to Comtrade.
    If the preview's quota runs out, the rest come from the cache only and meta["not_fetched"] lists the
    countries still missing; run again once the quota refills."""
    reporters, day_r = get_json(CT_REF.format("Reporters"), RAW / "comtrade_reporters.json")
    partners, _ = get_json(CT_REF.format("partnerAreas"), RAW / "comtrade_partners.json")
    code_of = {r["reporterCodeIsoAlpha3"]: r["reporterCode"] for r in reporters["results"]
               if not r["isGroup"] and not r.get("entryExpiredDate")}
    pname = {p["PartnerCode"]: p["text"] for p in partners["results"]}
    piso = {p["PartnerCode"]: p["PartnerCodeIsoAlpha3"].strip() for p in partners["results"]}
    is_total = lambda r: r.get("partner2Code", 0) == 0 and r.get("motCode", 0) == 0 and r.get("customsCode", "C00") == "C00"  # noqa: E731
    has_data = lambda d: isinstance(d, dict) and isinstance(d.get("data"), list) and not d.get("error")  # noqa: E731

    # each reporter's world totals by year, from one call per year and flow
    this_year = date.today().year
    totals, days = {}, set()
    for year in range(this_year - 1, this_year - 8, -1):
        for flow in FLOWS:
            d, day = get_json(CT.format("", year, flow, 0), RAW / f"comtrade_world_{flow}_{year}.json", ok=has_data)
            days.add(day)
            assert d["count"] < 500, f"{year} {flow}: the preview's 500-row cap was hit"
            for r in filter(is_total, d["data"]):
                totals.setdefault((r["reporterCode"], flow), {})[year] = r["primaryValue"]

    quota = {"out": None, "both": True}

    def fetch(url: str, path: Path) -> tuple[dict, str]:
        if quota["out"] and not path.exists():
            raise QuotaError(quota["out"])
        try:
            return get_json(url, path, ok=has_data)
        except QuotaError as e:
            quota["out"] = str(e)
            raise

    def partner_rows(iso: str, rep: int, latest: dict) -> dict:
        """{flow: (rows, day)}: one call for both flows when their latest years match, else one per flow."""
        each = {f: RAW / f"comtrade_{iso}_{f}_{y}.json" for f, y in latest.items()}
        both = RAW / f"comtrade_{iso}_XM_{latest.get('X')}.json"
        if len(latest) == 2 and latest["X"] == latest["M"] and not all(p.exists() for p in each.values()) and (quota["both"] or both.exists()):
            try:
                d, day = fetch(CT.format(rep, latest["X"], "X,M", ""), both)
            except QuotaError:
                raise
            except RuntimeError:  # the preview won't take both flows at once: one call per flow from now on
                quota["both"], d = False, None
            if d and d["count"] < 500:
                return {f: ([r for r in d["data"] if r["flowCode"] == f], day) for f in latest}
            both.unlink(missing_ok=True)  # over the preview's 500-row cap: one call per flow
        got = {}
        for f, y in latest.items():
            d, day = fetch(CT.format(rep, y, f, ""), each[f])
            assert d["count"] < 500, f"{iso} {f} {y}: the preview's 500-row cap was hit"
            got[f] = (d["data"], day)
        return got

    out, missing = {}, []
    for iso in countries:
        rep = code_of.get(iso)
        latest = {f: max(totals[(rep, f)]) for f in FLOWS if rep and totals.get((rep, f))}
        if not latest:
            continue
        try:
            got = partner_rows(iso, rep, latest)
        except QuotaError:
            missing.append(iso)
            continue
        for flow, (data, day) in got.items():
            word, year = FLOWS[flow], latest[flow]
            days.add(day)
            rows = [r for r in data if is_total(r) and r["partnerCode"] not in NOT_PARTNERS and r["primaryValue"]]
            rows.sort(key=lambda r: -r["primaryValue"])
            total = totals[(rep, flow)][year]
            top = []
            for r in rows[:TOP]:
                p = piso.get(r["partnerCode"], "")
                top.append({"iso3": p if re.fullmatch("[A-Z]{3}", p) else None, "on_map": p in countries,
                            "name": countries[p] if p in countries else pname.get(r["partnerCode"], str(r["partnerCode"])),
                            "value": r["primaryValue"], "share": round(r["primaryValue"] / total, 4)})
            out.setdefault(iso, {})[word] = {
                "year": year, "total": total, "partners_listed": len(rows), "top": top,
                "indicator": "HS TOTAL (all commodities), primary value: exports FOB, imports CIF",
                "source": "UN Comtrade", "reporter_code": rep, "collected": day}
    meta = {"name": "UN Comtrade", "url": "https://comtradeplus.un.org/", "api": CT.split("?")[0],
            "collected": " to ".join(sorted(days)[::max(len(days) - 1, 1)]) if days else day_r,
            "what": "Goods only, all commodities (HS TOTAL), as each country reports them; the five largest "
                    "partners by value. Partner shares are of the country's reported total with the world."}
    if missing:
        meta["not_fetched"] = missing
    return out, meta


def main() -> None:
    countries = map_countries()
    stats, old, ind = wdi(countries)
    partners, ct_meta = comtrade(countries)
    wdi_days = sorted({m["collected"] for m in ind.values()})
    out = {
        "generated": date.today().isoformat(),
        "script": "experiments/trade_stats.py",
        "countries_from": "ui/globe/data/countries.js: Natural Earth 1:110m admin-0 countries, keyed by iso3",
        "sources": {
            "wdi": {"name": "World Bank, World Development Indicators", "url": "https://databank.worldbank.org/source/world-development-indicators",
                    "api": WDI.split("/country")[0], "updated": max(m["updated"] for m in ind.values()),
                    "collected": " to ".join(wdi_days[::max(len(wdi_days) - 1, 1)]),
                    "what": "Each country's latest year with a value, per indicator; years differ by country."},
            "comtrade": ct_meta,
        },
        "indicators": ind,
        "countries": {},
    }
    for iso, name in sorted(countries.items()):
        c = {"name": name, "stats": stats[iso], "partners": partners.get(iso, {})}
        if old[iso]:
            c["too_old"] = old[iso]
        if not c["stats"] and not c["partners"]:
            c["note"] = NOTES.get(iso, f"The World Bank's latest trade figures for {name} are from {max(old[iso].values())}, too old to show."
                                  if old[iso] else f"No export or import figures for {name} in the World Bank or UN Comtrade data.")
        out["countries"][iso] = c
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    have = lambda k: sum(k in c["stats"] for c in out["countries"].values())  # noqa: E731
    print(f"wrote {OUT.relative_to(ROOT)}: {len(countries)} map countries")
    for key, code, _ in INDICATORS:
        years = [c["stats"][key]["year"] for c in out["countries"].values() if key in c["stats"]]
        print(f"  {code:18} {have(key):3} countries, years {min(years)} to {max(years)}, median {sorted(years)[len(years) // 2]}")
    for word in FLOWS.values():
        n = [c["partners"][word]["year"] for c in out["countries"].values() if word in c["partners"]]
        print(f"  Comtrade {word:8} {len(n):3} countries, years {min(n)} to {max(n)}")
    print("  no data:", ", ".join(c["name"] for c in out["countries"].values() if "note" in c) or "none")
    if ct_meta.get("not_fetched"):
        print(f"  Comtrade's quota ran out: no partners yet for {len(ct_meta['not_fetched'])} countries; run again in an hour")


if __name__ == "__main__":
    main()
