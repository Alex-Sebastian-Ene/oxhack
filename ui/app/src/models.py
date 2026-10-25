"""The Models page (models.js, models.css): what each of Seb's statistical and ML models answers, its headline
results, how it was tested and what it can't do, read at build time from notes/ and docs/ into window.MODELS.

Every number on the page comes out of a note here, by table cell or by a phrase in the text, with the note's
path and the date it was generated. A card whose numbers can't be found is left out with a warning, so a note
that changes never puts a stale or invented number on screen.

    python ui/app/src/models.py      # prints the cards it built and any it left out
"""
import csv
import functools
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


# ------------------------------------------------------------ reading the notes
@functools.lru_cache(None)
def _text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _clean(s):
    return s.replace("**", "").replace("`", "").strip()


def _cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


@functools.lru_cache(None)
def _tables(rel):
    """Every markdown table in a note: the heading it sits under, the line just before it, its header and rows."""
    lines, out, head, cap, i = _text(rel).splitlines(), [], "", "", 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            head, cap = ln.lstrip("#").strip(), ""
        elif ln.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip()):
            hdr, rows, i = [_clean(c) for c in _cells(ln)], [], i + 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append({"section": head, "caption": _clean(cap), "head": hdr, "rows": rows})
            cap = ""
            continue
        elif ln.strip():
            cap = ln.strip()
        i += 1
    return out


def _matching(rel, col, section=None, caption=None):
    return [t for t in _tables(rel) if col in t["head"] and (not section or section in t["section"])
            and (not caption or caption in t["caption"])]


def table(rel, col, section=None, caption=None):
    """The first table with this column (under a heading containing `section`, after a line containing `caption`)."""
    for t in _matching(rel, col, section, caption):
        return t
    raise LookupError(f"{rel}: no table with column {col!r} (section {section!r}, caption {caption!r})")


def cell(rel, row, col, section=None, caption=None):
    """One cell, by the first cell(s) of its row and its column header, from the first such table that has the row;
    bold and code marks removed."""
    key = (row,) if isinstance(row, str) else tuple(row)
    for t in _matching(rel, col, section, caption):
        j = t["head"].index(col)
        for r in t["rows"]:
            if tuple(_clean(c) for c in r[:len(key)]) == key:
                return _clean(r[j])
    raise LookupError(f"{rel}: no row {key!r} under {col!r} (section {section!r})")


def find(rel, pattern, group=1):
    m = re.search(pattern, _text(rel), re.M)
    if not m:
        raise LookupError(f"{rel}: no match for {pattern!r}")
    return m.group(group) if isinstance(group, int) else m.groups()


@functools.lru_cache(None)
def generated(rel):
    """The date a note was generated: its first line in italics, a CSV's `generated` column, a JSON's field."""
    if rel.endswith(".csv"):
        return max(r["generated"] for r in csv.DictReader(open(ROOT / rel, encoding="utf-8")))
    if rel.endswith(".json"):
        return json.loads(_text(rel))["generated"]
    if rel.startswith("docs/"):
        return None
    return find(rel, r"^_(?:Generated|Checked)\b.*? on (\d{4}-\d{2}-\d{2})")


def num(s):
    """A note's number for the page: a true minus sign."""
    return re.sub(r"(^|[\s(\[])-(?=[\d.])", "\\1\u2212", s)


def stat(v, label, src, note=""):
    return {"v": num(v), "label": label, "note": num(note), "src": src, "date": generated(src)}


def pct_vs(s):
    """'-8%' (our CRPS lower by) as '8% higher'; '+2%' as '2% lower'."""
    v = float(s.rstrip("%"))
    return f"{abs(v):g}% {'higher' if v < 0 else 'lower'}"


# ------------------------------------------------------------ the cards, in the chain's order
NG, LF, OP, OPM = "notes/non-gaussian-results.md", "notes/levy-fourier-results.md", "notes/oil-paths-results.md", "docs/oil-price-model.md"
LC = "notes/link-checks.md"


