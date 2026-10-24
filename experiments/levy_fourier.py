# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "scipy>=1.11", "pandas>=2.1"]
# ///
"""GARCH-scaled Lévy model for oil whose jump measure is learned: CGMY times exp(Fourier series).

    r_t = mu + sigma_t X_t,    sigma_t^2 = omega + alpha (r_{t-1} - mu)^2 + beta sigma_{t-1}^2

X_t are i.i.d. zero-mean, unit-variance increments of a pure-jump Lévy process with Lévy density

    nu(x) = C |x|^(-1-Y) exp(-M x + g_up(x))          x > 0
    nu(x) = C |x|^(-1-Y) exp(-G |x| + g_down(|x|))     x < 0
    g(s)  = sum_k a_k sin(pi s / L) sin(pi k s / L)  for s <= L, and 0 beyond

With every a_k = 0 this is CGMY. The Fourier part reshapes the tails while nu stays >= 0, so every
parameter value is a valid Lévy process (and h-day laws stay coherent). C is set so Var X = 1.
Independent Gaussian priors a_k ~ N(0, (tau / k)^2) make the fit a MAP estimate; tau is chosen on
the last VALID_YEARS of the training window, and a Laplace approximation gives bands for g.

The characteristic exponent is psi_CGMY(u) plus the integral of (e^{iux} - 1 - iux) against the
Fourier correction to nu, computed by one FFT on the frequency grid the COS method uses; the
density then comes from the COS series by one DCT.

Baselines share the same GARCH filter: Gaussian, Student-t and CGMY innovations. Daily scores are
log scores with Newey-West standard errors; 5- and 21-day forecasts are simulated (common random
numbers across models) and scored by CRPS.

    uv run experiments/levy_fourier.py check           # numerical self-checks
    uv run experiments/levy_fourier.py fit             # fixed split, writes runs/levy/fixed.json
    uv run experiments/levy_fourier.py rolling 2015    # train before 2015, score 2015
    uv run experiments/levy_fourier.py fit --family iid   # same with constant sigma (i.i.d. Lévy)
    uv run experiments/levy_fourier.py report          # runs/levy/*.json -> notes/levy-fourier-results.md
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import fft, optimize, signal, special, stats

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "DCOILBRENTEU.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
RUNS = ROOT / "runs" / "levy"
NOTE = ROOT / "notes" / "levy-fourier-results.md"
SPLIT = "2008-10-15"
VALID_YEARS = 4
SPRING_2020 = ("2020-03-01", "2020-05-31")

HALF = 40.0  # densities live on [-HALF, HALF] in units of sigma_t
TERMS = 8192  # COS terms, also the number of density grid points
N_FFT = 2 ** 17  # grid for the Lévy-measure integral; its period 4 * HALF matches the COS frequencies
L = 15.0  # the Fourier part of the Lévy density lives on |x| <= L
K = 6  # Fourier terms per side
TAUS = (0.0, 0.25, 0.5, 1.0, 2.0)
HORIZONS = (5, 21)
FLOOR = 1e-14
OFF_GRID_SLOPE = 50.0  # log-density drop per sd beyond [-HALF, HALF]
DEGENERATE_LP = 8.0  # a daily log density above this means a fit has collapsed (sigma -> 0)
TAILS = (0.01, 0.05, 0.95, 0.99)
QUICK = False  # --quick: few optimiser steps and two taus, to smoke-test the pipeline

U = np.arange(TERMS) * np.pi / (2 * HALF)
XG = np.linspace(-HALF, HALF, TERMS)
DX = 4 * HALF / N_FFT
_i = np.arange(N_FFT)
XF = DX * np.where(_i < N_FFT // 2, _i, _i - N_FFT)
UP = (XF > 0) & (XF <= L)
DOWN = (XF < 0) & (XF >= -L)
KS = np.arange(1, K + 1)


def fourier_basis(s: np.ndarray) -> np.ndarray:
    """Basis for g on [0, L], one column per k: sin(pi s / L) sin(pi k s / L).

    Every term vanishes like s^2 at 0 and at L, so nu joins CGMY smoothly at both ends, and the even
    terms are not symmetric about L / 2, so small and large jumps can be reshaped independently.
    """
    s = np.asarray(s, float)
    return np.sin(np.pi * s / L)[:, None] * np.sin(np.pi * np.outer(s, KS) / L)


B_UP = fourier_basis(XF[UP])
B_DOWN = fourier_basis(-XF[DOWN])


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


def sig(t):
    return 1 / (1 + np.exp(-t))


def logit(q: float) -> float:
    return float(np.log(q / (1 - q)))


# --- innovations ----------------------------------------------------------------------------

def increasing(cdf: np.ndarray) -> np.ndarray:
    """Make a CDF table strictly increasing so np.interp can invert it."""
    return np.maximum.accumulate(np.clip(cdf, 0, 1)) + 1e-15 * np.arange(len(cdf))


class Gauss:
    def logpdf(self, z):
        return stats.norm.logpdf(z)

    def cdf(self, z):
        return stats.norm.cdf(z)

    def table(self):
        return increasing(stats.norm.cdf(XG)), XG


class Student:
    def __init__(self, nu: float) -> None:
        self.nu, self.s = nu, np.sqrt((nu - 2) / nu)  # unit variance

    def logpdf(self, z):
        return stats.t.logpdf(z / self.s, self.nu) - np.log(self.s)

    def cdf(self, z):
        return stats.t.cdf(z / self.s, self.nu)

    def table(self):
        return increasing(self.cdf(XG)), XG


def levy_psi(G, M, Y, a_up, a_down) -> tuple[np.ndarray, float]:
    """Characteristic exponent at U of the zero-mean Lévy process with C = 1, and its variance."""
    gy = special.gamma(-Y)
    psi = gy * ((M - 1j * U) ** Y - M ** Y + (G + 1j * U) ** Y - G ** Y)
    psi -= 1j * U * gy * Y * (G ** (Y - 1) - M ** (Y - 1))  # remove the CGMY mean
    var = special.gamma(2 - Y) * (M ** (Y - 2) + G ** (Y - 2))
    if np.any(a_up) or np.any(a_down):
        h = np.zeros(N_FFT)  # CGMY density times (e^g - 1); vanishes like x^2 at 0 and at +-L
        xu, xd = XF[UP], -XF[DOWN]
        h[UP] = xu ** (-1 - Y) * np.exp(-M * xu) * np.expm1(B_UP @ a_up)
        h[DOWN] = xd ** (-1 - Y) * np.exp(-G * xd) * np.expm1(B_DOWN @ a_down)
        transform = N_FFT * np.fft.ifft(h)[:TERMS]  # sum_j h_j e^{i u x_j}
        psi = psi + DX * (transform - h.sum() - 1j * U * (XF * h).sum())
        var += DX * (XF ** 2 * h).sum()
    return psi, var


def cos_density(psi: np.ndarray) -> np.ndarray:
    """COS series on XG from the characteristic exponent, summed with one DCT-I."""
    coef = np.real(np.exp(psi + 1j * U * HALF)) / HALF
    coef[0] /= 2
    y = fft.dct(coef, type=1)
    return (y + coef[0] + (-1.0) ** np.arange(TERMS) * coef[-1]) / 2


class Levy:
    def __init__(self, G, M, Y, a_up, a_down) -> None:
        psi1, var1 = levy_psi(G, M, Y, a_up, a_down)
        self.C = 1 / var1
        f = cos_density(self.C * psi1)
        self.logf = np.log(np.maximum(f, FLOOR))
        mid = (f[1:] + f[:-1]) / 2 * (XG[1] - XG[0])
        cdf = np.concatenate([[0.0], np.cumsum(np.maximum(mid, 0))])
        self.cdf_grid = increasing(cdf / cdf[-1])

    def logpdf(self, z):
        # Beyond the grid the log density keeps falling steeply. Clamping it to the edge value
        # would let a fit shrink sigma to 0 and collect -log(sigma) without limit.
        edge = np.interp(z, XG, self.logf)
        return edge - OFF_GRID_SLOPE * np.maximum(np.abs(z) - HALF, 0)

    def cdf(self, z):
        return np.interp(z, XG, self.cdf_grid)

    def table(self):
        return self.cdf_grid, XG


# --- the model ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Spec:
    name: str
    kind: str  # gauss | student | levy
    tau: float = 0.0  # Fourier prior scale; 0 is plain CGMY
    garch: bool = True  # False: constant sigma, i.e. i.i.d. Lévy increments

    @property
    def fourier(self) -> bool:
        return self.kind == "levy" and self.tau > 0

    @property
    def a0(self) -> int:
        """Index of the first Fourier coefficient in the parameter vector."""
        return (4 if self.garch else 2) + 3


def unpack(spec: Spec, t: np.ndarray):
    """Parameters -> (mu, omega, alpha, beta, innovation); i.i.d. specs have alpha = beta = 0."""
    mu, omega = t[0], np.exp(t[1])
    if spec.garch:
        persistence = 0.999 * sig(t[2])
        alpha = persistence * sig(t[3])
        rest = t[4:]
    else:
        persistence = alpha = 0.0
        rest = t[2:]
    if spec.kind == "gauss":
        inn = Gauss()
    elif spec.kind == "student":
        inn = Student(2 + np.exp(rest[0]))
    else:
        a = rest[3:] if spec.fourier else np.zeros(2 * K)
        Y = 0.5 + 1.45 * sig(rest[2])
        if abs(Y - 1) < 1e-9:
            Y += 2e-9  # gamma(-Y) has a pole at Y = 1; the exponent is continuous across it
        inn = Levy(np.exp(rest[0]), np.exp(rest[1]), Y, a[:K], a[K:])
    return mu, omega, alpha, persistence - alpha, inn


def describe(spec: Spec, t: np.ndarray) -> dict:
    mu, omega, alpha, beta, inn = unpack(spec, t)
    out = {"mu": mu, "omega": omega, "alpha": alpha, "beta": beta} if spec.garch else \
        {"mu": mu, "sigma": np.sqrt(omega)}
    if spec.kind == "student":
        out["nu"] = inn.nu
    if spec.kind == "levy":
        rest = t[spec.a0 - 3:]
        out |= {"G": np.exp(rest[0]), "M": np.exp(rest[1]), "Y": 0.5 + 1.45 * sig(rest[2]), "C": inn.C}
        if spec.fourier:
            out |= {f"a_up{k}": rest[3 + k - 1] for k in KS} | {f"a_down{k}": rest[3 + K + k - 1] for k in KS}
    return {k: float(v) for k, v in out.items()}


def garch_sigma(r: np.ndarray, mu, omega, alpha, beta) -> np.ndarray:
    """sigma_t from returns up to t-1, started at the model's unconditional variance."""
    s2 = np.empty(len(r))
    s2[0] = omega / (1 - alpha - beta)
    e2 = (r[:-1] - mu) ** 2
    s2[1:] = signal.lfilter([1.0], [1.0, -beta], omega + alpha * e2, zi=[beta * s2[0]])[0]
    return np.sqrt(s2)


