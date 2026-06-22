from __future__ import annotations

BASE_URL = "https://data.binance.vision"
EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "trades",
    "taker_buy_base",
    "taker_buy_amount",
    "vwap",
    "factor",
)

# Derivatives fields sourced from Binance futures archives (daily-keyed, spot↔perp map).
# Written as separate .day.bin files alongside FIELDS and funding.day.bin.
# NaN where a coin has no perp or before its perp launch.
DERIVATIVES_FIELDS: tuple[str, ...] = (
    "oi",
    "oi_value",
    "ls_top",
    "ls_global",
    "taker_ratio",
    "basis",
)

SUPPORTED_INTERVALS = frozenset({"1d"})
SNAPSHOT_KEEP = 7
SCHEMA_VERSION = 2
