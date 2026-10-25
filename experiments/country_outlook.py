# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scikit-learn>=1.4"]
# ///
"""Each country's inflation outlook for the next 1, 2, 3, 6 and 12 months, from one model pooled across countries.

Data: FAOSTAT consumer price indices (monthly, general and food, 2015 = 100, about 200 countries; read with
country_oil.fao_levels) and Brent (FRED MCOILBRENTEU, US dollars, monthly average).

Target: the % change in a country's index over the next h months. Everything is worked in 100 x log changes, and
the models predict how far the next h months' annualised rate departs from the last 12 months' rate, so a model
that predicts zero is the naive rule ("the latest 12-month rate continues": (P_t / P_t-12)^(h/12) - 1).

Features at the origin month t (all known at t): the annualised 1-, 3- and 6-month rates minus the 12-month rate;
the 12-month rate; the country's own 5-year mean rate minus its 12-month rate; the cross-country median 12-month
rate minus the country's; own minus partner 12-month rate (food minus all, all minus food); Brent's 1-, 3- and
12-month log changes; the country's own seasonal pattern for the h months ahead (the average departure of the
same calendar months from an even pace over the last five years); month of year (sine, cosine).

Candidates, fitted per kind and horizon, pooled across countries: ridge, a median (least absolute deviation)
linear model, gradient-boosted trees (scikit-learn, squared loss on a clipped target), and the average of the
median model and the trees.

Backtest: rolling origins every 3 months, 2012-01 to 2024-10. At each origin the linear models are refitted on the
rows whose h-month outcome was known by then; the trees are refitted every second origin (6 months), the same way.
Skill = 1 - MAE(model) / MAE(naive) on the h-month % change, origins 2015-01 to 2024-10 (2012-2014 only warm up
the bands). The best candidate per kind and horizon is used; where none beats naive, naive is used.

Hyperinflation: Lebanon, Sudan, South Sudan, Syria, Venezuela and Zimbabwe (currency breaks, redenominations,
hyperinflation spells) are never trained on, scored apart, and forecast with the naive rule. Any country-month
whose 12-month rate is above 50% (or below -33%, the same log distance) is likewise left out of training and of
the main score, and forecast with the naive rule.

Band: the h-month forecast error divided by the country's own volatility (std of its monthly log changes, less their
usual seasonal pattern, over the previous 36 months) times sqrt(h); the 5% and 95% points of that ratio, pooled over
countries and origins, give the 90% band. Coverage is checked out of sample: each origin's band uses only errors already known at that origin.

    uv run experiments/country_outlook.py           # backtest and forecasts; writes notes/country-outlook.json and .md
    uv run experiments/country_outlook.py ablate    # skill with each feature group removed (slower)

Other modules can fit once and forecast any monthly index (IMF CPI divisions, say):

    model = fit({iso: {kind: level}}, brent)        # rule and band per kind and horizon from notes/country-outlook.json
    forecast(level, "food", brent, model, pair=all_level, iso="KEN")  # {"from": "YYYY-MM", "q": {"1": [q05, q50, q95]}}

Kinds other than food and all are fitted on their own data but take the rule and band of "all".
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd

import country_oil as co
import macro_data as md

OUT_JSON = md.ROOT / "notes" / "country-outlook.json"
OUT_MD = md.ROOT / "notes" / "country-outlook.md"
HORIZONS = (1, 2, 3, 6, 12)
KINDS = ("food", "all")
PAIR = {"food": "all", "all": "food"}  # other kinds pair with "all"
FRAGILE = ("LBN", "SDN", "SSD", "SYR", "VEN", "ZWE")
HYPER = 100 * np.log(1.5)  # |12-month log rate| above this (50% a year): naive rule, out of training and the main score
HIGH = 100 * np.log(1.10)  # the high-inflation group: above 10% a year at the origin
ORIGINS = pd.date_range("2012-01-01", "2024-10-01", freq="3MS")
SCORE_FROM = pd.Timestamp("2015-01-01")
STALE_MONTHS = 12  # a country whose latest month is this far behind the newest gets no forecast
CORE = ["d1", "d3", "d6", "r12", "lr"]
FEATURES = CORE + ["med", "gap", "b1", "b3", "b12", "seas", "msin", "mcos"]
FEATURE_TEXT = {"d1": "last month's rate, annualised, minus the 12-month rate", "d3": "the same for 3 months",
                "d6": "the same for 6 months", "r12": "the 12-month rate",
                "lr": "the country's own 5-year mean rate minus its 12-month rate",
                "med": "the cross-country median 12-month rate minus the country's",
                "gap": "own minus partner 12-month rate (food minus all, all minus food)",
                "b1": "Brent's 1-month log change", "b3": "Brent's 3-month log change", "b12": "Brent's 12-month log change",
                "seas": "the country's usual seasonal departure over the h months ahead (last five years)",
                "msin": "month of year (sine)", "mcos": "month of year (cosine)"}
GROUPS = {"own": ["d1", "d3", "d6", "lr", "seas"], "world": ["med"], "gap": ["gap"], "brent": ["b1", "b3", "b12"],
          "month": ["msin", "mcos"]}
RULES = ("ridge", "lad", "gbm", "blend")
# squared loss on a clipped target: absolute loss scored within 0.005 of it on a 2018 split and was up to ten times slower
GBM = {"max_iter": 150, "learning_rate": 0.06, "max_leaf_nodes": 15, "min_samples_leaf": 200,
       "l2_regularization": 1.0, "random_state": 0}
CLIP = (2.5, 97.5)  # training-target percentiles the trees are fitted within
GBM_EVERY = 2  # the trees are refitted every second origin (6 months), on outcomes known by then
Q = (0.05, 0.95)


CAVEATS = ("prices are FAOSTAT's current vintage, not what was published at each origin, so the backtest flatters "
           "every rule a little (naive included). Forecasts start at each country's latest price month and only use Brent up "
           "to that month; Brent's moves after it are not in them, so add the oil link on top for a scenario. "
           "Bands for the six fragile countries and for inflation above 50% come from the naive rule's errors elsewhere and "
           "under-cover there (see the fragile column).")


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def pct(x):
    """100 x log change -> % change."""
    return 100 * np.expm1(np.asarray(x, dtype=float) / 100)


# ------------------------------------------------------------------------------------------------ features
def log_wide(levels: dict, kind: str) -> pd.DataFrame:
    """100 x log index, months x countries, on a gap-free monthly index."""
    cols = {iso: d[kind][d[kind] > 0] for iso, d in levels.items() if kind in d and (d[kind] > 0).any()}
    if not cols:
        return pd.DataFrame()
    df = pd.DataFrame(cols)
    idx = pd.date_range(df.index.min(), df.index.max(), freq="MS")
    return 100 * np.log(df.reindex(idx))


def cross_median(L: pd.DataFrame, min_n: int = 20) -> pd.Series:
    """Median 12-month rate across countries (the six fragile ones left out), each month."""
    r12 = (L - L.shift(12)).drop(columns=[c for c in FRAGILE if c in L.columns])
    m = r12.median(axis=1)
    m[r12.notna().sum(axis=1) < min_n] = np.nan
    return m


def brent_changes(brent: pd.Series, idx: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    b = 100 * np.log(brent.dropna().resample("MS").mean())
    b = b.reindex(pd.date_range(min(b.index[0], idx[0]), max(b.index[-1], idx[-1]), freq="MS"))
    return {f"b{k}": (b - b.shift(k)).reindex(idx).to_numpy() for k in (1, 3, 12)}


def panel(L: pd.DataFrame, brent: pd.Series, med: pd.Series | None, pair: pd.DataFrame | None, h: int) -> pd.DataFrame:
    """Long frame indexed (month, iso): features at each origin month, the target y (annualised h-month rate minus
    the 12-month rate) and sigma, the band's scale: the std of the country's monthly log changes, less their usual
    seasonal pattern, over the previous 36 months, times sqrt(h)."""
    idx = L.index
    ch = lambda k: L - L.shift(k)
    r12 = ch(12)
    f = {"d1": 12 * ch(1) - r12, "d3": 4 * ch(3) - r12, "d6": 2 * ch(6) - r12, "r12": r12,
         "lr": (ch(60) / 5).fillna(ch(36) / 3).fillna(ch(24) / 2) - r12}
    m = med.reindex(idx).ffill(limit=6) if med is not None else pd.Series(np.nan, index=idx)
    f["med"] = (-r12).add(m, axis=0)
    if pair is not None and not pair.empty:
        p = pair.reindex(pd.date_range(min(pair.index[0], idx[0]), max(pair.index[-1], idx[-1]), freq="MS"))
        f["gap"] = r12 - (p - p.shift(12)).reindex(index=idx, columns=L.columns)
    else:
        f["gap"] = r12 * np.nan
    if h < 12:
        acc = []
        for j in range(1, 6):
            start, end = L.shift(12 * j), L.shift(12 * j - h)
            acc.append(((end - start) - h / 12 * (end - L.shift(12 * j - h + 12))).to_numpy())
        a = np.stack(acc)
        n = np.isfinite(a).sum(0)
        s = np.where(n >= 2, np.where(np.isfinite(a), a, 0.0).sum(0) / np.maximum(n, 1), np.nan)
        f["seas"] = pd.DataFrame(12 / h * s, index=idx, columns=L.columns)
    else:
        f["seas"] = r12 * 0.0
    f["y"] = 12 / h * (L.shift(-h) - L) - r12
    d1 = ch(1)
    past = [d1.shift(12 * j) for j in range(1, 6)]  # the same calendar month in the last five years
    n = sum(x.notna().astype(int) for x in past)
    seasonal = (sum(x.fillna(0.0) for x in past) / n.clip(lower=1)).where(n >= 2, 0.0)
    f["sigma"] = ((d1 - seasonal).rolling(36, min_periods=12).std() * np.sqrt(h)).clip(lower=0.05)
    out = pd.concat({k: v.stack(future_stack=True) for k, v in f.items()}, axis=1)
    out.index.names = ["month", "iso"]
    out = out[out["r12"].notna()]
    months = out.index.get_level_values(0)
    for k, v in brent_changes(brent, idx).items():
        out[k] = pd.Series(v, index=idx).reindex(months).to_numpy()
    out["msin"], out["mcos"] = np.sin(2 * np.pi * months.month / 12), np.cos(2 * np.pi * months.month / 12)
    for k in ("med", "gap", "seas", "b1", "b3", "b12"):
        out[k] = out[k].fillna(0.0)
    return out


# -------------------------------------------------------------------------------------------------- models
def fit_linear(X: np.ndarray, y: np.ndarray, lad: bool, alpha: float = 10.0, iters: int = 25) -> dict:
    """Ridge, or median regression by iteratively reweighted least squares, on clipped, standardised features."""
    lo, hi = np.nanpercentile(X, 1, axis=0), np.nanpercentile(X, 99, axis=0)
    Xc = np.clip(X, lo, hi)
    mu, sd = Xc.mean(0), Xc.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(Xc)), (Xc - mu) / sd])
    y = np.clip(y, *np.percentile(y, [1, 99]))
    pen = alpha * np.eye(Z.shape[1])
    pen[0, 0] = 0.0
    w = np.ones(len(y))
    for _ in range(iters if lad else 1):
        beta = np.linalg.solve(Z.T @ (Z * w[:, None]) + pen, Z.T @ (w * y))
        if lad:
            w = 1 / np.maximum(np.abs(y - Z @ beta), 0.05 * np.median(np.abs(y)) + 1e-6)
    return {"lo": lo, "hi": hi, "mu": mu, "sd": sd, "beta": beta}


def predict_linear(m: dict, X: np.ndarray) -> np.ndarray:
    Z = (np.clip(X, m["lo"], m["hi"]) - m["mu"]) / m["sd"]
    return m["beta"][0] + Z @ m["beta"][1:]


def fit_gbm(X: np.ndarray, y: np.ndarray):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(**GBM).fit(X, np.clip(y, *np.percentile(y, CLIP)))


def fit_models(D: pd.DataFrame, features=FEATURES, rules=RULES, gbm=None) -> dict:
    X, y = D[features].to_numpy(float), D["y"].to_numpy(float)
    m = {"features": list(features)}
    if "ridge" in rules:
        m["ridge"] = fit_linear(X, y, lad=False)
    if {"lad", "blend"} & set(rules):
        m["lad"] = fit_linear(X, y, lad=True)
    if {"gbm", "blend"} & set(rules):
        m["gbm"] = gbm if gbm is not None else fit_gbm(X, y)
    return m


def predict_models(m: dict, D: pd.DataFrame) -> dict[str, np.ndarray]:
    X = D[m["features"]].to_numpy(float)
    out = {"naive": np.zeros(len(D))}
    for k in ("ridge", "lad"):
        if k in m:
            out[k] = predict_linear(m[k], X)
    if "gbm" in m:
        out["gbm"] = m["gbm"].predict(X)
    if "lad" in m and "gbm" in m:
        out["blend"] = (out["lad"] + out["gbm"]) / 2
    return out


def trainable(P: pd.DataFrame) -> pd.Series:
    iso = P.index.get_level_values(1)
    return P[CORE + ["y"]].notna().all(axis=1) & ~iso.isin(FRAGILE) & (P["r12"].abs() <= HYPER)


# ------------------------------------------------------------------------------------------------ backtest
def backtest(levels: dict, brent: pd.Series, kinds=KINDS, horizons=HORIZONS, origins=ORIGINS, features=FEATURES,
             rules=RULES, gbm_every: int = GBM_EVERY, log=print) -> pd.DataFrame:
    """One row per (kind, h, origin, country): 100 x log h-month change, actual and each rule's forecast."""
    rows = []
    for kind in kinds:
        L, pair = log_wide(levels, kind), log_wide(levels, PAIR.get(kind, "all"))
        med = cross_median(L)
        for h in horizons:
            t0 = time.time()
            P = panel(L, brent, med, pair, h)
            ok = P[CORE + ["y"]].notna().all(axis=1)
            train = trainable(P)
            month = P.index.get_level_values(0)
            gbm = None
            for i, T in enumerate(origins):
                tr = train & (month <= T - pd.DateOffset(months=h))
                te = ok & (month == T)
                if tr.sum() < 500 or not te.any():
                    continue
                D = P[tr]
                if {"gbm", "blend"} & set(rules) and (gbm is None or i % gbm_every == 0):
                    gbm = fit_gbm(D[list(features)].to_numpy(float), D["y"].to_numpy(float))
                m = fit_models(D, features, rules, gbm=gbm)
                E = P[te]
                pr = predict_models(m, E)
                r12 = E["r12"].to_numpy()
                b = pd.DataFrame({"kind": kind, "h": h, "origin": T, "iso": E.index.get_level_values(1),
                                  "r12": r12, "sigma": E["sigma"].to_numpy(), "actual": h / 12 * (r12 + E["y"].to_numpy())})
                for k, v in pr.items():
                    b[k] = h / 12 * (r12 + v)
                rows.append(b)
            log(f"  {kind} h={h}: {time.time() - t0:.1f}s")
    B = pd.concat(rows, ignore_index=True)
    B["fragile"] = B["iso"].isin(FRAGILE) | (B["r12"].abs() > HYPER)
    B["high"] = ~B["fragile"] & (B["r12"] > HIGH)
    return B