def day_scores(spec: Spec, t: np.ndarray, r: np.ndarray):
    """Log density, PIT and sigma for every day of r (each using only earlier days)."""
    mu, omega, alpha, beta, inn = unpack(spec, t)
    s = garch_sigma(r, mu, omega, alpha, beta)
    z = (r - mu) / s
    return inn.logpdf(z) - np.log(s), inn.cdf(z), s


def objective(t, spec: Spec, r: np.ndarray) -> float:
    with np.errstate(all="ignore"):
        try:
            lp, _, _ = day_scores(spec, t, r)
        except (FloatingPointError, ValueError, ZeroDivisionError):
            return 1e12
        value = -lp.sum()
        if spec.fourier:
            a = t[spec.a0:]
            value += 0.5 * np.sum((np.tile(KS, 2) * a / spec.tau) ** 2)
    return float(value) if np.isfinite(value) else 1e12


def start(spec: Spec, r: np.ndarray) -> np.ndarray:
    v = float(np.var(r))
    t = [float(np.mean(r)), np.log(0.02 * v), logit(0.98 / 0.999), logit(0.07 / 0.98)] if spec.garch \
        else [float(np.mean(r)), np.log(v)]
    if spec.kind == "student":
        t += [np.log(4.0)]
    if spec.kind == "levy":
        t += [0.0, 0.0, logit(0.7 / 1.45)] + [0.0] * (2 * K if spec.fourier else 0)
    return np.array(t)


