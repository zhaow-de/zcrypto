---
status: open
---

# qlib `Mean of empty slice` runtime warning

## Context — what

When `zcrypto example` runs, qlib emits dozens of `RuntimeWarning: Mean of empty slice` messages from `qlib/utils/index_data.py:492` in `pyqlib` 0.9.7 (the offending line is `return np.nanmean(self.data)`). The warning fires every time qlib's per-step aggregator calls `np.nanmean` on an empty slice — common, for example, on days when our `TopkDropoutStrategy(topk=2, n_drop=1)` places no orders.

We currently suppress the warning at logger-configuration time in `cli/logging/config.py::configure()` via:

```python
warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning, module="qlib.utils.index_data")
```

## Why this matters

The warning is **benign** — `np.nanmean` of an empty array correctly returns `NaN`, qlib handles that downstream, and our integration test confirms every returned backtest metric is finite. But the hardcoded filter is a workaround for upstream behavior we don't control. As long as it's in place, a future legitimate "Mean of empty slice" warning from a refactored qlib code path would also be silenced.

## Findings so far

- Warning source in pyqlib 0.9.7: `.venv/lib/python3.12/site-packages/qlib/utils/index_data.py:492` — the line `return np.nanmean(self.data)` does not guard `self.data.size > 0` before calling `np.nanmean`.
- Verified benign during iter-2 debugging: all `risk_analysis` metrics return finite values; `tests/test_example_workflow.py::test_run_experiment_returns_finite_metrics` asserts `math.isfinite(v)` and passes.
- The filter is installed by `configure()` for the lifetime of every `zcrypto` invocation.

## Suggested next steps

- **Periodically (e.g. on every `pyqlib` bump in `pyproject.toml`)**: inspect `.venv/lib/python3.12/site-packages/qlib/utils/index_data.py` around the `np.nanmean(self.data)` call (was at line 492 in 0.9.7) and check whether the surrounding method now guards `self.data.size > 0` before calling `np.nanmean`.
- **On upstream fix**: remove the `warnings.filterwarnings(...)` call and the `import warnings` from `cli/logging/config.py`, flip this topic's front-matter to `status: resolved`, and verify `uv run zcrypto example` runs cleanly without the suppression.
- **If qlib is replaced** by another framework: drop the filter and this topic together with that migration.
- **Upstream issue tracking**: no qlib issue tracked yet — file one (or link an existing one) on the next investigation pass.