def add_bands(B: pd.DataFrame, rules=("naive",) + RULES) -> pd.DataFrame:
    """Out-of-sample 90% bands: at each origin, quantiles of z = error / sigma over the non-fragile rows
    whose outcome was known by then."""
    B = B.copy()
    for rule in rules:
        if rule not in B:
            continue
        lo, hi = np.full(len(B), np.nan), np.full(len(B), np.nan)
        z = (B["actual"] - B[rule]) / B["sigma"]
        for (kind, h), g in B.groupby(["kind", "h"]):
            main = g[~g["fragile"]]
            zm = z[main.index]
            ends = main["origin"] + pd.DateOffset(months=h)
            for T, gt in g.groupby("origin"):
                past = zm[(ends <= T).to_numpy()].dropna()
                if len(past) < 300:
                    continue
                q = np.quantile(past, Q)
                s = gt["sigma"].to_numpy()
                lo[gt.index], hi[gt.index] = gt[rule].to_numpy() + q[0] * s, gt[rule].to_numpy() + q[1] * s
        B[f"in_{rule}"] = np.where(np.isnan(lo), np.nan, ((B["actual"] >= lo) & (B["actual"] <= hi)).astype(float))
    return B


def z_quantiles(B: pd.DataFrame, rule: str, kind: str, h: int) -> list[float]:
    g = B[(B["kind"] == kind) & (B["h"] == h) & ~B["fragile"]]
    z = ((g["actual"] - g[rule]) / g["sigma"]).dropna()
    return [round(float(v), 4) for v in np.quantile(z, Q)]


