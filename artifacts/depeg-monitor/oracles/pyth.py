"""
Pyth Network oracle via Hermes REST API.
Dynamically discovers all price feeds — no hardcoding required.
"""
import requests
import logging
import time
from .config import PYTH_FEED_IDS

logger = logging.getLogger(__name__)

HERMES = "https://hermes.pyth.network"
SOURCE = "pyth"
BATCH_SIZE = 100

# Feed registry cache
_feeds: list[dict] = []       # [{id, symbol, name, ...}]
_feeds_ts: float = 0
_FEED_TTL = 1800               # refresh feed list every 30 min

# Price cache
_prices: dict[str, float] = {}  # feed_id → price
_prices_by_sym: dict[str, float] = {}  # symbol → price
_prices_ts: float = 0
_PRICE_TTL = 60


def _refresh_feeds():
    global _feeds, _feeds_ts
    try:
        r = requests.get(f"{HERMES}/v2/price_feeds", timeout=20)
        r.raise_for_status()
        raw = r.json()
        parsed = []
        for item in raw:
            attrs = item.get("attributes", {})
            symbol = attrs.get("generic_symbol", "") or attrs.get("symbol", "")
            parsed.append({
                "id": item["id"],
                "symbol": symbol,
                "base": attrs.get("base", ""),
                "quote": attrs.get("quote_currency", "USD"),
                "asset_type": attrs.get("asset_type", ""),
                "name": attrs.get("description", symbol),
            })
        _feeds = parsed
        _feeds_ts = time.time()
        logger.info(f"Pyth: loaded {len(_feeds)} feeds from Hermes")
    except Exception as e:
        logger.error(f"Pyth feed refresh error: {e}")


def get_all_feeds() -> list[dict]:
    if time.time() - _feeds_ts > _FEED_TTL or not _feeds:
        _refresh_feeds()
    return list(_feeds)


def _build_id_list(symbols: list[str] | None) -> list[str]:
    """Build list of Pyth feed IDs to fetch."""
    if symbols:
        ids = []
        for s in symbols:
            fid = PYTH_FEED_IDS.get(s)
            if fid:
                ids.append(fid)
        return ids

    # Use canonical IDs + dynamically discovered crypto/USD feeds
    id_set = set(PYTH_FEED_IDS.values())
    feeds = get_all_feeds()
    for f in feeds:
        if f.get("asset_type") == "Crypto" and f.get("quote") == "USD":
            id_set.add(f["id"])
    return list(id_set)


def _refresh_prices(ids: list[str]):
    global _prices, _prices_by_sym, _prices_ts

    id_to_symbol: dict[str, str] = {}
    for sym, fid in PYTH_FEED_IDS.items():
        id_to_symbol[fid] = sym

    feeds = get_all_feeds()
    for f in feeds:
        base = f.get("base", "")
        if base and f.get("quote") == "USD":
            id_to_symbol[f["id"]] = base.upper()

    new_prices: dict[str, float] = {}
    new_by_sym: dict[str, float] = {}

    # Fetch in batches
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i: i + BATCH_SIZE]
        params = [("ids[]", fid) for fid in batch]
        try:
            r = requests.get(
                f"{HERMES}/v2/updates/price/latest",
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            parsed = r.json().get("parsed", [])
            for item in parsed:
                fid = item["id"]
                p = item.get("price", {})
                raw_price = int(p.get("price", 0))
                expo = int(p.get("expo", 0))
                if raw_price == 0:
                    continue
                price = raw_price * (10 ** expo)
                new_prices[fid] = price
                sym = id_to_symbol.get(fid)
                if sym:
                    new_by_sym[sym] = price
        except Exception as e:
            logger.error(f"Pyth price batch error: {e}")

    _prices = new_prices
    _prices_by_sym = new_by_sym
    _prices_ts = time.time()


def fetch_prices(symbols: list[str] | None = None) -> dict[str, float | None]:
    if time.time() - _prices_ts > _PRICE_TTL or not _prices:
        ids = _build_id_list(None)
        _refresh_prices(ids)

    if symbols:
        return {s: _prices_by_sym.get(s) for s in symbols}

    return dict(_prices_by_sym)


def get_all_prices() -> dict[str, float]:
    """Return all discovered Pyth prices keyed by symbol."""
    if time.time() - _prices_ts > _PRICE_TTL or not _prices:
        ids = _build_id_list(None)
        _refresh_prices(ids)
    return dict(_prices_by_sym)


def get_feed_count() -> int:
    return len(get_all_feeds())
