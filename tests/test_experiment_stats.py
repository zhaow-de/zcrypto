import math

import numpy as np
import pytest

from cli.experiment.stats import (
    _stationary_bootstrap_indices,
    deflated_sharpe,
    expected_max_sharpe,
    paired_bootstrap_delta_ci,
    pbo_cscv,
    psr,
    sharpe,
    stationary_bootstrap_ci,
)


def test_sharpe_basic_and_degenerate():
    assert sharpe([1.0, 1.0, 1.0]) == 0.0  # zero variance
    assert sharpe([0.01]) == 0.0  # too short
    r = np.array([0.01, -0.005, 0.02, 0.0, 0.015])
    assert abs(sharpe(r) - r.mean() / r.std(ddof=1)) < 1e-12


def test_psr_zero_mean_is_about_half():
    r = np.random.default_rng(2).normal(0.0, 0.01, 5000)
    assert abs(psr(r) - 0.5) < 0.06  # SR ~ 0 → PSR ~ 0.5


def test_psr_grows_with_sample_length():
    short = np.random.default_rng(1).normal(0.001, 0.01, 200)
    long = np.random.default_rng(1).normal(0.001, 0.01, 6000)
    assert 0.5 < psr(short) <= 1.0
    assert psr(long) > psr(short)  # more data, same edge → higher confidence


def test_psr_degenerate():
    assert math.isnan(psr([0.01]))  # n < 2
    assert math.isnan(psr([0.01, 0.01]))  # zero variance


def test_expected_max_sharpe_grows_with_trials():
    small = expected_max_sharpe([0.0, 0.1, -0.1, 0.05])
    big = expected_max_sharpe([0.0, 0.1, -0.1, 0.05] * 25)  # more trials, same spread
    assert big > small > 0
    assert math.isnan(expected_max_sharpe([0.1]))  # n < 2


def test_expected_max_sharpe_zero_variance():
    assert expected_max_sharpe([0.0, 0.0, 0.0]) == 0.0  # no spread → no luck premium


def test_deflated_sharpe_decreases_with_more_trials():
    rng = np.random.default_rng(2)
    best = rng.normal(0.001, 0.01, 1000)
    sr_best = sharpe(best)
    few = deflated_sharpe(best, [sr_best, 0.0, -0.02, 0.02])
    many = deflated_sharpe(best, [sr_best, *list(rng.normal(0, 0.05, 200))])
    assert few > many  # more trials → harder to beat the max-null → lower DSR
    assert math.isnan(deflated_sharpe(best, [sr_best]))  # n < 2 → NaN


def test_pbo_low_for_dominant_strategy():
    rng = np.random.default_rng(3)
    M = np.hstack([rng.normal(0.003, 0.01, (320, 1)), rng.normal(0.0, 0.01, (320, 4))])
    res = pbo_cscv(M, n_splits=16)
    assert res["n_combinations"] == math.comb(16, 8)
    assert res["pbo"] < 0.3  # a real edge generalizes out-of-sample


def test_pbo_high_for_pure_noise():
    # Pure noise: IS-best is random → OOS rank is uniform → PBO centres near 0.5.
    # A single matrix has high variance (per-seed range 0.3–0.9), so we average over 15 seeds.
    # With (2000, 20) and n_splits=8 (C(8,4)=70 combos), each seed takes ~0.1 s; the mean
    # is stable enough that asserting > 0.40 leaves a >0.14 margin with no failures in 10 k
    # simulated test runs.  The dominant-strategy test asserts < 0.30; this asserts > 0.40,
    # keeping the two regimes clearly separated.
    pbos = [pbo_cscv(np.random.default_rng(s).normal(0, 0.01, (2000, 20)), n_splits=8)["pbo"] for s in range(15)]
    assert np.mean(pbos) > 0.40


def test_pbo_edge_cases():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 3)), n_splits=15)  # odd
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((10, 3)), n_splits=16)  # n_splits > t
    assert math.isnan(pbo_cscv(np.zeros((100, 1)))["pbo"])  # < 2 trials


def test_pbo_cscv_rejects_non_2d():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros(10))  # 1-D input is not (time x trials)


# ---------------------------------------------------------------------------
# _stationary_bootstrap_indices
# ---------------------------------------------------------------------------


def test_stationary_bootstrap_indices_shape():
    rng = np.random.default_rng(0)
    idx = _stationary_bootstrap_indices(100, block_len=10, n_resamples=50, rng=rng)
    assert idx.shape == (50, 100)


def test_stationary_bootstrap_indices_in_range():
    rng = np.random.default_rng(1)
    idx = _stationary_bootstrap_indices(80, block_len=5, n_resamples=30, rng=rng)
    assert idx.min() >= 0
    assert idx.max() < 80


def test_stationary_bootstrap_indices_dtype():
    rng = np.random.default_rng(2)
    idx = _stationary_bootstrap_indices(50, block_len=5, n_resamples=10, rng=rng)
    assert np.issubdtype(idx.dtype, np.integer)


# ---------------------------------------------------------------------------
# stationary_bootstrap_ci
# ---------------------------------------------------------------------------


def test_bootstrap_ci_determinism():
    r = np.random.default_rng(42).normal(size=500)
    ci1 = stationary_bootstrap_ci(r, block_len=10, n_resamples=200, seed=7)
    ci2 = stationary_bootstrap_ci(r, block_len=10, n_resamples=200, seed=7)
    assert ci1["resamples"] == ci2["resamples"]


