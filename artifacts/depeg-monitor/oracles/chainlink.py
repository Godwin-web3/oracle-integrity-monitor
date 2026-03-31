"""
Chainlink oracle — dynamically discovers feeds from Chainlink's reference data directory.
Reads prices on-chain via Web3.py using AggregatorV3Interface.
"""
import requests
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from web3 import Web3
from .config import CHAINS

logger = logging.getLogger(__name__)
SOURCE = "chainlink"

AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Reference data directory base URL
RDD_BASE = "https://reference-data-directory.vercel.app"

# Fallback known Ethereum Mainnet feeds
FALLBACK_FEEDS = {
    "ethereum": [
        {"symbol": "BTC", "proxy": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c", "decimals": 8},
        {"symbol": "ETH", "proxy": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", "decimals": 8},
        {"symbol": "LINK", "proxy": "0x2c1d072e956AFFC0D435Cb7AC308d97e0fab2Dd0", "decimals": 8},
        {"symbol": "USDT", "proxy": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D", "decimals": 8},
        {"symbol": "USDC", "proxy": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6", "decimals": 8},
        {"symbol": "DAI", "proxy": "0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9", "decimals": 8},
        {"symbol": "AVAX", "proxy": "0xFF3EEb22B5E3dE6e705b44749C2559d704923FD7", "decimals": 8},
        {"symbol": "BNB", "proxy": "0x14e613AC84a31f709eadbEF3bf98585AD3087BD0", "decimals": 8},
        {"symbol": "MATIC", "proxy": "0x7bAC85A8a13A4BcD8abb3eB7d6b4d632c895a1d7", "decimals": 8},
        {"symbol": "SOL", "proxy": "0x4ffC43a60e009B551865A93d232E33Fce9f01507", "decimals": 8},
        {"symbol": "ARB", "proxy": "0x31697852a68433DbCe2aE3ae5e970b0d7bc7d4e0", "decimals": 8},
        {"symbol": "OP", "proxy": "0x6B8d74CCA0095671B5c9F44D20fB9Fa42b5c1a61", "decimals": 8},
        {"symbol": "FRAX", "proxy": "0xB9E1E3A9feFf48998E45Fa90847ed4D467E8BcfD", "decimals": 8},
        {"symbol": "TUSD", "proxy": "0xec746eCF986E2927Abd291a2A1716c940100f8Ba", "decimals": 8},
    ]
}

# Cache: chain → list of feed dicts
_feed_cache: dict[str, list[dict]] = {}
_feed_cache_ts: dict[str, float] = {}
_FEED_TTL = 3600  # 1 hour

# Web3 connections
_web3_cache: dict[str, Web3] = {}

# Price cache per chain
_price_cache: dict[str, dict[str, float | None]] = {}
_price_cache_ts: dict[str, float] = {}
_PRICE_TTL = 60


def _get_web3(chain_key: str) -> Web3 | None:
    if chain_key in _web3_cache:
        return _web3_cache[chain_key]
    rpc = CHAINS.get(chain_key, {}).get("rpc")
    if not rpc:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 8}))
        _web3_cache[chain_key] = w3
        return w3
    except Exception as e:
        logger.error(f"Web3 connection to {chain_key}: {e}")
        return None


def _fetch_feed_list(chain_key: str) -> list[dict]:
    """Fetch feed list from Chainlink reference data directory."""
    net = CHAINS.get(chain_key, {}).get("chainlink_net")
    if not net:
        return []

    if (
        chain_key in _feed_cache
        and time.time() - _feed_cache_ts.get(chain_key, 0) < _FEED_TTL
    ):
        return _feed_cache[chain_key]

    # Try reference data directory
    try:
        url = f"{RDD_BASE}/feeds-{net}.json"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        raw_feeds = r.json()
        feeds = []
        for f in raw_feeds:
            proxy = f.get("proxyAddress") or f.get("contractAddress")
            if not proxy:
                continue
            pair = f.get("pair", [])
            if len(pair) >= 2:
                sym = pair[0].upper()
                quote = pair[1].upper()
                if quote != "USD":
                    continue  # Only USD-quoted feeds
            else:
                name = f.get("name", "")
                if "/" not in name:
                    continue
                parts = name.split(" / ")
                sym = parts[0].strip().upper()
                quote = parts[1].strip().upper() if len(parts) > 1 else ""
                if quote != "USD":
                    continue
            feeds.append({
                "symbol": sym,
                "proxy": proxy,
                "decimals": f.get("decimals", 8),
                "name": f.get("name", f"{sym}/USD"),
                "heartbeat": f.get("heartbeat", 3600),
            })
        _feed_cache[chain_key] = feeds
        _feed_cache_ts[chain_key] = time.time()
        logger.info(f"Chainlink {chain_key}: loaded {len(feeds)} USD feeds from RDD")
        return feeds
    except Exception as e:
        logger.warning(f"Chainlink RDD fetch failed for {chain_key}: {e}")

    # Fall back to hardcoded
    fallback = FALLBACK_FEEDS.get(chain_key, [])
    _feed_cache[chain_key] = fallback
    _feed_cache_ts[chain_key] = time.time()
    return fallback


def _read_price(w3: Web3, proxy_addr: str, decimals: int = 8) -> float | None:
    """Read price from an AggregatorV3 proxy contract."""
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(proxy_addr),
            abi=AGGREGATOR_ABI,
        )
        data = contract.functions.latestRoundData().call()
        answer = data[1]
        if answer <= 0:
            return None
        return float(answer) / (10 ** decimals)
    except Exception:
        return None


def fetch_chain_prices(chain_key: str) -> dict[str, float | None]:
    """Fetch all USD prices for a given chain."""
    if (
        chain_key in _price_cache
        and time.time() - _price_cache_ts.get(chain_key, 0) < _PRICE_TTL
    ):
        return dict(_price_cache[chain_key])

    feeds = _fetch_feed_list(chain_key)
    if not feeds:
        return {}

    w3 = _get_web3(chain_key)
    if not w3:
        return {}

    results: dict[str, float | None] = {}

    def read_one(feed: dict):
        price = _read_price(w3, feed["proxy"], feed.get("decimals", 8))
        return feed["symbol"], price

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(read_one, f): f for f in feeds[:50]}
        for fut in as_completed(futures, timeout=20):
            try:
                sym, price = fut.result()
                results[sym] = price
            except Exception:
                pass

    _price_cache[chain_key] = results
    _price_cache_ts[chain_key] = time.time()
    return dict(results)


def fetch_prices(symbols: list[str] | None = None) -> dict[str, float | None]:
    """Fetch Chainlink prices across all supported chains, merged by symbol."""
    merged: dict[str, float | None] = {}

    for chain_key in CHAINS:
        if CHAINS[chain_key].get("pyth_only") or not CHAINS[chain_key].get("chainlink_net"):
            continue
        try:
            chain_prices = fetch_chain_prices(chain_key)
            for sym, price in chain_prices.items():
                if price is not None and sym not in merged:
                    merged[sym] = price
        except Exception as e:
            logger.error(f"Chainlink {chain_key} error: {e}")

    if symbols:
        return {s: merged.get(s) for s in symbols}
    return merged


def get_chain_feeds(chain_key: str) -> list[dict]:
    return _fetch_feed_list(chain_key)


def get_all_supported_chains() -> list[str]:
    return [k for k, v in CHAINS.items() if v.get("chainlink_net") and not v.get("pyth_only")]