def levy():
    st = cell(NG, "Student-t", "Test log score vs Gaussian")
    vol = find(LF, r"\*\*Volatility state:\*\* GARCH-CGMY minus iid-CGMY ([+-][\d.]+ ± [\d.]+)")
    four = find(LF, r"Fourier minus CGMY: ([+-][\d.]+ ± [\d.]+)")
    c1, b1, t1 = (cell(OP, "1", c) for c in ("GARCH-CGMY CRPS", "bootstrap CRPS", "CGMY − bootstrap (t)"))
    cov1 = cell(OP, "1", "GARCH-CGMY in 90%")
    test0, test1, ndays = find(NG, r"test (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2}) \((\d+) days\)", None)
    norig, o0, o1 = find(OP, r"(\d+) forecast origins \((\d{4}-\d{2})\.\.(\d{4}-\d{2})\)", None)
    checks = [_clean(r[2]) for r in table(LC, "Result")["rows"]]
    nproc = len(table(NG, "Test log score vs Gaussian")["rows"])
    y0 = min(_clean(r[0]) for r in table(LF, "Fourier - CGMY", section="Rolling refits")["rows"] if _clean(r[0]).isdigit())
    tails, years = find(OPM, r"about\s+(\d+)\s+days\s+beyond\s+4\s+sd\s+in\s+(\d+)\s+training\s+years", None)
    crisis6 = cell(OP, "6, crisis", "GARCH-CGMY in 90%")
    return {
        "id": "levy", "group": "oil", "title": "Oil price distribution", "kind": "Lévy processes + GARCH", "wide": True,
        "asks": "How big are Brent's moves over a day, a week and a month, and how often do the extremes come? "
                "It gives the spread of prices the chain is fed, not their direction.",
        "stats": [
            stat(st, "nats a day: fat tails beat the bell curve",
                 NG, f"Student-t over the Gaussian, test log score on {ndays} days to {test1}"),
            stat(vol, "nats a day from a changing volatility",
                 LF, "GARCH-CGMY over the same jumps with constant volatility"),
            stat(four, "nats a day from a learned tail shape",
                 LF, "Fourier-learned Lévy measure over plain CGMY, both with GARCH: no gain"),
            stat(c1, f"1-month error (CRPS, points), against {b1} for a bootstrap",
                 OP, f"Brent's monthly change, GARCH-CGMY paths (t {t1.split('t ')[-1].rstrip(')')}); {cov1} inside the 90% band"),
        ],
        "tested": f"{nproc} Lévy processes fitted on Brent before {test0} and scored on {ndays} unseen days to {test1}, "
                  f"with rolling refits for every year since {y0} on Iridis. Monthly paths backtested on {norig} forecast "
                  f"origins ({o0} to {o1}). Cross-checks between scripts, machines and closed forms: "
                  f"{sum(c.startswith('PASS') for c in checks)} of {len(checks)} pass.",
        "limits": [
            "It doesn't predict direction: its central forecast is about \"same as today\".",
            f"Daily data hold too few extremes to learn a tail shape (about {tails} days beyond 4 sd in {years} years), "
            "which is the one cross-check that fails: the learned tail's coefficients don't reproduce.",
            f"In crises its bands are too narrow: {crisis6} of 6-month outcomes fall inside the 90% band.",
        ],
        "files": [NG, LF, OP, LC, OPM],
    }


FP, PREM, HFC, CHAIN = "notes/flow-price-link.md", "notes/flow-premium-iea.csv", "notes/hormuz-flow-check.md", "docs/chain.md"


def flow():
    rows = list(csv.DictReader(open(ROOT / PREM, encoding="utf-8")))
    obs = [r for r in rows if not r["source"].startswith("assumption")]
    peak, last = max(rows, key=lambda r: float(r["e_mid"])), rows[-1]
    p = lambda r, k: f"{100 * float(r[k]):.2f}%"
    jump, d20, b20 = (cell(FP, "+20", c) for c in ("Change since 5 days before", "Date", "Brent"))
    reg = cell(FP, "2019-2025 only", "Hormuz, same month")
    h0, h1 = find(HFC, r"within noise at every horizon from (\d+) to (\d+) trading days", None)
    small = find(CHAIN, r"loss under about (\d+) Hormuz points")
    return {
        "id": "flow", "group": "oil", "title": "Lost flow → Brent", "kind": "Event study + regression",
        "asks": "When tankers stop crossing Hormuz, how much does Brent rise for each point of normal flow lost, and how fast does that fade?",
        "stats": [
            stat(p(peak, "e_mid"), f"of Brent per point of lost flow at the peak, day {peak['trading_day']}",
                 PREM, f"log premium, band {p(peak, 'e_low')} to {p(peak, 'e_high')}, fitted to the 2026 closure on the IEA's lost flow"),
            stat(p(last, "e_mid"), "per point once it settles",
                 PREM, f"the plateau, held flat beyond the {len(obs)} observed trading days: an assumption"),
            stat(jump, "Brent 20 trading days into the 2026 closure",
                 FP, f"{b20} on {d20}, against 5 days before it began"),
            stat(reg, "% of Brent per point, 2019–2025 months",
                 FP, "monthly regression without the closure: too small to tell from zero"),
        ],
        "tested": f"Out of sample on the 2023–24 Bab el-Mandeb disruption: the 2026 response, scaled to Hormuz-equivalent flow, "
                  f"predicts its Brent move within noise at every horizon from {h0} to {h1} trading days. "
                  "The band comes from 2019–2025 placebo days.",
        "limits": [
            f"Its size rests on one event: no loss since 2019 except 2026 is big enough to test it, and a loss under about {small} points "
            "can't be told from Brent's own 20-day noise.",
            "The closure mixes lost barrels with a risk premium and stock releases.",
            "PortWatch sees AIS-visible tankers only, so the curve is fitted per point of the IEA's count, which includes dark transits.",
        ],
        "files": [FP, PREM, HFC, CHAIN],
    }