def mae(g: pd.DataFrame, rule: str) -> float:
    return float(np.mean(np.abs(pct(g["actual"]) - pct(g[rule]))))


def summarise(B: pd.DataFrame, rules=RULES) -> dict:
    """{kind: {h: {...}}}: the winning rule's skill against naive, pooled and by group, with band coverage."""
    S = B[B["origin"] >= SCORE_FROM]
    out = {}
    for (kind, h), g in S.groupby(["kind", "h"]):
        main = g[~g["fragile"]]
        cand = {r: round(1 - mae(main, r) / mae(main, "naive"), 4) for r in rules if r in main}
        best = max(cand, key=cand.get)
        rule = best if cand[best] > 0 else "naive"

        def block(x: pd.DataFrame, r: str) -> dict:
            if x.empty:
                return {"skill_vs_naive": None, "mae_model": None, "mae_naive": None, "n": 0, "coverage90": None}
            mm, mn = mae(x, r), mae(x, "naive")
            cov = x[f"in_{r}"].dropna() if f"in_{r}" in x else pd.Series(dtype=float)
            return {"skill_vs_naive": round(1 - mm / mn, 4), "mae_model": round(mm, 4), "mae_naive": round(mn, 4),
                    "n": len(x), "coverage90": round(float(cov.mean()), 4) if len(cov) else None}

        frag = g[g["fragile"]]
        yr = main["origin"].dt.year
        by_year = {str(y): {"skill_vs_naive": round(1 - mae(x, rule) / mae(x, "naive"), 3),
                            "coverage90": round(float(x[f"in_{rule}"].mean()), 3) if x.get(f"in_{rule}", pd.Series()).notna().any() else None}
                   for y, x in main.groupby(yr)}
        out.setdefault(kind, {})[str(h)] = block(main, rule) | {"by_origin_year": by_year,
            "model": rule, "candidates": cand, "z": z_quantiles(B, rule, kind, h), "z_naive": z_quantiles(B, "naive", kind, h),
            "groups": {"high": block(main[main["high"]], rule), "rest": block(main[~main["high"]], rule),
                       # fragile rows are forecast with naive; the model's skill there is for information only
                       "fragile": block(frag, best) | {"coverage90": block(frag, "naive")["coverage90"], "used": "naive"}}}
    return out


