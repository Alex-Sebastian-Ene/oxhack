"""Correlated shocks across the knock-on series, and scores for joint forecasts.

Every member of experiments/macro_chain.py draws each series' monthly surprise independently, so
the series share the oil path but nothing else: each series' band is right on its own, but joint
answers (inflation and rates both up, a household bill that adds several series) come out too
narrow. Here:
- fit:        a t-copula per fold, from training months only. Each series' one-step residual of
              its own momentum and oil lags (the regression of macro_bayes.point_post), as rank
              normal scores; their correlation, shrunk towards the identity; the copula's tail index
              by maximum likelihood over a grid, on months where every series is observed
- CopulaRNG:  wraps a numpy Generator so that standard_t draws over the K target series are
              correlated through the copula. Each draw keeps exactly its own Student-t marginal, so a
              member's per-series forecasts are unchanged in distribution; only their dependence changes.
              It slots into macro_bayes.simulate and macro_global.simulate unchanged
- energy_score, variogram_score: proper scores for a joint forecast of several series
"""

from __future__ import annotations

import numpy as np
from scipy import stats

import macro_bayes as mb

SHRINK = 0.2  # weight of the identity in the correlation (22 series from 70-280 months)
NU_GRID = (3.0, 5.0, 8.0, 15.0, 30.0, 100.0)
NU_DEFAULT = 8.0  # when too few months have every series observed
MIN_COMPLETE = 24
MIN_PAIR = 12  # months two series must share for their correlation to be estimated


def residuals(data: dict, st: mb.Stats, last: int, info: dict) -> np.ndarray:
    """Standardised one-step residuals [months 13..last, K]: per series, least squares of the
    standardised monthly change on a constant, its last change and its oil lags (0..12, or 0..2
    for fuel and freight). NaN where the series or its last change is missing."""
    d = mb.design(data, st, last)
    X = d["Xp"] + d["Xn"]
    out = np.full(d["y"].shape, np.nan)
    for k in range(d["y"].shape[1]):
        ok = np.isfinite(d["y"][:, k]) & np.isfinite(d["yprev"][:, k])
        A = np.column_stack([np.ones(ok.sum()), d["yprev"][ok, k], X[ok, :info["lags"][k] + 1]])
        w, *_ = np.linalg.lstsq(A, d["y"][ok, k], rcond=None)
        r = d["y"][ok, k] - A @ w
        out[ok, k] = r / r.std()
    return out


def normal_scores(r: np.ndarray) -> np.ndarray:
    """Per column, ranks of the observed values -> standard normal scores (NaN stays NaN)."""
    z = np.full(r.shape, np.nan)
    for k in range(r.shape[1]):
        ok = np.isfinite(r[:, k])
        z[ok, k] = stats.norm.ppf(stats.rankdata(r[ok, k]) / (ok.sum() + 1))
    return z


def correlation(z: np.ndarray, shrink: float = SHRINK) -> np.ndarray:
    """Pairwise-complete correlation of the columns, shrunk towards the identity and made a valid
    (positive definite, unit diagonal) correlation matrix."""
    K = z.shape[1]
    R = np.eye(K)
    for i in range(K):
        for j in range(i + 1, K):
            ok = np.isfinite(z[:, i]) & np.isfinite(z[:, j])
            if ok.sum() >= MIN_PAIR:
                R[i, j] = R[j, i] = np.corrcoef(z[ok, i], z[ok, j])[0, 1]
    R = (1 - shrink) * R + shrink * np.eye(K)
    w, V = np.linalg.eigh(R)
    R = (V * np.maximum(w, 1e-6)) @ V.T
    d = np.sqrt(np.diag(R))
    return R / np.outer(d, d)


def t_copula_loglik(u: np.ndarray, R: np.ndarray, nu: float) -> float:
    """Log-likelihood of pseudo-observations u [n, K] under a t-copula (R, nu)."""
    x = stats.t.ppf(np.clip(u, 1e-10, 1 - 1e-10), nu)
    joint = stats.multivariate_t(loc=np.zeros(len(R)), shape=R, df=nu).logpdf(x)
    return float(np.sum(joint - stats.t.logpdf(x, nu).sum(1)))


