"""Derive buy/sell trades from a sequence of qlib position snapshots."""

from __future__ import annotations

import pandas as pd


def trades_from_positions(positions) -> pd.DataFrame:
    """Derive buy/sell trades from a positions mapping.

    positions: dict[pd.Timestamp, obj] where obj.position is a dict with symbol keys
               (and "cash", "now_account_value" non-symbol keys to skip).
               A symbol entry looks like {"amount": float, "price": float}.
    """
    COLS = ["date", "side", "symbol", "qty", "price", "value"]
    if not positions:
        return pd.DataFrame(columns=COLS)

    rows = []
    prev_holdings: dict[str, dict] = {}  # symbol -> {"amount": float, "price": float}

    for date in sorted(positions.keys()):
        day_position = positions[date].position
        # Extract current holdings (skip non-symbol keys)
        curr_holdings: dict[str, dict] = {}
        for k, v in day_position.items():
            if isinstance(v, dict) and "amount" in v:
                curr_holdings[k] = v

        # All symbols seen either today or yesterday
        all_symbols = set(prev_holdings) | set(curr_holdings)

        for symbol in sorted(all_symbols):
            prev_amount = prev_holdings[symbol]["amount"] if symbol in prev_holdings else 0.0
            curr_amount = curr_holdings[symbol]["amount"] if symbol in curr_holdings else 0.0
            delta = curr_amount - prev_amount

            if abs(delta) <= 1e-12:
                continue

            # Price: today's price if available, else prior day's price
            if symbol in curr_holdings and "price" in curr_holdings[symbol]:
                price = curr_holdings[symbol]["price"]
            elif symbol in prev_holdings and "price" in prev_holdings[symbol]:
                price = prev_holdings[symbol]["price"]
            else:
                price = float("nan")

            side = "buy" if delta > 0 else "sell"
            qty = abs(delta)
            value = qty * price
            rows.append({"date": date, "side": side, "symbol": symbol, "qty": qty, "price": price, "value": value})

        prev_holdings = curr_holdings

    df = pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


def trade_summary(trades: pd.DataFrame) -> dict:
    """Summarize a trades DataFrame."""
    if trades.empty:
        return {"total": 0, "buys": 0, "sells": 0, "turnover": 0.0, "per_symbol": {}}
    return {
        "total": len(trades),
        "buys": int((trades["side"] == "buy").sum()),
        "sells": int((trades["side"] == "sell").sum()),
        "turnover": float(trades["value"].sum()),
        "per_symbol": trades.groupby("symbol").size().to_dict(),
    }