OCL, CV, KV = "notes/oil-chain-links.md", "notes/oil-chain-cv.md", "docs/knock-on-validation.md"
LINKS = ["Oil -> petrol price", "Oil -> energy CPI", "Oil -> headline CPI", "Oil -> core CPI",
         "Oil -> 5y inflation expectations", "10y Treasury -> mortgage rate", "Fed funds -> mortgage rate (holding 10y)"]


def chain():
    rows = []
    for ln in LINKS:
        unit = cell(OCL, ln, "Unit")
        rows.append([ln.replace("->", "→"), num(cell(CV, ln, "Effect, whole window")), num(unit),
                     cell(CV, ln, "Folds with R² > 0"), cell(CV, ln, "Verdict")])
    fed = table(CV, "Range across folds", section="Fed reaction")["rows"]
    lo = min(float(_clean(r[2]).split(" to ")[0]) for r in fed)
    hi = max(float(_clean(r[2]).split(" to ")[1]) for r in fed)
    nfold = find(CV, r"gives (\d+) folds per link")
    k0, k1 = find(CV, r"every k from (\d+) to (\d+)", None)
    return {
        "id": "chain", "group": "chain", "title": "Knock-on links", "kind": f"Regressions, {nfold} folds each", "wide": True,
        "asks": "When oil rises 10%, how much do petrol, energy bills, inflation, the Fed and mortgages move, and which links survive data they never saw?",
        "stats": [
            stat(cell(CV, LINKS[0], "Effect, whole window"), "% on US petrol within 2 months",
                 CV, f"per 10% oil rise; {cell(CV, LINKS[0], 'Verdict').lower()}"),
            stat(cell(CV, LINKS[2], "Effect, whole window"), "points on US headline CPI within a year",
                 CV, f"per 10% oil rise; beats a constant in {cell(CV, LINKS[2], 'Folds with R² > 0')} folds"),
            stat(f"{lo:+.2f} to {hi:+.2f}", "the Fed's response per point of core inflation",
                 CV, "Taylor-rule coefficient, depending on which block is held out: unstable"),
        ],
        "table": {"head": ["Link", "Effect", "Folds R² > 0", "Verdict"], "rows": rows, "src": CV, "date": generated(CV)},
        "tested": f"Each link's whole window, 1991–2026, is cut into k = {k0} to {k1} blocks ({nfold} folds per link). Each block is "
                  "held out once with a gap the length of the lags, and a forward version predicts each block from earlier ones only.",
        "limits": [
            "These are average historical pass-throughs, mixing demand- and supply-driven oil moves: not the causal effect of a supply shock.",
            "Oil barely reaches core inflation, so the Fed step is shown as a range, not a forecast.",
            "Mortgages follow the 10-year yield, not the policy rate.",
        ],
        "files": [OCL, CV, KV],
    }


MB, ME = "notes/macro-bayes-results.md", "docs/macro-ensemble.md"


def bayes():
    sk = lambda tgt, col: cell(MB, (tgt, "all"), col, section="Skill by horizon")
    origin = "2025-09"   # the last fold's latest origin: the closure falls inside its 12 months
    act, wi = (cell(MB, (origin, "us_cpi@12"), c) for c in ("Actual", "What-if (90%)"))
    end = f"{int(origin[:4]) + 1}{origin[4:]}"
    samp = [r for r in table(MB, "Max R-hat", section="Sampler health")["rows"] if _clean(r[1]) == "Bayes+own-vol"]
    rhat, ess = max(float(_clean(r[5])) for r in samp), min(float(_clean(r[6])) for r in samp)
    dm = cell(MB, "Bayes+own-vol what-if vs anchored nn_mean", "inflation")
    o0, o1, norig = find(MB, r"\((\d{4}-\d{2})\.\.(\d{4}-\d{2}), (\d+) forecast origins\)", None)
    cov = {t: cell(MB, t, "Bayes+own-vol what-if", section="Calibration") for t in ("inflation", "unemployment", "cost")}
    nser = find(ME, r"single model for all (\d+) target series")
    return {
        "id": "bayes", "group": "chain", "title": "Bayesian pass-through", "kind": "Bayesian, MCMC",
        "asks": f"One model for {nser} series (inflation, unemployment, policy rates and industry costs in the US, UK and euro area): "
                "given an oil path, where will each be in 1 to 12 months, and how sure is it?",
        "stats": [
            stat(sk("inflation", "Bayes+own-vol what-if"), "inflation skill, given the oil path", MB, "all horizons; 0 = climatology"),
            stat(sk("inflation", "Bayes+own-vol forecast"), "inflation skill, forecasting oil too", MB, "nothing after the forecast date is known"),
            stat(act, f"% on US CPI, {origin} to {end}", MB, f"actual; the model said {wi} from {origin}, given the oil path"),
            stat(cov["inflation"], "of inflation outcomes inside its 90% band",
                 MB, "target 90%"),
        ],
        "tested": f"8 forward-chaining folds, {norig} forecast origins ({o0} to {o1}), each fitted only on earlier months. The sampler "
                  f"converged on every fold (max R-hat {rhat:.3f}, min ESS {ess:.0f}). It beats the anchored network ensemble on inflation "
                  f"(Diebold–Mariano {dm}).",
        "limits": [
            f"Unemployment: no skill ({sk('unemployment', 'Bayes+own-vol what-if')}), and its oil response has the demand sign, so it is not a what-if link.",
            f"Its bands are a little narrow: {cov['inflation']} of inflation, {cov['cost']} of costs and {cov['unemployment']} of unemployment outcomes land inside the 90% band.",
            "Scored on revised data, not the figures as first published, and it doesn't separate supply from demand shocks.",
        ],
        "files": [MB, ME],
    }


