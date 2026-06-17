"""Generate the committed synthetic qlib provider fixture used by experiment tests.

Run: uv run python cli/experiment/data/scripts/gen_fixture.py

Overwrites cli/experiment/data/provider/ with a deterministic, seed-based dataset.
No network I/O.  All 21 instruments span the full calendar (2023-01-02..2024-06-28).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

PROVIDER_DIR = Path(__file__).resolve().parents[1] / "provider"

# ---------------------------------------------------------------------------
# Calendar: 2023-01-02 .. 2024-06-28 (every calendar day — daily crypto trades)
# ---------------------------------------------------------------------------
CAL_START = dt.date(2023, 1, 2)
CAL_END = dt.date(2024, 6, 28)

# Fixed stamp for index.json so re-running the generator is byte-identical (git-clean).
_FIXED_UPDATED_AT = "2024-06-29T00:00:00Z"

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
USDT_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOGEUSDT",
    "TRXUSDT",
    "DOTUSDT",
    "POLUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "UNIUSDT",
    "NEARUSDT",
    "ARBUSDT",
    "APTUSDT",
    "PEPEUSDT",
]

REFERENCE_PAIRS = ["BTCEUR", "ETHBTC"]

ALL_PAIRS = USDT_PAIRS + REFERENCE_PAIRS  # 21 total

# base/quote parsing: strip a known quote suffix
_KNOWN_QUOTES = ("USDT", "EUR", "BTC")


def _split_pair(sym: str) -> tuple[str, str]:
    for q in _KNOWN_QUOTES:
        if sym.endswith(q):
            return sym[: -len(q)], q
    raise ValueError(f"Cannot infer base/quote from {sym!r}")


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


def _build_calendar() -> list[dt.date]:
    n = (CAL_END - CAL_START).days + 1
    return [CAL_START + dt.timedelta(days=i) for i in range(n)]


def _gen_ohlcv(rng: np.random.Generator, n: int, base_price: float) -> dict[str, list[float]]:
    """Generate plausible OHLCV via a log-random-walk."""
    # log-returns: μ=0, σ=0.015
    log_returns = rng.normal(0.0, 0.015, size=n)
    closes = base_price * np.exp(np.cumsum(log_returns))
    # open = previous close (first open = base_price)
    opens = np.empty(n)
    opens[0] = base_price
    opens[1:] = closes[:-1]
    # high/low: add a small random spread
    spread = np.abs(rng.normal(0.0, 0.005, size=n))
    highs = np.maximum(opens, closes) * (1.0 + spread)
    lows = np.minimum(opens, closes) * (1.0 - spread)
    # volume: log-normal around 1000
    volumes = np.exp(rng.normal(np.log(1000.0), 0.5, size=n))
    vwap = (opens + highs + lows + closes) / 4.0
    amount = volumes * vwap
    trades = np.round(rng.lognormal(mean=6.0, sigma=0.4, size=n)).astype(float)
    taker_buy_base = volumes * rng.uniform(0.4, 0.6, size=n)
    taker_buy_amount = taker_buy_base * vwap
    return {
        "open": opens.tolist(),
        "high": highs.tolist(),
        "low": lows.tolist(),
        "close": closes.tolist(),
        "volume": volumes.tolist(),
        "amount": amount.tolist(),
        "trades": trades.tolist(),
        "taker_buy_base": taker_buy_base.tolist(),
        "taker_buy_amount": taker_buy_amount.tolist(),
        "vwap": vwap.tolist(),
        "factor": [1.0] * n,
    }


def main() -> None:
    from cli.data.config import FIELDS, SCHEMA_VERSION
    from cli.data.index import (
        CalendarEntry,
        FieldEntry,
        FileEntry,
        IndexData,
        PairEntry,
        PairIntervalEntry,
        compute_sha256,
        save_index,
    )
    from cli.data.qlib_writer import write_bin, write_calendar, write_instruments

    out = PROVIDER_DIR
    # Wipe and recreate for idempotency
    import shutil

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    calendar = _build_calendar()
    n = len(calendar)

    write_calendar(out, calendar)

    pairs_to_range: dict[str, tuple[dt.date, dt.date]] = {sym: (calendar[0], calendar[-1]) for sym in ALL_PAIRS}
    write_instruments(out, pairs_to_range)

    # Build each pair
    pairs: dict[str, PairEntry] = {}
    for sym in ALL_PAIRS:
        # Distinct seed per symbol so they produce different series
        seed = sum(ord(c) * (i + 1) for i, c in enumerate(sym))
        rng = np.random.default_rng(seed)
        # Base price: roughly realistic
        base_price = rng.uniform(0.01, 60_000.0)
        data = _gen_ohlcv(rng, n, float(base_price))

        fields: dict[str, FieldEntry] = {}
        for field in FIELDS:
            bin_rel = f"features/{sym.lower()}/{field}.day.bin"
            bin_path = out / bin_rel
            write_bin(bin_path, data[field], start_index=0)
            fields[field] = FieldEntry(
                bin=bin_rel,
                sha256=compute_sha256(bin_path),
                updated_at=_FIXED_UPDATED_AT,
            )

        base_asset, quote_asset = _split_pair(sym)
        pairs[sym] = PairEntry(
            base_asset=base_asset,
            quote_asset=quote_asset,
            intervals={
                "1d": PairIntervalEntry(
                    from_date=calendar[0].isoformat(),
                    to_date=calendar[-1].isoformat(),
                    rows=n,
                    fields=fields,
                )
            },
        )

    now = _FIXED_UPDATED_AT
    index = IndexData(
        schema_version=SCHEMA_VERSION,
        updated_at=now,
        calendar=CalendarEntry(
            freq="day",
            from_date=calendar[0].isoformat(),
            to_date=calendar[-1].isoformat(),
            days=n,
        ),
        pairs=pairs,
        other_files={
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(out / "calendars" / "day.txt"),
                updated_at=now,
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(out / "instruments" / "all.txt"),
                updated_at=now,
            ),
        },
    )
    save_index(out, index)

    print(f"Generated {len(ALL_PAIRS)} instruments × {n} bars ({calendar[0]}..{calendar[-1]})")
    print(f"Provider: {out}")


if __name__ == "__main__":
    main()