def fit(spec: Spec, r: np.ndarray, t0: np.ndarray | None = None) -> np.ndarray:
    t = start(spec, r) if t0 is None else np.asarray(t0, float)
    res = optimize.minimize(objective, t, args=(spec, r), method="L-BFGS-B",
                            options={"maxiter": 20 if QUICK else 1000, "eps": 1e-7})
    polish = optimize.minimize(objective, res.x, args=(spec, r), method="Nelder-Mead",
                               options={"maxiter": 40 if QUICK else 3000, "xatol": 1e-6, "fatol": 1e-4,
                                        "adaptive": True})
    return polish.x if polish.fun <= res.fun else res.x


def laplace_band(spec: Spec, t: np.ndarray, r: np.ndarray, draws: int = 500) -> dict:
    """Gaussian approximation to the posterior of the Fourier coefficients -> bands for g(s)."""
    n, step = len(t), 1e-3
    f0 = objective(t, spec, r)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            ei, ej = np.eye(n)[i] * step, np.eye(n)[j] * step
            H[i, j] = H[j, i] = (objective(t + ei + ej, spec, r) - objective(t + ei - ej, spec, r)
                                 - objective(t - ei + ej, spec, r) + objective(t - ei - ej, spec, r)) / (4 * step ** 2)
    w, V = np.linalg.eigh(H)
    cov = (V / np.maximum(w, 1e-8)) @ V.T
    rng = np.random.default_rng(0)
    a0 = spec.a0
    a = rng.multivariate_normal(t[a0:], cov[a0:, a0:], size=draws)
    s = np.array([0.5, 1, 2, 3, 4, 6, 8, 10, 12])
    basis = fourier_basis(s)
    out = {"s": s.tolist(), "min_hessian_eig": float(w.min()), "f0": f0}
    for side, cols in (("up", slice(0, K)), ("down", slice(K, 2 * K))):
        g = a[:, cols] @ basis.T
        out[side] = {"map": (basis @ t[a0:][cols]).tolist(),
                     "lo": np.quantile(g, 0.05, axis=0).tolist(),
                     "hi": np.quantile(g, 0.95, axis=0).tolist()}
    return out


# --- multi-day forecasts --------------------------------------------------------------------

