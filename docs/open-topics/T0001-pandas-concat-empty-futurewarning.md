---
status: open
---

# pandas concat-with-empty FutureWarning in _build_staging

## Context — what

`_build_staging` in `cli/data/pipeline.py` merges each pair's existing rows
with its newly-fetched rows via `pd.concat([old_df, new_df], ignore_index=True)`.
When a pair contributes no new rows — a backfill **carry-over** pair (not being
extended), or any pair whose fetch returned nothing — `new_df` is an empty
`DataFrame(columns=["date"] + FIELDS)`. pandas emits:

> FutureWarning: The behavior of DataFrame concatenation with empty or all-NA
> entries is deprecated. In a future version, this will no longer exclude empty
> or all-NA columns when determining the result dtypes.

## Why this matters

Today pandas **excludes** empty/all-NA frames when inferring result dtypes, so
concatenating a float-typed `old_df` with the empty (object-dtype) `new_df`
keeps the float dtypes. A future pandas will **include** those empty columns in
dtype inference, which can upcast numeric columns to `object`. `write_bin`
re-casts every value with `float(...)`, so the on-disk bins are not at immediate
risk — but the warning grows louder (and eventually errors) across pandas
upgrades, and the object upcast is a latent correctness trap if the write path
ever stops force-casting.

## Findings so far

- Trigger: `cli/data/pipeline.py` `_build_staging` concat; the empty `new_df`
  originates at the backfill carry-over assignment and the
  `new_rows_per_sym.get(..., <empty>)` defaults.
- Surfaces as a pytest warnings-summary entry (e.g. `tests/test_data_backfill.py`,
  `tests/test_data_e2e.py`), **not** in the `zcrypto` JSONL logs — it is a Python
  `warnings` emission captured by pytest, not routed through `cli/logging`.
- Present on `develop` (same concat line) as well as the in-flight data branches.

## Suggested next steps

- Skip the concat when `new_df` is empty:
  `merged[sym] = old_df if new_df.empty else pd.concat([old_df, new_df], ignore_index=True)`
  — avoids the empty-frame dtype-inference path entirely; minimal fix.
- Alternatively, construct `new_df` with explicit per-field float dtypes so it is
  never object-typed, or filter empty frames before concat.
- Once fixed, scope a `filterwarnings=error` for this module in pytest so the
  warning cannot silently return.
