"""
Price aggregator — fetches from all 5 oracle sources in parallel,
computes disagreements and depeg severity scores.
"""
import logging
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import STABLECOIN_SYMBOLS, DEFAULT_DISAGREEMENT_THRESHOLD, DEFAULT_DEPEG_THRESHOLD
from . import coingecko, binance, pyth, chainlink, api3

logger = logging.getLogger(__name__)

SOURCES = {
    "coingecko": coingecko,
    "binance": binance,
    "pyth": pyth,
    "chainlink": chainlink,
    "api3": api3,
}

SOURCE_COLORS = {
    "coingecko": "#8CC63F",
    "binance": "#F0B90B",
    "pyth": "#9945FF",
    "chainlink": "#375BD2",
    "api3": "#00A3FF",
}

# Last aggregated result cache
_last_result: dict = {}
_last_result_ts: float = 0
_CACHE_TTL = 55  # slightly under 60s refresh


def _severity_score(deviation: float) -> int:
    """Return severity score 1-10 based on fractional deviation."""
    pct = deviation * 100
    if pct < 0.05:  return 1
    if pct < 0.1:   return 2
    if pct < 0.2:   return 3
    if pct < 0.5:   return 4
    if pct < 1.0:   return 5
    if pct < 2.0:   return 6
    if pct < 3.0:   return 7
    if pct < 5.0:   return 8
    if pct < 10.0:  return 9
    return 10


def _fetch_all_parallel() -> dict[str, dict[str, float | None]]:
    """Fetch prices from all sources in parallel. Returns {source: {symbol: price}}."""
    results: dict[str, dict[str, float | None]] = {}

    def fetch_source(name: str, module):
        try:
            prices = module.fetch_prices()
            return name, prices or {}
        except Exception as e:
            logger.error(f"Aggregator {name} error: {e}")
            return name, {}

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fetch_source, n, m): n for n, m in SOURCES.items()}
        for fut in as_completed(futures, timeout=40):
            try:
                name, prices = fut.result()
                results[name] = prices
            except Exception as e:
                logger.error(f"Aggregator parallel fetch error: {e}")

    return results


def aggregate() -> dict:
    """
    Main aggregation function.
    Returns:
      {
        "prices":        {symbol: {source: price, ...}},
        "consensus":     {symbol: median_price},
        "disagreements": [{symbol, prices, max_deviation, severity, leading, lagging}],
        "depeg_alerts":  [{symbol, price, peg, deviation, severity, source}],
        "by_source":     {source: {symbol: price}},
        "timestamp":     float,
      }
    """
    global _last_result, _last_result_ts
    now = time.time()
    if now - _last_result_ts < _CACHE_TTL and _last_result:
        return dict(_last_result)

    raw = _fetch_all_parallel()

    # Collect all symbols seen
    all_symbols: set[str] = set()
    for prices in raw.values():
        all_symbols.update(k for k, v in prices.items() if v is not None)

    # Build per-symbol price table
    price_table: dict[str, dict[str, float]] = {}
    for sym in all_symbols:
        sym_prices: dict[str, float] = {}
        for src, prices in raw.items():
            p = prices.get(sym)
            if p is not None and p > 0:
                sym_prices[src] = p
        if sym_prices:
            price_table[sym] = sym_prices

    # Compute consensus (median of all sources)
    consensus: dict[str, float] = {}
    for sym, prices in price_table.items():
        vals = list(prices.values())
        consensus[sym] = statistics.median(vals)

    # Detect disagreements
    disagreements: list[dict] = []
    for sym, prices in price_table.items():
        if len(prices) < 2:
            continue
        median = consensus[sym]
        deviations = {src: abs(p - median) / median for src, p in prices.items()}
        max_dev = max(deviations.values())
        if max_dev >= DEFAULT_DISAGREEMENT_THRESHOLD:
            sorted_prices = sorted(prices.items(), key=lambda x: x[1])
            leading = sorted_prices[-1][0]  # highest price source
            lagging = sorted_prices[0][0]   # lowest price source
            disagreements.append({
                "symbol": sym,
                "prices": prices,
                "median": median,
                "max_deviation": max_dev,
                "max_deviation_pct": max_dev * 100,
                "severity": _severity_score(max_dev),
                "leading": leading,
                "lagging": lagging,
                "source_deviations": {s: d * 100 for s, d in deviations.items()},
            })

    disagreements.sort(key=lambda x: x["max_deviation"], reverse=True)

    # Detect depeg events (stablecoins only)
    depeg_alerts: list[dict] = []
    for sym in STABLECOIN_SYMBOLS:
        if sym not in consensus:
            continue
        median = consensus[sym]
        peg = 1.0
        deviation = abs(median - peg) / peg
        if deviation >= DEFAULT_DEPEG_THRESHOLD:
            depeg_alerts.append({
                "symbol": sym,
                "price": median,
                "peg": peg,
                "deviation": deviation,
                "deviation_pct": deviation * 100,
                "severity": _severity_score(deviation),
                "direction": "below" if median < peg else "above",
                "sources": price_table.get(sym, {}),
            })

    result = {
        "prices": price_table,
        "consensus": consensus,
        "disagreements": disagreements,
        "depeg_alerts": depeg_alerts,
        "by_source": raw,
        "timestamp": now,
    }

    _last_result = result
    _last_result_ts = now
    return result


def get_last_result() -> dict:
    return _last_result or {}


def compare_symbol(symbol: str) -> dict | None:
    """Get full price comparison for a single symbol across all sources."""
    agg = aggregate()
    prices = agg["prices"].get(symbol.upper())
    if not prices:
        return None
    median = agg["consensus"].get(symbol.upper(), 0)
    return {
        "symbol": symbol.upper(),
        "prices": prices,
        "median": median,
        "disagreement": any(
            d["symbol"] == symbol.upper() for d in agg["disagreements"]
        ),
        "sources_available": len(prices),
    }
