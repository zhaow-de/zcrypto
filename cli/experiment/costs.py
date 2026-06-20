"""Calibrated execution-cost constants for the experiment cost model (see docs/specs/00018).

These are the DEFAULT realistic-cost parameters: qlib's Exchange ``impact_cost`` (size-scaled
slippage, applied per instrument as ``impact_cost * (order$ / bar$-volume) ** 2``) and a
``maker_fill_haircut`` (an additive per-side cost fraction approximating the taker penalty when
a maker limit order does not fill). They are calibrated from the iter-17 aggTrades sample by
``cli/experiment/scripts/calibrate_execution.py``.

NOTE: the values below are PROVISIONAL placeholders set during implementation; they are replaced
at the iter-19 closeout with the values printed by calibrate_execution.py on the real sample.
``tiers`` records the per-liquidity-tier breakdown for the record (the wired model uses the
single representative ``impact_cost`` / ``maker_fill_haircut`` — qlib's exchange cost knobs are
single scalars).
"""

from __future__ import annotations

COST_CALIBRATION: dict = {
    # PROVISIONAL — replaced at closeout from calibrate_execution.py on the real aggTrades sample.
    "impact_cost": 0.1,  # qlib Exchange impact_cost coefficient (single representative)
    "maker_fill_haircut": 0.0005,  # additive per-side cost fraction (5 bps) for non-fills
    "tiers": {},  # per-tier {tier: {"impact_cost": c, "fill_rate": f, "spread": s}} — analysis record
}
