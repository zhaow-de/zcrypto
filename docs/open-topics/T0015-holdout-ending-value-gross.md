---
status: open
---

# Holdout `ending_value` is gross (pre-cost)

## Context — what

The `--seeds` multi-seed holdout (`run_holdout_seeds` in `cli/experiment/multiseed.py`)
computes each seed's reported `ending_value` from the **gross** daily return —
`account * (1 + report_df["return"]).cumprod()` (`multiseed.py:216`) — while the same
per-seed dict's `sharpe` and `psr` are computed from the **net** return
`cost_adj = report_df["return"] - report_df["cost"]` (`multiseed.py:214`). So within one
result the headline ending-value ignores trading costs that the risk metrics do account for.

## Why this matters

`ending_value` is the most-quoted number in our re-measures, and it overstates the achievable
result by exactly the cumulative cost. It is also **cost-insensitive**: two runs that differ
only in the cost model produce the same gross `ending_value`. iter-19 (execution costs) hit this
directly — the realistic-vs-`--fees-only` A/B showed ~0% difference on median `ending_value`
even though the cost model genuinely changed, and the effect was only visible in the
cost-adjusted Sharpe (and the main-run with-cost annualized return). Any past ending-value
figure that carried trading cost (iter-14 multi-seed, iter-18 survivorship) is a **gross**
number; the gap widens with turnover and with the now-default realistic costs.

## Findings so far

- `multiseed.py:216` uses `report_df["return"]` (gross) for `ending_value`; `:214` uses
  `report_df["return"] - report_df["cost"]` (net) for `sharpe`/`psr`. Surfaced during iter-19
  (spec/plan `00018`); see the iter-19 entry in `docs/iterations-history.md`.
- Not yet audited: whether the **single-run** holdout `ending_value` (the scaffold path —
  `run_experiment` / `metrics.json` / the `"10000 -> X"` stdout line) is also gross or already
  net. The CPCV path Sharpes are cost-adjusted (`cpcv.py`), but the displayed account value's
  cost-treatment needs the same check.

## Suggested next steps

- Make the holdout `ending_value` **cost-adjusted** — `account * (1 + (report_df["return"] -
  report_df["cost"])).cumprod()` — so it agrees with the seed's `sharpe`/`psr`.
- Audit the single-run `ending_value` (`cli/experiment/scaffold.py`) and the report/stdout
  account-value line; align them to net if they are gross.
- Once fixed, note in the changelog that prior ending-value figures were gross (no need to
  re-run historical experiments — the gross/net gap is recoverable from the recorded costs).
