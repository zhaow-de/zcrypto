"""Keyless Coin Metrics BTC on-chain fetcher and NVM cache builder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import urllib3
import urllib3.exceptions

_BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
_METRICS = "CapMrktCurUSD,AdrActCnt"
_TIMEOUT = 30.0
_ATTEMPTS = 3

# Module-level pool; mirrors cli/data/binance.py pattern.
_pool = urllib3.PoolManager(num_pools=2, maxsize=4, retries=False)


def fetch_btc_onchain(start: str, end: str | None = None) -> pd.DataFrame:
    """Paginated GET to Coin Metrics community API; returns date-indexed DataFrame.

    Columns: ``market_cap`` (float64), ``active_addr`` (float64).
    Index: UTC-normalized DatetimeIndex.

    Parameters
    ----------
    start:
        ISO date string for start_time query param (e.g. ``"2019-01-01"``).
    end:
        ISO date string for end_time query param; omit to fetch through today.
    """
    params: dict[str, str] = {
        "assets": "btc",
        "metrics": _METRICS,
        "frequency": "1d",
        "start_time": start,
    }
    if end is not None:
        params["end_time"] = end

    rows: list[dict] = []
    while True:
        # Build URL with query string.
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{_BASE_URL}?{qs}"

        resp = _retryable_get(url)
        payload = json.loads(resp.data)
        page_rows = payload.get("data", [])
        rows.extend(page_rows)

        next_token = payload.get("next_page_token")
        if not next_token:
            break
        params["next_page_token"] = next_token

    if not rows:
        return pd.DataFrame(columns=["market_cap", "active_addr"])

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["time"], utc=True).dt.normalize()
    df.index.name = "date"
    df["market_cap"] = pd.to_numeric(df["CapMrktCurUSD"], errors="coerce").astype("float64")
    df["active_addr"] = pd.to_numeric(df["AdrActCnt"], errors="coerce").astype("float64")
    return df[["market_cap", "active_addr"]]


def build_btc_nvm_cache(
    path: str = "data/onchain/btc_nvm.parquet",
    start: str = "2019-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch BTC on-chain data, compute NVM, and write a date-indexed parquet.

    ``NVM = log(market_cap / active_addr²)``. Non-finite values (zero or negative
    addresses) are replaced with NaN.

    Parameters
    ----------
    path:
        Output parquet path. Parent directory is created if necessary.
    start:
        Earliest date to fetch (ISO date string).
    end:
        Latest date to fetch; omit to fetch through today.

    Returns
    -------
    DataFrame with a single ``nvm`` column and a UTC-normalized DatetimeIndex.
    """
    df = fetch_btc_onchain(start, end)
    raw = np.log(df["market_cap"] / df["active_addr"] ** 2)
    df["nvm"] = np.where(np.isfinite(raw), raw, np.nan)

    out = df[["nvm"]]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p)
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _retryable_get(url: str) -> urllib3.BaseHTTPResponse:
    """GET ``url`` with timeout + retry on transient failures.

    Mirrors the retry discipline in ``cli/data/binance.py``: retry on urllib3
    connection/timeout exceptions and 5xx responses; raise immediately on 4xx.
    """
    import time

    last_exc: BaseException | None = None
    for attempt in range(_ATTEMPTS):
        try:
            resp = _pool.request("GET", url, timeout=_TIMEOUT)
            if 200 <= resp.status < 300:
                return resp
            if 400 <= resp.status < 500:
                raise urllib3.exceptions.HTTPError(f"HTTP {resp.status} on {url}")
            # 5xx — will retry
            last_exc = urllib3.exceptions.HTTPError(f"HTTP {resp.status} on {url}")
        except urllib3.exceptions.HTTPError:
            raise
        except (urllib3.exceptions.RequestError, OSError, TimeoutError) as e:
            last_exc = e
        if attempt < _ATTEMPTS - 1:
            time.sleep(1.0 * (2**attempt))
    raise last_exc  # type: ignore[misc]
