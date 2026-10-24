# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "scipy>=1.11", "pandas>=2.1"]
# ///
"""Which non-Gaussian Levy process fits oil prices?

Each model is a Levy process for log Brent, given by its characteristic exponent psi(u) per
trading day. Brownian motion is psi(u) = i mu u - sigma^2 u^2 / 2; the non-Gaussian models replace
that quadratic. The density at any horizon h is recovered from exp(h psi(u)) as a Fourier-cosine
series (the COS method, Fang & Oosterlee 2008), so every model is fitted and scored the same way.
Closed-form densities are used instead where the series struggles: Gaussian and Merton (thin
tails would be clipped) and variance gamma (its characteristic function decays slowly, so the
series rings in the far tails). CDFs, used for tail coverage, come from the series for every model
without a closed form.

Fitted by maximum likelihood on daily returns before SPLIT, scored after it on:
  * daily log score (mean log density of each realised return) and tail coverage,
  * 5- and 21-day returns using the daily fit scaled by h, over every overlapping h-day window:
    the Levy-specific check that the model's time scaling (i.i.d., infinitely divisible
    increments) matches the data,
  * daily returns divided by an EWMA volatility, to separate fat tails from volatility
    clustering (a crude stand-in for a stochastic-volatility state-space model).
Every score difference comes with a Newey-West standard error, with and without Mar-May 2020.

Zero-return days are kept. To keep every likelihood bounded on them, Merton and Kou have a
diffusion floor (sigma >= 0.1 sd) and variance gamma has nu <= 2 days (no density pole at h = 1).

    uv run experiments/non_gaussian.py   # fetches Brent from FRED, writes notes/non-gaussian-results.md
"""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "DCOILBRENTEU.csv"
OUT = ROOT / "notes" / "non-gaussian-results.md"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
SPLIT = "2008-10-15"  # first half of the history trains, second half tests
SPRING_2020 = ("2020-03-01", "2020-05-31")  # the WTI-goes-negative months, reported separately
EWMA_LAMBDA = 0.94  # RiskMetrics daily decay
EWMA_SEED = 50  # days used to start the EWMA; they are not fitted or scored
SIGMA_FLOOR = 0.1  # jump-diffusion sigma >= this times the data's sd, so no atom forms
HAC_LAG = 10
FLOOR = 1e-12  # COS densities below this are clipped (counted in the tables)
TAILS = (0.01, 0.05, 0.95, 0.99)


def load_brent() -> tuple[pd.Series, str]:
    """Daily Brent spot in $/bbl, cached under data/raw/ (git-ignored)."""
    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FRED_URL, RAW)
    fetched = datetime.fromtimestamp(RAW.stat().st_mtime, UTC).date().isoformat()
    df = pd.read_csv(RAW, parse_dates=["observation_date"])
    price = pd.to_numeric(df["DCOILBRENTEU"], errors="coerce")
    price.index = df["observation_date"]
    return price.dropna(), fetched


@dataclass
class Cos:
    """Density and CDF of a characteristic function on [-half, half] as a Fourier-cosine series."""

    half: float
    terms: int = 2048

    def __post_init__(self) -> None:
        self.a = -self.half
        self.u = np.arange(self.terms) * np.pi / (2 * self.half)
        self.w = np.full(self.terms, 1 / self.half)  # 2 / (b - a), first term halved
        self.w[0] /= 2

    def coef(self, log_cf: np.ndarray) -> np.ndarray:
        return self.w * np.real(np.exp(log_cf - 1j * self.u * self.a))

    def basis(self, x: np.ndarray) -> np.ndarray:
        return np.cos(np.outer(x - self.a, self.u))

    def cdf(self, x: np.ndarray, coef: np.ndarray) -> np.ndarray:
        y = x - self.a
        return np.clip(coef[0] * y + np.sin(np.outer(y, self.u[1:])) @ (coef[1:] / self.u[1:]), 0, 1)


class Data:
    """Returns at one horizon, with the COS basis precomputed since the data never change."""

    def __init__(self, x, cos: Cos) -> None:
        self.x, self.cos = np.asarray(x, float), cos
        self.basis = cos.basis(self.x)


