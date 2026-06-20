"""One-time idempotent script: acquire Terra's old-LUNA into the dataset as LUNCUSDT.

Background: Binance reused the LUNAUSDT symbol — old LUNA's archives end at the
2022-05-13 Terra crash, then the same symbol carries Luna 2.0 from 2022-05-31.
The normal `zcrypto data download` command cannot capture old-LUNA-only (a past
--to is rejected as a truncation). This script's trick is to fetch old-LUNA klines
bounded at 2022-05-13 (the cap) so Luna 2.0 archives are never touched, then call
the existing rename_pipeline to bridge into LUNCUSDT.

Result: LUNCUSDT spans old-LUNA[2020-08-21..2022-05-13] + NaN gap[2022-05-14..
2022-09-08] (the gap between the cap and LUNC's first archive day). The LUNC tail
from 2022-09-09 onward is picked up by the next routine `zcrypto data backfill`
run — rename_pipeline (Variant 1) stops at the day before LUNC's first archive.

Phase 1 — insert capped old-LUNA as LUNAUSDT:
    Uses _build_staging + _execute_mutation (snapshot-safe, post-verified).
Phase 2 — rename LUNAUSDT → LUNCUSDT:
    Uses rename_pipeline (Variant 1); fills NaN gap days; does NOT fetch LUNC tail.

Idempotency:
    - LUNCUSDT already in index → "already-acquired", no-op.
    - LUNAUSDT already in index (Phase 1 done, Phase 2 not) → skip Phase 1.

Usage:
    uv run python cli/data/scripts/acquire_old_luna.py [--data-dir <path>] [--dry-run]

This script is NOT part of the routine `zcrypto data` flow.
See cli/data/scripts/README.md for details.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cli.config import load_config, resolve_backup_dir, resolve_data_dir

# Real production cap: last day old LUNA traded before the Terra collapse.
_DEFAULT_CAP = dt.date(2022, 5, 13)


def acquire_old_luna(
    paths: "object",  # DatasetPaths
    source: "object",  # Source
    *,
    cap: dt.date = _DEFAULT_CAP,
    mirror_root: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Phase 1 (capped old-LUNA insert via _build_staging) + Phase 2 (rename to LUNCUSDT).

    Idempotent: re-run after success is a no-op; resumes at Phase 2 if Phase 1 already landed.

    Args:
        paths: DatasetPaths with .data_dir and .backup_dir.
        source: Source (real BinanceSource or FakeSource) for kline fetches.
        cap: Last calendar day to fetch for old LUNA. Defaults to 2022-05-13 (the Terra crash).
        mirror_root: optional mirror dir for caching archive zips. Defaults to
                     paths.backup_dir / "raw".
        dry_run: If True, pass dry_run through to _execute_mutation / rename_pipeline.

    Returns:
        dict with "status" and optional "luna_from", "luna_to", "rows" keys.
    """
    import dataclasses

    import pandas as pd

    from cli.data.index import load_index
    from cli.data.klines import assert_no_internal_gaps
    from cli.data.layout import DatasetPaths
    from cli.data.pipeline import (
        _build_staging,
        _execute_mutation,
        _fetch_one_date,
        _PerPair,
        find_available_range,
        rename_pipeline,
    )

    data_dir: Path = paths.data_dir  # type: ignore[attr-defined]
    backup_dir: Path = paths.backup_dir  # type: ignore[attr-defined]

    if mirror_root is None:
        mirror_root = backup_dir / "raw"

    # --- Load and validate existing index ---
    existing = load_index(data_dir)
    if existing is None:
        raise RuntimeError(f"no index.json found at {data_dir}; run 'zcrypto data download' first")

    # --- Idempotency checks ---
    if "LUNCUSDT" in existing.pairs:
        print(f"acquire_old_luna: LUNCUSDT already in index at {data_dir}; nothing to do.")
        return {"status": "already-acquired"}

    phase1_skip = "LUNAUSDT" in existing.pairs

    if not phase1_skip:
        # --- Phase 1: insert capped old-LUNA as LUNAUSDT ---
        # Resolve old-LUNA's actual first archive date (bounded by cap on the hi side).
        rng = find_available_range(source, "LUNAUSDT", "1d", dt.date(2020, 1, 1), cap)
        if rng is None:
            raise RuntimeError(f"no LUNAUSDT kline archive found in [2020-01-01, {cap}] on Binance")
        lo, _ = rng  # hi is probed up to cap; lo is the first available day

        # Fetch each day in [lo, cap] and collect rows.
        cur = lo
        rows_list = []
        while cur <= cap:
            _, _, df = _fetch_one_date(source, "LUNAUSDT", "1d", cur, mirror_root)
            rows_list.append(df)
            cur += dt.timedelta(days=1)

        luna_df = pd.concat(rows_list, ignore_index=True).sort_values("date").reset_index(drop=True)

        # Assert no interior gap in old-LUNA's archive (it traded continuously through the crash).
        expected_days = [lo + dt.timedelta(days=i) for i in range((cap - lo).days + 1)]
        assert_no_internal_gaps(luna_df["date"].tolist(), expected_days, "LUNAUSDT")

        # Build the per-pair plan: all existing pairs unchanged + the new capped LUNAUSDT.
        perpair_plan: list[_PerPair] = []
        for sym, pe in existing.pairs.items():
            ie = pe.intervals["1d"]
            perpair_plan.append(
                _PerPair(
                    symbol=sym,
                    base=pe.base_asset,
                    quote=pe.quote_asset,
                    effective_from=dt.date.fromisoformat(ie.from_date),
                    effective_to=dt.date.fromisoformat(ie.to_date),
                    is_new=False,
                    existing_from=dt.date.fromisoformat(ie.from_date),
                )
            )
        perpair_plan.append(
            _PerPair(
                symbol="LUNAUSDT",
                base="LUNA",
                quote="USDT",
                effective_from=lo,
                effective_to=cap,
                is_new=True,
                existing_from=None,
            )
        )

        # Capture for closures (avoid late-binding).
        _plan = perpair_plan
        _luna_df = luna_df
        _existing = existing
        _source = source
        _mirror_root = mirror_root

        def plan_fn(out_dir: Path):
            # plan_fn is read-only: return a lightweight object with is_noop and dry_run_summary.
            @dataclasses.dataclass
            class _AcquirePlan:
                is_noop: bool = False

                def dry_run_summary(self) -> str:
                    return (
                        f"DRY-RUN: acquire-old-luna Phase 1: insert LUNAUSDT [{lo} .. {cap}] ({len(_plan)} total pairs in staging)"
                    )

            return _AcquirePlan()

        def apply_fn(paths_inner, staging: Path, plan_obj) -> None:
            _build_staging(
                paths_inner.data_dir,
                staging,
                _plan,
                {"LUNAUSDT": _luna_df},
                _existing,
                "1d",
                _source,
                _mirror_root,
            )

        _execute_mutation(paths, "acquire-old-luna", plan_fn, apply_fn, dry_run=dry_run)

        print(f"acquire_old_luna: Phase 1 complete — LUNAUSDT [{lo} .. {cap}] inserted.")

        if dry_run:
            return {"status": "dry-run"}

    # --- Phase 2: rename LUNAUSDT → LUNCUSDT (fetch LUNC tail + merge via rename_pipeline) ---
    print("acquire_old_luna: Phase 2 — renaming LUNAUSDT → LUNCUSDT ...")
    rename_pipeline(paths, "LUNAUSDT", "LUNCUSDT", source, dry_run=dry_run)

    if dry_run:
        return {"status": "dry-run"}

    # Reload index to report outcome.
    final_idx = load_index(paths.data_dir)
    assert final_idx is not None
    lunc_entry = final_idx.pairs.get("LUNCUSDT")
    if lunc_entry is None:
        return {"status": "done"}

    iv = lunc_entry.intervals["1d"]
    return {
        "status": "done",
        "luna_from": iv.from_date,
        "luna_to": iv.to_date,
        "rows": iv.rows,
    }


def main() -> None:
    import argparse

    from cli.data.binance import BinanceSource
    from cli.data.layout import DatasetPaths

    parser = argparse.ArgumentParser(description="Acquire Terra's old-LUNA into the dataset as LUNCUSDT (idempotent one-off).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to the compiled dataset directory (default: from zcrypto.toml).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan and verify without writing any files.",
    )
    args = parser.parse_args()

    cfg = load_config()
    data_dir = resolve_data_dir(args.data_dir, cfg)
    backup_dir = resolve_backup_dir(None, cfg)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    source = BinanceSource(fetch=cfg.fetch)

    print(f"Acquiring old-LUNA into {data_dir} as LUNCUSDT ...")
    result = acquire_old_luna(paths, source, cap=_DEFAULT_CAP, dry_run=args.dry_run)
    print(f"Done: {result}")


if __name__ == "__main__":
    main()
