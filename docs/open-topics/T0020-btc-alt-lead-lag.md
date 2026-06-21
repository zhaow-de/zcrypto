---
status: open
---

# BTC→altcoin lead-lag (intraday cross-coin predictability)

## Context — what

The Phase 2 orientation
([`docs/research/03.phase2-orientation.md`](../research/03.phase2-orientation.md)) identifies
**BTC→altcoin lead-lag** — whether BTC's (and ETH's) recent intraday move predicts altcoin moves
over the next several hours — as the most promising *genuine relative-alpha* (Channel B) idea,
and the strongest documented effect that is both free (Binance klines) and aligned with the
hours-to-days horizon. It is structurally invisible to the daily-bar work that produced the
`T0018` wall.

## Why this matters

Unlike cross-sectional momentum (refuted OOS, `T0018`) and on-chain data (a BTC/ETH regime
overlay only, `T0021`), lead-lag is an economically-motivated effect — **slow information
diffusion across coins** — with literature support for an out-of-sample, cost-surviving
long/short signal ("Cross-cryptocurrency return predictability," Binance data). It is the
project's best remaining shot at an edge that is *relative* rather than just market-timing. On
spot (no shorting) it must be expressed as a long/cash over/underweight tilt, not a
market-neutral spread.

## Findings so far

- None yet (Phase 2). Requires intraday (e.g. 1h) klines — a new ingestion path. Qlib's
  high-frequency support is less mature, so expect custom dumping of Binance 1m/1h klines into
  the qlib binary format (start at 1h/4h before 1m). The free Binance archive
  (`data.binance.vision`) already covers this frequency.
- Phase 1 caution carried forward: any "it stacks" assumption must be *tested* — funding did
  **not** stack with cross-asset features once gated (iters 25/26), so a lead-lag tilt must prove
  it adds value on top of the `T0019` trend core rather than being assumed additive.

## Suggested next steps

- **Ingest 1h klines** for the universe into the qlib dataset (new freq); verify
  open-timestamp / lookahead discipline (a bar labeled 12:00 closes at 13:00 — only closed bars
  are usable at decision time; this off-by-one silently inflates intraday backtests).
- **Lead-lag features:** lagged BTC (and ETH) returns over the prior *k* hours as predictors of
  each alt's next-*h*-hour return; a cross-coin lagged-return matrix; shrinkage / adaptive-LASSO
  to avoid overfitting the cross-coin coefficients.
- **Express as a long/cash tilt** (overweight alts whose next move BTC's recent move predicts up;
  underweight/flat otherwise), composed with the regime gate; evaluate on the OOS stress harness
  + bootstrap CIs.
- **Success bar:** beats both the Stage-0 null *and* the `T0019` trend+vol-target core on the
  CPCV distribution (not best-path), net of the higher intraday turnover cost. **Kill:** if the
  edge doesn't survive realistic intraday costs, or doesn't stack on trend, keep it (if at all)
  only as a minor overlay.
- Be critical about turnover: an hourly-reacting signal churns; enforce a no-trade band / minimum
  hold horizon so fees don't consume the edge (mirrors the roadmap §14 turnover discipline).
