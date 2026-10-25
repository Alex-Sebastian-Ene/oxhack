# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Refined-product margins for the knock-on chain, so the fuel targets are not driven by Brent alone.

In the 2026 Hormuz closure, diesel, jet fuel and the refinery PPI rose 9-26 points more than every
knock-on model expected, even given the real Brent path (notes/verification.md, section 5, branch
claude/silly-fermat-ac28f6). Product margins (crack spreads) widened, and nothing in the chain
modelled them. This layer adds them.

Data: daily spot prices from the EIA's spot price workbook (PET_PRI_SPT_S1_D.xls, no key), in $/bbl:
    diesel    New York Harbor ULSD (EER_EPD2DXL0_PF4_Y35NY_DPG) from 2006-06; before that New York
              Harbor No. 2 heating oil (EER_EPD2F_PF4_Y35NY_DPG), spliced on the log ratio
    jet       US Gulf Coast kerosene-type jet fuel (EER_EPJK_PF4_RGC_DPG), the series of FRED DJFUELUSGULF
    gasoline  US Gulf Coast conventional regular gasoline (EER_EPMRU_PF4_RGC_DPG)
    rbob      Los Angeles reformulated RBOB regular gasoline (EER_EPMRR_PF4_Y05LA_DPG), from 2003-03
Crack spread = product - Brent, in $/bbl, from monthly means of daily prices. Brent is the panel's
daily FRED DCOILBRENTEU. The model works on the log ratio r = log(product / Brent), so a product's
monthly log change is exactly Brent's plus the change in r.

The margin model is fitted per product, month by month, on each fold's training months from 1990-06:
    dr[t] = c + seasonal + kappa gap[t-1] + phi dr[t-1] + gamma sticky[t] + beta x[t] + crisis[t] + e[t]
    e[t] = exp((a + lambda v[t]) / 2) z[t]