@dataclass
class Model:
    name: str
    start: Callable[[float, float], list[float]]  # (centre, sd) of daily data -> unconstrained
    unpack: Callable[[np.ndarray], dict]
    psi: Callable[[dict, np.ndarray], np.ndarray]  # daily characteristic exponent
    exact_logpdf: Callable[[dict, np.ndarray, float], np.ndarray] | None = None
    exact_cdf: Callable[[dict, np.ndarray, float], np.ndarray] | None = None
    alt_starts: Callable[[float, float], list[list[float]]] | None = None
    sigma_floor: bool = False


def logpdf(model: Model, p: dict, data: Data, h: float) -> tuple[np.ndarray, int]:
    if model.exact_logpdf:
        return model.exact_logpdf(p, data.x, h), 0
    f = data.basis @ data.cos.coef(h * model.psi(p, data.cos.u))
    return np.log(np.maximum(f, FLOOR)), int((f < FLOOR).sum())


def cdf(model: Model, p: dict, data: Data, h: float) -> np.ndarray:
    if model.exact_cdf:
        return model.exact_cdf(p, data.x, h)
    return data.cos.cdf(data.x, data.cos.coef(h * model.psi(p, data.cos.u)))


def sig(t):
    return 1 / (1 + np.exp(-t))


def logit(q: float) -> float:
    return float(np.log(q / (1 - q)))


# --- the models -----------------------------------------------------------------------------

def gauss_logpdf(p, x, h):
    return stats.norm.logpdf(x, p["mu"] * h, p["sigma"] * np.sqrt(h))


def gauss_cdf(p, x, h):
    return stats.norm.cdf(x, p["mu"] * h, p["sigma"] * np.sqrt(h))


def student_psi(p, u):
    nu = p["nu"]
    z = np.sqrt(nu) * np.abs(p["scale"] * u)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_phi = ((nu / 2) * np.log(z) + np.log(special.kve(nu / 2, z)) - z
                   - special.gammaln(nu / 2) - (nu / 2 - 1) * np.log(2))
    return 1j * p["mu"] * u + np.where(z == 0, 0.0, log_phi)


def nig_psi(p, u):
    a, b, d = p["alpha"], p["beta"], p["delta"]
    return 1j * p["mu"] * u + d * (np.sqrt(a * a - b * b) - np.sqrt(a * a - (b + 1j * u) ** 2))


def vg_psi(p, u):
    s, n, th = p["sigma"], p["nu"], p["theta"]
    return 1j * p["mu"] * u - np.log(1 - 1j * th * n * u + 0.5 * s * s * n * u * u) / n


def vg_logpdf(p, x, h):
    """Madan, Carr & Chang (1998) density: theta G + sigma W(G), G ~ Gamma(h / nu, nu)."""
    s, n, th = p["sigma"], p["nu"], p["theta"]
    y = x - p["mu"] * h
    c = 2 * s * s / n + th * th
    z = np.abs(y) * np.sqrt(c) / (s * s)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (np.log(2) + th * y / (s * s) - (h / n) * np.log(n) - 0.5 * np.log(2 * np.pi)
                - np.log(s) - special.gammaln(h / n) + (h / (2 * n) - 0.25) * np.log(y * y / c)
                + np.log(special.kve(h / n - 0.5, z)) - z)


def merton_psi(p, u):
    jump = np.exp(1j * p["mu_j"] * u - 0.5 * (p["sigma_j"] * u) ** 2) - 1
    return 1j * p["mu"] * u - 0.5 * (p["sigma"] * u) ** 2 + p["lam"] * jump


def merton_mix(p, h):
    lam_h = p["lam"] * h
    n = np.arange(int(lam_h + 10 * np.sqrt(lam_h) + 30))[:, None]
    scale = np.sqrt(p["sigma"] ** 2 * h + n * p["sigma_j"] ** 2)
    return stats.poisson.logpmf(n, lam_h), p["mu"] * h + n * p["mu_j"], scale


def merton_logpdf(p, x, h):
    w, loc, scale = merton_mix(p, h)
    return special.logsumexp(w + stats.norm.logpdf(x, loc, scale), axis=0)


def merton_cdf(p, x, h):
    w, loc, scale = merton_mix(p, h)
    return (np.exp(w) * stats.norm.cdf(x, loc, scale)).sum(axis=0)