MG = "notes/macro-global-results.md"
BENCH = [("SPF median, latest survey at every month-end", "Professional forecasters (SPF median)"),
         ("Cleveland Fed 1-year expected inflation (FRED EXPINF1YR)", "Cleveland Fed model"),
         ("Michigan 1-year expectations (FRED MICH)", "Michigan households"),
         ("Random walk: last 12-month pace carries on", "Last 12 months' pace carries on")]


def global_net():
    sec12 = "US CPI over the next 12 months"
    ref = BENCH[0][0]
    ours = [("Bayesian pass-through", cell(MG, ref, "Bayes own-vol skill", section=sec12)),
            ("Global network (global_lin)", cell(MG, ref, "global_lin skill", section=sec12))]
    norig = cell(MG, ref, "Origins", section=sec12)
    bars = [{"name": n, "v": float(v), "ours": True} for n, v in ours]
    bars += [{"name": short, "v": float(cell(MG, full, "Benchmark skill", section=sec12)), "ours": False} for full, short in BENCH]
    vs_spf = cell(MG, ref, "global_lin CRPS lower by", section=sec12)
    t_spf = cell(MG, ref, "global_lin minus benchmark (t)", section=sec12)
    vs_cle = cell(MG, BENCH[1][0], "global_lin CRPS lower by", section=sec12)
    m1 = cell(MG, "1", BENCH[1][0], section="US CPI by horizon", caption="global_lin minus each benchmark")
    dm = cell(MG, "global_lin vs Bayes own-vol", "inflation", section="Forecast mode")
    a25, g25, s25 = (cell(MG, "2025-05", c, section="2024–25 survey dates").split(" (")[0] for c in ("Actual", "global_lin", "SPF median"))
    seeds = find(ME, r"Each variant has (\d+) seeds")
    return {
        "id": "global", "group": "chain", "title": "Global network", "kind": "Neural network", "wide": True,
        "asks": "One small neural network shared by all the series, simulated forward month by month. Does it beat the Bayesian model, "
                "and how does it stand against the Fed's and professional forecasters' inflation forecasts?",
        "stats": [
            stat(cell(MG, ("inflation", "all"), "global_lin", section="Skill by horizon"), "inflation skill, given the oil path",
                 MG, f"Bayesian model {cell(MG, ('inflation', 'all'), 'Bayes own-vol', section='Skill by horizon')}"),
            stat(cell(MG, ("inflation", "all"), "global_lin forecast", section="Forecast mode"), "inflation skill, forecasting oil too",
                 MG, f"Bayesian model {cell(MG, ('inflation', 'all'), 'Bayes own-vol forecast', section='Forecast mode')}; difference {dm}"),
            stat(pct_vs(vs_spf), "error than the SPF, US CPI over a year",
                 MG, f"CRPS, {norig} shared months; t {t_spf.split('(')[-1].rstrip(')')}, not significant"),
            stat(pct_vs(vs_cle), "error than the Cleveland Fed, same test", MG, f"at 1 month: {pct_vs(m1.split(', ')[-1])} (t {m1.split('(')[1].split(')')[0]})"),
        ],
        "bars": {"title": f"US CPI over the next 12 months: skill on {norig} shared forecast months",
                 "bars": bars, "src": MG, "date": generated(MG)},
        "tested": f"The same 8 folds as the Bayesian model, {seeds} seeds per variant. The forecast mode knows nothing after the forecast "
                  "date: each draw follows its own oil path, bootstrapped from training months and scaled to oil-options volatility (OVX). "
                  "Each SPF survey is counted from the end of its release month.",
        "limits": [
            "None of our models beats the professional forecasters on US CPI over a year; none of those gaps is significant.",
            f"In May 2025 the SPF expected {s25}% over the next year and the network {g25}%; CPI rose {a25}%.",
            "The surveys were made in real time; we are scored on revised data, which flatters us slightly.",
            "Unemployment still trails a plain ridge regression.",
        ],
        "files": [MG, ME],
    }


