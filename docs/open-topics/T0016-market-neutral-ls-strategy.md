---
status: open
priority: medium
---

# First-class market-neutral long/short strategy / recipe

## Context — what

iter-21 (spec/plan `00020`) showed that a **market-neutral long/short** construction monetizes the
base cross-sectional alpha — the first profitable backtest in the project (`steady` long-only
Sharpe −0.585 → L/S Sharpe +0.60, ending ~1.33 = +33% net of realistic daily-turnover costs over
the 2025+ holdout). But it was built as an **evaluator** (`cli/experiment/longshort.py`
`long_short_spread`) — a metric computed over the holdout signal that reports `ls_sharpe`/`ls_ending`
per seed. It is **not a tradeable strategy**: it produces no run bundle / trades / positions, can't
be walk-forwarded or regime-gated, and has no path to paper/live execution. This topic tracks
promoting the market-neutral L/S from an evaluation into a **first-class strategy + recipe**.

## Why this matters

The evaluator proved the *concept* but the long-only `TopkDropoutStrategy` book is what every recipe
actually trades — and it loses to beta. If the L/S edge survives out-of-sample (see gating below), a
real market-neutral strategy is the only way to capture it as deployable P&L: a `*_ls` recipe that
emits a dollar-neutral long/short book, flows through the full scaffold (run bundle, trades.csv,
metrics, report), composes with walk-forward (`T0009`) and regime gating (`T0003`), and can reach the
paper-trading harness (`T0006`). Without it, the project's one profitable result stays a research
metric, not a strategy.

## Findings so far

- iter-21 `long_short_spread` evaluator + verdict: market-neutral monetizes; **funding does not
  survive market-neutral** (its long-only edge was a defensive low-beta long tilt L/S removes). See
  the iter-21 entry in `docs/iterations-history.md`.
- **qlib's `SimulatorExecutor` cannot short** (`exchange.py:900` clips sells to the held amount;
  `# TODO: make the trading shortable`). So a real L/S strategy can't reuse the existing qlib backtest
  path as-is — it needs either a custom short-capable executor/exchange, or a strategy that computes
  the dollar-neutral book's P&L outside qlib's `Account` (extending the iter-21 spread approach to a
  full position/trade ledger). This is the load-bearing build cost.

## Suggested next steps

- **Gate on out-of-sample validation first (`T0007`).** The iter-21 +33% is on a single holdout that
  has been the dev test-segment since iter-9 (selection-bias risk). Do NOT build the strategy until the
  L/S edge survives a fresh OOS / multi-window stress — otherwise it risks productionizing an overfit.
- If it validates: build a **market-neutral L/S strategy** (resolve the no-shorting limitation — a
  custom executor/exchange or an out-of-qlib position ledger), a `*_ls` recipe, and route it through
  the scaffold (bundle/trades/metrics/report) so it's a first-class citizen alongside the long-only
  recipes; then compose with walk-forward (`T0009`) and regime gating (`T0003`).
