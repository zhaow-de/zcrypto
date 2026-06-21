"""Calibrated execution-cost constants for the experiment cost model (see docs/specs/00018).

These are the DEFAULT realistic-cost parameters: qlib's Exchange ``impact_cost`` (size-scaled
slippage, applied per instrument as ``impact_cost * (order$ / bar$-volume) ** 2``) and a
``maker_fill_haircut`` (an additive per-side cost fraction approximating the taker penalty when
a maker limit order does not fill). They are calibrated from the iter-17 aggTrades sample by
``cli/experiment/scripts/calibrate_execution.py``.

Calibrated at the iter-19 closeout from the iter-17 aggTrades sample (540 pair-days across
6 pairs, 2024-12-01..2025-02-28) via calibrate_execution.py. ``tiers`` records the per-liquidity
breakdown: the impact coefficient diverges ~3.3x across tiers (deep 39.3 < mid 86.0 < thin 130.1),
confirming liquidity-dependent slippage; the wired model uses the single representative
``impact_cost`` / ``maker_fill_haircut`` (qlib's exchange cost knobs are single scalars), which
slightly over-penalizes deep books and under-penalizes thin ones (PEPE) — per-tier wiring (a
custom Exchange) is the parked refinement. At the $10k account size the ``(order$/bar$-vol)**2``
slippage term is near-zero (orders are a tiny fraction of daily volume), so the ~2.2 bps
maker-fill haircut is the dominant realistic-cost effect.
"""

from __future__ import annotations

COST_CALIBRATION: dict = {
    "impact_cost": 85.14243442280177,  # qlib Exchange impact_cost coefficient (single representative; mean of tiers)
    "maker_fill_haircut": 0.00021654821992135172,  # additive per-side cost fraction (~2.2 bps) for non-fills
    "tiers": {
        "deep": {
            "impact_cost": 39.28165029327256,
            "fill_rate": 0.513232498702903,
            "spread": 0.00022708598637513895,
            "haircut": 0.00015262253934312592,
        },
        "mid": {
            "impact_cost": 86.0003786694619,
            "fill_rate": 0.5122754353276546,
            "spread": 0.0005356714868837059,
            "haircut": 0.00022817498430834082,
        },
        "thin": {
            "impact_cost": 130.14527430567085,
            "fill_rate": 0.5086827049011732,
            "spread": 0.0006943931296312728,
            "haircut": 0.0002688471361125884,
        },
    },
}