def kou_psi(p, u):
    up, down, q = p["eta_up"], p["eta_down"], p["p_up"]
    jump = q * up / (up - 1j * u) + (1 - q) * down / (down + 1j * u) - 1
    return 1j * p["mu"] * u - 0.5 * (p["sigma"] * u) ** 2 + p["lam"] * jump


def cgmy_psi(p, u):
    C, G, M, Y = p["C"], p["G"], p["M"], p["Y"]
    return 1j * p["mu"] * u + C * special.gamma(-Y) * (
        (M - 1j * u) ** Y - M ** Y + (G + 1j * u) ** Y - G ** Y)


def stable_psi(p, u):
    a = p["alpha"]
    return 1j * p["mu"] * u - np.abs(p["c"] * u) ** a * (
        1 - 1j * p["beta"] * np.sign(u) * np.tan(np.pi * a / 2))


def cgmy_start(c, s):
    Y, G = 1.3, 0.5 / s
    C = s * s / (special.gamma(2 - Y) * 2 * G ** (Y - 2))
    return [c, np.log(C), np.log(G), np.log(G), logit(Y / 1.999)]


MODELS = [
    Model("Gaussian (Brownian motion)",
          lambda c, s: [c, np.log(s)],
          lambda t: {"mu": t[0], "sigma": np.exp(t[1])},
          lambda p, u: 1j * p["mu"] * u - 0.5 * (p["sigma"] * u) ** 2,
          gauss_logpdf, gauss_cdf),
    Model("Student-t",
          lambda c, s: [c, np.log(0.6 * s), np.log(2.5)],
          lambda t: {"mu": t[0], "scale": np.exp(t[1]), "nu": 0.5 + np.exp(t[2])},
          student_psi),
    Model("NIG (normal inverse Gaussian)",
          lambda c, s: [np.log(1.5 / s), 0.0, np.log(1.5 * s), c],
          lambda t: {"alpha": np.exp(t[0]), "beta": np.exp(t[0]) * np.tanh(t[1]),
                     "delta": np.exp(t[2]), "mu": t[3]},
          nig_psi),
    Model("Variance gamma",
          lambda c, s: [c, np.log(s), logit(0.5), 0.0],
          lambda t: {"mu": t[0], "sigma": np.exp(t[1]), "nu": 2 * sig(t[2]), "theta": t[3]},
          vg_psi, vg_logpdf),
    Model("Merton jump-diffusion",
          lambda c, s: [c, np.log(0.7 * s), np.log(0.05), 0.0, np.log(3 * s)],
          lambda t: {"mu": t[0], "sigma": np.exp(t[1]), "lam": np.exp(t[2]), "mu_j": t[3],
                     "sigma_j": np.exp(t[4])},
          merton_psi, merton_logpdf, merton_cdf,
          alt_starts=lambda c, s: [[c, np.log(0.3 * s), np.log(0.5), 0.0, np.log(1.5 * s)],
                                   [c, np.log(0.9 * s), np.log(0.01), 0.0, np.log(6 * s)]],
          sigma_floor=True),
    Model("Kou double-exponential jumps",
          lambda c, s: [c, np.log(0.7 * s), np.log(0.1), 0.0, np.log(0.5 / s), np.log(0.5 / s)],
          lambda t: {"mu": t[0], "sigma": np.exp(t[1]), "lam": np.exp(t[2]), "p_up": sig(t[3]),
                     "eta_up": np.exp(t[4]), "eta_down": np.exp(t[5])},
          kou_psi,
          alt_starts=lambda c, s: [[c, np.log(0.3 * s), np.log(1.0), 0.0, np.log(1 / s), np.log(1 / s)],
                                   [c, np.log(0.9 * s), np.log(0.02), 0.0, np.log(0.2 / s), np.log(0.2 / s)]],
          sigma_floor=True),
    Model("CGMY (tempered stable)",
          cgmy_start,
          lambda t: {"mu": t[0], "C": np.exp(t[1]), "G": np.exp(t[2]), "M": np.exp(t[3]),
                     "Y": 1.999 * sig(t[4])},
          cgmy_psi),
    Model("alpha-stable",
          lambda c, s: [c, np.log(0.5 * s), logit(0.7), 0.0],
          lambda t: {"mu": t[0], "c": np.exp(t[1]), "alpha": 1 + sig(t[2]), "beta": np.tanh(t[3])},
          stable_psi),
]


