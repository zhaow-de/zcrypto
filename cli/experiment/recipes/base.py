"""Recipe contract and resolver for zcrypto experiment pipelines."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

# (open_cost, close_cost) round-trip fee fractions
FEE_PRESETS: dict[str, tuple[float, float]] = {
    "vip2_bnb": (0.0006, 0.0006),
    "vip2_std": (0.0008, 0.0008),
    "zero": (0.0, 0.0),
}

_RECIPES_DIR = Path(__file__).parent


def _available_recipes() -> list[str]:
    return sorted(p.stem for p in _RECIPES_DIR.glob("*.py") if p.stem not in ("__init__", "base"))


@dataclass(frozen=True)
class Recipe:
    """Frozen specification for one experiment run.

    The scaffold fills in instruments/segment-times/signal at runtime;
    this dataclass declares only the swappable configuration knobs.
    """

    name: str
    handler_kwargs: dict  # extra Alpha158 kwargs (infer_processors, learn_processors)
    model_config: dict  # full init_instance_by_config dict for the model
    strategy_config: dict  # full init_instance_by_config dict for the strategy
    segments: dict  # {"train": (s, e), "valid": (s, e), "test": (s, e)} ISO date strings
    universe: tuple  # traded USDT symbols (uppercase)
    reference_instruments: tuple  # chart-only, not traded
    account: float = field(default=10_000.0)
    benchmark: str = field(default="BTCUSDT")
    fee_preset: str = field(default="vip2_bnb")
    # CPCV / purge-embargo knobs (see docs/specs/00008). Defaults match Alpha158's
    # default label horizon and longest feature window; behavior-preserving.
    label_horizon_days: int = field(default=2)
    feature_lookback_days: int = field(default=60)
    cv_n_groups: int = field(default=6)
    cv_test_groups: int = field(default=2)
    # Pluggable feature handler class (see docs/specs/00013). Default = Alpha158.
    feature_config: dict = field(default_factory=lambda: {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"})
    # Walk-forward holdout retraining (see docs/specs/00011). Off = single-fit holdout.
    wf_enabled: bool = field(default=False)
    wf_retrain_freq: str = field(default="quarter")  # quarter | year
    wf_window: str = field(default="expanding")  # expanding | rolling
    wf_rolling_years: int = field(default=3)


def resolve_recipe(name: str) -> Recipe:
    """Return the Recipe for *name*, or raise ValueError listing available recipes."""
    available = _available_recipes()
    if name not in available:
        raise ValueError(f"Recipe '{name}' not found. Available: {', '.join(available)}")
    module = importlib.import_module(f"cli.experiment.recipes.{name}")
    return module.RECIPE
