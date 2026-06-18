"""Backtest-validation statistics: probabilistic / deflated Sharpe and PBO.

Pure functions on plain sequences — no qlib. All Sharpe inputs are per-period
(non-annualized). References: Bailey & López de Prado (2012, PSR; 2014, DSR);
Bailey, Borwein, López de Prado, Zhu (2015, PBO / CSCV).
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
from scipy.stats import norm

_EULER_GAMMA = 0.5772156649015329


def sharpe(returns) -> float:
    """Per-period (non-annualized) Sharpe of a return series; 0.0 if degenerate."""
    r = np.asarray(returns, dtype="float64")
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float(r.mean() / sd)


def psr(returns, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true per-period SR > sr_benchmark).

    Corrects the observed Sharpe for sample length and the return distribution's
    skewness and (non-excess) kurtosis. Returns a probability in [0, 1], or NaN
    for a degenerate series.
    """
    r = np.asarray(returns, dtype="float64")
    n = r.size
    if n < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return float("nan")
    sr = float(r.mean() / sd)
    m = r - r.mean()
    s2 = float((m**2).mean())
    if s2 <= 0:
        return float("nan")
    g3 = float((m**3).mean() / s2**1.5)  # skewness
    g4 = float((m**4).mean() / s2**2)  # non-excess kurtosis (normal == 3)
    denom = math.sqrt(max(1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr**2, 1e-12))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def expected_max_sharpe(sr_trials) -> float:
    """Expected maximum per-period Sharpe under the null across N >= 2 trials."""
    s = np.asarray(sr_trials, dtype="float64")
    n = s.size
    if n < 2:
        return float("nan")
    var = float(s.var(ddof=1))
    if not np.isfinite(var) or var <= 0:
        return 0.0
    sigma = math.sqrt(var)
    z1 = float(norm.ppf(1.0 - 1.0 / n))
    z2 = float(norm.ppf(1.0 - 1.0 / (n * math.e)))
    return float(sigma * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))


def deflated_sharpe(returns_best, sr_trials) -> float:
    """Deflated Sharpe Ratio: PSR of the best trial against the expected-max-Sharpe null.

    `sr_trials`: per-period Sharpe of every trial (including the best). Returns
    P(the best trial's true SR exceeds what N random trials would yield by luck),
    or NaN for fewer than 2 trials.
    """
    s = np.asarray(sr_trials, dtype="float64")
    if s.size < 2:
        return float("nan")
    return psr(returns_best, sr_benchmark=expected_max_sharpe(s))


def pbo_cscv(returns_matrix, n_splits: int = 16) -> dict:
    """Probability of Backtest Overfitting via Combinatorially-Symmetric CV.

    `returns_matrix`: 2-D (rows = aligned time observations, cols = trials).
    Returns ``{"pbo": float, "logits": list[float], "n_combinations": int}``.
    PBO is the fraction of in-sample/out-of-sample splits where the IS-best trial
    lands OOS below the median. NaN / empty for fewer than 2 trials.
    """
    matrix = np.asarray(returns_matrix, dtype="float64")
    if matrix.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (time x trials)")
    t, n = matrix.shape
    if n < 2:
        return {"pbo": float("nan"), "logits": [], "n_combinations": 0}
    if n_splits % 2 != 0:
        raise ValueError(f"n_splits must be even, got {n_splits}")
    if n_splits > t:
        raise ValueError(f"n_splits={n_splits} exceeds the number of observations t={t}")
    groups = [g for g in np.array_split(np.arange(t), n_splits) if g.size]
    s = len(groups)
    logits: list[float] = []
    for is_combo in combinations(range(s), s // 2):
        is_set = set(is_combo)
        is_rows = np.concatenate([groups[i] for i in is_combo])
        oos_rows = np.concatenate([groups[i] for i in range(s) if i not in is_set])
        is_sr = np.array([sharpe(matrix[is_rows, j]) for j in range(n)])
        oos_sr = np.array([sharpe(matrix[oos_rows, j]) for j in range(n)])
        best = int(np.argmax(is_sr))
        rank = int((oos_sr <= oos_sr[best]).sum())  # 1..n  (n == OOS-best)
        omega = min(max(rank / (n + 1), 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))
    pbo = float(np.mean([1.0 if x <= 0 else 0.0 for x in logits])) if logits else float("nan")
    return {"pbo": pbo, "logits": logits, "n_combinations": len(logits)}
