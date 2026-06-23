---
status: partial
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
- **iter-51 (PR pending) — FEASIBILITY PROBE → NO-GO for the liquid majors at 1–6h.** Rather than
  build the intraday harness blind, a cheap offline statistical probe (pre-registered 40-cell pooled
  predictive regression, HAC + clustered SEs, BH-FDR, deflated-IC, bootstrap CI, per-year sign-
  stability, economic decile-spread; spec `00045`) tested whether the signal exists on a free 1h pull
  of the 10 majors 2023-2025. **Decisive NO-GO:** zero of 40 cells positive-and-significant; the
  strongest effects are weak *negatives* (~−0.05 IC, all q≥0.62); sign-flips across years; economic
  decile spread −4.7 bps. So BTC/ETH's recent return has **no exploitable positive lead** over the
  liquid majors at 1–6h — they're efficiently priced. The probe is trustworthy (adversarial review:
  no look-ahead, sound stats). **The multi-week harness build was correctly NOT triggered.**

## Done so far

- iter-51 (spec `00045`, PR pending): built the reusable offline lead-lag probe (`cli/research/leadlag/`:
  1h fetcher-reader + pre-registered predictive-regression study + GO/NO-GO) and ran it on the 10 majors
  → **NO-GO**. The expensive intraday-harness build (1h ingestion → harness → signal → OOS) is gated off.
  The probe machinery is reusable for the residual variants below.

## Suggested next steps

The harness build stays gated (the majors showed no signal). The only residual, cheap variants — reuse the
iter-51 probe, just change the inputs:

- **Wider, less-liquid alt universe (the diffusion hypothesis's best remaining shot):** re-run the probe on
  smaller / lower-cap alts, where cross-coin information may propagate *slower* than in the efficiently-priced
  majors. If this is also null, `T0020` is refuted outright.
- **Sub-hourly (15m) horizon:** a single confirmatory probe at 15m — but lower priority (an even-faster signal
  needs an even-faster, higher-cost harness, so it must be far stronger to be tradeable; and the 1h majors
  showed *negative* IC, so a sub-hourly positive lead is unlikely).
- Only if a residual probe is GO does the full harness build (1h ingestion → intraday harness → lead-lag
  feature → OOS net-of-cost, with a min-hold/no-trade-band for turnover) become justified, with the original
  success bar (beats the Stage-0 null *and* the `T0019` trend core on the CPCV distribution net of intraday cost).
