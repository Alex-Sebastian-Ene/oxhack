"""The Households page (households.js): Seb's household cost-of-living data (OXH-8), cut down at build time from
notes/household-*.csv (experiments/household.py report) into window.HOUSEHOLDS. Real series carry their source,
code and fetch date from notes/household-panel.csv; the two scenario files are model output and are labelled so
on the page. Without the notes the build leaves the page out.
"""
import csv
import json
import pathlib

NOTES = pathlib.Path(__file__).resolve().parents[3] / "notes"
REGIONS = ("us", "uk", "ea")
# essentials against pay, per region: (item, label)
ITEMS = {"us": [("food", "Food"), ("energy_home", "Home energy"), ("motor_fuel", "Motor fuel"), ("rent", "Rent")],
         "uk": [("food", "Food"), ("energy_home", "Home energy"), ("motor_fuel", "Motor fuel"), ("housing", "Housing")],
         "ea": [("food", "Food"), ("energy_home", "Home energy"), ("motor_fuel", "Motor fuel"), ("rent", "Rent")]}
GROUP_SCEN = ("none", "closure_25", "closure_50", "closure_100", "outlook")
SHARES = {"01": "food", "04.5": "energy", "07.2.2": "fuel"}
HCI = "ONS, Household Costs Indices for UK household groups: April to June 2026 (released 2026-08-28)"


def _rows(name):
    return list(csv.DictReader(open(NOTES / name, encoding="utf-8")))


def data():
    if not all((NOTES / f).exists() for f in ("household-measures.csv", "household-groups.csv", "household-group-weights.csv",
                                             "household-scenarios.csv", "household-group-scenarios.csv", "household-panel.csv")):
        return None
    meas = {}
    for r in _rows("household-measures.csv"):
        meas.setdefault(r["measure"], []).append((r["month"], float(r["value"])))
    real_pay = {g: [[m, round(v, 2)] for m, v in meas[f"{g}_real_pay"] if m >= "2005-01"] for g in REGIONS}
    essentials = {}
    for g in REGIONS:
        rows = []
        for item, label in ITEMS[g]:
            s = meas.get(f"{g}_{item}_vs_pay") or []
            if not s:
                continue
            peak = max((p for p in s if p[0] >= "2019-01"), key=lambda p: p[1])
            rows.append({"item": item, "label": label, "month": s[-1][0], "value": round(s[-1][1], 1), "peak": round(peak[1], 1), "peak_month": peak[0]})
        essentials[g] = rows
    pet = meas["us_minutes_petrol"]
    y19 = [v for m, v in pet if m.startswith("2019")]
    peak = max((p for p in pet if p[0] >= "2019-01"), key=lambda p: p[1])
    petrol = {"y2019": round(sum(y19) / len(y19), 1), "peak": round(peak[1], 1), "peak_month": peak[0], "now": round(pet[-1][1], 1), "month": pet[-1][0]}
    # ONS Household Costs Indices, all items (code 0): official 12-month rate, and the change since December 2019
    groups = {}
    for r in _rows("household-groups.csv"):
        if r["code"] != "0":
            continue
        g = groups.setdefault(r["group"], {"type": r["group_type"], "group": r["group"]})
        if r["month"] == "2019-12":
            g["i2019"] = float(r["index"])
        g["month"], g["index"] = r["month"], float(r["index"])
        if r["rate_12m"]:
            g["rate"] = float(r["rate_12m"])
    for g in groups.values():
        g["since2019"] = round(100 * (g["index"] / g["i2019"] - 1), 1) if g.get("i2019") else None
        g.pop("i2019", None)
    wyear = max(int(r["year"]) for r in _rows("household-group-weights.csv"))
    for r in _rows("household-group-weights.csv"):
        if int(r["year"]) == wyear and r["code"] in SHARES and r["group"] in groups:
            groups[r["group"]].setdefault("shares", {})[SHARES[r["code"]]] = round(float(r["parts_per_thousand"]) / 10, 1)
    # lost flow held for 12 months (drop = points), or the IEA's 2026 path (drop = "iea"; the scenario column is newer)
    scen = [{"region": r["region"], "drop": "iea" if r.get("scenario") == "iea_2026_path" else int(float(r["flow_drop_points"])),
             "h": int(r["months_ahead"]), "q05": float(r["real_pay_q05"]), "q50": float(r["real_pay_q50"]), "q95": float(r["real_pay_q95"]),
             "actual": float(r["real_pay_actual"]) if r["real_pay_actual"] else None} for r in _rows("household-scenarios.csv")]
    gs_rows = _rows("household-group-scenarios.csv")
    gscen = [{"group": r["group"], "scen": r["scenario"], "origin": r["origin"], "h": int(r["months_ahead"]),
              "q50": float(r["cost_q50"]), "q05": float(r["cost_q05_bound"]), "q95": float(r["cost_q95_bound"]),
              "energy": float(r["energy_part"]), "fuel": float(r["motor_fuel_part"]), "food": float(r["food_part"])}
             for r in gs_rows if r["scenario"] in GROUP_SCEN and int(r["months_ahead"]) in (3, 6, 12)]
    meta = {}
    for r in _rows("household-panel.csv"):
        meta.setdefault(r["series"], [r["label"], r["source"], r["code"], r["fetched"]])
    # the HCI file's fetch date, from the files table of notes/household-costs.md; the item fans' run date
    hci_fetched = next((ln.rstrip(" |\n").rsplit("|", 1)[-1].strip() for ln in open(NOTES / "household-costs.md", encoding="utf-8")
                        if ln.startswith("| `household-groups.csv` |")), None)
    fans = NOTES / "cost-of-living-fans.csv"
    fans_generated = max(r["generated"] for r in _rows(fans.name)) if fans.exists() else None
    return {"real_pay": real_pay, "essentials": essentials, "petrol": petrol, "groups": list(groups.values()), "weights_year": wyear,
            "groups_source": HCI, "groups_fetched": hci_fetched, "scen": scen, "scen_origin": "2026-02", "gscen": gscen,
            "gscen_source": gs_rows[0]["source"], "fans_generated": fans_generated, "meta": meta}


