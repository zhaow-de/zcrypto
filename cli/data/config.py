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

SUPPORTED_INTERVALS = frozenset({"1d"})
SNAPSHOT_KEEP = 7
SCHEMA_VERSION = 1