# ----------------------------------------------------------------------------------------- fit / forecast
def fit(levels: dict, brent: pd.Series, backtest: dict | None = None, features=FEATURES) -> dict:
    """Fit the pooled models once on every row whose outcome is known. levels: {iso: {kind: monthly index Series}}.
    backtest: the backtest section of notes/country-outlook.json (rule and band per kind and horizon); read from
    there when not given. Kinds missing from it use the rule and band of "all"."""
    if backtest is None:
        backtest = json.loads(OUT_JSON.read_text(encoding="utf-8"))["backtest"]
    horizons = [int(h) for h in backtest.get("all", next(iter(backtest.values())))]
    kinds = sorted({k for d in levels.values() for k in d})
    model = {"med": {}, "kinds": {}, "horizons": list(horizons)}
    for kind in kinds:
        L, pair = log_wide(levels, kind), log_wide(levels, PAIR.get(kind, "all"))
        model["med"][kind] = cross_median(L)
        bt = backtest.get(kind, backtest.get("all"))
        for h in horizons:
            spec = bt[str(h)]
            rule = spec["model"]
            P = panel(L, brent, model["med"][kind], pair, h)
            D = P[trainable(P)]
            m = fit_models(D, features, (rule,)) if rule != "naive" else {"features": list(features)}
            model["kinds"].setdefault(kind, {})[str(h)] = {"rule": rule, "m": m, "z": spec["z"], "z_naive": spec["z_naive"]}
    return model