# --- fitting and scoring --------------------------------------------------------------------

def fit(model: Model, data: Data, centre: float, sd: float) -> tuple[dict, float, int]:
    def nll(t):
        with np.errstate(all="ignore"):
            p = model.unpack(t)
            if model.sigma_floor and p["sigma"] < SIGMA_FLOOR * sd:
                return 1e12
            lp, _ = logpdf(model, p, data, 1.0)
            value = -lp.sum()
        return value if np.isfinite(value) else 1e12

    opts = {"maxiter": 8000, "maxfev": 8000, "xatol": 1e-6, "fatol": 1e-4, "adaptive": True}
    starts = [model.start(centre, sd)] + (model.alt_starts(centre, sd) if model.alt_starts else [])
    best = None
    for t in starts:
        t = np.array(t, float)
        for _ in range(3):  # Nelder-Mead stalls; restarting from its own answer helps
            res = optimize.minimize(nll, t, method="Nelder-Mead", options=opts)
            t = res.x
        if best is None or res.fun < best.fun:
            best = res
    return model.unpack(best.x), -best.fun, len(best.x)


def coverage(pit: np.ndarray) -> list[float]:
    return [float(np.mean(pit < q) if q < 0.5 else np.mean(pit > q)) for q in TAILS]


def ewma_sigma(r: np.ndarray) -> np.ndarray:
    """Volatility forecast for day t from returns up to t-1 (seeded on the first EWMA_SEED days)."""
    var = np.empty(len(r))
    var[0] = np.var(r[:EWMA_SEED])
    for i in range(1, len(r)):
        var[i] = EWMA_LAMBDA * var[i - 1] + (1 - EWMA_LAMBDA) * r[i - 1] ** 2
    return np.sqrt(var)


def hac_se(d: np.ndarray, lag: int) -> float:
    """Newey-West standard error of the mean of d."""
    d = d - d.mean()
    n = len(d)
    v = d @ d / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return float(np.sqrt(v / n))


def diff_cell(a: np.ndarray, b: np.ndarray, lag: int) -> str:
    d = a - b
    return f"{d.mean():+.4f} ± {hac_se(d, lag):.4f}"


def fmt_params(p: dict) -> str:
    return ", ".join(f"{k}={v:.4g}" for k, v in p.items())


def pct(values: list[float]) -> str:
    return " / ".join(f"{100 * v:.2f}" for v in values)