def script():
    d = data()
    return "" if d is None else f"<script>/* households: notes/household-*.csv (OXH-8) */\nwindow.HOUSEHOLDS = {json.dumps(d, separators=(',', ':'))};\n</script>\n"


CSS = """/* Households page (households.py, households.js) */
.hz-hh { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 12px; align-content: start; overflow-y: auto; padding-bottom: 16px; }
.hz-hh[hidden] { display: none !important; }
.hz-hh .col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.hz-hh .card { min-width: 0; }
.hz-hh h3 { margin: 0; font: 700 15px var(--pix); color: var(--oil-soft); letter-spacing: .4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hz-hh .lede { margin: 0; font-size: 13.5px; color: var(--text); }
.hz-hh .src { margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--faint); }
.hz-hh .tagm { font: 400 15px var(--mono); padding: 0 6px; border: 2px dashed #7c63c9; color: #c9b8ff; letter-spacing: 1px; }
.hz-hh .keys { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12.5px; color: var(--muted); }
.hz-hh .keys i { display: inline-block; width: 14px; height: 4px; margin-right: 6px; vertical-align: 3px; }
.hz-hh svg text { font-family: var(--mono); font-size: 15px; fill: var(--muted); }
.hz-hh svg .grid line { stroke: var(--line); }
.hz-hh svg text.halo { paint-order: stroke; stroke: var(--panel); stroke-width: 4px; stroke-linejoin: round; }
.hz-hh .ctrl { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.hz-hh .ctrl .seg button { min-height: 30px; padding: 0 9px; font: 400 17px var(--mono); }
.hz-hh .rows { display: flex; flex-direction: column; gap: 6px; }
.hz-hh .rrow { display: grid; grid-template-columns: 150px minmax(0, 1fr) 150px; gap: 10px; align-items: center; font-size: 13px; }
.hz-hh .rrow .nm { display: flex; align-items: center; gap: 7px; min-width: 0; }
.hz-hh .rrow .nm .flag { flex: none; }
.hz-hh .rrow .v { font: 400 17px var(--mono); text-align: right; color: var(--text); white-space: nowrap; }
.hz-hh .rrow .v small { color: var(--faint); font-size: 14px; }
.hz-hh .track { position: relative; height: 16px; background: var(--ink); border: 1px solid var(--line2); }
.hz-hh .track .zero { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--muted); opacity: .6; }
.hz-hh .track .band { position: absolute; top: 3px; bottom: 3px; opacity: .45; }
.hz-hh .track .mid { position: absolute; top: -2px; bottom: -2px; width: 4px; margin-left: -2px; border: 1px solid var(--ink); }
.hz-hh .track .seg2 { position: absolute; top: 2px; bottom: 2px; }
.hz-hh table { width: 100%; border-collapse: collapse; font-size: 13px; }
.hz-hh th { font: 600 11px var(--pix); letter-spacing: .6px; text-transform: uppercase; color: var(--oil-soft); text-align: right; padding: 4px 6px; }
.hz-hh th:first-child, .hz-hh td:first-child { text-align: left; }
.hz-hh td { padding: 4px 6px; border-top: 1px solid var(--line); text-align: right; font: 400 17px var(--mono); color: var(--text); }
.hz-hh td:first-child { font: 13px var(--sans, system-ui); color: var(--text); }
.hz-hh td .hot { color: var(--harm); } .hz-hh td .ok { color: #7ee0b0; }
.hz-hh td small { color: var(--faint); font-size: 13px; }
.hz-hh .mini { display: inline-flex; height: 10px; width: 120px; background: var(--ink); border: 1px solid var(--line2); vertical-align: middle; }
.hz-hh .mini i { display: block; height: 100%; }
.hz-hh .grp-h { font: 600 11px var(--pix); letter-spacing: .6px; text-transform: uppercase; color: var(--faint); padding-top: 8px; }
.hz-hh .track .mid.act { width: 3px; margin-left: -1.5px; top: -5px; bottom: -5px; }
.hz-hh .rrow.axis { font-size: 11px; color: var(--faint); margin-top: -2px; }
.hz-hh .rrow.axis .ax { display: flex; justify-content: space-between; }
.hz-hh .rrow.all .nm, .hz-hh tr.all td:first-child { color: var(--oil-soft); }
.hz-hh .hz-th { display: inline-flex; align-items: center; gap: 5px; }
.hz-hh .keys span { display: inline-flex; align-items: center; gap: 0; }
.hz-hh .keys .flag { margin-right: 6px; }
.hz-hh h3 .flag { width: 22px; height: 16px; }
.hz-hh code { font: 14px var(--mono); color: var(--muted); }
.hz-hh .hz-srcd summary { cursor: pointer; font-size: 12px; color: var(--muted); }
.hz-hh .hz-saved { padding: 0 2px; }
.hz-hh .hz-outlook { min-height: 30px; padding: 0 9px; font: 400 17px var(--mono); }
.hz-hh .hz-outlook[aria-pressed="true"] { background: var(--violet, #b58cff) !important; color: #140c24 !important; font-weight: 700; }
/* three views: on a phone the switch takes its own row under the title */
@media (max-width: 560px) { .bar .brand { flex-wrap: wrap; } .bar .brand .modeseg { order: 9; flex: 1 1 100%; } .bar .brand .modeseg button { flex: 1 1 0; } }
/* the World view's households step, in "The shock" card */
.hz-hhstep .tagm { font: 400 14px var(--mono); padding: 0 5px; border: 2px dashed #7c63c9; color: #c9b8ff; letter-spacing: 1px; margin-left: 4px; }
.hz-hhmini { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.hz-hhmini .hz-mh { grid-column: 1 / -1; font-size: 12px; color: var(--muted); }
.hz-hhmini .hz-mr { display: grid; grid-template-columns: auto 1fr; gap: 2px 6px; align-items: center; padding: 6px 8px; background: var(--ink); border: 1px solid var(--line2); }
.hz-hhmini .hz-mr .mono { grid-column: 1 / -1; font: 400 22px var(--mono); color: var(--text); }
.hz-hhmini .hz-mr small { grid-column: 1 / -1; font-size: 11px; color: var(--faint); }
.hz-hhstep .sub .flag { margin-right: 4px; }
.hz-hhgo { min-height: 30px; font-size: 12.5px; align-self: flex-start; }
/* reading order: a headline, then numbered cards left to right, top to bottom; sources behind each card's info button */
.hz-hh { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.hz-hh .hz-head, .hz-hh .hz-saved { grid-column: 1 / -1; }
.hz-hh .hz-head { gap: 10px; border-color: var(--oil) !important; }
.hz-hh .hz-kick { font: 600 11px var(--pix); letter-spacing: .8px; text-transform: uppercase; color: var(--oil-soft); }
.hz-hh .hz-hl { margin: 0; font-size: 16px; line-height: 1.6; color: var(--text); text-wrap: pretty; }
.hz-hh .hz-hl b { color: var(--oil-soft); }
.hz-hh .hz-hlnums { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
.hz-hh .hz-t { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; background: var(--panel2); border: 2px solid var(--ink); }
.hz-hh .hz-t b { font: 400 30px/1 var(--mono); color: var(--text); }
.hz-hh .hz-t.hurt b { color: var(--harm); }
.hz-hh .hz-t span { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); }
.hz-hh .hz-t small { font-size: 11.5px; color: var(--faint); }
.hz-hh .hz-ch { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; position: relative; padding-right: 40px; min-height: 32px; }
.hz-hh .hz-ch h3 { flex: 0 1 auto; }
.hz-hh .hz-n { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; flex: none; background: var(--oil); color: var(--ink, #070b16); font: 700 14px var(--pix); }
/* the info button sits in the header's top-right corner, so a long title can't push it onto a line of its own */
.hz-hh .hz-ch .hz-i { position: absolute; top: 0; right: 0; width: 32px; min-height: 32px; }
.hz-hh .tagr { font: 400 15px var(--mono); padding: 0 6px; border: 2px dashed #3f9a6e; color: #7ee0b0; letter-spacing: 1px; }
.hz-hh .hz-keys-c { justify-content: center; margin-top: -4px; }
/* step 3: each value on one line, so its rows sit at the same spacing as the table beside it */
.hz-hh #hh-gs-rows { gap: 0; }
.hz-hh #hh-gs-rows .rrow { grid-template-columns: 130px minmax(0, 1fr) 200px; min-height: 30px; border-top: 1px solid var(--line); }
.hz-hh #hh-gs-rows .rrow:first-child { border-top: 0; }
.hz-hh #hh-gs-rows .rrow .v small { font-size: 13px; }
@media (max-width: 560px) { .hz-hh #hh-gs-rows .rrow { grid-template-columns: 90px minmax(0, 1fr) 150px; } }
@media (max-width: 980px) { .hz-hh { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .hz-hh { overflow: visible; } }
@media (max-width: 560px) { .hz-hh .rrow { grid-template-columns: 96px minmax(0, 1fr) 104px; font-size: 12px; } .hz-hh .mini { width: 70px; } }
"""
