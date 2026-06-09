"""Shared, non-test helpers for cli/data tests. Imported explicitly by tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile


def synthetic_kline_csv(date: dt.date, *, base_price: float = 100.0, base_vol: float = 50.0) -> str:
    """One Binance-shaped 12-column 1d kline CSV row for the given UTC date."""
    open_ms = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    open_ = base_price
    close = base_price * 1.01
    high = close * 1.02
    low = open_ * 0.98
    volume = base_vol
    quote_volume = volume * (open_ + close) / 2.0
    trades = 100
    taker_buy_base = volume * 0.5
    taker_buy_quote = quote_volume * 0.5
    return (
        f"{open_ms},{open_},{high},{low},{close},{volume},{close_ms},{quote_volume},{trades},{taker_buy_base},{taker_buy_quote},0\n"
    )


def make_zip_with_checksum(csv_text: str, inner_name: str) -> tuple[bytes, str]:
    """Pack csv_text into a zip with inner_name; return (zip_bytes, sha256_hex)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    zip_bytes = buf.getvalue()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest()
