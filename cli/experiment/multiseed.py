"""Pure multi-seed metric aggregation and separation utilities.

No qlib import — numpy and stdlib only. Task 3 will add qlib-dependent functions
with deferred in-function imports.
"""

import math
import statistics


def summarize_seed_metrics(per_seed: list[dict]) -> dict:
    """Aggregate per-seed metric dicts into per-metric distribution stats.

    Args:
        per_seed: list of dicts with keys ``ending_value``, ``sharpe``, ``psr``, ``max_drawdown``.

    Returns:
        ``{metric: {"mean": float, "std": float, "min": float, "max": float, "n": int}}``
        Std uses sample std (ddof=1) for n > 1, 0.0 for n == 1.
    """
    if not per_seed:
        return {}
    metrics = list(per_seed[0].keys())
    result = {}
    for m in metrics:
        vals = [d[m] for d in per_seed]
        n = len(vals)
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if n > 1 else 0.0
        result[m] = {"mean": mean, "std": std, "min": min(vals), "max": max(vals), "n": n}
    return result


def separation(a: dict, b: dict, metric: str = "sharpe") -> dict:
    """Measure whether recipe *a*'s distribution is separated from *b*'s beyond seed noise.

    Args:
        a: summary dict from :func:`summarize_seed_metrics` for recipe a.
        b: summary dict from :func:`summarize_seed_metrics` for recipe b.
        metric: the metric key to compare (default ``"sharpe"``).

    Returns:
        ``{"mean_gap": float, "pooled_std": float, "z": float}``
        where ``z = mean_gap / pooled_std`` (positive → a above b).
        Divide-by-zero guard: pooled_std == 0 and mean_gap != 0 → z = inf;
        pooled_std == 0 and mean_gap == 0 → z = 0.0.
    """
    std_a = a[metric]["std"]
    std_b = b[metric]["std"]
    mean_gap = a[metric]["mean"] - b[metric]["mean"]
    pooled_std = math.sqrt((std_a**2 + std_b**2) / 2)
    if pooled_std == 0.0:
        z = float("inf") if mean_gap != 0.0 else 0.0
    else:
        z = mean_gap / pooled_std
    return {"mean_gap": mean_gap, "pooled_std": pooled_std, "z": z}