- gap is r less its mean over the last five years. kappa < 0 means margins revert to that local
  mean, with a half-life of a few months. (Five years was chosen over three and ten on the
  margins' own rolling errors, 2008-2025; a fixed mean left a drift as margins rose over the decades.)
- sticky is the change in r if the dollar crack stayed put while Brent moved by x. gamma = 1 means a
  fully sticky dollar margin; gamma = 0 means a margin proportional to Brent.
- v is Brent volatility (log mean |x| over 3 months, standardised). It sets the width of the band.
- crisis is the excess margin change in the 12 months after the onset of a major supply disruption.
  The events are the IEA's collective stock actions (1991, 2005, 2011, 2022, 2026), each dated by the
  disruption's first full month. The other terms are fitted on months outside these windows. Each
  earlier event's residuals give its crisis path, and a draw takes one past event's path, so the
  band spans the past crises.
- z: standardised training residuals, resampled.

Into the chain. The fuel targets map onto product prices, fitted on training months only:
    ind_gasdesw          US retail diesel: diesel, lags 0-1
    ind_djfuelusgulf     jet fuel spot: jet (an identity)
    ind_pcu324110324110  refinery PPI: diesel, gasoline and jet, lags 0-1
Two ways in, both scored on the folds (notes/margins-results.md):
- member (recommended): the mapping driven by the Brent path plus a simulated margin path, as a
  fourth equal-weight member for the fuel targets. It beats the chain in every fold.
- correction: each ensemble draw plus the mapped *margin news*. The news is the margin model's mean
  path from the actual state (the gap, momentum, season and any crisis) minus the same model, on
  the same Brent path, from a neutral state (a margin at its five-year mean with nothing of its
  own to tell). The knock-on members, fed only Brent, already carry the second part. It helps from
  2019 on and hurts before, so it is reported, not used.

Draw n of every layer uses oil path n, as in macro_chain.py.

    uv run experiments/margins.py data      # fetch, notes/margins-monthly.csv
    uv run experiments/margins.py fold 3    # -> runs/macro/margins-fold-3.json (needs runs/macro/chain-3-<member>.npz)
    BAYES_CHAINS=4 BAYES_WARMUP=1000 uv run experiments/margins.py replay   # 2026 closure from 2026-02
    uv run experiments/margins.py report    # notes/margins-results.md
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import macro_data as md

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
SPOT_URL = "https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_D.xls"
SPOT_FILE = "eia_PET_PRI_SPT_S1_D.xls"
GAL = 42.0  # gallons per barrel
SERIES = {  # key: (EIA source key, name)
    "ulsd_nyh": ("EER_EPD2DXL0_PF4_Y35NY_DPG", "New York Harbor ultra-low-sulfur No. 2 diesel"),
    "heating_oil_nyh": ("EER_EPD2F_PF4_Y35NY_DPG", "New York Harbor No. 2 heating oil"),
    "jet_usgc": ("EER_EPJK_PF4_RGC_DPG", "US Gulf Coast kerosene-type jet fuel"),
    "gasoline_usgc": ("EER_EPMRU_PF4_RGC_DPG", "US Gulf Coast conventional regular gasoline"),
    "rbob_la": ("EER_EPMRR_PF4_Y05LA_DPG", "Los Angeles reformulated RBOB regular gasoline"),
}
PRODUCTS = {"diesel": ("ulsd_nyh", "heating_oil_nyh"), "jet": ("jet_usgc", None),
            "gasoline": ("gasoline_usgc", None), "rbob": ("rbob_la", None)}  # (main, spliced before it starts)
SPLICE = 24  # months of overlap that set the splice offset
TARGETS = {"ind_gasdesw": ("diesel",), "ind_djfuelusgulf": ("jet",),
           "ind_pcu324110324110": ("diesel", "gasoline", "jet")}
# Major supply disruptions: the IEA's collective actions (1991, 2005, 2011, twice in 2022, and
# 11 March 2026), each dated by the first full month of the disruption it answered.
EVENTS = (("1990-08", "Iraq invades Kuwait (IEA action January 1991)"),
          ("2005-09", "Hurricanes Katrina and Rita (IEA action September 2005)"),
          ("2011-03", "Libyan civil war (IEA action June 2011)"),
          ("2022-03", "Russia invades Ukraine (IEA actions March and April 2022)"),
          ("2026-03", "Hormuz closure (IEA action 11 March 2026)"))
CRISIS_MONTHS = 12
FIT_START = pd.Timestamp("1990-06-01")  # jet starts 1990-04; two months of lags
REF_START = pd.Timestamp("2001-01-01")  # the knock-on panel's first training month
AHEAD = 12
FEATURES = ("const", "sin1", "cos1", "sin2", "cos2", "gap", "momentum", "sticky", "brent")
LOCAL, LOCAL_MIN = 60, 3  # margins revert to their mean over the last five years (from 3 months of data)
VOL_FLOOR = 0.05  # as macro_bayes.VOL_FLOOR, on |x| / sd
LOST_2026 = 82.0  # oil_paths.LOST_2026: points of Hormuz flow lost in 2026
MEMBERS = ("bayes_own", "global_lin", "global")  # the recommended ensemble of macro_chain.py
MODES = ("whatif", "levy")
# base: the chain; margin: + margin news; member: + the margin member (4 equal); member_neutral: the
# same member on a margin with nothing of its own to tell (is it the margins or the product structure?);
# member_only: the margin member alone
VARIANTS = ("base", "margin", "margin_nocrisis", "member", "member_nocrisis", "member_neutral", "member_only")
MEMBER_VARIANTS = ("member", "member_nocrisis", "member_neutral")
SEED = 4242


# --- data ------------------------------------------------------------------------------------

def daily_spot() -> tuple[dict[str, pd.Series], str]:
    """Every daily series in the EIA spot workbook, by source key, in the file's units, and the
    date the file was fetched (cached under data/raw/macro/, git-ignored)."""
    path = md._get(SPOT_URL, md.RAW / SPOT_FILE)
    out = {}
    book = pd.ExcelFile(path)
    for sheet in book.sheet_names:
        if not sheet.startswith("Data"):
            continue
        df = pd.read_excel(book, sheet_name=sheet, header=None)
        dates = pd.to_datetime(df.iloc[3:, 0])
        for col in range(1, df.shape[1]):
            s = pd.Series(pd.to_numeric(df.iloc[3:, col], errors="coerce").values, index=dates)
            out[str(df.iloc[1, col])] = s.dropna()
    return out, datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


def build(brent: pd.Series, spot: dict[str, pd.Series], start: str = "1987-01-01") -> dict:
    """Monthly arrays on a calendar index: Brent ($/bbl, monthly mean), its log change x, and per
    product its price, crack ($/bbl) and log ratio r = log(product / Brent)."""
    b = brent.resample("MS").mean()
    idx = pd.date_range(start, b.index.max(), freq="MS")
    B = b.reindex(idx)
    price = {k: (spot[code] * GAL).resample("MS").mean().reindex(idx) for k, (code, _) in SERIES.items() if code in spot}
    r, used = {}, {}
    for p, (main, splice) in PRODUCTS.items():
        rm = np.log(price[main]) - np.log(B)
        used[p] = pd.Series(main, index=idx).where(rm.notna(), "")
        if splice:
            rm[rm.first_valid_index()] = np.nan  # the main series' first month may be partial
            rs = np.log(price[splice]) - np.log(B)
            both = rm.notna() & rs.notna()
            offset = float((rm - rs)[both].iloc[:SPLICE].mean())
            before = idx < rm.first_valid_index()
            rm = rm.where(~before, rs + offset)
            used[p] = used[p].where(~before | rs.isna(), f"{splice} + {offset:.4f}")
        r[p] = rm.values
    return {"index": idx, "brent": B.values, "x": np.log(B).diff().values, "price": {k: v.values for k, v in price.items()},
            "r": r, "used": used}


def margins_data() -> dict:
    import oil_paths as op

    brent, b_fetched = op.daily_brent()
    spot, fetched = daily_spot()
    mm = build(brent, spot)
    mm["fetched"], mm["brent_fetched"] = fetched, b_fetched
    return mm


def write_monthly(mm: dict) -> Path:
    """notes/margins-monthly.csv: every month and series, with source and fetch date."""
    rows = ["month,series,name,price_usd_bbl,brent_usd_bbl,crack_usd_bbl,log_ratio,source,fetched"]
    for k, (code, name) in SERIES.items():
        p = mm["price"][k]
        for i, m in enumerate(mm["index"]):
            if np.isfinite(p[i]) and np.isfinite(mm["brent"][i]):
                rows.append(f"{m:%Y-%m},{k},{name},{p[i]:.3f},{mm['brent'][i]:.3f},{p[i] - mm['brent'][i]:.3f},"
                            f"{np.log(p[i] / mm['brent'][i]):.5f},EIA {code} (spot; Brent FRED DCOILBRENTEU),"
                            f"{mm['fetched']}")
    path = NOTES / "margins-monthly.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# --- the margin model ------------------------------------------------------------------------

def harmonics(month) -> np.ndarray:
    a = 2 * np.pi * np.asarray(month, float) / 12
    return np.stack([np.sin(a), np.cos(a), np.sin(2 * a), np.cos(2 * a)], -1)


def regressors(r_prev, dr_prev, x, month, local) -> np.ndarray:
    """Rows of the margin equation [..., len(FEATURES)] (see the module docstring). local: the mean
    of r over the LOCAL months up to last month; month None leaves out the seasonal terms."""
    r_prev, dr_prev, x, local = np.broadcast_arrays(*(np.asarray(a, float) for a in (r_prev, dr_prev, x, local)))
    m = np.expm1(r_prev)  # crack / Brent last month
    sticky = np.log1p(np.maximum(m * np.exp(-x), -0.9)) - np.log1p(m)  # a negative crack can't exceed Brent
    seas = np.zeros(x.shape + (4,)) if month is None else np.broadcast_to(harmonics(month), x.shape + (4,))
    return np.concatenate([np.ones(x.shape + (1,)), seas, (r_prev - local)[..., None], dr_prev[..., None],
                           sticky[..., None], x[..., None]], -1)


def local_mean(r: np.ndarray) -> np.ndarray:
    """Mean of r over the LOCAL months up to and including each month (from LOCAL_MIN months of data)."""
    return pd.Series(r).rolling(LOCAL, min_periods=LOCAL_MIN).mean().values


def mean_abs3(x: np.ndarray) -> np.ndarray:
    """Mean |x| over the month and the two before it, along the last axis (NaN for the first two)."""
    a = np.abs(x)
    out = np.full(a.shape, np.nan)
    out[..., 2:] = (a[..., 2:] + a[..., 1:-1] + a[..., :-2]) / 3
    return out


def onsets() -> list[pd.Timestamp]:
    return [pd.Timestamp(e) for e, _ in EVENTS]


def months_since(month: pd.Timestamp, onset: pd.Timestamp) -> int:
    return (month.year - onset.year) * 12 + month.month - onset.month


@dataclass
class Fit:
    product: str
    last: pd.Timestamp
    beta: np.ndarray
    cov: np.ndarray
    logvar: tuple[float, float]  # log residual variance = a + lambda * v
    z: np.ndarray  # standardised residuals of the normal months
    vol: tuple[float, float, float]  # sd of x, mean and sd of log mean |x| / sd (training)
    excess: dict[str, np.ndarray] = field(default_factory=dict)  # onset -> [CRISIS_MONTHS] (NaN past `last`)
    ref: np.ndarray = None  # Brent-only margin equation: const, x[t], x[t-1], x[t-2]
    ref_res: np.ndarray = None
    months: int = 0
    r2: float = float("nan")

    def v(self, mean_abs: np.ndarray) -> np.ndarray:
        sd, vm, vs = self.vol
        return (np.log(mean_abs / sd + VOL_FLOOR) - vm) / vs

    def sigma(self, v: np.ndarray) -> np.ndarray:
        return np.exp(0.5 * (self.logvar[0] + self.logvar[1] * v))

    def events(self) -> np.ndarray:
        """[training events, CRISIS_MONTHS] excess paths (rows with at least one finite month)."""
        rows = [e for e in self.excess.values() if np.isfinite(e).any()]
        return np.array(rows) if rows else np.zeros((0, CRISIS_MONTHS))


def fit(mm: dict, product: str, last: pd.Timestamp, crisis_to: pd.Timestamp | None = None) -> Fit:
    """The margin equation on months FIT_START..last: OLS on the months outside crisis windows,
    a log-variance regression on volatility, then weighted least squares; each training event's
    excess path; and the Brent-only reference on REF_START..last (every month). crisis_to (after
    last) also takes the crisis paths of events up to that month, measured against the same fit:
    in sample, for a scenario only."""
    idx, r, x = mm["index"], mm["r"][product], mm["x"]
    dr = np.r_[np.nan, np.diff(r)]
    lm = local_mean(r)
    end = max(last, crisis_to) if crisis_to is not None else last
    t = np.arange(3, len(idx))
    ok = ((idx[t] >= FIT_START) & (idx[t] <= end) & np.isfinite(r[t]) & np.isfinite(r[t - 1])
          & np.isfinite(dr[t - 1]) & np.isfinite(x[t]) & np.isfinite(x[t - 2]) & np.isfinite(lm[t - 1]))
    t_all = t[ok]
    t = t_all[idx[t_all] <= last]
    X = regressors(r[t - 1], dr[t - 1], x[t], idx[t].month, lm[t - 1])
    y = dr[t]
    since = np.array([[months_since(idx[s], o) for o in onsets()] for s in t])  # [rows, events]
    crisis = ((since >= 0) & (since < CRISIS_MONTHS)).any(1)
    normal = ~crisis
    train_x = x[(idx >= FIT_START) & (idx <= last)]
    sd = float(np.nanstd(train_x))
    la = np.log(mean_abs3(x) / sd + VOL_FLOOR)
    vm, vs = float(np.nanmean(la[t][normal])), float(np.nanstd(la[t][normal]))
    v = (la[t] - vm) / vs
    b, *_ = np.linalg.lstsq(X[normal], y[normal], rcond=None)
    e = y[normal] - X[normal] @ b
    A = np.column_stack([np.ones(normal.sum()), v[normal]])
    c, *_ = np.linalg.lstsq(A, np.log(e ** 2 + 0.01 * np.mean(e ** 2)), rcond=None)
    s2 = np.exp(A @ c)
    k = float(np.mean(e ** 2 / s2))  # rescale so the standardised residuals have unit variance
    w = 1 / np.sqrt(s2 * k)
    b, *_ = np.linalg.lstsq(X[normal] * w[:, None], y[normal] * w, rcond=None)
    e = y[normal] - X[normal] @ b
    z = e * w
    Xw = X[normal] * w[:, None]
    cov = np.linalg.inv(Xw.T @ Xw) * float(np.var(z))
    excess = {}
    Xa, ya = regressors(r[t_all - 1], dr[t_all - 1], x[t_all], idx[t_all].month, lm[t_all - 1]), dr[t_all]
    since_a = np.array([[months_since(idx[s], o) for o in onsets()] for s in t_all])
    pred = Xa @ b
    for i, (onset, _) in enumerate(EVENTS):
        if pd.Timestamp(onset) > end:
            continue
        path = np.full(CRISIS_MONTHS, np.nan)
        rows = np.flatnonzero((since_a[:, i] >= 0) & (since_a[:, i] < CRISIS_MONTHS))
        path[since_a[rows, i]] = ya[rows] - pred[rows]
        excess[onset] = path
    sel = idx[t] >= REF_START
    R = np.column_stack([np.ones(sel.sum()), x[t][sel], x[t - 1][sel], x[t - 2][sel]])
    ref, *_ = np.linalg.lstsq(R, y[sel], rcond=None)
    return Fit(product, last, b, cov, (float(c[0] + np.log(k)), float(c[1])), z, (sd, vm, vs), excess, ref,
               y[sel] - R @ ref, int(normal.sum()), float(1 - np.var(y[normal] - X[normal] @ b) / np.var(y[normal])))


def history(mm: dict, i: int, n: int) -> np.ndarray:
    """Brent's log changes in months i-1 and i, broadcast to [n, 2] (the start of a path's window)."""
    return np.broadcast_to(mm["x"][i - 1:i + 1], (n, 2))


def coefficients(f: Fit, n: int, rng) -> np.ndarray:
    """n draws [n, features] of the margin equation's coefficients from their sampling distribution."""
    return rng.multivariate_normal(f.beta, f.cov, size=n)


def simulate(f: Fit, mm: dict, i: int, xf: np.ndarray, crisis: np.ndarray, rng, noise: bool = True,
             beta: np.ndarray | None = None, neutral: bool = False) -> np.ndarray:
    """Monthly margin changes dr [N, H] in the H months after calendar month i (the origin), given
    Brent's monthly log changes xf [N, H] and a crisis path [N, H] (excess dr, 0 outside crises).
    beta: coefficients per draw [N, features] (default: the point estimate). noise: plus the
    resampled residual, scaled by the path's own Brent volatility. neutral: start from a margin that
    has sat at its five-year mean, with no momentum, season or crisis: what the same Brent path does
    to a margin with nothing of its own to tell."""
    N, H = xf.shape
    r = mm["r"][f.product]
    beta = np.broadcast_to(f.beta, (N, len(f.beta))) if beta is None else beta
    buf = np.broadcast_to(r[max(i - LOCAL + 1, 0):i + 1], (N, min(LOCAL, i + 1))).copy()  # r over the window
    if neutral:
        buf[:] = np.nanmean(buf[0])
        r_prev, dr_prev, crisis = buf[:, -1].copy(), np.zeros(N), np.zeros_like(crisis)
    else:
        r_prev, dr_prev = np.full(N, r[i]), np.full(N, r[i] - r[i - 1])
    xa = np.concatenate([history(mm, i, N), xf], 1)
    v = f.v(mean_abs3(xa)[:, 2:])  # [N, H]
    months = [None if neutral else (mm["index"][i] + pd.DateOffset(months=s + 1)).month for s in range(H)]
    out = np.zeros((N, H))
    for s in range(H):
        X = regressors(r_prev, dr_prev, xf[:, s], months[s], np.nanmean(buf, 1))
        d = np.einsum("nf,nf->n", X, beta) + crisis[:, s]
        if noise:
            d = d + f.sigma(v[:, s]) * rng.choice(f.z, size=N)
        r_prev, dr_prev = r_prev + d, d
        buf = np.concatenate([buf[:, 1:] if buf.shape[1] == LOCAL else buf, r_prev[:, None]], 1)
        out[:, s] = d
    return out


def news(f: Fit, mm: dict, i: int, xf: np.ndarray, crisis: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Margin news [N, H]: the mean margin path from the actual state (its gap to the five-year mean,
    momentum, season, crisis) minus the same model from a neutral state on the same Brent path. The
    knock-on members, fed only Brent, already carry the second; the first is what they miss."""
    rng = np.random.default_rng(0)  # unused without noise
    return (simulate(f, mm, i, xf, crisis, rng, noise=False, beta=beta)
            - simulate(f, mm, i, xf, crisis, rng, noise=False, beta=beta, neutral=True))


def reference(f: Fit, mm: dict, i: int, xf: np.ndarray) -> np.ndarray:
    """The margin path Brent alone predicts [N, H]: what a knock-on model fed only Brent can learn."""
    xa = np.concatenate([history(mm, i, len(xf)), xf], 1)
    c, b0, b1, b2 = f.ref
    return c + b0 * xa[:, 2:] + b1 * xa[:, 1:-1] + b2 * xa[:, :-2]


def crisis_paths(f: Fit, origin: pd.Timestamp, events: list[tuple[pd.Timestamp, float]], n: int, rng,
                 horizon: int = AHEAD) -> np.ndarray:
    """Excess margin changes [n, horizon] in the months after the origin from the given crises
    (onset, scale). Each draw takes one training event's path (where that event's month is missing,
    the mean of the events that have it), so the draws span the past crises."""
    E = f.events()
    out = np.zeros((n, horizon))
    if not len(E) or not events:
        return out
    fin = np.isfinite(E)
    mean = np.where(fin, E, 0.0).sum(0) / np.maximum(fin.sum(0), 1)
    pick = rng.integers(len(E), size=n)
    for onset, scale in events:
        for s in range(horizon):
            m = months_since(origin + pd.DateOffset(months=s + 1), onset)
            if 0 <= m < CRISIS_MONTHS:
                vals = E[pick, m]
                out[:, s] += scale * np.where(np.isfinite(vals), vals, mean[m])
    return out


def known_events(origin: pd.Timestamp, mode: str, lost: float = 0.0) -> list[tuple[pd.Timestamp, float]]:
    """Crises a draw knows about. whatif: every listed event (it is given what happened, as it is
    given the Brent path); forecast: those already under way at the origin; a flow scenario adds a
    crisis from the next month, scaled by the points of Hormuz flow lost against 2026's 82."""
    if mode == "whatif":
        return [(o, 1.0) for o in onsets()]
    out = [(o, 1.0) for o in onsets() if 0 <= months_since(origin, o) < CRISIS_MONTHS]
    if lost > 0:
        out.append((origin + pd.DateOffset(months=1), lost / LOST_2026))
    return out


# --- from margins to the fuel targets --------------------------------------------------------

@dataclass
class Map:
    target: str
    products: tuple[str, ...]
    coef: np.ndarray  # const, then (product lag 0, product lag 1) per product, then own lag
    res: np.ndarray
    r2: float

    @property
    def rho(self) -> float:
        return float(self.coef[-1])

    def theta(self, p: str) -> tuple[float, float]:
        j = 1 + 2 * self.products.index(p)
        return float(self.coef[j]), float(self.coef[j + 1])


def product_changes(mm: dict, p: str) -> np.ndarray:
    """100 x monthly log change of product p's price (Brent's plus its margin's)."""
    return 100 * (mm["x"] + np.r_[np.nan, np.diff(mm["r"][p])])


def fit_map(target: pd.Series, mm: dict, key: str, last: pd.Timestamp) -> Map:
    """target: the fuel target's 100 x monthly log change on mm's calendar index. Least squares on
    REF_START..last of target[t] on its products' changes at t and t-1 and target[t-1]."""
    prods = TARGETS[key]
    y = target.reindex(mm["index"]).values
    cols = [np.ones(len(y))]
    for p in prods:
        dp = product_changes(mm, p)
        cols += [dp, np.r_[np.nan, dp[:-1]]]
    cols.append(np.r_[np.nan, y[:-1]])
    X = np.column_stack(cols)
    ok = np.isfinite(X).all(1) & np.isfinite(y) & (mm["index"] >= REF_START) & (mm["index"] <= last)
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    res = y[ok] - X[ok] @ coef
    return Map(key, prods, coef, res, float(1 - res.var() / y[ok].var()))


def correction(mp: Map, news: dict[str, np.ndarray]) -> np.ndarray:
    """Cumulative change of the target [N, H] (its units: 100 x log) caused by margin news
    news[p] [N, H] (dr, log units) in months 1..H after the origin; nothing before the origin is news."""
    N, H = next(iter(news.values())).shape
    d = np.zeros((N, H))
    for s in range(H):
        inc = mp.rho * d[:, s - 1] if s else np.zeros(N)
        for p in mp.products:
            t0, t1 = mp.theta(p)
            inc = inc + 100 * (t0 * news[p][:, s] + (t1 * news[p][:, s - 1] if s else 0.0))
        d[:, s] = inc
    return np.cumsum(d, 1)


def member(mp: Map, mm: dict, target: pd.Series, i: int, pub_lag: int, xf: np.ndarray,
           drs: dict[str, np.ndarray], rng) -> np.ndarray:
    """The margin member: cumulative target change [N, H] after calendar month i, from Brent paths
    xf and margin paths drs [N, H], through the mapping with resampled residuals. Months the target
    has not published yet (pub_lag) are nowcast from the known product prices."""
    N, H = xf.shape
    y = target.reindex(mm["index"]).values
    hist = {p: product_changes(mm, p) for p in mp.products}
    fut = {p: 100 * (xf + drs[p]) for p in mp.products}

    def dp(p, s):  # product change in month i + s, [N]
        return np.broadcast_to(hist[p][i + s], (N,)) if s <= 0 else fut[p][:, s - 1]

    prev = np.full(N, np.nan_to_num(y[i - pub_lag]))
    cum, out = np.zeros(N), np.zeros((N, H))
    for s in range(1 - pub_lag, H + 1):
        m = mp.coef[0] + mp.rho * prev + rng.choice(mp.res, size=N)
        for p in mp.products:
            t0, t1 = mp.theta(p)
            m = m + t0 * dp(p, s) + t1 * dp(p, s - 1)
        prev = m
        if s >= 1:
            cum = cum + m
            out[:, s - 1] = cum
    return out


def target_series(data: dict, key: str) -> pd.Series:
    import macro_bayes as mb

    k = data["target_keys"].index(key)
    return pd.Series(data["dM"][:, k], index=mb.month_index(data))


def crack_levels(mm: dict, i: int, p: str, xf: np.ndarray, dr: np.ndarray) -> np.ndarray:
    """Crack spread in $/bbl [N, H] in the months after i, from Brent paths and margin paths."""
    B = mm["brent"][i] * np.exp(np.cumsum(xf, 1))
    return B * np.expm1(mm["r"][p][i] + np.cumsum(dr, 1))


# --- one fold --------------------------------------------------------------------------------

def fuel_columns(names: list[str]) -> dict[str, list[int]]:
    return {k: [c for c, nm in enumerate(names) if nm.split("@")[0] == k] for k in TARGETS}


def layer(fits: dict, maps: dict, targets: dict, mm: dict, i: int, pub_lags: dict, xf: np.ndarray,
          events: list, rng) -> dict:
    """Everything the margin layer adds at one origin (calendar month i), for oil paths xf [N, H]:
    per target the correction with and without the crisis term and the member's draws, per product
    the simulated margin paths."""
    N = len(xf)
    out = {"news": {}, "news_nocrisis": {}, "dr": {}, "dr_nocrisis": {}, "dr_neutral": {}}
    for p, f in fits.items():
        beta = coefficients(f, N, rng)  # one coefficient draw per path, shared by every run
        cr = crisis_paths(f, mm["index"][i], events, N, rng)
        none = np.zeros_like(cr)
        out["news"][p] = news(f, mm, i, xf, cr, beta)
        out["news_nocrisis"][p] = news(f, mm, i, xf, none, beta)
        out["dr"][p] = simulate(f, mm, i, xf, cr, rng, beta=beta)
        out["dr_nocrisis"][p] = simulate(f, mm, i, xf, none, rng, beta=beta)
        out["dr_neutral"][p] = simulate(f, mm, i, xf, none, rng, beta=beta, neutral=True)
    out["margin"] = {k: correction(mp, out["news"]) for k, mp in maps.items()}
    out["margin_nocrisis"] = {k: correction(mp, out["news_nocrisis"]) for k, mp in maps.items()}
    for v, dr in (("member", "dr"), ("member_nocrisis", "dr_nocrisis"), ("member_neutral", "dr_neutral")):
        out[v] = {k: member(mp, mm, targets[k], i, pub_lags[k], xf, out[dr], rng) for k, mp in maps.items()}
    return out


class ChainMargins:
    """The margin layer as macro_chain.py would call it: fitted once on a fold's training months,
    then applied to the chain's draws (draw n with oil path n).

        cm = ChainMargins(data, last)                    # last: the last training month (panel index)
        D = cm.member_draws(t, oil, "whatif")            # the margin member [N, origins, outputs] (fuel columns)
        M = cm.correct(M, t, oil, "forecast", lost=82)   # or margin news on a mixture; lost: a flow scenario
    """

    def __init__(self, data: dict, last: int, mm: dict | None = None, crisis_to: pd.Timestamp | None = None) -> None:
        import macro_bayes as mb

        self.data, self.mm = data, margins_data() if mm is None else mm
        self.idx = mb.month_index(data)
        ok = np.isfinite(data["oil_m"])
        gap = float(np.nanmax(np.abs(self.mm["x"][self.mm["index"].get_indexer(self.idx)][ok] - data["oil_m"][ok])))
        assert gap < 1e-9, f"the margins' Brent and the panel's disagree by {gap}"
        self.last = self.idx[last]
        self.fits = {p: fit(self.mm, p, self.last, crisis_to) for p in PRODUCTS}
        self.targets = {k: target_series(data, k) for k in TARGETS}
        self.maps = {k: fit_map(self.targets[k], self.mm, k, self.last) for k in TARGETS}
        info = mb.series_info(data)
        self.pub = {k: int(info["pub_lag"][info["keys"].index(k)]) for k in TARGETS}
        self.cols = fuel_columns(data["names"])
        self.h = {k: np.array([int(data["names"][c].split("@")[1]) for c in cs]) for k, cs in self.cols.items()}

    def at(self, tt: int, xf: np.ndarray, mode: str, lost: float = 0.0, seed: tuple = ()) -> dict:
        """layer() at origin tt (panel month index) for oil paths xf [N, 12]."""
        i = int(self.mm["index"].get_loc(self.idx[tt]))
        rng = np.random.default_rng([SEED, *seed, int(tt)])
        return layer(self.fits, self.maps, self.targets, self.mm, i, self.pub, xf,
                     known_events(self.idx[tt], mode, lost), rng)

    def correct(self, M: np.ndarray, t: np.ndarray, oil: np.ndarray, mode: str, lost: float = 0.0,
                seed: tuple = (), crisis: bool = True) -> np.ndarray:
        """M with the margin news added to the fuel targets' columns."""
        M = M.copy()
        for o, tt in enumerate(t):
            out = self.at(tt, np.broadcast_to(oil[:, o], (M.shape[0], oil.shape[-1])), mode, lost, seed)
            for k, cs in self.cols.items():
                M[:, o, cs] += out["margin" if crisis else "margin_nocrisis"][k][:, self.h[k] - 1]
        return M

    def member_draws(self, t: np.ndarray, oil: np.ndarray, mode: str, lost: float = 0.0, seed: tuple = (),
                     like: np.ndarray | None = None, n: int | None = None) -> np.ndarray:
        """The margin member's draws [N, origins, outputs]: the fuel targets' columns from the member,
        the others copied from `like` (e.g. any other member's draws, which the mixture never uses for
        them) or NaN. N: like's draws, else n, else oil's (a single what-if path needs n). Mix it in as
        one more equal-weight member for the fuel columns (macro_chain.with_margins)."""
        N = like.shape[0] if like is not None else n or oil.shape[0]
        D = np.full((N, len(t), len(self.data["names"])), np.nan) if like is None else like.copy()
        for o, tt in enumerate(t):
            out = self.at(tt, np.broadcast_to(oil[:, o], (N, oil.shape[-1])), mode, lost, seed)
            for k, cs in self.cols.items():
                D[:, o, cs] = out["member"][k][:, self.h[k] - 1]
        return D

    def describe(self) -> dict:
        """The fitted coefficients, for the run files."""
        fits = {p: {"beta": dict(zip(FEATURES, f.beta.tolist())), "se": dict(zip(FEATURES, np.sqrt(np.diag(f.cov)).tolist())),
                    "logvar": f.logvar, "months": f.months, "r2": f.r2, "ref": f.ref.tolist(),
                    "events": {o: e.tolist() for o, e in f.excess.items()}} for p, f in self.fits.items()}
        maps = {k: {"products": mp.products, "coef": mp.coef.tolist(), "r2": mp.r2} for k, mp in self.maps.items()}
        return {"train_to": f"{self.last:%Y-%m}", "fits": fits, "maps": maps, "fetched": self.mm["fetched"]}


def run_fold(j: int) -> dict:
    """Fold j: fit the margin layer on the training months, rebuild the ensemble's draws and oil
    paths, and score the fuel targets with and without margins, and the margins themselves."""
    import macro_bayes as mb
    import macro_chain as mc
    import macro_nn as mn
    import oil_paths as op

    data = mn.make_dataset(mn.V1_BLOCKS)
    idx = mb.month_index(data)
    _, test, last = mb.fold_window(data, j)
    t = data["t"][test]
    cm = ChainMargins(data, last)
    mm, fits, cal_last, cols = cm.mm, cm.fits, cm.last, cm.cols
    names = data["names"]
    H = np.array(mn.HORIZONS)
    # the chain's draws: the equal-weight mixture exactly as macro_chain.report builds it
    S = {mode: np.stack([np.load(RUNS / f"chain-{j}-{m}.npz")[mode] for m in MEMBERS]).astype(float) for mode in MODES}
    summ = json.loads((RUNS / f"chain-{j}-{MEMBERS[0]}.json").read_text())
    assert summ["test_dates"] == [f"{d:%Y-%m}" for d in data["dates"][test]], f"fold {j}: origins differ"
    N = S["whatif"].shape[1]
    order = np.random.default_rng(1234 + j).permutation(N)
    w3, w4 = np.full(len(MEMBERS), 1 / len(MEMBERS)), np.full(len(MEMBERS) + 1, 1 / (len(MEMBERS) + 1))
    base = {mode: mc.mixture(S[mode], w3, order) for mode in MODES}
    market, (prices, _) = mb.market_inputs(data), op.daily_brent()
    oil = {"whatif": np.broadcast_to(data["OIL"][test][None], (N,) + data["OIL"][test].shape),
           # the levy paths of macro_chain.oil_modes, regenerated with the same seed
           "levy": op.monthly_paths(prices, idx[t], N, np.random.default_rng(900 + j), "cgmy", market["drift"][t])}
    y = data["Y"][test]
    fuel = [c for k in TARGETS for c in cols[k]]
    res = {"fold": j, "test_dates": summ["test_dates"], "names": [names[c] for c in fuel], "y": y[:, fuel].tolist(),
           "modes": {}} | cm.describe()
    for mode in MODES:
        draws = {v: base[mode][..., fuel].copy() for v in VARIANTS}
        mem = {v: np.zeros((N, len(t), len(fuel))) for v in MEMBER_VARIANTS}
        margin = {p: {"crps": [], "crps_ref": [], "crps_nocrisis": [], "y": []} for p in PRODUCTS}
        cracks = {p: [] for p in PRODUCTS}
        for o, tt in enumerate(t):
            i = int(mm["index"].get_loc(idx[tt]))
            xf = oil[mode][:, o]
            out = cm.at(tt, xf, mode, seed=(j, MODES.index(mode)))
            rng = np.random.default_rng([SEED, j, MODES.index(mode), o, 1])
            for k in TARGETS:
                c = [fuel.index(cc) for cc in cols[k]]
                draws["margin"][:, o, c] += out["margin"][k][:, H - 1]
                draws["margin_nocrisis"][:, o, c] += out["margin_nocrisis"][k][:, H - 1]
                for v in MEMBER_VARIANTS:
                    mem[v][:, o, c] = out[v][k][:, H - 1]
            for p, f in fits.items():  # the margins themselves: cumulative dr over each horizon
                r = mm["r"][p]
                act = np.array([r[i + h] - r[i] if i + h < len(r) else np.nan for h in H])
                cum = np.cumsum(out["dr"][p], 1)[:, H - 1]
                ref = np.cumsum(reference(f, mm, i, xf) + rng.choice(f.ref_res, size=xf.shape), 1)[:, H - 1]
                cum_nc = np.cumsum(out["dr_nocrisis"][p], 1)[:, H - 1]
                fin = np.isfinite(act)
                for key, sims in (("crps", cum), ("crps_ref", ref), ("crps_nocrisis", cum_nc)):
                    margin[p][key].append(np.where(fin, mb.crps_samples(sims, np.nan_to_num(act)), np.nan).tolist())
                margin[p]["y"].append(act.tolist())
                if mode == "whatif":
                    cl = crack_levels(mm, i, p, xf, out["dr"][p])
                    cl_nc = crack_levels(mm, i, p, xf, out["dr_nocrisis"][p])
                    cracks[p].append({"mean": cl.mean(0).tolist(), "q05": np.quantile(cl, 0.05, 0).tolist(),
                                      "q95": np.quantile(cl, 0.95, 0).tolist(), "mean_nocrisis": cl_nc.mean(0).tolist(),
                                      "q05_nocrisis": np.quantile(cl_nc, 0.05, 0).tolist(),
                                      "q95_nocrisis": np.quantile(cl_nc, 0.95, 0).tolist()})
        for v in MEMBER_VARIANTS:
            draws[v] = mc.mixture(np.concatenate([S[mode][..., fuel], mem[v][None]], 0), w4, order)
        draws["member_only"] = mem["member"]
        res["modes"][mode] = {v: mb.summarise(d, y[:, fuel]) for v, d in draws.items()}
        res["modes"][mode]["margins"] = margin
        if mode == "whatif":
            res["modes"][mode]["cracks"] = cracks
        print(f"fold {j} {mode}: " + ", ".join(f"{v} {np.nanmean(res['modes'][mode][v]['crps']):.3f}" for v in VARIANTS), flush=True)
    # the training months' h-month margin changes, for a climatology yardstick
    clim = {}
    for p in PRODUCTS:
        r = mm["r"][p]
        sel = np.flatnonzero((mm["index"] >= FIT_START) & (mm["index"] <= cal_last))
        clim[p] = [[float(r[s + h] - r[s]) for s in sel if s + h < len(r) and mm["index"][s + h] <= cal_last
                    and np.isfinite(r[s + h] - r[s])] for h in H]
    res["margin_clim"] = clim
    res["generated"] = datetime.now(UTC).isoformat(timespec="seconds")
    res["fetched"] = mm["fetched"]
    return res


# --- the 2026 closure: replay and scenario ---------------------------------------------------

REPLAY_ORIGIN = "2026-02"  # macro_chain.REPLAY_ORIGIN: the last month before the closure
LOSTS = (0.0, 25.0, 50.0, 82.0, 100.0)  # macro_chain.LOSTS


def replay_ensemble(origin: str = REPLAY_ORIGIN) -> dict:
    """The chain's replay draws for the recommended members, rebuilt as macro_chain.replay does
    (same fits, seeds and oil paths, so the same numbers), cached in runs/macro/margins-replay-ens.npz."""
    path = RUNS / "margins-replay-ens.npz"
    if path.exists():
        z = np.load(path, allow_pickle=False)
        return {"S": {k[2:]: z[k] for k in z.files if k.startswith("S_")}, "oil": {k[4:]: z[k] for k in z.files if k.startswith("oil_")},
                "diag": json.loads(str(z["diag"]))}
    import macro_bayes as mb
    import macro_chain as mc
    import macro_global as mg
    import macro_nn as mn
    import oil_paths as op

    data = mn.make_dataset(mn.V1_BLOCKS)
    market, (prices, _) = mb.market_inputs(data), op.daily_brent()
    idx = mb.month_index(data)
    m = int(idx.get_loc(pd.Timestamp(origin)))
    last, t = m - 1, np.array([m])
    st, info = mb.Stats(data, last), mb.series_info(data)
    real = data["oil_m"][m + 1:m + 1 + mn.OIL_AHEAD]
    oil = {"whatif": np.nan_to_num(np.r_[real, np.full(mn.OIL_AHEAD - len(real), np.nan)])[None, None]}
    for lost in LOSTS:
        oil[f"lost {lost:g}"] = op.monthly_paths(prices, idx[t], mb.DRAWS, np.random.default_rng(900), "cgmy",
                                                 market["drift"][t], lost=lost)
    S, diag = {mode: [] for mode in oil}, {"chains": mb.CHAINS, "warmup": mb.WARMUP}
    for member_ in MEMBERS:
        if member_ == "bayes_own":
            post, st_b, info_b, d = mb.fit(data, last, seed=99, vol="own")
            diag["bayes_own"] = d
            sim = lambda fut, rng: mb.simulate(post, st_b, info_b, data, t, fut, rng)  # noqa: E731
        else:
            nets, _ = mc.fit_nets(data, info, st, last, member_, 90_000)
            sim = lambda fut, rng, nets=nets: mg.simulate(nets, st, info, data, t, fut, rng, n=mb.DRAWS)  # noqa: E731
        for mode, fut in oil.items():
            S[mode].append(sim(fut, np.random.default_rng(300))[:, 0])  # [N, outputs]
        print(f"replay: {member_} simulated", flush=True)
    out = {"S": {mode: np.stack(v).astype(np.float32) for mode, v in S.items()},
           "oil": {mode: np.broadcast_to(v[:, 0], (mb.DRAWS, mn.OIL_AHEAD)).copy() for mode, v in oil.items()}, "diag": diag}
    RUNS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **{f"S_{k}": v for k, v in out["S"].items()}, **{f"oil_{k}": v for k, v in out["oil"].items()},
                        diag=json.dumps(diag))
    return out


