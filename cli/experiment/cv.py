"""Pure combinatorial purged cross-validation (CPCV) split math — no qlib.

Works on an ordered calendar by INDEX position. The crypto calendar is 24/7
daily and contiguous, so one position == one day; `purge_days` / `embargo_days`
are therefore position counts.

References: López de Prado, *Advances in Financial Machine Learning*, Ch. 7
(purged k-fold + embargo) and Ch. 12 (CPCV, backtest paths).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb


@dataclass(frozen=True)
class CVSplit:
    test_group_ids: tuple  # group indices forming the test set
    train_dates: list  # calendar dates used for training (purged + embargoed)
    test_dates: list  # calendar dates in the test groups


@dataclass(frozen=True)
class CVPlan:
    n_groups: int
    test_groups: int
    purge_days: int
    embargo_days: int
    groups: list  # list[list[date]] — each group's dates in calendar order
    splits: list  # list[CVSplit], length C(n_groups, test_groups)

    @property
    def n_paths(self) -> int:
        return comb(self.n_groups - 1, self.test_groups - 1)


def _group_index_bounds(n_dates: int, n_groups: int) -> list[tuple[int, int]]:
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if n_dates < n_groups:
        raise ValueError(f"calendar too short ({n_dates} dates) for {n_groups} groups")
    base, extra = divmod(n_dates, n_groups)
    bounds, start = [], 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def _contiguous_blocks(sorted_positions):
    """Yield (start, end) half-open index ranges of maximal contiguous runs."""
    if not sorted_positions:
        return
    start = prev = sorted_positions[0]
    for p in sorted_positions[1:]:
        if p == prev + 1:
            prev = p
            continue
        yield (start, prev + 1)
        start = prev = p
    yield (start, prev + 1)


def build_cv_plan(calendar, *, n_groups: int, test_groups: int, purge_days: int, embargo_days: int) -> CVPlan:
    if not 1 <= test_groups < n_groups:
        raise ValueError(f"test_groups must be in [1, n_groups), got {test_groups} (n_groups={n_groups})")
    cal = list(calendar)
    n = len(cal)
    bounds = _group_index_bounds(n, n_groups)
    groups = [cal[s:e] for (s, e) in bounds]

    splits = []
    for test_ids in combinations(range(n_groups), test_groups):
        test_pos = set()
        for gid in test_ids:
            s, e = bounds[gid]
            test_pos.update(range(s, e))
        train_pos = set(range(n)) - test_pos
        for s, e in _contiguous_blocks(sorted(test_pos)):
            for p in range(max(0, s - purge_days), s):  # purge: leading edge
                train_pos.discard(p)
            for p in range(e, min(n, e + embargo_days)):  # embargo: trailing edge
                train_pos.discard(p)
        splits.append(
            CVSplit(
                test_group_ids=test_ids,
                train_dates=[cal[i] for i in sorted(train_pos)],
                test_dates=[cal[i] for i in sorted(test_pos)],
            )
        )

    return CVPlan(
        n_groups=n_groups,
        test_groups=test_groups,
        purge_days=purge_days,
        embargo_days=embargo_days,
        groups=groups,
        splits=splits,
    )


def assemble_paths(plan: CVPlan, predictions: dict):
    """Stitch per-split test predictions into ``plan.n_paths`` full-span path Series.

    ``predictions``: ``{split_index -> pd.Series}`` indexed by ``(datetime,
    instrument)`` over that split's ``test_dates``. Returns ``list[pd.Series]``,
    each spanning the full calendar (every date once), sorted by index.

    Path ``j`` takes, for every group, that group's slice from the ``j``-th split
    in which the group is a test group — so each (group, split) test cell is used
    exactly once across all paths.
    """
    import pandas as pd

    group_to_splits = {g: [] for g in range(plan.n_groups)}
    for si, split in enumerate(plan.splits):
        for gid in split.test_group_ids:
            group_to_splits[gid].append(si)

    paths = []
    for j in range(plan.n_paths):
        pieces = []
        for gid in range(plan.n_groups):
            si = group_to_splits[gid][j]
            group_dates = set(plan.groups[gid])
            pred = predictions[si]
            mask = pred.index.get_level_values(0).isin(group_dates)
            pieces.append(pred[mask])
        paths.append(pd.concat(pieces).sort_index())
    return paths