EXPERT_NAMES = {"SPF median, latest survey": "Professional forecasters (SPF)", "Cleveland Fed": "Cleveland Fed model",
                "Michigan": "Michigan households"}


def experts():
    """The panel above the cards: our statistical and ML models against the experts, inflation by region, from the
    global network's forecast-mode tables (nothing after the forecast date is known)."""
    sec = "Inflation by region: our models against the experts"
    ours = (("stats", "Bayes own-vol"), ("ml", "global_lin"))
    rows = []
    for region, label in (("US, UK and euro area", "All three"), ("US", "US"), ("UK", "UK"), ("Euro area", "Euro area")):
        g = lambda col, h="12": _clean(cell(MG, (region, h), col, section=sec))
        r = {"region": label, "full": region, "n": g("Origins"), **{k: num(g(col)) for k, col in ours},
             "naive": num(g("Random walk")), "expert": None}
        best = g("Best expert")
        if best != "n/a":
            r["expert"] = {"name": EXPERT_NAMES[best], "v": num(g(best)),
                           "t": {k: num(g(f"{col} minus best expert (t)").split("(")[1].rstrip(")")) for k, col in ours},
                           "others": [[EXPERT_NAMES[e], num(g(e))] for e in EXPERT_NAMES if e != best and g(e) != "n/a"]}
        rows.append(r)
    origin = find(MG, r"^### Inflation over the next 12 months by region, from (\d{4}-\d{2})")
    psec = f"Inflation over the next 12 months by region, from {origin}"
    point = lambda s: None if _clean(s) == "n/a" else float(_clean(s).split(" (")[0])
    pred = []
    for r in rows[1:]:
        p = lambda col: point(cell(MG, r["full"], col, section=psec))
        band = lambda col: [float(x) for x in re.findall(r"[+-]?\d+\.\d", _clean(cell(MG, r["full"], col, section=psec)).split("(")[1])]
        best = next((k for k, v in EXPERT_NAMES.items() if r["expert"] and v == r["expert"]["name"]), None)
        pred.append({"region": r["region"], "actual": p("Actual"), "stats": p("Bayes own-vol"), "ml": p("global_lin"),
                     "stats_band": band("Bayes own-vol"), "ml_band": band("global_lin"),
                     "expert": p(best) if best else None, "naive": p("Random walk")})
    end = f"{int(origin[:4]) + 1}{origin[4:]}"
    return {"rows": rows, "pred": pred, "origin": origin, "end": end, "src": MG, "date": generated(MG),
            "span": find(MG, r"\((\d{4}-\d{2}\.\.\d{4}-\d{2}), \d+ forecast origins\)").replace("..", "–")}


COL, COLD = "notes/cost-of-living.md", "docs/cost-of-living.md"


def cost_of_living():
    ev = "The 2026 Hormuz closure as a test"
    inside = "Actuals inside the 90% interval, basket items, rest, headline and composites"
    ours, avg = cell(COL, inside, "Bayesian, supply-shock terms", section=ev), cell(COL, inside, "Average link", section=ev)
    skill = lambda row: cell(COL, row, "Bayesian, given oil and gas", caption="Skill against climatology, all horizons")
    cap = "Our US composite (items + rest) against each benchmark"
    spf = cell(COL, BENCH[0][0], "h=12", section="Timing matched", caption=cap)
    cle = cell(COL, BENCH[1][0], "h=12", section="Timing matched", caption=cap)
    norig, o0, o1 = find(COL, r"^(\d+) forecast origins, (\d{4}-\d{2}) to (\d{4}-\d{2})", None)
    fits = find(COL, r"from (\d+) converged fits")
    disr = find(COL, r"Supply-disruption months in the fit: (\d+)")
    base, after = find(COL, r"^## The 2026 Hormuz closure as a test: fitted to (\d{4}-\d{2}), scored (\d+) months on", None)
    return {
        "id": "col", "group": "chain", "title": "Cost of living, item by item", "kind": "Bayesian, by basket item",
        "asks": "Through the basket item by item (bread, meat, electricity, gas, petrol, air fares, rent) in the US, UK and euro area: "
                "how much does an oil and gas supply shock add, and how wide is the range?",
        "stats": [
            stat(ours, "2026 outcomes inside the 90% band", COL, f"fitted to {base}, scored {after} months on; the average link {avg}"),
            stat(skill("Motor fuel"), "motor-fuel skill, given oil and gas", COL, "all horizons; 0 = climatology"),
            stat(skill("US headline: composite"), "US CPI skill, built item by item", COL, "given oil and gas"),
            stat(spf.split(" (")[0], "error than the SPF, US CPI over a year", COL,
                 f"forecasting oil too, timing matched ({spf.split('(')[1].rstrip(')')}); the Cleveland Fed: {cle.split(' (')[0]}"),
        ],
        "tested": f"8 forward-chaining folds, {norig} forecast origins ({o0} to {o1}), from {fits} converged fits on Iridis. Two event "
                  f"tests fitted before the shock: the 2026 closure ({disr} supply-disruption months in the fit) and 2022's. Against "
                  "the surveys it only uses the CPI they had when they were made.",
        "limits": [
            "Only two supply shocks since 2000, so the extra pass-through in a disruption is learned from very little.",
            "At 1 to 3 months it trails the Cleveland Fed's nowcast, which reads daily oil and weekly petrol prices.",
            "2022's food surge is outside what it can explain.",
            "Unemployment and rates have no validated oil link.",
        ],
        "files": [COL, COLD],
    }


