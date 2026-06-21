---
status: open
---

# Paper-trading harness before live

## Context — what

The experiment skeleton (spec `00006`) stops at a historical backtest + report.
Before any capital, the roadmap requires ≥3 months of paper trading against live
Binance with paper fills, comparing paper P&L to backtest weekly.

## Why this matters

Research §13 Stage 4 — paper trading is the gate that catches a wrong backtest
(>20% divergence over a quarter ⇒ backtest is wrong, return to Stage 2). It's the
bridge between research and risking the $10k.

## Findings so far

Deferred from the experiment skeleton (spec `00006`); far downstream
(Stage 4–5). References: research §13 Stage 4–5, §12.

## Suggested next steps

- Wire a live data feed + paper-fill executor (python-binance / CCXT).
- Run the recipe daily; log paper-vs-backtest divergence.
- Define the go/no-go gate before live, small-size deployment.
