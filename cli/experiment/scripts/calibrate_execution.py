"""One-off: calibrate the realistic execution-cost constants from the iter-17 aggTrades sample.

Usage:
    uv run python cli/experiment/scripts/calibrate_execution.py [--backup-dir <path>]

Parses the aggTrades zips in the raw mirror (per pair, per day), estimates per-pair/per-tier
(impact coefficient c, maker-fill rate f, spread s), and PRINTS a COST_CALIBRATION dict to paste
into cli/experiment/costs.py at the iter-19 closeout. NOT part of the routine flow — see
cli/experiment/scripts/README.md.

The estimators are deliberately simple, daily-granularity approximations (documented in the spec):
  - impact c: simulate consuming `probe_frac` of the bar's $-volume from the first trade price;
    realized VWAP slippage (ratio) = c * probe_frac**2  →  c = slippage_ratio / probe_frac**2.
  - fill (f, s): spread s = (mean taker-buy price - mean maker price) / mid; fill rate f =
    fraction of volume resting as maker (is_buyer_maker aggregated) as a fill proxy.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Liquidity tiers for the iter-17 sample (by daily $-volume); confirmed at calibration.
TIERS: dict[str, tuple[str, ...]] = {
    "deep": ("BTCUSDT", "ETHUSDT"),
    "mid": ("SOLUSDT", "LINKUSDT", "ATOMUSDT"),
    "thin": ("PEPEUSDT",),
}


def estimate_impact_coef(trades: pd.DataFrame, bar_dollar_volume: float, probe_frac: float = 0.005) -> float:
    """Recover qlib's impact coefficient c from one bar's trades.

    Consume `probe_frac` of `bar_dollar_volume` starting at the first trade; the realized VWAP
    slippage ratio vs the first price equals c * probe_frac**2, so c = ratio / probe_frac**2.
    """
    if trades.empty or bar_dollar_volume <= 0 or probe_frac <= 0:
        return 0.0
    p0 = float(trades["price"].iloc[0])
    target = bar_dollar_volume * probe_frac
    cum_val = 0.0
    cum_qty = 0.0
    for price, qty in zip(trades["price"].to_numpy(), trades["quantity"].to_numpy()):
        take = float(qty)
        line_val = float(price) * take
        if cum_val + line_val >= target:
            take = max((target - cum_val) / float(price), 0.0)
            line_val = float(price) * take
        cum_val += line_val
        cum_qty += take
        if cum_val >= target:
            break
    if cum_qty <= 0 or p0 <= 0:
        return 0.0
    vwap = cum_val / cum_qty
    slippage_ratio = abs(vwap - p0) / p0
    return float(slippage_ratio / (probe_frac**2))


def estimate_fill(trades: pd.DataFrame) -> tuple[float, float]:
    """Estimate (maker_fill_rate, spread_ratio) from one bar's trades.

    fill_rate = fraction of volume where is_buyer_maker is True (a resting-maker proxy);
    spread = (mean price of taker-buy trades - mean price of maker trades) / mid, clamped >= 0.
    """
    if trades.empty:
        return 0.0, 0.0
    qty = trades["quantity"].to_numpy(dtype=float)
    maker_mask = trades["is_buyer_maker"].to_numpy(dtype=bool)
    total = float(qty.sum())
    fill_rate = float(qty[maker_mask].sum() / total) if total > 0 else 0.0
    maker_px = trades.loc[maker_mask, "price"]
    taker_px = trades.loc[~maker_mask, "price"]
    mid = float(trades["price"].mean())
    if len(maker_px) and len(taker_px) and mid > 0:
        spread = max((float(taker_px.mean()) - float(maker_px.mean())) / mid, 0.0)
    else:
        spread = 0.0
    return fill_rate, spread


def calibrate(sample_frames: dict[str, list[pd.DataFrame]], *, taker_premium: float = 0.0002) -> dict:
    """Aggregate per-pair estimates into the COST_CALIBRATION dict.

    `sample_frames` maps SYMBOL -> list of per-day trades DataFrames. Returns the
    {"impact_cost", "maker_fill_haircut", "tiers"} dict (single representative impact_cost +
    haircut; per-tier breakdown recorded under "tiers").
    """
    sym_to_tier = {s: t for t, syms in TIERS.items() for s in syms}
    per_tier: dict[str, dict] = {}
    for sym, frames in sample_frames.items():
        tier = sym_to_tier.get(sym, "mid")
        cs, fs, ss = [], [], []
        for tr in frames:
            bar_vol = float((tr["price"] * tr["quantity"]).sum())
            cs.append(estimate_impact_coef(tr, bar_vol))
            f, s = estimate_fill(tr)
            fs.append(f)
            ss.append(s)
        bucket = per_tier.setdefault(tier, {"c": [], "f": [], "s": []})
        bucket["c"].extend(cs)
        bucket["f"].extend(fs)
        bucket["s"].extend(ss)

    def _mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else 0.0

    tiers_out = {}
    for tier, b in per_tier.items():
        f = _mean(b["f"])
        s = _mean(b["s"])
        tiers_out[tier] = {
            "impact_cost": _mean(b["c"]),
            "fill_rate": f,
            "spread": s,
            "haircut": (1.0 - f) * (s / 2.0 + taker_premium),
        }
    # Single representative = mean across tiers present (the closeout records whether tiers diverge).
    impact = _mean([t["impact_cost"] for t in tiers_out.values()])
    haircut = _mean([t["haircut"] for t in tiers_out.values()])
    return {"impact_cost": impact, "maker_fill_haircut": haircut, "tiers": tiers_out}


def _load_sample_frames(backup_dir: Path) -> dict[str, list[pd.DataFrame]]:
    """Read the aggTrades mirror zips into per-pair lists of trades DataFrames.

    The mirror lays zips out at ``<backup-dir>/raw/spot/daily/aggTrades/<SYMBOL>/<YYYY>/…``
    (see ``cli/data/binance.aggtrades_archive_parts``); we discover them by recursive glob
    rather than building per-(symbol, date) paths, so the daily filenames need not be enumerated.
    """
    import zipfile

    cols = ["agg_id", "price", "quantity", "first_id", "last_id", "ts", "is_buyer_maker", "is_best_match"]
    root = backup_dir / "raw"
    frames: dict[str, list[pd.DataFrame]] = {}
    base = root / "spot" / "daily" / "aggTrades"
    for sym_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []:
        sym = sym_dir.name
        for zpath in sorted(sym_dir.rglob("*.zip")):
            with zipfile.ZipFile(zpath) as zf:
                name = zf.namelist()[0]
                df = pd.read_csv(zf.open(name), header=None, names=cols, usecols=["price", "quantity", "is_buyer_maker"])
            frames.setdefault(sym, []).append(df)
    return frames


def main() -> None:
    import argparse
    import json

    from cli.config import load_config, resolve_backup_dir

    parser = argparse.ArgumentParser(description="Calibrate realistic execution costs from the aggTrades sample.")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Mirror backup dir (default: from zcrypto.toml).")
    args = parser.parse_args()

    backup_dir = resolve_backup_dir(args.backup_dir, load_config())
    print(f"Calibrating execution costs from aggTrades under {backup_dir}/raw ...")
    frames = _load_sample_frames(backup_dir)
    print(f"Loaded {sum(len(v) for v in frames.values())} pair-days across {len(frames)} pairs.")
    result = calibrate(frames)
    print("COST_CALIBRATION = " + json.dumps(result, indent=4))


if __name__ == "__main__":
    main()