def summary(x: np.ndarray) -> dict:
    """mean, 5/50/95% quantiles of draws along axis 0."""
    return {"mean": x.mean(0).tolist(), "q05": np.quantile(x, 0.05, 0).tolist(),
            "q50": np.quantile(x, 0.5, 0).tolist(), "q95": np.quantile(x, 0.95, 0).tolist()}


def run_replay(origin: str = REPLAY_ORIGIN) -> dict:
    """The 2026 closure from the origin: the chain's ensemble with and without the margin layer,
    fitted on months before the origin only, and the margin fan for each flow scenario."""
    import macro_bayes as mb
    import macro_chain as mc
    import macro_nn as mn

    data = mn.make_dataset(mn.V1_BLOCKS)
    idx = mb.month_index(data)
    m = int(idx.get_loc(pd.Timestamp(origin)))
    cm = ChainMargins(data, m - 1)
    mm, fits, cols = cm.mm, cm.fits, cm.cols
    i = int(mm["index"].get_loc(pd.Timestamp(origin)))
    names = data["names"]
    H = np.array(mn.HORIZONS)
    ens = replay_ensemble(origin)
    N = ens["S"]["whatif"].shape[1]
    order = np.random.default_rng(1234).permutation(N)  # macro_chain.replay's mixture
    w3, w4 = np.full(len(MEMBERS), 1 / len(MEMBERS)), np.full(len(MEMBERS) + 1, 1 / (len(MEMBERS) + 1))
    actual = {}
    for c, nm in enumerate(names):
        key, h = nm.split("@")
        seg = data["dM"][m + 1:m + 1 + int(h), data["target_keys"].index(key)]
        actual[nm] = float(seg.sum()) if len(seg) == int(h) and np.isfinite(seg).all() else None
    seen = int(np.isfinite(data["oil_m"][m + 1:m + 1 + mn.OIL_AHEAD]).sum())
    res = {"origin": origin, "names": names, "actual": actual, "seen_brent": seen,
           "fuel": [names[c] for k in TARGETS for c in cols[k]], "modes": {}, "diag": ens["diag"],
           "events_used": {p: sorted(f.excess) for p, f in fits.items()},
           "actual_cracks": {p: [float(mm["brent"][i + s] * np.expm1(mm["r"][p][i + s])) if i + s < len(mm["index"]) else None
                                 for s in range(AHEAD + 1)] for p in PRODUCTS},
           "actual_months": [f"{mm['index'][i] + pd.DateOffset(months=s):%Y-%m}" for s in range(AHEAD + 1)]} | cm.describe()
    for mode, S in ens["S"].items():
        S = S.astype(float)
        xf = ens["oil"][mode]
        lost = 0.0 if mode == "whatif" else float(mode.split()[1])
        events = known_events(pd.Timestamp(origin), "whatif" if mode == "whatif" else "forecast", lost)
        out = cm.at(m, xf, "whatif" if mode == "whatif" else "forecast", lost, seed=(99, list(ens["S"]).index(mode)))
        base = mc.mixture(S, w3, order)
        draws = {v: base.copy() for v in VARIANTS}
        mem = {v: S[0].copy() for v in MEMBER_VARIANTS}
        for k in TARGETS:
            draws["margin"][:, cols[k]] += out["margin"][k][:, H - 1]
            draws["margin_nocrisis"][:, cols[k]] += out["margin_nocrisis"][k][:, H - 1]
            for v in MEMBER_VARIANTS:
                mem[v][:, cols[k]] = out[v][k][:, H - 1]
        fuel = [c for k in TARGETS for c in cols[k]]
        for v in MEMBER_VARIANTS:
            draws[v][:, fuel] = mc.mixture(np.concatenate([S, mem[v][None]], 0), w4, order)[:, fuel]
        draws["member_only"][:, fuel] = mem["member"][:, fuel]
        res["modes"][mode] = {"lost": lost, "events": [(f"{o:%Y-%m}", s) for o, s in events],
                              "draws": {v: summary(d) for v, d in draws.items()},
                              "inside": {v: [bool(np.quantile(d[:, c], 0.05) <= actual[nm] <= np.quantile(d[:, c], 0.95))
                                             if actual[nm] is not None and int(nm.split("@")[1]) <= 6 else None
                                             for c, nm in enumerate(names)] for v, d in draws.items()},
                              "cracks": {p: summary(crack_levels(mm, i, p, xf, out["dr"][p])) for p in PRODUCTS},
                              "cracks_nocrisis": {p: summary(crack_levels(mm, i, p, xf, out["dr_nocrisis"][p])) for p in PRODUCTS},
                              "dr": {p: summary(np.cumsum(out["dr"][p], 1)) for p in PRODUCTS}}
        print(f"replay {mode}: done", flush=True)
    # the forward scenario with 2026's own crisis path in the pool (in sample): the normal-times fit
    # is the same; the crisis paths add 2026-03 onwards, measured against it
    cm26 = ChainMargins(data, m - 1, mm=mm, crisis_to=mm["index"][-2])  # the last full month
    res["in_sample_events"] = sorted(cm26.fits["diesel"].excess)
    for mode, S in ens["S"].items():
        if mode == "whatif":
            continue
        S = S.astype(float)
        xf = ens["oil"][mode]
        lost = float(mode.split()[1])
        out = cm26.at(m, xf, "forecast", lost, seed=(98, list(ens["S"]).index(mode)))
        mem = S[0].copy()
        for k in TARGETS:
            mem[:, cols[k]] = out["member"][k][:, H - 1]
        mix = mc.mixture(np.concatenate([S, mem[None]], 0), w4, order)
        res["modes"][mode]["in_sample"] = {"cracks": {p: summary(crack_levels(mm, i, p, xf, out["dr"][p])) for p in PRODUCTS},
                                           "member": summary(mix)}
    return res