def forecast(level: pd.Series, kind: str, brent: pd.Series, model: dict, pair: pd.Series | None = None,
             iso: str | None = None, at: str | None = None) -> dict | None:
    """{"from": "YYYY-MM", "q": {"h": [q05, q50, q95]}, "rule": {"h": rule}}: % change over the next h months from
    the series' latest month (or month `at`, YYYY-MM). pair: the same country's partner index (all items for food
    and other kinds, food for all), used for the gap feature; without it the gap is taken as zero. A fragile country
    (iso in FRAGILE) or a 12-month rate beyond +-50% gets the naive rule and its band."""
    key = iso or "x"
    L = log_wide({key: {kind: level}}, kind)
    if L.empty:
        return None
    P_pair = log_wide({key: {"p": pair}}, "p") if pair is not None else None
    t = pd.Timestamp(at + "-01") if at else L[key].last_valid_index()
    return forecast_wide(L, P_pair, kind, brent, model, {key: t}).get(key)


def forecast_wide(L: pd.DataFrame, pair: pd.DataFrame | None, kind: str, brent: pd.Series, model: dict,
                  at: dict | None = None) -> dict[str, dict]:
    """forecast() for many countries at once: L and pair as from log_wide, at = {column: origin month} (default:
    each column's latest month). Columns named after a fragile country get the naive rule."""
    kinds = model["kinds"]
    spec_k = kinds.get(kind, kinds.get("all"))
    med = model["med"].get(kind, model["med"].get("all"))
    at = at or {c: L[c].last_valid_index() for c in L.columns}
    out: dict[str, dict] = {}
    for h in model["horizons"]:
        spec = spec_k[str(h)]
        P = panel(L, brent, med, pair, h)
        keys = [(t, c) for c, t in at.items() if t is not None and (t, c) in P.index]
        rows = P.loc[keys] if keys else P.iloc[:0]
        rows = rows[rows[CORE].notna().all(axis=1) & np.isfinite(rows["sigma"])]
        if rows.empty:
            continue
        r12 = rows["r12"].to_numpy()
        naive = rows.index.get_level_values(1).isin(FRAGILE) | (np.abs(r12) > HYPER)
        rule = spec["rule"]
        yhat = predict_models(spec["m"], rows)[rule] if rule != "naive" else np.zeros(len(rows))
        mid = h / 12 * (r12 + np.where(naive, 0.0, yhat))
        z = np.where(naive[:, None], spec["z_naive"], spec["z"])
        sd = rows["sigma"].to_numpy()
        lo, hi = pct(mid + z[:, 0] * sd), pct(mid + z[:, 1] * sd)
        for i, (t, c) in enumerate(rows.index):
            o = out.setdefault(c, {"from": t.strftime("%Y-%m"), "q": {}, "rule": {}})
            o["q"][str(h)] = [round(float(lo[i]), 2), round(float(pct(mid[i])), 2), round(float(hi[i]), 2)]
            o["rule"][str(h)] = "naive" if naive[i] else rule
    return {c: o for c, o in out.items() if len(o["q"]) == len(model["horizons"])}