def crps_pit(samples: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """CRPS and PIT per row of samples (rows = forecast origins)."""
    x = np.sort(samples, axis=1)
    n = x.shape[1]
    spread = (2 * np.arange(1, n + 1) - n - 1) @ x.T * 2 / n ** 2
    return np.mean(np.abs(x - y[:, None]), axis=1) - 0.5 * spread, np.mean(x <= y[:, None], axis=1)


def horizon_scores(fits: dict, r: np.ndarray, origins: np.ndarray, paths: int, seed: int,
                   chunk: int = 50) -> dict:
    """Simulate each model's GARCH-Lévy path from every origin; score the 5- and 21-day sums."""
    hmax = max(HORIZONS)
    origins = origins[origins + hmax <= len(r)]
    cum = np.concatenate([[0.0], np.cumsum(r)])
    realised = {h: cum[origins + h] - cum[origins] for h in HORIZONS}
    prepared = {}
    for name, (spec, t) in fits.items():
        mu, omega, alpha, beta, inn = unpack(spec, t)
        cdf_tab, x_tab = inn.table()
        prepared[name] = (mu, omega, alpha, beta, cdf_tab, x_tab, garch_sigma(r, mu, omega, alpha, beta))
    out = {name: {h: {"crps": [], "pit": []} for h in HORIZONS} for name in fits}
    rng = np.random.default_rng(seed)
    for lo in range(0, len(origins), chunk):
        o = origins[lo:lo + chunk]
        uni = rng.random((hmax, len(o), paths))  # common random numbers across models
        for name, (mu, omega, alpha, beta, cdf_tab, x_tab, s) in prepared.items():
            s2 = np.repeat(s[o, None] ** 2, paths, axis=1)
            total = np.zeros_like(s2)
            for step in range(hmax):
                e = np.sqrt(s2) * np.interp(uni[step], cdf_tab, x_tab)
                total += mu + e
                s2 = omega + alpha * e * e + beta * s2
                if step + 1 in HORIZONS:
                    c, p = crps_pit(total, realised[step + 1][lo:lo + chunk])
                    out[name][step + 1]["crps"].append(c)
                    out[name][step + 1]["pit"].append(p)
    for name in out:
        for h in HORIZONS:
            out[name][h] = {k: np.concatenate(v).tolist() for k, v in out[name][h].items()}
    return {"origins": origins.tolist(), "models": out}


# --- runs -----------------------------------------------------------------------------------

FAMILIES = ("garch", "iid")  # GARCH(1,1) sigma_t, or constant sigma (i.i.d. Lévy increments)


def baselines(family: str) -> list[Spec]:
    prefix, garch = ("GARCH", True) if family == "garch" else ("iid", False)
    return [Spec(f"{prefix}-Gaussian", "gauss", garch=garch), Spec(f"{prefix}-Student-t", "student", garch=garch),
            Spec(f"{prefix}-CGMY", "levy", garch=garch)]


def run(name: str, r: pd.Series, cutoff: str, end: str | None, paths: int, band: bool,
        family: str = "garch") -> dict:
    """Fit on returns before cutoff (choosing tau on its last years), score [cutoff, end)."""
    started = time.time()
    values = r.values
    n_fit = int((r.index < cutoff).sum())
    n_inner = int((r.index < pd.Timestamp(cutoff) - pd.DateOffset(years=VALID_YEARS)).sum())
    n_end = len(r) if end is None else int((r.index < end).sum())
    fit_r, inner_r = values[:n_fit], values[:n_inner]
    specs = baselines(family)
    cgmy, garch = specs[2], specs[2].garch

    # Choose tau: fit on the inner window, score the validation years.
    t_inner = {0.0: fit(cgmy, inner_r)}
    validation = {}
    for tau in (0.0, 1.0) if QUICK else TAUS:
        spec = Spec(f"tau={tau}", "levy", tau, garch)
        if tau > 0:
            t_inner[tau] = fit(spec, inner_r, np.concatenate([t_inner[0.0], np.zeros(2 * K)]))
        lp, _, _ = day_scores(spec, t_inner[tau], fit_r)
        validation[tau] = float(lp[n_inner:].mean())
        print(f"  {name} {family} tau={tau}: validation log score {validation[tau]:.4f}", flush=True)
    tau_best = max((tau for tau in validation if tau > 0), key=validation.get)

    fits = {}
    for spec in specs:
        t0 = t_inner[0.0] if spec.kind == "levy" else None
        fits[spec.name] = (spec, fit(spec, fit_r, t0))
        print(f"  {name} {spec.name} fitted ({time.time() - started:.0f}s)", flush=True)
    fourier = Spec(cgmy.name.replace("CGMY", "Fourier-CGMY"), "levy", tau_best, garch)
    t0 = np.concatenate([fits[cgmy.name][1], t_inner[tau_best][fourier.a0:]])
    fits[fourier.name] = (fourier, fit(fourier, fit_r, t0))
    print(f"  {name} {fourier.name} (tau={tau_best}) fitted ({time.time() - started:.0f}s)", flush=True)

    result = {"name": name, "family": family, "cutoff": cutoff, "end": end, "tau": tau_best, "validation": validation,
              "dates": [d.date().isoformat() for d in r.index[n_fit:n_end]], "models": {}}
    for model, (spec, t) in fits.items():
        lp, pit, _ = day_scores(spec, t, values[:n_end])
        result["models"][model] = {
            "params": describe(spec, t), "k": len(t), "train_ll": -objective(t, spec, fit_r),
            "lp": lp[n_fit:].tolist(), "pit": pit[n_fit:].tolist(),
            # only the Fourier-series (Lévy) densities can be clipped; Gaussian and t are exact
            "clipped": int((lp[n_fit:] <= np.log(FLOOR) + 1).sum()) if spec.kind == "levy" else 0}
    result["horizons"] = horizon_scores(fits, values, np.arange(n_fit, n_end), paths, seed=n_fit)
    if band:
        result["band"] = laplace_band(fourier, fits[fourier.name][1], fit_r)
    result["meta"] = {"paths": paths, "runtime_s": time.time() - started, "host": platform.node(),
                      "slurm_job": os.environ.get("SLURM_ARRAY_JOB_ID") or os.environ.get("SLURM_JOB_ID"),
                      "quick": QUICK, "finished": datetime.now(UTC).isoformat()}
    return result


def save(result: dict, stem: str) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{stem}.json"
    path.write_text(json.dumps(result, default=float), encoding="utf-8")
    print(f"wrote {path}")


# --- report ---------------------------------------------------------------------------------

def hac_se(d: np.ndarray, lag: int) -> float:
    """Newey-West standard error of the mean of d."""
    d = d - d.mean()
    n = len(d)
    v = d @ d / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return float(np.sqrt(v / n))


def coverage(pit: np.ndarray) -> list[float]:
    return [float(np.mean(pit < q) if q < 0.5 else np.mean(pit > q)) for q in TAILS]


def pct(values) -> str:
    return " / ".join(f"{100 * v:.2f}" for v in values)


def diff_cell(a: np.ndarray, b: np.ndarray, lag: int, scale: float = 1.0) -> str:
    d = (a - b) * scale
    return f"{d.mean():+.4f} ± {hac_se(d, lag):.4f}"


def fit_health() -> str:
    """One line saying whether any fit in runs/levy collapsed (a daily log density above DEGENERATE_LP)."""
    peak, bad = -np.inf, []
    for path in sorted(RUNS.glob("*.json")):
        run_ = json.loads(path.read_text(encoding="utf-8"))
        for m, v in run_["models"].items():
            top = max(v["lp"])
            peak = max(peak, top)
            if top > DEGENERATE_LP:
                bad.append(f"{path.stem}/{m}")
    if bad:
        return f"**Fit health: COLLAPSED FITS in {', '.join(bad)}; their numbers are not usable.**"
    return (f"Fit health: no collapsed fits in {len(list(RUNS.glob('*.json')))} runs (largest daily log density "
            f"{peak:.2f}, threshold {DEGENERATE_LP:g}).")


def write_report() -> None:
    fixed = json.loads((RUNS / "fixed.json").read_text(encoding="utf-8"))
    rolling = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNS.glob("rolling-[0-9]*.json"))]
    _, fetched = load_brent()
    names = list(fixed["models"])
    ref = "GARCH-Student-t"
    dates = pd.to_datetime(fixed["dates"])
    calm = ~((dates >= SPRING_2020[0]) & (dates <= SPRING_2020[1]))
    lp = {m: np.array(fixed["models"][m]["lp"]) for m in names}
    meta = fixed["meta"]
    where = f"Iridis job {meta['slurm_job']}" if meta.get("slurm_job") else f"host {meta['host']}"
    if meta.get("quick") or any(run_["meta"].get("quick") for run_ in rolling):
        where += " (SMOKE TEST: --quick fits, numbers are not results)"
    out = [
        "# Learned-Lévy GARCH model for Brent: results",
        "",
        f"_Generated by `experiments/levy_fourier.py report` on {datetime.now(UTC).date().isoformat()} "
        f"from runs on {where}. Data: Brent spot, FRED series DCOILBRENTEU (source EIA), fetched "
        f"{fetched}. Daily log returns, zero-return days kept. Fixed split: train before "
        f"{fixed['cutoff']}, test {fixed['dates'][0]} to {fixed['dates'][-1]} ({len(dates)} days). "
        f"Nothing here is synthetic._",
        "",
        "Model: r_t = mu + sigma_t X_t with GARCH(1,1) sigma_t. X_t is Gaussian, Student-t, CGMY, or "
        "CGMY whose Lévy density is multiplied by exp(Fourier series) on each side (independent "
        f"Gaussian priors a_k ~ N(0, (tau/k)^2), tau chosen on the last {VALID_YEARS} training years). "
        "All innovations have unit variance. Errors are Newey-West (lag 10 daily, lag h for h-day). "
        "Higher log score is better; lower CRPS is better.",
        "",
        fit_health(),
        "",
        "## 1. Fixed split, daily",
        "",
        f"Validation log score by tau (0 = plain CGMY): "
        + ", ".join(f"{float(k):g}: {v:.4f}" for k, v in fixed["validation"].items())
        + f". Chosen tau = {fixed['tau']:g}.",
        "",
        f"| Model | Params | Test log score | vs {ref} | vs {ref}, without Mar-May 2020 | Tails % (1 / 5 / 95 / 99) | Clipped |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in names:
        cov = coverage(np.array(fixed["models"][m]["pit"]))
        out.append(f"| {m} | {fixed['models'][m]['k']} | {lp[m].mean():.4f} | {diff_cell(lp[m], lp[ref], 10)} | "
                   f"{diff_cell(lp[m][calm], lp[ref][calm], 10)} | {pct(cov)} | {fixed['models'][m]['clipped'] if 'CGMY' in m else '-'} |")
    n = len(dates)
    out += [
        "",
        f"Binomial standard error of a tail percentage over {n} days: "
        f"{100 * np.sqrt(0.01 * 0.99 / n):.2f} at 1%, {100 * np.sqrt(0.05 * 0.95 / n):.2f} at 5%. "
        f"Fourier minus CGMY: {diff_cell(lp['GARCH-Fourier-CGMY'], lp['GARCH-CGMY'], 10)} "
        f"(without Mar-May 2020: {diff_cell(lp['GARCH-Fourier-CGMY'][calm], lp['GARCH-CGMY'][calm], 10)}).",
        "",
        "## 2. Fixed split, simulated 5- and 21-day forecasts",
        "",
        f"{meta['paths']} paths per origin, every test day an origin. CRPS in log-return units x 100.",
        "",
        f"| Model | " + " | ".join(f"{h}-day CRPS | vs {ref} | {h}-day tails %" for h in HORIZONS) + " |",
        "|---|" + "---|---|---|" * len(HORIZONS),
    ]
    hz = fixed["horizons"]["models"]
    for m in names:
        cells = []
        for h in HORIZONS:
            c, cr = np.array(hz[m][str(h)]["crps"]), np.array(hz[ref][str(h)]["crps"])
            cells.append(f"{100 * c.mean():.3f} | {diff_cell(c, cr, h, 100)} | {pct(coverage(np.array(hz[m][str(h)]['pit'])))}")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    if "band" in fixed:
        b = fixed["band"]
        out += [
            "",
            "## 3. Learned tail shape (Laplace 90% band for g, the log ratio to CGMY's Lévy density)",
            "",
            "| Jump size (sd) | " + " | ".join(f"{s:g}" for s in b["s"]) + " |",
            "|---|" + "---|" * len(b["s"]),
        ]
        for side in ("up", "down"):
            cells = [f"{mp:+.2f} [{lo:+.2f}, {hi:+.2f}]" for mp, lo, hi in zip(b[side]["map"], b[side]["lo"], b[side]["hi"])]
            out.append(f"| {side} | " + " | ".join(cells) + " |")
        out += ["", f"A band that excludes 0 means the data move the tail away from CGMY there. "
                    f"Smallest Hessian eigenvalue {b['min_hessian_eig']:.2g}."]
    if rolling:
        out += [
            "",
            "## 4. Rolling refits: train on all years before, score the calendar year",
            "",
            "| Year | Days | tau | Fourier - CGMY | CGMY - Student-t | Student-t - Gaussian | 21-day CRPS x100, Fourier - Student-t |",
            "|---|---|---|---|---|---|---|",
        ]
        pooled = {m: [] for m in names}
        pooled_c = {m: [] for m in names}
        wins = {m: 0 for m in names}
        for run_ in rolling:
            l = {m: np.array(run_["models"][m]["lp"]) for m in names}
            c = {m: np.array(run_["horizons"]["models"][m]["21"]["crps"]) for m in names}
            for m in names:
                pooled[m].append(l[m])
                pooled_c[m].append(c[m])
            wins[max(names, key=lambda m: l[m].mean())] += 1
            out.append(f"| {run_['dates'][0][:4]} | {len(run_['dates'])} | {run_['tau']:g} | "
                       f"{diff_cell(l['GARCH-Fourier-CGMY'], l['GARCH-CGMY'], 10)} | "
                       f"{diff_cell(l['GARCH-CGMY'], l[ref], 10)} | {diff_cell(l[ref], l['GARCH-Gaussian'], 10)} | "
                       f"{diff_cell(c['GARCH-Fourier-CGMY'], c[ref], 21, 100)} |")
        P = {m: np.concatenate(v) for m, v in pooled.items()}
        Pc = {m: np.concatenate(v) for m, v in pooled_c.items()}
        out += [
            f"| **pooled** | {len(P[ref])} | | {diff_cell(P['GARCH-Fourier-CGMY'], P['GARCH-CGMY'], 10)} | "
            f"{diff_cell(P['GARCH-CGMY'], P[ref], 10)} | {diff_cell(P[ref], P['GARCH-Gaussian'], 10)} | "
            f"{diff_cell(Pc['GARCH-Fourier-CGMY'], Pc[ref], 21, 100)} |",
            "",
            "Years each model had the best daily log score: " + ", ".join(f"{m} {w}" for m, w in wins.items()) + ".",
        ]
    if (RUNS / "fixed-iid.json").exists():
        out += iid_section(fixed, rolling)
    out.append("")
    NOTE.parent.mkdir(exist_ok=True)
    NOTE.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {NOTE}")


def iid_section(fixed_garch: dict, rolling_garch: list[dict]) -> list[str]:
    """Section 5: the same models with constant sigma, where the tails are not absorbed by GARCH."""
    fixed = json.loads((RUNS / "fixed-iid.json").read_text(encoding="utf-8"))
    rolling = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNS.glob("rolling-iid-*.json"))]
    names, ref = list(fixed["models"]), "iid-Student-t"
    dates = pd.to_datetime(fixed["dates"])
    calm = ~((dates >= SPRING_2020[0]) & (dates <= SPRING_2020[1]))
    lp = {m: np.array(fixed["models"][m]["lp"]) for m in names}
    g_cgmy = np.array(fixed_garch["models"]["GARCH-CGMY"]["lp"])
    fourier, cgmy = "iid-Fourier-CGMY", "iid-CGMY"
    out = [
        "",
        "## 5. Without the volatility state: i.i.d. Lévy increments (constant sigma)",
        "",
        "The same four innovations with sigma held constant, so the tails have to carry the volatility "
        "clustering too. This is where a learned Lévy density has the most to work with.",
        "",
        "Validation log score by tau (0 = plain CGMY): "
        + ", ".join(f"{float(k):g}: {v:.4f}" for k, v in fixed["validation"].items())
        + f". Chosen tau = {fixed['tau']:g}.",
        "",
        f"| Model | Params | Test log score | vs {ref} | vs {ref}, without Mar-May 2020 | Tails % (1 / 5 / 95 / 99) | Clipped |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in names:
        cov = coverage(np.array(fixed["models"][m]["pit"]))
        out.append(f"| {m} | {fixed['models'][m]['k']} | {lp[m].mean():.4f} | {diff_cell(lp[m], lp[ref], 10)} | "
                   f"{diff_cell(lp[m][calm], lp[ref][calm], 10)} | {pct(cov)} | {fixed['models'][m]['clipped'] if 'CGMY' in m else '-'} |")
    hz = fixed["horizons"]["models"]
    c21 = {m: np.array(hz[m]["21"]["crps"]) for m in names}
    out += [
        "",
        f"**Learned tail, i.i.d.:** Fourier minus CGMY {diff_cell(lp[fourier], lp[cgmy], 10)} nats/day "
        f"(without Mar-May 2020: {diff_cell(lp[fourier][calm], lp[cgmy][calm], 10)}); 21-day CRPS x100 "
        f"{diff_cell(c21[fourier], c21[cgmy], 21, 100)} (negative is better). "
        f"**Volatility state:** GARCH-CGMY minus iid-CGMY {diff_cell(g_cgmy, lp[cgmy], 10)} nats/day.",
    ]
    if "band" in fixed:
        b = fixed["band"]
        out += [
            "",
            "Learned tail shape, i.i.d. (Laplace 90% band for g, the log ratio to CGMY's Lévy density):",
            "",
            "| Jump size (sd) | " + " | ".join(f"{s:g}" for s in b["s"]) + " |",
            "|---|" + "---|" * len(b["s"]),
        ]
        for side in ("up", "down"):
            cells = [f"{mp:+.2f} [{lo:+.2f}, {hi:+.2f}]" for mp, lo, hi in zip(b[side]["map"], b[side]["lo"], b[side]["hi"])]
            out.append(f"| {side} | " + " | ".join(cells) + " |")
    if rolling:
        garch_by_year = {run_["dates"][0][:4]: run_ for run_ in rolling_garch}
        out += [
            "",
            "Rolling refits, i.i.d.:",
            "",
            "| Year | tau | Fourier - CGMY (iid) | GARCH-CGMY - iid-CGMY |",
            "|---|---|---|---|",
        ]
        pf, pg = [], []
        for run_ in rolling:
            year = run_["dates"][0][:4]
            l = {m: np.array(run_["models"][m]["lp"]) for m in names}
            d = l[fourier] - l[cgmy]
            pf.append(d)
            vol = "-"
            if year in garch_by_year and len(garch_by_year[year]["dates"]) == len(run_["dates"]):
                g = np.array(garch_by_year[year]["models"]["GARCH-CGMY"]["lp"]) - l[cgmy]
                pg.append(g)
                vol = f"{g.mean():+.4f} ± {hac_se(g, 10):.4f}"
            out.append(f"| {year} | {run_['tau']:g} | {d.mean():+.4f} ± {hac_se(d, 10):.4f} | {vol} |")
        d = np.concatenate(pf)
        g = np.concatenate(pg) if pg else np.array([np.nan])
        out.append(f"| **pooled** | | {d.mean():+.4f} ± {hac_se(d, 10):.4f} | "
                   f"{g.mean():+.4f} ± {hac_se(g, 10) if pg else float('nan'):.4f} |")
    return out


def self_check() -> None:
    """Numerical checks of the pieces against slow direct computations; prints the errors."""
    from scipy import integrate

    rng = np.random.default_rng(1)
    coef = rng.normal(size=TERMS) / np.arange(1, TERMS + 1)
    direct = np.cos(np.outer(XG[::997] + HALF, U)) @ np.concatenate([[coef[0] / 2], coef[1:]])
    via_dct = (fft.dct(np.concatenate([[coef[0] / 2], coef[1:]]), type=1)
               + coef[0] / 2 + (-1.0) ** np.arange(TERMS) * coef[-1]) / 2
    print(f"DCT-I vs direct cosine sum: max error {np.abs(direct - via_dct[::997]).max():.1e}")

    cases = [("CGMY", 0.8, 1.1, 1.3, np.zeros(K), np.zeros(K)),
             ("Fourier", 0.6, 1.4, 1.2, np.array([0.5, -0.3, 0.2, 0, 0, 0.1]),
              np.array([-0.4, 0.6, 0, 0.2, -0.1, 0]))]
    for name, G, M, Y, a_up, a_down in cases:
        psi, var = levy_psi(G, M, Y, a_up, a_down)

        def nu(x):
            s = abs(x)
            g = (a_up if x > 0 else a_down) @ fourier_basis([s])[0] if s <= L else 0.0
            return s ** (-1 - Y) * np.exp(-(M if x > 0 else G) * s + g)

        def lk(u):  # Lévy-Khintchine integral, done directly
            parts = []
            for f in (lambda x: (np.cos(u * x) - 1) * nu(x), lambda x: (np.sin(u * x) - u * x) * nu(x)):
                parts.append(sum(integrate.quad(f, lo, hi, limit=400)[0]
                                 for lo, hi in ((-80, -1), (-1, 0), (0, 1), (1, 80))))
            return parts[0] + 1j * parts[1]

        var_direct = sum(integrate.quad(lambda x: x * x * nu(x), lo, hi, limit=400)[0]
                         for lo, hi in ((-80, 0), (0, 80)))
        err = max(abs(psi[k] - lk(U[k])) / max(1, abs(lk(U[k]))) for k in (1, 7, 40, 150))
        print(f"{name}: exponent vs direct Lévy-Khintchine, max rel error {err:.1e}; "
              f"variance {var:.6f} vs {var_direct:.6f}")
        inn = Levy(G, M, Y, a_up, a_down)
        f = np.exp(inn.logf)
        dx = XG[1] - XG[0]
        mean = (XG * f).sum() * dx
        print(f"  density: mass {f.sum() * dx:.6f}, mean {mean:+.2e}, variance {(XG ** 2 * f).sum() * dx:.6f}, "
              f"min {f.min():.1e}")
        x = np.interp(rng.random(400_000), inn.cdf_grid, XG)
        print(f"  sampler: mean {x.mean():+.4f}, variance {x.var():.4f}, "
              f"KS vs grid CDF {stats.kstest(x[:20000], inn.cdf).statistic:.4f}")
        far = inn.logpdf(np.array([HALF - 1, HALF + 5, -HALF - 5, 1e6]))
        assert far[1] < far[0] - 200 and far[2] < far[0] - 200 and far[3] < -1e7, far
        print(f"  off-grid log density falls: {far[0]:.1f} at {HALF - 1:g} sd, {far[1]:.1f} at {HALF + 5:g} sd")

    # A collapsing fit (sigma -> 0, every day off the grid) must score far worse than a sane one.
    price, _ = load_brent()
    rr = np.log(price).diff().dropna().values[:4500]
    cgmy = Spec("c", "levy")
    sane = objective(start(cgmy, rr), cgmy, rr)
    collapsed = start(cgmy, rr)
    collapsed[0], collapsed[1] = 7.0, -300.0  # huge mu, omega -> 0: z far off the grid
    print(f"collapsed-fit objective {objective(collapsed, cgmy, rr):.3g} vs sane start {sane:.3g}")
    assert objective(collapsed, cgmy, rr) > sane

    r = rng.standard_t(4, 300) * 0.02
    s = garch_sigma(r, 0.001, 2e-5, 0.08, 0.9)
    loop = [np.sqrt(2e-5 / 0.02)]
    for i in range(1, len(r)):
        loop.append(np.sqrt(2e-5 + 0.08 * (r[i - 1] - 0.001) ** 2 + 0.9 * loop[-1] ** 2))
    print(f"GARCH filter vs loop: max error {np.abs(s - np.array(loop)).max():.1e}")

    samples, y = rng.normal(size=(3, 300)), np.array([0.1, -1.0, 2.0])
    brute = [np.mean(np.abs(sm - yy)) - 0.5 * np.mean(np.abs(sm[:, None] - sm[None, :])) for sm, yy in zip(samples, y)]
    print(f"CRPS vs brute force: max error {np.abs(crps_pit(samples, y)[0] - brute).max():.1e}")

    price, _ = load_brent()
    rr = np.log(price).diff().dropna().values[:4500]
    spec = Spec("t", "levy", 1.0)
    t0 = np.concatenate([start(Spec("c", "levy"), rr), np.full(2 * K, 0.1)])
    began = time.time()
    for _ in range(10):
        objective(t0, spec, rr)
    print(f"objective on 4500 days with the Fourier part: {(time.time() - began) * 100:.1f} ms per call")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="numerical self-checks")
    f = sub.add_parser("fit", help="fixed split: train before SPLIT, test after")
    rl = sub.add_parser("rolling", help="train on years before YEAR, score YEAR")
    rl.add_argument("year", type=int)
    for q in (f, rl):
        q.add_argument("--paths", type=int, default=2000)
        q.add_argument("--quick", action="store_true", help="smoke test: tiny fits, two taus")
        q.add_argument("--family", choices=FAMILIES, default="garch",
                       help="garch: GARCH(1,1) sigma_t; iid: constant sigma")
    sub.add_parser("report")
    args = p.parse_args()
    global QUICK
    QUICK = getattr(args, "quick", False)
    if args.cmd == "check":
        self_check()
        return
    if args.cmd == "report":
        write_report()
        return
    price, _ = load_brent()
    r = np.log(price).diff().dropna()
    tag = "" if args.family == "garch" else f"-{args.family}"
    if args.cmd == "fit":
        save(run("fixed", r, SPLIT, None, args.paths, band=True, family=args.family), f"fixed{tag}")
    else:
        save(run(str(args.year), r, f"{args.year}-01-01", f"{args.year + 1}-01-01", args.paths, band=False,
                 family=args.family), f"rolling{tag}-{args.year}")


if __name__ == "__main__":
    main()