CT = "notes/country-trends.json"


def sector():
    d = json.loads(_text(CT))
    run, C = d["run"], d["countries"]
    ind = [c for c in C.values() if c.get("price") or c.get("output")]   # the rest have consumer prices only
    sk = {t: [c["skill"][t] for c in C.values() if t in c.get("skill", {})] for t in ("price", "output")}
    tot = {t: (sum(s["beats"] for s in v), sum(s["of"] for s in v)) for t, v in sk.items()}
    med = {t: statistics.median(s["skill"] for s in v) for t, v in sk.items()}
    stats = [
        stat(f"{tot['price'][0]} of {tot['price'][1]}", "producer-price series beat climatology", CT,
             f"{run['model']}; median country skill {med['price']:+.3f} across {len(sk['price'])} countries"),
        stat(f"{tot['output'][0]} of {tot['output'][1]}", "output series beat climatology", CT,
             f"median country skill {med['output']:+.3f}: output is barely forecastable"),
    ]
    rep, files = run.get("report"), [CT]
    if rep and (ROOT / rep).exists():   # the sector run's own report, once it is on this branch
        try:
            stats.append(stat(cell(rep, "global vs global, no oil", "price"), "price skill that knowing oil adds", rep,
                              "the network with and without its oil inputs; Diebold–Mariano"))
            files.append(rep)
        except LookupError as e:
            print(f"models: {e}", file=sys.stderr)
    return {
        "id": "sector", "group": "industry", "title": "Industries by country", "kind": "Neural network, by industry",
        "asks": f"For {len(d['industries'])} mining, refining, chemicals and metals industries in {len(ind)} countries: "
                "how do producer prices and output follow oil, and can we forecast them?",
        "stats": stats,
        "tested": f"The global network's {run['model']} variant on {run['folds']} forward-chaining folds, {run['origins']} forecast "
                  f"origins ({run['first']} to {run['last']}), fold files from {run['fold_files'].split(' to ')[0]}. Skill is scored "
                  "per series against its own climatology.",
        "limits": [
            f"What-if only ({run['mode'].split(': ')[-1]}).",
            "Output barely beats climatology: it is shown as a trend, not a forecast.",
            "US industries are the closest NAICS matches, not exact ones.",
        ],
        "files": files,
    }


MR = "notes/margins-results.md"


def margins():
    base, mem, diff, t, k, n = find(MR, r"given the real Brent path:\*\* skill over the three ([+-][\d.]+) for the chain, ([+-][\d.]+) "
                                        r"with the margin member mixed in \(difference ([+-][\d.]+) \(t ([+-][\d.]+)\); better in (\d+) of (\d+) folds\)", None)
    crack, model, lo, hi = find(MR, r"diesel crack was \$(\d+)/bbl against \$(\d+) \((\d+)\.\.(\d+)\)", None)
    d0, d1 = find(MR, r"retail diesel ([+-][\d.]+) → ([+-][\d.]+) \(member\)", None)
    return {
        "id": "margins", "group": "industry", "title": "Refining margins", "kind": "Regression + mixture member",
        "asks": "Diesel and jet fuel overshoot what Brent alone predicts. Do refiners' margins (the crack spread) explain it?",
        "stats": [
            stat(mem, "fuel skill with the margin member", MR, f"against {base} without it, given the Brent path; better in {k} of {n} folds (t {t})"),
            stat(f"${crack}", "diesel crack in March 2026, a barrel", MR, f"the margin model expected ${model} (${lo} to ${hi})"),
            stat(d1, "points by which diesel still beat the 1-month forecast", MR, f"in 2026, with the margin member; {d0} without it"),
        ],
        "tested": "On the chain's 8 folds, both given the real Brent path and with Lévy oil paths, plus two out-of-sample checks: "
                  "the 2022 diesel squeeze and the 2026 closure.",
        "limits": [
            "It narrows the 2026 overshoot only a little: the 90% band still misses diesel and jet fuel at 1 month.",
            "Only 2022 widened margins on 2026's scale, so a crisis's effect on margins is learned from one episode.",
        ],
        "files": [MR],
    }