def main() -> None:
    started = time.time()
    price, fetched = load_brent()
    r = np.log(price).diff().dropna()
    sigma_t = pd.Series(ewma_sigma(r.values), r.index)
    train = (r.index < SPLIT) & (np.arange(len(r)) >= EWMA_SEED)
    test = r.index >= SPLIT
    centre, sd = float(r[train].mean()), float(r[train].std())

    daily_tr, daily_te = Data(r[train], Cos(3.0, 4096)), Data(r[test], Cos(3.0, 4096))
    z = r / sigma_t
    z_tr, z_te = Data(z[train], Cos(20.0, 1024)), Data(z[test], Cos(20.0, 1024))
    log_sigma_te = np.log(sigma_t[test].values)
    calm = ~((r.index[test] >= SPRING_2020[0]) & (r.index[test] <= SPRING_2020[1]))
    # Every overlapping h-day window in the test period, starting from the last training close.
    lp_test = np.log(price[price.index >= r[train].index[-1]])
    horizons = {}
    for h, half in ((5, 4.0), (21, 5.0)):
        x = lp_test.values[h:] - lp_test.values[:-h]
        ends = lp_test.index[h:]
        horizons[h] = (Data(x, Cos(half, 2048)),
                       ~((ends >= SPRING_2020[0]) & (lp_test.index[:-h] <= SPRING_2020[1])))

    rows = []
    for model in MODELS:
        t0 = time.time()
        p, ll_train, k = fit(model, daily_tr, centre, sd)
        lp_te, floor_hits = logpdf(model, p, daily_te, 1.0)
        row = {"model": model, "p": p, "k": k, "aic": 2 * k - 2 * ll_train, "lp": lp_te,
               "floor": floor_hits, "cover": coverage(cdf(model, p, daily_te, 1.0)), "h": {}}
        for h, (data, _) in horizons.items():
            lp_h, hits_h = logpdf(model, p, data, float(h))
            row["h"][h] = (lp_h, coverage(cdf(model, p, data, float(h))), hits_h)
        pz, _, _ = fit(model, z_tr, float(z[train].mean()), float(z[train].std()))
        lz, hits_z = logpdf(model, pz, z_te, 1.0)
        row["ewma"] = (lz - log_sigma_te, coverage(cdf(model, pz, z_te, 1.0)), pz, hits_z)
        rows.append(row)
        print(f"{model.name}: test log score {lp_te.mean():.4f}, "
              f"EWMA {row['ewma'][0].mean():.4f} ({time.time() - t0:.0f}s)", flush=True)

    # The Fourier-series densities should match the closed forms where those exist.
    by_name = {row["model"].name: row for row in rows}
    checks = []
    p = by_name["Student-t"]["p"]
    checks.append(("Student-t", stats.t.logpdf(daily_te.x, p["nu"], p["mu"], p["scale"]), MODELS[1], p))
    p = by_name["NIG (normal inverse Gaussian)"]["p"]
    checks.append(("NIG", stats.norminvgauss.logpdf(daily_te.x, p["alpha"] * p["delta"],
                                                     p["beta"] * p["delta"], p["mu"], p["delta"]),
                   MODELS[2], p))
    p = by_name["Variance gamma"]["p"]
    checks.append(("Variance gamma", vg_logpdf(p, daily_te.x, 1.0), MODELS[3], p))
    p = by_name["Merton jump-diffusion"]["p"]
    checks.append(("Merton", merton_logpdf(p, daily_te.x, 1.0), MODELS[4], p))
    check_lines = []
    for name, exact, model, p in checks:
        f = daily_te.basis @ daily_te.cos.coef(model.psi(p, daily_te.cos.u))
        ok = exact > np.log(1e-6)
        err = np.abs(np.log(np.maximum(f, FLOOR)) - exact)[ok].max()
        check_lines.append(f"| {name} | {err:.2e} | {ok.sum()} |")

    write_report(rows, check_lines, price, fetched, r, train, test, horizons, calm,
                 runtime=time.time() - started)


