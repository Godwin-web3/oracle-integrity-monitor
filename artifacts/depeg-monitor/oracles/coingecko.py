"""CoinGecko oracle — REST API, no key required."""
import requests
import logging
import time
from .config import COINGECKO_IDS

logger = logging.getLogger(__name__)

BASE = "https://api.coingecko.com/api/v3"
SOURCE = "coingecko"

_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 90  # seconds


def fetch_prices(symbols: list[str] | None = None) -> dict[str, float | None]:
    global _cache, _cache_ts
    now = time.time()

    if now - _cache_ts < _CACHE_TTL and _cache:
        if symbols is None:
            return dict(_cache)
        return {s: _cache.get(s) for s in symbols}

    ids_needed = list(COINGECKO_IDS.values()) if symbols is None else [
        COINGECKO_IDS[s] for s in symbols if s in COINGECKO_IDS
    ]
    if not ids_needed:
        return {}

    ids_str = ",".join(set(ids_needed))
    try:
        r = requests.get(
            f"{BASE}/simple/price",
            params={"ids": ids_str, "vs_currencies": "usd"},
            timeout=12,
        )
        r.raise_for_status()
        raw = r.json()

        id_to_symbol = {v: k for k, v in COINGECKO_IDS.items()}
        result: dict[str, float | None] = {}
        for cg_id, data in raw.items():
            sym = id_to_symbol.get(cg_id)
            if sym:
                result[sym] = data.get("usd")

        _cache = result
        _cache_ts = now
        return {s: result.get(s) for s in symbols} if symbols else result

    except Exception as e:
        logger.error(f"CoinGecko fetch error: {e}")
        return {s: _cache.get(s) for s in (symbols or list(COINGECKO_IDS))}


def search(query: str) -> list[dict]:
    """Search CoinGecko for a coin by name or symbol."""
    try:
        r = requests.get(f"{BASE}/search", params={"query": query}, timeout=10)
        r.raise_for_status()
        coins = r.json().get("coins", [])[:10]
        results = []
        for c in coins:
            results.append({
                "id": c.get("id"),
                "symbol": c.get("symbol", "").upper(),
                "name": c.get("name"),
                "thumb": c.get("thumb"),
                "source": SOURCE,
            })
        return results
    except Exception as e:
        logger.error(f"CoinGecko search error: {e}")
        return []


def get_price_for_id(cg_id: str) -> float | None:
    """Fetch price for a specific CoinGecko ID."""
    try:
        r = requests.get(
            f"{BASE}/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get(cg_id, {}).get("usd")
    except Exception as e:
        logger.error(f"CoinGecko price for {cg_id}: {e}")
        return None