SAL = "notes/steel-aluminium-links.md"


def metals():
    steel, alu = "US PPI steel mill products (BLS)", "US PPI aluminum mill shapes (BLS)"
    st = lambda s: cell(SAL, s, "After 12 months", section="Result")
    pm = lambda s: cell(SAL, s, "± (12 m)", section="Result")
    vf = lambda s: cell(SAL, s, "Validated in folds", section="Result")
    happ = lambda s: cell(SAL, s, "What happened", section="The 2026 closure")
    link = lambda s: cell(SAL, s, "Link: oil part plus trend", section="The 2026 closure")
    world = cell(SAL, steel, "World demand held fixed", section="Sensitivity").split(" (")[0]
    m0, m1 = find(SAL, r"Price change (\d{4}-\d{2}) → (\d{4}-\d{2})", None)
    return {
        "id": "metals", "group": "industry", "title": "Steel and aluminium", "kind": "Regression",
        "asks": "Does a 10% rise in oil feed through to steel and aluminium prices, and by how much?",
        "stats": [
            stat(f"{st(steel)}%", "US steel mill prices after 12 months", SAL, f"per sustained 10% oil rise, ± {pm(steel)}; validated in {vf(steel)} folds"),
            stat(f"{st(alu)}%", "US aluminium mill shapes after 12 months", SAL, f"± {pm(alu)}; validated in {vf(alu)} folds"),
            stat(f"{happ(steel)}%", f"what steel actually did, {m0} to {m1}", SAL, f"the link, given the Brent path, expected {link(steel)}%"),
        ],
        "tested": "8 forward-chaining folds, each fitted only on months before its test block. A link counts as validated when the "
                  "all-data fit and at least 6 of the 8 folds clear two Newey–West errors.",
        "limits": [
            f"Metals and oil both follow world demand: holding that fixed shrinks steel's link to {num(world)}%.",
            f"It undershot in 2026: aluminium mill shapes rose {happ(alu)}% against {link(alu)}% expected.",
        ],
        "files": [SAL],
    }


NN, SA = "notes/macro-nn-results.md", "notes/stocks-ablation.md"


def ensemble():
    inf = lambda row: cell(NN, row, "all h", section="Inflation")
    resp = cell(NN, "us_cpi", "nn_mean", section="Response to a +10% Brent move (fit on all data")
    lin = find(NN, r"for comparison: US CPI \+([\d.]+) pp")
    cov = cell(NN, "nn_mean", "inflation", section="Calibration")
    job = find(NN, r"Iridis job (\d+)")
    seeds, orig, ep = find(ME, r"trained with \*\*(\d+) seeds\*\*"), find(ME, r"There are (\d+) monthly origins"), find(ME, r"lowest after (\S+) epochs")
    verdict = find(SA, r"\*\*Verdict: (.+?)\*\*").rstrip(".")
    return {
        "id": "nn", "group": "checks", "title": "Deep sequence ensemble", "kind": "Neural networks, first attempt",
        "asks": "Can deep sequence networks (LSTM, TCN, Transformer, N-BEATS) learn the knock-on chain straight from monthly data? "
                "Its failure is why the global network exists.",
        "stats": [
            stat(inf("nn_mean"), "inflation skill, ensemble mean", NN, f"best single network {inf('lstm_base')}; the stacker {inf('stack')}"),
            stat(resp, "points on US CPI from a 10% oil rise", NN, f"against +{lin} for the validated linear link"),
            stat(cov, "of inflation outcomes inside its 90% band", NN, "target 90%"),
        ],
        "tested": f"Five architectures in two sizes with {seeds} seeds each, on the same 8 forward-chaining folds (Iridis job {job}). "
                  "In its own diagnostics, shuffled training targets drop its skill to 0 or below: no leak.",
        "limits": [
            f"Too little data: {orig} monthly origins, and validation loss bottomed out after {ep} epochs, so the networks barely trained.",
            "Fixing the oil pass-through to the validated links helped prices, but the anchor did the work, not the networks.",
            f"Oil stocks as an extra input: {verdict.lower()} (`notes/stocks-ablation.md`).",
        ],
        "files": [NN, SA, ME],
    }


HDI = "notes/hdi-link.md"