def write_report(rows, check_lines, price, fetched, r, train, test, horizons, calm, runtime):
    base, t_row = rows[0], rows[1]
    today = datetime.now(UTC).date().isoformat()
    tr, te = r.index[train], r.index[test]
    zeros = int((r[test] == 0).sum()) + int((r[train] == 0).sum())
    out = [
        "# Non-Gaussian Lévy models for Brent: results",
        "",
        f"_Generated by `experiments/non_gaussian.py` on {today} in {runtime / 60:.1f} min. Data: "
        f"Brent spot, FRED series DCOILBRENTEU (source EIA), fetched {fetched}, covering "
        f"{price.index[0].date()} to {price.index[-1].date()}. Daily log returns, all days kept "
        f"({zeros} of them zero). Train {tr[0].date()} to {tr[-1].date()} ({len(tr)} days, after "
        f"the {EWMA_SEED}-day EWMA seed), test {te[0].date()} to {te[-1].date()} ({len(te)} days). "
        f"Nothing here is synthetic._",
        "",
        "**How to read it.** Log score = mean log density of the realised test return; higher is "
        "better, and differences are in nats per observation. ± is a Newey-West standard error "
        f"(lag {HAC_LAG} daily, lag h for h-day windows): a difference within about twice its ± is "
        "not distinguishable from zero. \"Without Mar-May 2020\" drops the months when WTI went "
        "negative and Brent fell 64% in a day (2020-04-21), which on its own moves the Gaussian's "
        "mean score by about 0.07. Tail columns give the % of test days below the model's 1% and 5% "
        "quantiles and above its 95% and 99% quantiles; a calibrated model shows 1 / 5 / 5 / 1. "
        "Clipped counts days where the Fourier-series density fell below 1e-12.",
        "",
        "## 1. Daily returns, i.i.d. Lévy increments",
        "",
        "| Model | Params | Train AIC vs Gaussian | Test log score vs Gaussian | without Mar-May 2020 | vs Student-t | Tails % (1 / 5 / 95 / 99) | Clipped |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        out.append(f"| {row['model'].name} | {row['k']} | {row['aic'] - base['aic']:+.0f} | "
                   f"{diff_cell(row['lp'], base['lp'], HAC_LAG)} | "
                   f"{diff_cell(row['lp'][calm], base['lp'][calm], HAC_LAG)} | "
                   f"{diff_cell(row['lp'], t_row['lp'], HAC_LAG)} | {pct(row['cover'])} | {row['floor']} |")
    n = len(te)
    out += [
        "",
        f"Gaussian test log score: {base['lp'].mean():.4f} nats/day ({base['lp'][calm].mean():.4f} "
        f"without Mar-May 2020). Binomial standard error of a tail percentage over {n} days: "
        f"{100 * np.sqrt(0.01 * 0.99 / n):.2f} at 1%, {100 * np.sqrt(0.05 * 0.95 / n):.2f} at 5%.",
        "",
        "## 2. Longer horizons from the daily fit (Lévy time scaling)",
        "",
        "The daily parameters are scaled to h days (exp(h ψ)) and scored on every overlapping h-day "
        "test window, so the result does not depend on which day the windows start.",
        "",
        "| Model | " + " | ".join(f"{h}-day vs Gaussian | {h}-day without Mar-May 2020 | {h}-day vs Student-t | "
                                  f"{h}-day tails % | Clipped" for h in horizons) + " |",
        "|---|" + "---|---|---|---|---|" * len(horizons),
    ]
    for row in rows:
        cells = []
        for h, (data, calm_h) in horizons.items():
            lp_h, cov_h, hits_h = row["h"][h]
            lp_b, lp_t = base["h"][h][0], t_row["h"][h][0]
            cells.append(f"{diff_cell(lp_h, lp_b, h)} | {diff_cell(lp_h[calm_h], lp_b[calm_h], h)} | "
                         f"{diff_cell(lp_h, lp_t, h)} | {pct(cov_h)} | {hits_h}")
        out.append(f"| {row['model'].name} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Windows: " + ", ".join(f"{len(d.x)} at {h} days" for h, (d, _) in horizons.items())
        + ". Overlapping windows share days, which the lag-h standard errors account for.",
        "",
        "## 3. Daily returns after dividing by an EWMA volatility (λ = 0.94)",
        "",
        "Each model is refitted to r_t / σ_t, where σ_t uses returns up to t−1 only; scores are in "
        "return units so they compare with section 1. The gain over section 1 is what volatility "
        "clustering explains; what is left between models is the tail shape.",
        "",
        "| Model | vs Gaussian+EWMA | without Mar-May 2020 | vs Student-t+EWMA | vs i.i.d. Gaussian | Tails % (1 / 5 / 95 / 99) | Clipped |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lz, cov_z, _, hits_z = row["ewma"]
        out.append(f"| {row['model'].name} | {diff_cell(lz, base['ewma'][0], HAC_LAG)} | "
                   f"{diff_cell(lz[calm], base['ewma'][0][calm], HAC_LAG)} | "
                   f"{diff_cell(lz, t_row['ewma'][0], HAC_LAG)} | {diff_cell(lz, base['lp'], HAC_LAG)} | "
                   f"{pct(cov_z)} | {hits_z} |")
    out += [
        "",
        "## Fitted parameters (daily, i.i.d.)",
        "",
        "| Model | Parameters |",
        "|---|---|",
    ] + [f"| {row['model'].name} | {fmt_params(row['p'])} |" for row in rows] + [
        "",
        "## Check: Fourier-cosine densities against closed forms",
        "",
        "Largest absolute error in log density over test days where the density exceeds 1e-6. "
        "Variance gamma's row is large because its characteristic function decays slowly, so the "
        "series rings in the far tails; its scores use the closed form, and its CDF from the series "
        "(used for the tail columns) is accurate to about 1e-5.",
        "",
        "| Model | Max abs log error | Days checked |",
        "|---|---|---|",
    ] + check_lines + [""]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