# ------------------------------------------------------------------------------------------------- running
def load() -> tuple[dict, pd.Series]:
    ref = json.loads(md._get(co.CT_REPORTERS, co.RAW / "reporters.json").read_text(encoding="utf-8"))["results"]
    m49_iso = {r["reporterCode"]: r["reporterCodeIsoAlpha3"].strip() for r in ref if not r.get("isGroup")} | co.M49_FIX
    return co.fao_levels(md._get(co.FAO_URL, co.FAO_ZIP), m49_iso), md.fetch_fred("MCOILBRENTEU")


def ablate(levels: dict, brent: pd.Series) -> dict:
    """Pooled skill of the median linear model and the trees with each feature group removed (origins every 6 months)."""
    out = {}
    origins = ORIGINS[(ORIGINS >= SCORE_FROM) & (ORIGINS.month.isin([1, 7]))]
    for name, drop in [("all features", [])] + list(GROUPS.items()):
        feats = [f for f in FEATURES if f not in drop]
        B = backtest(levels, brent, origins=origins, features=feats, rules=("lad", "gbm"), log=lambda *_: None)
        S = B[~B["fragile"]]
        out[name] = {f"{k} {h}": {r: round(1 - mae(g, r) / mae(g, "naive"), 3) for r in ("lad", "gbm")}
                     for (k, h), g in S.groupby(["kind", "h"])}
        print(name, json.dumps(out[name]))
    return out