def fit(data: dict, st: mb.Stats, last: int, info: dict) -> dict:
    """The fold's t-copula from its training months: correlation R, its Cholesky factor and tail index."""
    z = normal_scores(residuals(data, st, last, info))
    R = correlation(z)
    full = np.isfinite(z).all(1)
    if full.sum() >= MIN_COMPLETE:
        u = stats.norm.cdf(z[full])
        ll = [t_copula_loglik(u, R, nu) for nu in NU_GRID]
        nu = NU_GRID[int(np.argmax(ll))]
    else:
        nu = NU_DEFAULT
    off = R[np.triu_indices(len(R), 1)]
    return {"R": R, "L": np.linalg.cholesky(R), "nu": float(nu), "complete_months": int(full.sum()),
            "months": int(np.isfinite(z).any(1).sum()), "mean_abs_corr": float(np.abs(off).mean()),
            "max_corr": float(off.max())}


class CopulaRNG:
    """A numpy Generator whose standard_t draws are correlated across the last axis when it has the
    copula's K series, through the t-copula (R, nu). Each element keeps its own Student-t marginal
    with the df asked for. Draws over any other last axis, and every other method, pass through."""

    def __init__(self, rng: np.random.Generator, cop: dict) -> None:
        self.rng, self.L, self.nu, self.K = rng, cop["L"], cop["nu"], len(cop["L"])

    def standard_t(self, df, size=None):
        df = np.asarray(df, float)
        shape = df.shape if size is None else np.broadcast_shapes(df.shape, tuple(np.atleast_1d(size)))
        if shape[-1] != self.K:
            return self.rng.standard_t(df, size=size)
        z = self.rng.standard_normal(shape) @ self.L.T  # correlated normals across the series
        w = self.rng.chisquare(self.nu, size=shape[:-1] + (1,)) / self.nu  # one mixing draw per vector
        u = np.clip(stats.t.cdf(z / np.sqrt(w), self.nu), 1e-12, 1 - 1e-12)
        return stats.t.ppf(u, np.broadcast_to(df, shape))

    def __getattr__(self, name):
        return getattr(self.rng, name)


# --- joint scores ----------------------------------------------------------------------------

def energy_score(S: np.ndarray, y: np.ndarray, shifts: tuple[int, ...] = (1, 7, 53, 131)) -> float:
    """Energy score of samples S [N, D] at y [D]: E||X - y|| - E||X - X'|| / 2, the second term from
    pairing every sample with the one `shift` places on (no sample paired with itself). Lower is better."""
    t1 = np.linalg.norm(S - y, axis=1).mean()
    t2 = np.mean([np.linalg.norm(S - np.roll(S, s % len(S) or 1, 0), axis=1).mean() for s in shifts])
    return float(t1 - 0.5 * t2)


def variogram_score(S: np.ndarray, y: np.ndarray, p: float = 0.5) -> float:
    """Variogram score of order p (Scheuerer and Hamill 2015), equal weights: how well the samples get
    the size of the differences between every pair of series. Lower is better."""
    i, j = np.triu_indices(len(y), 1)
    vy = np.abs(y[i] - y[j]) ** p
    vs = (np.abs(S[:, i] - S[:, j]) ** p).mean(0)
    return float(np.sum((vy - vs) ** 2))


def joint_scores(S: np.ndarray, y: np.ndarray, scale: np.ndarray, H: np.ndarray, horizons) -> tuple[np.ndarray, np.ndarray]:
    """Energy and variogram scores [origins, horizons] of the joint forecast of every series at each
    horizon. S: [N, origins, outputs]; outputs are put on one scale by dividing by `scale` (each
    output's climatology CRPS); series without an outcome at an origin are left out there."""
    O = y.shape[0]
    es, vs = np.full((O, len(horizons)), np.nan), np.full((O, len(horizons)), np.nan)
    for hi, h in enumerate(horizons):
        c = np.where(H == h)[0]
        for o in range(O):
            ok = c[np.isfinite(y[o, c])]
            if len(ok) >= 2:
                Ss, ys = S[:, o, ok] / scale[ok], y[o, ok] / scale[ok]
                es[o, hi], vs[o, hi] = energy_score(Ss, ys), variogram_score(Ss, ys)
    return es, vs
