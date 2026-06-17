from math import comb

import pandas as pd
import pytest

from cli.experiment.cv import _contiguous_blocks, assemble_paths, build_cv_plan


def test_split_and_path_counts():
    plan = build_cv_plan(list(range(60)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    assert len(plan.splits) == comb(6, 2) == 15
    assert plan.n_paths == comb(5, 1) == 5


def test_groups_partition_calendar_contiguously():
    plan = build_cv_plan(list(range(60)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    assert [d for g in plan.groups for d in g] == list(range(60))


def test_uneven_groups_partition():
    # 61 / 6 = 10 remainder 1 → the first group absorbs the extra date.
    plan = build_cv_plan(list(range(61)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    assert [len(g) for g in plan.groups] == [11, 10, 10, 10, 10, 10]
    assert [d for g in plan.groups for d in g] == list(range(61))


def test_purge_and_embargo_clear_train_around_each_test_block():
    purge, embargo, n = 3, 5, 60
    plan = build_cv_plan(list(range(n)), n_groups=6, test_groups=2, purge_days=purge, embargo_days=embargo)
    for split in plan.splits:
        train = set(split.train_dates)
        assert not (train & set(split.test_dates))  # disjoint
        forbidden = set()
        for s, e in _contiguous_blocks(sorted(split.test_dates)):
            forbidden |= set(range(max(0, s - purge), s)) | set(range(e, min(n, e + embargo)))
        assert not (train & forbidden)


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        build_cv_plan(list(range(60)), n_groups=6, test_groups=6, purge_days=0, embargo_days=0)
    with pytest.raises(ValueError):
        build_cv_plan(list(range(3)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)


def test_assemble_paths_full_coverage_and_provenance():
    cal = list(pd.date_range("2020-01-01", periods=60, freq="D"))
    plan = build_cv_plan(cal, n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    # fake predictions: for split i, a Series over its test dates × 2 instruments,
    # value == i so each path slice can be traced back to the split it came from.
    preds = {}
    for i, split in enumerate(plan.splits):
        idx = pd.MultiIndex.from_product([split.test_dates, ["A", "B"]], names=["datetime", "instrument"])
        preds[i] = pd.Series(float(i), index=idx)
    paths = assemble_paths(plan, preds)
    assert len(paths) == plan.n_paths

    # reconstruct group -> ordered test-split indices (mirrors assemble_paths)
    group_to_splits = {g: [] for g in range(plan.n_groups)}
    for si, split in enumerate(plan.splits):
        for gid in split.test_group_ids:
            group_to_splits[gid].append(si)

    for j, path in enumerate(paths):
        dates = path.index.get_level_values(0).unique()
        assert len(dates) == 60  # full span, every date once
        assert path.index.is_monotonic_increasing
        for gid in range(plan.n_groups):
            expected_si = group_to_splits[gid][j]
            group_dates = set(plan.groups[gid])
            group_slice = path[path.index.get_level_values(0).isin(group_dates)]
            assert (group_slice == float(expected_si)).all()  # provenance, not just coverage