def hdi():
    eff = cell(HDI, ("Oil importers", "without 2020-2021"), "10% oil rise, 2-year effect")
    effg = cell(HDI, ("Gulf exporters", "without 2020-2021"), "10% oil rise, 2-year effect")
    span = cell(HDI, ("Oil importers", "all years"), "Span")
    lo, hi = find(HDI, r"rises by (\d+) to (\d+) thousandths a year", None)
    return {
        "id": "hdi", "group": "checks", "title": "Human development (HDI)", "kind": "Panel regression",
        "asks": "Do oil prices move the UN's Human Development Index, for importers or for Gulf exporters?",
        "stats": [
            stat(eff, "thousandths of HDI over 2 years, per 10% oil rise", HDI, f"oil importers, without 2020–21; Gulf exporters {effg}"),
            stat(f"{lo} to {hi}", "thousandths a year: a typical country's normal HDI growth", HDI, "for scale"),
        ],
        "tested": f"Country fixed effects on UNDP data, {span}, with and without the 2020–21 pandemic years; Newey–West errors.",
        "limits": [
            "HDI rises with oil for importers and exporters alike: that is global booms, not a supply-shock effect.",
            "It is annual and slow, so it is context, not a monthly link in the what-if chain.",
        ],
        "files": [HDI],
    }


VER = "notes/verification.md"


def verify():
    res = lambda k: cell(VER, k, "Result", section="Pass/fail")
    tests = find(VER, r"PASS\*\*: (\d+) passed")
    dec = re.search(r"to (\d+) decimals", res("3")).group(1)
    inside, of = re.search(r"(\d+) of (\d+) inside the 90% band", res("5")).groups()
    shuf = re.search(r"inflation ([+-][\d.]+)", res("4a")).group(1)
    commit = find(VER, r"at\s+commit\s+`(\w+)`")
    day = generated(VER)
    return {
        "id": "verify", "group": "checks", "title": "Independent verification", "kind": "Audit",
        "asks": "If someone else re-runs the code from the saved runs, do they get the same numbers? Does any test peek at the future?",
        "stats": [
            stat(tests, "automated tests pass", VER, "the full suite"),
            stat(f"{dec} decimals", "every skill reproduces to", VER, "from the saved run files, against the notes"),
            stat(f"{inside} of {of}", "2026 outcomes inside the Bayesian 90% band", VER, "12 months ahead, given the oil path"),
        ],
        "tested": f"Checked on {day} against commit {commit} with the model code unchanged and the inputs copied read-only. "
                  "The leakage audit checks fold boundaries and publication lags by index arithmetic and perturbation tests.",
        "limits": [
            f"The shuffled-target control fails as specified (inflation {num(shuf)} instead of 0 or below): not leakage, but a soft yardstick.",
            "The chain isn't validated end to end: flow → Brent rests on one event.",
            f"It covers the knock-on runs as they were on {day}; later notes, such as the cost-of-living model ({generated(COL)}) "
            f"and the IEA premium curve ({generated(PREM)}), are not covered.",
        ],
        "files": [VER],
    }


CARDS = [levy, flow, chain, bayes, global_net, cost_of_living, sector, margins, metals, ensemble, hdi, verify]
GROUPS = [("oil", "The oil price"), ("chain", "From oil to prices and rates"), ("industry", "Industry"), ("checks", "Tried, rejected and checked")]


def data():
    cards = []
    for f in CARDS:
        try:
            c = f()
        except (LookupError, OSError, ValueError, KeyError, IndexError, AttributeError) as e:
            print(f"models: left out the {f.__name__} card: {e}", file=sys.stderr)
            continue
        c["files"] = [{"path": p, "date": generated(p)} for p in dict.fromkeys(c["files"])]
        c["asks"], c["tested"], c["limits"] = num(c["asks"]), num(c["tested"]), [num(x) for x in c["limits"]]
        cards.append(c)
    try:
        ex = experts()
    except (LookupError, OSError, ValueError, KeyError, IndexError) as e:
        print(f"models: left out the experts panel: {e}", file=sys.stderr)
        ex = None
    return {"cards": cards, "groups": GROUPS, "experts": ex} if cards else None


def script():
    d = data()
    return "" if d is None else f"<script>/* models: notes/ and docs/ (models.py) */\nwindow.MODELS = {json.dumps(d, ensure_ascii=False, separators=(',', ':'))};\n</script>\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    d = data() or {"cards": []}
    if d.get("experts"):
        ex = d["experts"]
        print(f"== Against the experts ({ex['src']} {ex['date']}, backtest {ex['span']})")
        for r in ex["rows"]:
            print(f"   {r['region']:>10}  stats {r['stats']}  ml {r['ml']}  expert {r['expert'] and (r['expert']['name'], r['expert']['v'], r['expert']['t'])}  naive {r['naive']}  n={r['n']}")
        for p in ex["pred"]:
            print(f"   {ex['origin']}..{ex['end']} {p}")
    for c in d["cards"]:
        print(f"\n== {c['title']} ({c['kind']})")
        for s in c["stats"]:
            print(f"   {s['v']:>18}  {s['label']}  [{s['note']}]  {s['src']} {s['date']}")
        if c.get("table"):
            for r in c["table"]["rows"]:
                print("   ", " | ".join(r))
        if c.get("bars"):
            print("   ", [(b["name"], b["v"]) for b in c["bars"]["bars"]])
        print("   tested:", c["tested"])
        for x in c["limits"]:
            print("   -", x)