# --- report ----------------------------------------------------------------------------------

LABELS = {"base": "chain (3 members)", "margin": "chain + margin news", "margin_nocrisis": "chain + margin news, no crisis term",
          "member": "chain + margin member (4 equal)", "member_nocrisis": "chain + margin member, no crisis term",
          "member_neutral": "chain + member on a neutral margin", "member_only": "margin member alone"}
NAME = {"ind_gasdesw": "retail diesel", "ind_djfuelusgulf": "jet fuel", "ind_pcu324110324110": "refinery PPI"}
SHORT = {"ind_gasdesw": "Diesel, US retail (GASDESW)", "ind_djfuelusgulf": "Jet fuel, US Gulf (DJFUELUSGULF)",
         "ind_pcu324110324110": "Refinery PPI (PCU324110324110)"}


def half_life(kappa: float) -> float:
    return float(np.log(0.5) / np.log(1 + kappa)) if -1 < kappa < 0 else float("nan")


def scenario_csvs(rep: dict) -> tuple[Path, Path]:
    """notes/margin-scenarios.csv (crack fan per flow scenario) and notes/chain-fuel-scenarios-margins.csv
    (the fuel rows of notes/chain-scenarios-3m.csv with the margin layer, same columns)."""
    gen = datetime.now(UTC).date().isoformat()
    rows = ["product,series,flow_drop_points,months_ahead,month,crack_mean,crack_q05,crack_q50,crack_q95,actual_crack,"
            "unit,crisis_term,crisis_events,validated,origin,source,fitted_to,generated"]
    pools = (("cracks", "-".join(e[:4] for e in rep["events_used"]["diesel"]), "yes (2026 out of sample)"),
             ("in_sample", "-".join(e[:4] for e in rep["in_sample_events"]), "no (2026 in sample)"))
    for mode, r in rep["modes"].items():
        if mode == "whatif":
            continue
        crisis = "none" if r["lost"] == 0 else f"past crises x {r['lost'] / LOST_2026:.2f}"
        for key, pool, validated in pools:
            cracks = r[key]["cracks"] if key == "in_sample" else r[key]
            for p in PRODUCTS:
                c = cracks[p]
                for s in range(AHEAD):
                    a = rep["actual_cracks"][p][s + 1]
                    a = None if a is None or not np.isfinite(a) else a
                    rows.append(f"{p},{SERIES[PRODUCTS[p][0]][0]},{r['lost']:g},{s + 1},{rep['actual_months'][s + 1]},"
                                f"{c['mean'][s]:.2f},{c['q05'][s]:.2f},{c['q50'][s]:.2f},{c['q95'][s]:.2f},"
                                f"{'' if a is None else f'{a:.2f}'},$/bbl (monthly mean of daily product minus Brent),"
                                f"{crisis},{pool},{validated},{rep['origin']},experiments/margins.py replay (EIA spot fetched "
                                f"{rep['fetched']}; oil: GARCH-CGMY + notes/flow-premium.csv premium sampled in its band),{rep['train_to']},{gen}")
    a = NOTES / "margin-scenarios.csv"
    a.write_text("\n".join(rows) + "\n", encoding="utf-8")
    rows = ["series,group,flow_drop_points,months_ahead,mean,q05,q50,q95,actual,unit,validated,origin,source,fitted_to,generated"]
    names = rep["names"]
    for nm in rep["fuel"]:
        key, h = nm.split("@")
        c = names.index(nm)
        for mode, r in rep["modes"].items():
            if mode == "whatif":
                continue
            d = r["draws"]["member"]  # the recommended variant: the margin member, 4 equal
            act = rep["actual"][nm]
            rows.append(f"{key},cost,{r['lost']:g},{h},{d['mean'][c]:.4f},{d['q05'][c]:.4f},{d['q50'][c]:.4f},{d['q95'][c]:.4f},"
                        f"{'' if act is None else f'{act:.4f}'},100 x log change (about %),yes,{rep['origin']},"
                        f"experiments/margins.py replay (chain: {'+'.join(MEMBERS)} + margin member; oil: GARCH-CGMY + "
                        f"notes/flow-premium.csv premium sampled in its band),{rep['train_to']},{gen}")
    b = NOTES / "chain-fuel-scenarios-margins.csv"
    b.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return a, b