def report(d: dict) -> str:
    lines = ["# Country inflation outlook", "",
             f"_Generated by `experiments/country_outlook.py` on {d['generated']}. Nothing here is synthetic._", "",
             f"Sources: {d['sources']}.", "", f"Method: {d['method']}.", "",
             "Features, all known at the origin month: " + "; ".join(FEATURE_TEXT.get(f, f) for f in d["features"]) + ".", "",
             f"Caveats: {CAVEATS}", "",
             "## Backtest", "",
             "Skill = 1 - MAE(model) / MAE(naive) on the h-month % change, pooled over countries and origins every 3 months "
             "from 2015-01 to 2024-10; above zero beats naive. Naive: the latest 12-month rate continues. "
             f"{d['exclusions']}", "",
             "| Prices | h | Model used | Skill | MAE model | MAE naive | n | 90% band coverage | Candidates (skill) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for kind, v in d["backtest"].items():
        for h, s in v.items():
            cand = ", ".join(f"{k} {x:+.3f}" for k, x in s["candidates"].items())
            lines.append(f"| {kind} | {h} | {s['model']} | {s['skill_vs_naive']:+.3f} | {s['mae_model']:.2f} | "
                         f"{s['mae_naive']:.2f} | {s['n']} | {s['coverage90']:.0%} | {cand} |")
    lines += ["", "By group (skill of the model used, and its band coverage):", "",
              "| Prices | h | High inflation (>10%) | n | coverage | Rest | n | coverage | Fragile six and >50%: best model's skill (not used) | n | naive band coverage |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    sk = lambda x: "n/a" if x is None else f"{x:+.3f}"
    cv = lambda x: "n/a" if x is None else f"{x:.0%}"
    for kind, v in d["backtest"].items():
        for h, s in v.items():
            g = s["groups"]
            lines.append(" | ".join([f"| {kind}", h] + [f"{sk(g[k]['skill_vs_naive'])} | {g[k]['n']} | {cv(g[k]['coverage90'])}"
                                                       for k in ("high", "rest", "fragile")]) + " |")
    lines += ["", "By origin year, 12-month horizon (skill of the model used / band coverage):", "",
              "| Prices | " + " | ".join(d["backtest"]["all"]["12"]["by_origin_year"]) + " |",
              "|---|" + "---|" * len(d["backtest"]["all"]["12"]["by_origin_year"])]
    for kind, v in d["backtest"].items():
        lines.append(f"| {kind} | " + " | ".join(f"{x['skill_vs_naive']:+.2f} / {cv(x['coverage90'])}"
                                                  for x in v["12"]["by_origin_year"].values()) + " |")
    lines += ["", d["reading"], "", "## Forecasts", "",
              f"{len(d['countries'])} countries, from each one's latest month ({d['latest']} for most). "
              f"No forecast (latest month more than {STALE_MONTHS} months old): {', '.join(d['skipped']) or 'none'}. "
              "q values are the % change over the next h months: 5th percentile, median, 95th percentile.", "",
              "| Country | Prices | From | 3 mo | 12 mo |", "|---|---|---|---|---|"]
    for iso in ("USA", "GBR", "DEU", "IND", "CHN", "JPN", "PAK", "EGY", "KEN", "NGA", "TUR", "ARG", "IRN", "LBN"):
        for kind in KINDS:
            c = d["countries"].get(iso, {}).get(kind)
            if c:
                f = ["{1:+.1f}% ({0:+.1f} to {2:+.1f})".format(*c["q"][h]) for h in ("3", "12")]
                lines.append(f"| {iso} | {kind} | {c['from']} | {f[0]} | {f[1]} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.time()
    levels, brent = load()
    if what == "ablate":
        ablate(levels, brent)
        return
    print(f"backtest: {len(levels)} countries, {len(ORIGINS)} origins")
    B = add_bands(backtest(levels, brent, horizons=HORIZONS, origins=ORIGINS))
    bt = summarise(B)
    for kind, v in bt.items():
        for h, s in v.items():
            g = s["groups"]
            print(f"{kind:4} h={h:>2} {s['model']:6} skill {s['skill_vs_naive']:+.3f} cov {s['coverage90']:.2f} "
                  f"high {g['high']['skill_vs_naive']:+.3f} rest {g['rest']['skill_vs_naive']:+.3f} "
                  f"fragile(best) {g['fragile']['skill_vs_naive']:+.3f}  {s['candidates']}")
    print("fitting the final models")
    model = fit(levels, brent, bt)
    newest = max(s.index[-1] for d in levels.values() for s in d.values())
    countries: dict[str, dict] = {}
    for kind in KINDS:
        L = log_wide(levels, kind)
        at = {c: L[c].last_valid_index() for c in L.columns}
        at = {c: t for c, t in at.items() if t is not None and t >= newest - pd.DateOffset(months=STALE_MONTHS)}
        for iso, f in forecast_wide(L, log_wide(levels, PAIR[kind]), kind, brent, model, at).items():
            countries.setdefault(iso, {})[kind] = f
    countries = dict(sorted(countries.items()))
    skipped = sorted(set(levels) - set(countries))
    fetched = datetime.fromtimestamp(co.FAO_ZIP.stat().st_mtime, UTC).strftime("%Y-%m-%d")
    brent_at = datetime.fromtimestamp((md.RAW / "fred_MCOILBRENTEU.csv").stat().st_mtime, UTC).strftime("%Y-%m-%d")
    wins = {k: {h: s["model"] for h, s in v.items()} for k, v in bt.items()}
    d = {"generated": today(), "script": "experiments/country_outlook.py",
         "sources": (f"FAOSTAT consumer price indices (general and food, 2015 = 100, monthly; https://www.fao.org/faostat/en/#data/CP), "
                     f"fetched {fetched}; Brent: FRED MCOILBRENTEU (monthly average, US$), fetched {brent_at}"),
         "method": ("one model per price kind and horizon, pooled across countries, predicting how far the next h months' "
                    "annualised log rate departs from the last 12 months'; candidates ridge, median (LAD) linear, gradient-"
                    "boosted trees (squared loss, clipped target) and the LAD/trees average; rolling-origin backtest every 3 months, "
                    "linear models refitted at each origin and trees every 6 months, on outcomes known by then; the best candidate per kind and horizon is used, naive where "
                    "none beats it; 90% band = forecast + pooled 5%/95% quantiles of error / (the country's "
                    "own 36-month volatility of seasonally adjusted monthly changes x sqrt h)"),
         "exclusions": ("Lebanon, Sudan, South Sudan, Syria, Venezuela and Zimbabwe are never trained on and get the naive rule; "
                        "so does any country-month with 12-month inflation above 50% (or below -33%). Those rows are scored "
                        "apart (the fragile column), not in the pooled skill."),
         "features": FEATURES, "models_used": wins, "backtest": bt, "latest": newest.strftime("%Y-%m"),
         "skipped": skipped, "countries": countries}
    d["reading"] = reading(bt)
    OUT_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(report(d), encoding="utf-8")
    print("wrote", OUT_JSON, "and", OUT_MD, f"in {time.time() - t0:.0f}s")


def reading(bt: dict) -> str:
    """Plain sentences on the backtest table."""
    names = {"ridge": "ridge", "lad": "the median linear model", "gbm": "the gradient-boosted trees",
             "blend": "the average of the median linear model and the trees", "naive": "naive"}
    cells = [(k, int(h), s) for k, v in bt.items() for h, s in v.items()]
    beat = [f"{k} {h} mo" for k, h, s in cells if s["model"] != "naive"]
    lost = [f"{k} {h} mo" for k, h, s in cells if s["model"] == "naive"]
    wins = pd.Series([s["model"] for _, _, s in cells]).value_counts()
    sk = sorted(cells, key=lambda c: c[2]["skill_vs_naive"])
    cov = [s["coverage90"] for _, _, s in cells]
    hi = [s["groups"]["high"]["skill_vs_naive"] for _, _, s in cells]
    rest = [s["groups"]["rest"]["skill_vs_naive"] for _, _, s in cells]
    out = [f"The pooled model beats naive at {len(beat)} of {len(cells)} kind-horizon cells"
           + (f"; nothing beat naive at {', '.join(lost)}, so the outlook uses naive there." if lost else ".")]
    out.append("Winner by cell: " + ", ".join(f"{names[r]} {n}" for r, n in wins.items()) + ".")
    out.append(f"Skill runs from {sk[0][2]['skill_vs_naive']:+.3f} ({sk[0][0]} {sk[0][1]} mo) to "
               f"{sk[-1][2]['skill_vs_naive']:+.3f} ({sk[-1][0]} {sk[-1][1]} mo): the model cuts the naive rule's mean "
               f"absolute miss by that share.")
    out.append(f"It helps in both groups: {min(hi):+.3f} to {max(hi):+.3f} where inflation was above 10% at the origin, "
               f"{min(rest):+.3f} to {max(rest):+.3f} elsewhere.")
    out.append(f"Out-of-sample 90% band coverage is {min(cov):.0%} to {max(cov):.0%} across cells.")
    yr = [(f"{k} {y}", x["coverage90"]) for k, v in bt.items() if "12" in v for y, x in v["12"]["by_origin_year"].items()
          if x["coverage90"] is not None]
    worst = sorted(yr, key=lambda t: t[1])[:3]
    if worst and min(cov) < 0.87:
        out.append("At 12 months the shortfall sits in a few origin years (lowest: "
                   + ", ".join(f"{y} {c:.0%}" for y, c in worst) + "), when outcomes ran beyond the errors the band "
                   "had seen before; the skill also varies by year, so the gain is an average over calm and turbulent spells.")
    return " ".join(out)


if __name__ == "__main__":
    main()
