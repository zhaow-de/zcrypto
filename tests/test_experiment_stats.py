import math

import numpy as np
import pytest

from cli.experiment.stats import deflated_sharpe, expected_max_sharpe, pbo_cscv, psr, sharpe


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