def run_ids(runs: list[dict]) -> str:
    jobs = sorted({int(j) for j in ((r.get("meta") or {}).get("job") for r in runs) if j})
    local = any(not (r.get("meta") or {}).get("job") for r in runs)
    out = [f"Iridis Slurm jobs {jobs[0]}–{jobs[-1]} (`cluster/iridis/margins.slurm`)" if len(jobs) > 1
           else f"Iridis Slurm job {jobs[0]}" if jobs else ""]
    return " and ".join(x for x in out + (["local runs"] if local else []) if x)


def report() -> None:
    import macro_bayes as mb

    folds = [json.loads((RUNS / f"margins-fold-{j}.json").read_text()) for j in range(8)
             if (RUNS / f"margins-fold-{j}.json").exists()]
    if not folds:
        raise SystemExit("no runs/macro/margins-fold-*.json yet")
    rep = mb.load("margins-replay.json")
    mm = margins_data()
    names = folds[0]["names"]
    keys = np.array([n.split("@")[0] for n in names])
    Hs = np.array([int(n.split("@")[1]) for n in names])
    clim = []
    for f in folds:
        v1 = mb.load(f"fold-{f['fold']}.json")
        assert v1["test_dates"] == f["test_dates"], f"fold {f['fold']}: v1 origins differ"
        c = [v1["names"].index(n) for n in names]
        clim.append(np.array(v1["models"]["climatology"]["crps"], float)[:, c])
    scale = np.nanmean(np.vstack(clim), 0)  # as macro_chain.report: the v1 climatology over every fold
    y = np.vstack([np.array(f["y"], float) for f in folds])
    C = {(mode, v): np.vstack([np.array(f["modes"][mode][v]["crps"], float) for f in folds]) for mode in MODES for v in VARIANTS}
    Q = {(mode, v, q): np.vstack([np.array(f["modes"][mode][v][q], float) for f in folds])
         for mode in MODES for v in VARIANTS for q in ("q05", "q95", "mu")}

    def sel(k=None, h=None):
        return np.flatnonzero(((keys == k) if k else np.ones(len(keys), bool)) & ((Hs == h) if h else True))

    def skill(M, c):
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / scale[c])

    def dm(A, B, c):
        d = np.nanmean((A[:, c] - B[:, c]) / scale[c], 1)
        return f"{np.nanmean(d):+.3f} (t {mb.nw_t(d):+.1f})"

    def cover(mode, v, c):
        ok = np.isfinite(y[:, c])
        inside = (y[:, c] >= Q[(mode, v, "q05")][:, c]) & (y[:, c] <= Q[(mode, v, "q95")][:, c])
        return f"{inside[ok].mean():.0%}"

    first, last = folds[0]["test_dates"][0], folds[-1]["test_dates"][-1]
    n_orig = y.shape[0]
    gen = datetime.now(UTC).date().isoformat()
    out = ["# Refined-product margins in the knock-on chain", "",
           f"_Generated by `experiments/margins.py report` on {gen}. Product spot prices: EIA spot price workbook "
           f"`PET_PRI_SPT_S1_D.xls` (`data/raw/macro/{SPOT_FILE}`, fetched {mm['fetched']}); daily Brent: FRED "
           f"DCOILBRENTEU (fetched {mm['brent_fetched']}); monthly margins in `notes/margins-monthly.csv`. Folds: the "
           f"{len(folds)} forward-chaining folds of `notes/macro-chain-results.md` ({first}..{last}, {n_orig} origins), "
           "and the chain's own draws (`runs/macro/chain-J-<member>.npz`, 3 members, equal weights). Outcomes and "
           f"prices are real. Simulated: oil paths, model draws, margin paths. Run files: {run_ids(folds + ([rep] if rep else []))}._", ""]
    # --- data
    out += ["## The margins", "",
            "Crack spread = product spot price − Brent, $/bbl, monthly mean of daily prices. Diesel is New York "
            "Harbor ULSD from 2006-06 and New York Harbor No. 2 heating oil before that (spliced on the log ratio).", "",
            "| Month | Brent | Diesel (NYH ULSD) | Jet (USGC) | Gasoline (USGC conv.) | RBOB (Los Angeles) |", "|---|---|---|---|---|---|"]
    for mo in ("1990-07", "1990-10", "2005-09", "2008-06", "2020-04", "2022-02", "2022-05", "2022-10", "2025-12",
               "2026-02", "2026-03", "2026-06", "2026-09"):
        ii = int(mm["index"].get_loc(pd.Timestamp(mo)))
        cells = [f"{mm['price'][PRODUCTS[p][0]][ii] - mm['brent'][ii]:.1f}" if np.isfinite(mm["price"][PRODUCTS[p][0]][ii]) else "–"
                 for p in PRODUCTS]
        if not np.isfinite(mm["price"]["ulsd_nyh"][ii]):
            cells[0] = f"{mm['price']['heating_oil_nyh'][ii] - mm['brent'][ii]:.1f} (heating oil)"
        out.append(f"| {mo} | {mm['brent'][ii]:.1f} | " + " | ".join(cells) + " |")
    # --- the model, as fitted for the replay (data to 2026-01) and on everything (description only)
    full = {p: fit(mm, p, mm["index"][-2]) for p in PRODUCTS}  # the last full month
    if rep:
        out += ["", f"## The margin model (fitted on {FIT_START:%Y-%m}..{rep['train_to']}, as used in the replay)", "",
                "Monthly change of the log ratio r = log(product / Brent); the crisis windows are left out of the fit. "
                "Standard errors in brackets.", "",
                "| Product | Reversion to the 5-year mean κ (half-life, months) | Momentum φ | Sticky dollar margin γ | Brent β | "
                "Volatility on log variance λ | R² (normal months) | Months |", "|---|---|---|---|---|---|---|---|"]
        for p, fr in rep["fits"].items():
            b, s = fr["beta"], fr["se"]
            out.append(f"| {p} | {b['gap']:+.3f} ({s['gap']:.3f}; {half_life(b['gap']):.1f}) | {b['momentum']:+.3f} "
                       f"({s['momentum']:.3f}) | {b['sticky']:+.2f} ({s['sticky']:.2f}) | {b['brent']:+.3f} ({s['brent']:.3f}) | "
                       f"{fr['logvar'][1]:+.2f} | {fr['r2']:.2f} | {fr['months']} |")
        out += ["", "**Fuel targets on product prices** (least squares, 2001..training end; coefficients on the "
                "product's 100 × log change at lag 0 / lag 1, then the target's own last change):", "",
                "| Target | Products | Coefficients | R² |", "|---|---|---|---|"]
        for k, mpr in rep["maps"].items():
            co = mpr["coef"]
            parts = [f"{p} {co[1 + 2 * n]:.2f} / {co[2 + 2 * n]:.2f}" for n, p in enumerate(mpr["products"])]
            out.append(f"| {SHORT[k]} | {', '.join(mpr['products'])} | {'; '.join(parts)}; own {co[-1]:+.2f} | {mpr['r2']:.2f} |")
    out += ["", "## What a supply crisis does to margins", "",
            "Excess change of the log ratio (actual minus the normal-times model, one step ahead), summed over the first "
            "1, 3 and 6 months from the onset. Descriptive: the normal-times model here is fitted on every month to "
            f"{mm['index'][-2]:%Y-%m}, so 2026's own row is in sample. The chain only ever uses events before its training end.", "",
            "| Event | Onset | " + " | ".join(f"{p} 1 / 3 / 6 m" for p in PRODUCTS) + " |", "|---|---|" + "---|" * len(PRODUCTS)]
    for onset, label in EVENTS:
        cells = []
        for p in PRODUCTS:
            e = full[p].excess.get(onset)
            cells.append("–" if e is None or not np.isfinite(e[0]) else
                         " / ".join(f"{np.nansum(e[:n]):+.2f}" for n in (1, 3, 6)))
        out.append(f"| {label} | {onset} | " + " | ".join(cells) + " |")
    pre = {p: np.array([full[p].excess[o] for o, _ in EVENTS[:-1] if o in full[p].excess and np.isfinite(full[p].excess[o][0])])
           for p in PRODUCTS}
    out.append("| Mean of the events before 2026 | | " + " | ".join(
        " / ".join(f"{np.nanmean(np.nansum(pre[p][:, :n], 1)):+.2f}" for n in (1, 3, 6)) for p in PRODUCTS) + " |")
    out += ["", "In log-ratio points: +0.10 is a product about 10% dearer against Brent than otherwise."]
    # --- margins on the folds
    H = sorted(set(Hs.tolist()))
    out += ["", "## Margin forecasts on the folds", "",
            "Skill of the h-month change in the log ratio, against the empirical distribution of training months' h-month "
            "changes (1 − CRPS / CRPS of climatology). **Model**: the margin model given the Brent path (what-if) or "
            "Lévy oil paths (forecast; crises only if under way at the origin). **Brent only**: a regression of the "
            "margin's change on Brent's at lags 0-2 (2001 on), with its own residuals: all a model fed only Brent can "
            "know about the margin.", "",
            "| Product | h | Model, what-if | Model, no crisis term | Brent only, what-if | Model, forecast (Lévy) |",
            "|---|---|---|---|---|---|"]
    for p in PRODUCTS:
        for hi, h in enumerate(H):
            cs = {key: [] for key in ("crps", "crps_nocrisis", "crps_ref", "levy", "clim")}
            for f in folds:
                mw, ml = f["modes"]["whatif"]["margins"][p], f["modes"]["levy"]["margins"][p]
                yy = np.array(mw["y"], float)[:, hi]
                samp = np.array(f["margin_clim"][p][hi], float)
                ok = np.isfinite(yy)
                if not ok.any() or not len(samp):
                    continue
                for key in ("crps", "crps_nocrisis", "crps_ref"):
                    cs[key] += list(np.array(mw[key], float)[ok, hi])
                cs["levy"] += list(np.array(ml["crps"], float)[ok, hi])
                cs["clim"] += list(mb.crps_samples(samp[:, None], yy[ok]))
            cl = np.mean(cs["clim"])
            out.append(f"| {p} | {h} | " + " | ".join(f"{1 - np.mean(cs[key]) / cl:+.3f}" for key in ("crps", "crps_nocrisis", "crps_ref", "levy")) + " |")
    # --- fuel targets on the folds
    for mode, title in (("whatif", "given the Brent path that happened (what-if)"), ("levy", "with Lévy oil paths (forecast)")):
        out += ["", f"## Fuel targets on the folds, {title}", "",
                "Skill against the v1 climatology (as `notes/macro-chain-results.md`), all horizons, per target and for "
                "the three together; the scaled CRPS difference against the chain over the three, with its Newey–West t "
                "(negative: better than the chain); and the share of outcomes inside the 90% band.", "",
                "| Model | " + " | ".join(SHORT[k] for k in TARGETS) + " | **All three** | vs chain | In 90% |", "|---|---|---|---|---|---|---|"]
        for v in VARIANTS:
            out.append(f"| {LABELS[v]} | " + " | ".join(f"{skill(C[(mode, v)], sel(k)):+.3f}" for k in TARGETS)
                       + f" | **{skill(C[(mode, v)], sel()):+.3f}** | {'' if v == 'base' else dm(C[(mode, v)], C[(mode, 'base')], sel())} | "
                       f"{cover(mode, v, sel())} |")
        out += ["", f"By horizon (all three targets, {mode}): skill, and the difference against the chain (t).", "",
                "| h | " + " | ".join(LABELS[v] for v in ("base", "margin", "member", "member_neutral")) + " | margin news vs chain | margin member vs chain |",
                "|---|---|---|---|---|---|---|"]
        for h in H:
            c = sel(h=h)
            out.append(f"| {h} | " + " | ".join(f"{skill(C[(mode, v)], c):+.3f}" for v in ("base", "margin", "member", "member_neutral"))
                       + f" | {dm(C[(mode, 'margin')], C[(mode, 'base')], c)} | {dm(C[(mode, 'member')], C[(mode, 'base')], c)} |")
        out += ["", f"By fold (all three targets, {mode}): skill.", "",
                "| Fold | Test origins | " + " | ".join(LABELS[v] for v in ("base", "margin", "member", "member_neutral")) + " |",
                "|---|---|---|---|---|---|"]
        o0 = 0
        for f in folds:
            n = len(f["test_dates"])
            rows = slice(o0, o0 + n)
            c = sel()
            out.append(f"| {f['fold']} | {f['test_dates'][0]}..{f['test_dates'][-1]} | " + " | ".join(
                f"{1 - np.nanmean(np.nanmean(C[(mode, v)][rows][:, c], 0) / scale[c]):+.3f}"
                for v in ("base", "margin", "member", "member_neutral")) + " |")
            o0 += n
    # --- 2022, out of sample (fold 6)
    f6 = next((f for f in folds if f["fold"] == 6), None)
    if f6:
        o = f6["test_dates"].index("2022-02")
        ii = int(mm["index"].get_loc(pd.Timestamp("2022-02")))
        events6 = sorted(f6["fits"]["diesel"]["events"])
        out += ["", "## Check 1: the 2022 diesel squeeze (out of sample)", "",
                f"Fold 6 is trained on months to {f6['train_to']}: the 2022 crisis is **out of sample**, and its crisis "
                f"term comes from {', '.join(events6)} only. Origin 2022-02, the month before the first full month of the "
                "war; what-if (given the Brent path and that a crisis started in 2022-03). Crack spread, $/bbl.", "",
                "| Product | h | Actual | Margin model (90%) | Without the crisis term (90%) |", "|---|---|---|---|---|"]
        for p in ("diesel", "jet", "gasoline"):
            cr = f6["modes"]["whatif"]["cracks"][p][o]
            for h in (1, 3, 6):
                a = mm["brent"][ii + h] * np.expm1(mm["r"][p][ii + h])
                out.append(f"| {p} | {h} | {a:.1f} | {cr['mean'][h - 1]:.1f} ({cr['q05'][h - 1]:.1f}..{cr['q95'][h - 1]:.1f}) | "
                           f"{cr['mean_nocrisis'][h - 1]:.1f} ({cr['q05_nocrisis'][h - 1]:.1f}..{cr['q95_nocrisis'][h - 1]:.1f}) |")
        out += ["", "Fuel targets from the same origin (100 × log change; mean and 90% band):", "",
                "| Target | h | Actual | Chain | + margin news | + margin member |", "|---|---|---|---|---|---|"]
        fn = f6["names"]
        for k in TARGETS:
            for h in (1, 3, 6):
                c = fn.index(f"{k}@{h}")
                a = f6["y"][o][c]
                cells = []
                for v in ("base", "margin", "member"):
                    d = f6["modes"]["whatif"][v]
                    cells.append(f"{d['mu'][o][c]:+.1f} ({d['q05'][o][c]:+.1f}..{d['q95'][o][c]:+.1f})")
                out.append(f"| {SHORT[k]} | {h} | {'n/a' if a is None else f'{a:+.1f}'} | " + " | ".join(cells) + " |")
    # --- 2026 inside the folds: fold 7's 12-month targets
    f7 = next((f for f in folds if f["fold"] == 7), None)
    if f7:
        out += ["", "## Check 2a: the 2026 closure inside fold 7 (12 months ahead, out of sample)", "",
                f"Fold 7 is trained on months to {f7['train_to']}; its crisis term comes from "
                f"{', '.join(sorted(f7['fits']['diesel']['events']))}. The table of `notes/verification.md` section 5, "
                "with the margin layer added (what-if).", "",
                "| Origin | Target | Actual | Chain | + margin news | + margin member |", "|---|---|---|---|---|---|"]
        fn = f7["names"]
        for od in ("2025-03", "2025-06", "2025-09"):
            if od not in f7["test_dates"]:
                continue
            o = f7["test_dates"].index(od)
            for k in TARGETS:
                c = fn.index(f"{k}@12")
                a = f7["y"][o][c]
                cells = [f"{f7['modes']['whatif'][v]['mu'][o][c]:+.1f} ({f7['modes']['whatif'][v]['q05'][o][c]:+.1f}.."
                         f"{f7['modes']['whatif'][v]['q95'][o][c]:+.1f})" for v in ("base", "margin", "member")]
                out.append(f"| {od} | {SHORT[k]} | {'n/a' if a is None else f'{a:+.1f}'} | " + " | ".join(cells) + " |")
    # --- the replay
    if rep:
        nm = rep["names"]
        out += ["", "## Check 2b: the 2026 closure replay from 2026-02 (out of sample for the margin layer)", "",
                f"Every model and the margin layer are fitted on months to {rep['train_to']}. The crisis term comes from "
                f"{', '.join(rep['events_used']['diesel'])}: **2026 is out of sample, 2022 is in sample** here. The chain's "
                "draws are rebuilt as `macro_chain.py replay` builds them (same fits and seeds; Bayes sampler: "
                f"{rep['diag']['chains']} chains, warmup {rep['diag']['warmup']}; on another machine the sampler's floating "
                "point can move a number by about 0.1, e.g. retail diesel at 1 month +12.0 here against +11.9 in "
                "`notes/chain-replay-2026-3m.md`). What-if: given the Brent path and that a "
                "crisis started in 2026-03. Lost 82: the flow scenario (in sample for the flow → Brent link), with the "
                "crisis term at full size (82 / 82). Lost 0: a forecast with neither.", "",
                "| Target | h | Actual | What-if: chain | What-if: + margin news | What-if: + margin member | Lost 82: chain | "
                "Lost 82: + margin news | Lost 82: + margin member | Lost 0: chain | Lost 0: + margin member |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]

        def cell(mode, v, c):
            d = rep["modes"][mode]["draws"][v]
            a = rep["actual"][nm[c]]
            mark = "" if a is None else (" ✓" if d["q05"][c] <= a <= d["q95"][c] else " ✗")
            return f"{d['mean'][c]:+.1f} ({d['q05'][c]:+.1f}..{d['q95'][c]:+.1f}){mark}"
        for k in TARGETS:
            for h in (1, 3, 6):
                c = nm.index(f"{k}@{h}")
                a = rep["actual"][nm[c]]
                out.append(f"| {SHORT[k]} | {h} | {'n/a' if a is None else f'{a:+.1f}'} | " + " | ".join(
                    cell(mode, v, c) for mode, vs in (("whatif", ("base", "margin", "member")), ("lost 82", ("base", "margin", "member")),
                                                      ("lost 0", ("base", "member"))) for v in vs) + " |")
        out += ["", "**The overshoot** (actual minus the what-if mean, 100 × log change):", "",
                "| Target | h | " + " | ".join(LABELS[v] for v in VARIANTS) + " |", "|---|---|" + "---|" * len(VARIANTS)]
        for k in TARGETS:
            for h in (1, 3, 6):
                c = nm.index(f"{k}@{h}")
                a = rep["actual"][nm[c]]
                if a is None:
                    continue
                out.append(f"| {SHORT[k]} | {h} | " + " | ".join(f"{a - rep['modes']['whatif']['draws'][v]['mean'][c]:+.1f}" for v in VARIANTS) + " |")
        out += ["", "**All 22 series, horizons 1–6 with published outcomes** (only the three fuel targets change): share inside the 90% band.", "",
                "| Mode | " + " | ".join(LABELS[v] for v in VARIANTS) + " |", "|---|" + "---|" * len(VARIANTS)]
        for mode in ("whatif", "lost 82", "lost 0"):
            cells = []
            for v in VARIANTS:
                ins = [x for x in rep["modes"][mode]["inside"][v] if x is not None]
                cells.append(f"{np.mean(ins):.0%} of {len(ins)}")
            out.append(f"| {mode} | " + " | ".join(cells) + " |")
        out += ["", "**Margins themselves, 2026** (what-if; crack spread, $/bbl; mean and 90% band):", "",
                "| Product | Month | Actual | Margin model | Without the crisis term |", "|---|---|---|---|---|"]
        for p in ("diesel", "jet", "gasoline"):
            for s in (1, 2, 3, 6, rep["seen_brent"]):
                a = rep["actual_cracks"][p][s]
                cr, cn = rep["modes"]["whatif"]["cracks"][p], rep["modes"]["whatif"]["cracks_nocrisis"][p]
                out.append(f"| {p} | {rep['actual_months'][s]} | {'n/a' if a is None else f'{a:.1f}'} | "
                           f"{cr['mean'][s - 1]:.1f} ({cr['q05'][s - 1]:.1f}..{cr['q95'][s - 1]:.1f}) | "
                           f"{cn['mean'][s - 1]:.1f} ({cn['q05'][s - 1]:.1f}..{cn['q95'][s - 1]:.1f}) |")
        a_csv, b_csv = scenario_csvs(rep)
        out += ["", "## The margin scenario for a Hormuz closure", "",
                f"From {rep['origin']} with the oil paths of the flow scenario (GARCH-CGMY plus the premium of `notes/flow-premium.csv`, each path drawn within its band), "
                "the crisis term scaled by lost flow / 82 (an assumption: past crises are not sized in points of Hormuz "
                f"flow). Fitted on months to {rep['train_to']}. Crack spread, $/bbl, mean (90% band). Full table: "
                f"`{a_csv.relative_to(ROOT).as_posix()}`; the fuel targets with the margin layer: `{b_csv.relative_to(ROOT).as_posix()}` "
                "(same columns as `notes/chain-scenarios-3m.csv`).", "",
                "| Product | Lost (points) | 1 month | 3 months | 6 months | 12 months |", "|---|---|---|---|---|---|"]
        for p in ("diesel", "jet", "gasoline"):
            for lost in LOSTS:
                cr = rep["modes"][f"lost {lost:g}"]["cracks"][p]
                out.append(f"| {p} | {lost:g} | " + " | ".join(f"{cr['mean'][s - 1]:.0f} ({cr['q05'][s - 1]:.0f}..{cr['q95'][s - 1]:.0f})"
                                                           for s in (1, 3, 6, 12)) + " |")
        out += ["", f"The same with 2026's own crisis path in the pool ({', '.join(rep['in_sample_events'])}; **in sample**, "
                "so lost 82 partly reproduces 2026 by construction; for a forward scenario, not as evidence). Actual 2026 "
                "cracks for comparison (months 1, 3, 6): " + "; ".join(
                    f"{p} " + ", ".join(f"{rep['actual_cracks'][p][s]:.0f}" for s in (1, 3, 6)) for p in ("diesel", "jet", "gasoline"))
                + ".", "",
                "| Product | Lost (points) | 1 month | 3 months | 6 months | 12 months |", "|---|---|---|---|---|---|"]
        for p in ("diesel", "jet", "gasoline"):
            for lost in (50.0, 82.0, 100.0):
                cr = rep["modes"][f"lost {lost:g}"]["in_sample"]["cracks"][p]
                out.append(f"| {p} | {lost:g} | " + " | ".join(f"{cr['mean'][s - 1]:.0f} ({cr['q05'][s - 1]:.0f}..{cr['q95'][s - 1]:.0f})"
                                                           for s in (1, 3, 6, 12)) + " |")
    top = ["## Summary", ""]
    blocks = np.split(np.arange(n_orig), np.cumsum([len(f["test_dates"]) for f in folds])[:-1])
    for mode, label in (("whatif", "given the real Brent path"), ("levy", "with Lévy oil paths")):
        c = sel()
        wins = sum(skill(C[(mode, "member")][rows], c) > skill(C[(mode, "base")][rows], c) for rows in blocks)
        top.append(f"- **Fuel targets on the 8 folds, {label}:** skill over the three {skill(C[(mode, 'base')], c):+.3f} for the "
                   f"chain, {skill(C[(mode, 'member')], c):+.3f} with the margin member mixed in (difference "
                   f"{dm(C[(mode, 'member')], C[(mode, 'base')], c)}; better in {wins} of {len(folds)} folds). The same "
                   f"member on a neutral margin: {skill(C[(mode, 'member_neutral')], c):+.3f}. Margin news added to the "
                   f"chain instead: {skill(C[(mode, 'margin')], c):+.3f} ({dm(C[(mode, 'margin')], C[(mode, 'base')], c)}).")
    if rep:
        nm = rep["names"]
        parts = []
        for k in TARGETS:
            cc = nm.index(f"{k}@1")
            a = rep["actual"][nm[cc]]
            w = rep["modes"]["whatif"]["draws"]
            parts.append(f"{NAME[k]} {a - w['base']['mean'][cc]:+.1f} → {a - w['member']['mean'][cc]:+.1f} "
                         f"(member) / {a - w['margin']['mean'][cc]:+.1f} (news)")
        top.append("- **The 2026 overshoot, out of sample** (actual minus the what-if mean after 1 month, 100 × log change): "
                   + "; ".join(parts) + ". The 90% band still misses diesel and jet fuel at 1 month.")
        d = rep["modes"]["whatif"]["cracks"]["diesel"]
        top.append(f"- **Why so little:** in 2026-03 the diesel crack was ${rep['actual_cracks']['diesel'][1]:.0f}/bbl against "
                   f"${d['mean'][0]:.0f} ({d['q05'][0]:.0f}..{d['q95'][0]:.0f}) from the margin model with the crisis term of the "
                   "earlier crises. Of those, only 2022 widened margins on this scale (see the crisis table).")
    out[4:4] = top + [""]  # after the title and the provenance line
    (NOTES / "margins-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'margins-results.md'}")


# --- entry -----------------------------------------------------------------------------------

def save(obj: dict, name: str) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / name
    path.write_text(json.dumps(obj | {"meta": {"generated": datetime.now(UTC).isoformat(timespec="seconds"),
                                                "job": os.environ.get("SLURM_JOB_ID")}}))
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("data", "fold", "replay", "report"))
    p.add_argument("j", nargs="*", type=int, default=[])
    a = p.parse_args()
    if a.cmd == "data":
        mm = margins_data()
        print(f"wrote {write_monthly(mm)} (EIA spot fetched {mm['fetched']}, Brent {mm['brent_fetched']})")
    elif a.cmd == "fold":
        for j in a.j or range(8):
            print(f"wrote {save(run_fold(j), f'margins-fold-{j}.json')}", flush=True)
    elif a.cmd == "replay":
        print(f"wrote {save(run_replay(), 'margins-replay.json')}")
    else:
        report()


if __name__ == "__main__":
    main()