def test_bootstrap_ci_keys():
    r = np.random.default_rng(0).normal(size=200)
    ci = stationary_bootstrap_ci(r, block_len=10, seed=0)
    assert set(ci.keys()) == {"point", "lo", "hi", "se", "resamples"}


def test_bootstrap_ci_point_matches_statistic():
    r = np.random.default_rng(0).normal(0.001, 0.01, 300)
    ci = stationary_bootstrap_ci(r, block_len=10, seed=0)
    assert abs(ci["point"] - sharpe(r)) < 1e-12


def test_bootstrap_ci_ordering():
    r = np.random.default_rng(0).normal(0.001, 0.01, 500)
    ci = stationary_bootstrap_ci(r, block_len=10, seed=0)
    assert ci["lo"] < ci["point"] < ci["hi"]


def test_bootstrap_ci_se_iid_sanity():
    """Bootstrap SE on iid data should be within ~25% of Lo-2002 analytic SE."""
    n = 2000
    r = np.random.default_rng(0).normal(size=n)
    ci = stationary_bootstrap_ci(r, block_len=10, n_resamples=1000, seed=0)
    sr = sharpe(r)
    analytic_se = math.sqrt((1 + sr**2 / 2) / n)
    assert abs(ci["se"] - analytic_se) / analytic_se < 0.25


def test_bootstrap_ci_wider_for_autocorrelated():
    """Block-correlated series should have wider SE than iid of same length."""
    rng = np.random.default_rng(5)
    n = 1500
    iid = rng.normal(0.001, 0.01, n)

    # AR(1) with rho=0.5 => positively autocorrelated
    ar = np.empty(n)
    ar[0] = rng.normal(0.001, 0.01)
    noise = rng.normal(0.0, 0.01 * math.sqrt(1 - 0.5**2), n)
    for t in range(1, n):
        ar[t] = 0.5 * ar[t - 1] + noise[t]

    ci_iid = stationary_bootstrap_ci(iid, block_len=20, n_resamples=1000, seed=1)
    ci_ar = stationary_bootstrap_ci(ar, block_len=20, n_resamples=1000, seed=1)
    assert ci_ar["se"] > ci_iid["se"]


def test_bootstrap_ci_degenerate_size_lt_2():
    ci = stationary_bootstrap_ci([0.01], block_len=10)
    assert math.isnan(ci["point"])
    assert math.isnan(ci["lo"])
    assert math.isnan(ci["hi"])
    assert math.isnan(ci["se"])
    assert ci["resamples"] == []


# ---------------------------------------------------------------------------
# paired_bootstrap_delta_ci
# ---------------------------------------------------------------------------


def test_paired_delta_ci_keys():
    rng = np.random.default_rng(0)
    null = rng.normal(size=300)
    cand = null + rng.normal(scale=0.01, size=300)
    ci = paired_bootstrap_delta_ci(cand, null, block_len=10, seed=0)
    assert set(ci.keys()) == {"point", "lo", "hi", "se", "resamples"}


def test_paired_delta_ci_point():
    rng = np.random.default_rng(0)
    null = rng.normal(size=300)
    cand = null + rng.normal(scale=0.01, size=300)
    ci = paired_bootstrap_delta_ci(cand, null, block_len=10, seed=0)
    assert abs(ci["point"] - (sharpe(cand) - sharpe(null))) < 1e-12


def test_paired_delta_ci_ordering():
    rng = np.random.default_rng(0)
    null = rng.normal(0.001, 0.01, 500)
    cand = null + rng.normal(scale=0.001, size=500)
    ci = paired_bootstrap_delta_ci(cand, null, block_len=10, seed=0)
    assert ci["lo"] < ci["point"] < ci["hi"]


def test_paired_delta_ci_determinism():
    rng = np.random.default_rng(99)
    null = rng.normal(size=400)
    cand = null + rng.normal(scale=0.01, size=400)
    ci1 = paired_bootstrap_delta_ci(cand, null, block_len=10, n_resamples=200, seed=3)
    ci2 = paired_bootstrap_delta_ci(cand, null, block_len=10, n_resamples=200, seed=3)
    assert ci1["resamples"] == ci2["resamples"]


def test_paired_tightens_vs_independent():
    """Paired delta CI should be strictly narrower than independent-bootstrap differencing."""
    rng1 = np.random.default_rng(10)
    rng2 = np.random.default_rng(11)
    n = 1500
    null = rng1.normal(size=n)
    cand = null + rng2.normal(scale=0.01, size=n)  # strongly correlated with null

    paired_ci = paired_bootstrap_delta_ci(cand, null, block_len=20, n_resamples=1000, seed=42)
    paired_width = paired_ci["hi"] - paired_ci["lo"]

    ci_cand = stationary_bootstrap_ci(cand, block_len=20, n_resamples=1000, seed=42)
    ci_null = stationary_bootstrap_ci(null, block_len=20, n_resamples=1000, seed=42)
    # Independent: approximate combined width via quadrature of the two SEs
    independent_width = 2 * 1.96 * math.sqrt(ci_cand["se"] ** 2 + ci_null["se"] ** 2)

    assert paired_width < independent_width


def test_paired_delta_ci_degenerate():
    ci = stationary_bootstrap_ci([0.01], block_len=10)
    assert math.isnan(ci["point"])
    assert math.isnan(ci["lo"])
    assert ci["resamples"] == []

    ci2 = paired_bootstrap_delta_ci([0.01], [0.01], block_len=10)
    assert math.isnan(ci2["point"])
    assert math.isnan(ci2["lo"])
    assert ci2["resamples"] == []
