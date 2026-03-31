"""Binance public API oracle — no API key required."""
import requests
import logging
import time
from .config import BINANCE_PAIRS

logger = logging.getLogger(__name__)

BASE = "https://api.binance.com/api/v3"
SOURCE = "binance"

_all_tickers: dict[str, float] = {}
_tickers_ts: float = 0
_CACHE_TTL = 60  # seconds


def _refresh_all_tickers():
    global _all_tickers, _tickers_ts
    try:
        r = requests.get(f"{BASE}/ticker/price", timeout=12)
        r.raise_for_status()
        data = r.json()
        _all_tickers = {item["symbol"]: float(item["price"]) for item in data}
        _tickers_ts = time.time()
    except Exception as e:
        logger.error(f"Binance ticker refresh error: {e}")


def _ensure_fresh():
    if time.time() - _tickers_ts > _CACHE_TTL:
        _refresh_all_tickers()


def fetch_prices(symbols: list[str] | None = None) -> dict[str, float | None]:
    _ensure_fresh()
    target = symbols or list(BINANCE_PAIRS.keys())
    result: dict[str, float | None] = {}

    for sym in target:
        pair = BINANCE_PAIRS.get(sym)
        if not pair:
            result[sym] = None
            continue
        price = _all_tickers.get(pair)
        if price is not None:
            # For stablecoin/USDT pairs (e.g. USDCUSDT), price is in USDT ≈ USD
            result[sym] = price
        else:
            result[sym] = None

    return result


def search(query: str) -> list[dict]:
    """Search Binance for trading pairs matching the query."""
    _ensure_fresh()
    query_upper = query.upper()
    results = []
    seen = set()
    for symbol in _all_tickers:
        if query_upper in symbol and symbol.endswith("USDT"):
            base = symbol[: -4]  # strip USDT
            if base not in seen:
                seen.add(base)
                results.append({
                    "symbol": base,
                    "pair": symbol,
                    "price": _all_tickers[symbol],
                    "source": SOURCE,
                })
            if len(results) >= 15:
                break
    return results


def get_price_for_pair(pair: str) -> float | None:
    """Get price for a specific Binance pair like BTCUSDT."""
    _ensure_fresh()
    return _all_tickers.get(pair)


def get_all_usdt_pairs() -> dict[str, float]:
    """Return all USDT-quoted pairs as {base_symbol: price}."""
    _ensure_fresh()
    return {
        sym[:-4]: price
        for sym, price in _all_tickers.items()
        if sym.endswith("USDT") and len(sym) > 4
    }
