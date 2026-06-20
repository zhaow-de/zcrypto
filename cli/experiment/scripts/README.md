This directory holds one-time-use operational scripts that are not part of the routine `zcrypto experiment` flow.

`calibrate_execution.py` is a one-off script that estimates the realistic execution-cost constants
(`impact_cost`, `maker_fill_haircut`) from the iter-17 aggTrades sample. It reads the aggTrades
zips from the raw mirror (per pair, per day), computes per-pair/per-tier estimates of the qlib
impact coefficient and maker-fill haircut, and PRINTS a `COST_CALIBRATION` dict to paste into
`cli/experiment/costs.py` at the iter-19 closeout. It does NOT write `costs.py` directly.
Run it with `uv run python cli/experiment/scripts/calibrate_execution.py [--backup-dir <path>]`.
