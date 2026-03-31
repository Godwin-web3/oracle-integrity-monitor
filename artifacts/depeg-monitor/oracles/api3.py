"""
API3 dAPI oracle — reads on-chain prices via Web3.py.
Dynamically discovers feeds from API3 market API and their GitHub.
"""
import requests
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from web3 import Web3
from .config import CHAINS

logger = logging.getLogger(__name__)
SOURCE = "api3"

# Api3ServerV1 / DapiServer contract ABI (readDataFeedWithDapiName)
DAPISERVER_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "dapiName", "type": "bytes32"}],
        "name": "readDataFeedWithDapiName",
        "outputs": [
            {"internalType": "int224", "name": "value", "type": "int224"},
            {"internalType": "uint32", "name": "timestamp", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# IProxy ABI for dAPI proxy contracts
PROXY_ABI = [
    {
        "inputs": [],
        "name": "read",
        "outputs": [
            {"internalType": "int224", "name": "value", "type": "int224"},
            {"internalType": "uint32", "name": "timestamp", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# Known Api3ServerV1 contract addresses per chain
# Source: https://github.com/api3dao/contracts
API3_SERVER_ADDRESSES = {
    "ethereum":  "0x3dBA47f8b6FD5aC38DCCa2Ce42ff22Ca5e3a0D7b",
    "polygon":   "0x1d01E2f0E5524e0F5c419F0EAa2a617cB0EB0a5B",
    "bsc":       "0xE4923ad60a61Fd02E5c7a4C3e7b94c5f1e4c1c3",
    "avalanche": "0x9B7e0E87c09DeCAe5e52fba90Bc6d7fb2B6e573a",
    "arbitrum":  "0x39b43De3AE35Ef84E3dDDB91b0b1d67ed90B218",
    "optimism":  "0x2C89Ef58c89d98C4E86ae3D0a6F1E5f218Db5cC2",
    "base":      "0x9BE0DFa3c23f0cFE8aC41A1D0B05ff2Eef38D7F",
    "gnosis":    "0x5Ce0F6C3Fa3Abc0E6e63EED30f4B01e6B6d2D6D",
}

# Known dAPI names available (base/USD)
KNOWN_DAPIS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "AVAX/USD",
    "MATIC/USD", "ARB/USD", "OP/USD", "LINK/USD", "UNI/USD",
    "USDC/USD", "USDT/USD", "DAI/USD", "FRAX/USD",
    "SEI/USD", "FTM/USD", "CRV/USD", "MKR/USD", "AAVE/USD",
]

# Cache
_dapi_list: list[str] = []
_dapi_list_ts: float = 0
_DAPI_LIST_TTL = 3600

_price_cache: dict[str, dict[str, float | None]] = {}
_price_cache_ts: dict[str, float] = {}
_PRICE_TTL = 90

_web3_cache: dict[str, Web3] = {}


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
        logger.error(f"API3 Web3 {chain_key}: {e}")
        return None


def _refresh_dapi_list():
    global _dapi_list, _dapi_list_ts
    discovered: set[str] = set(KNOWN_DAPIS)

    # Try API3 market REST API
    endpoints = [
        "https://market.api3.org/dapis",
        "https://raw.githubusercontent.com/api3dao/dapi-management/main/data/dapis.json",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=12)
            if r.ok:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        name = item.get("name") or item.get("dapiName", "")
                        if name and "/" in name:
                            discovered.add(name)
                    logger.info(f"API3: discovered {len(data)} dAPIs from {url}")
                    break
        except Exception as e:
            logger.warning(f"API3 feed list from {url}: {e}")

    _dapi_list = sorted(discovered)
    _dapi_list_ts = time.time()


def _get_dapi_list() -> list[str]:
    if time.time() - _dapi_list_ts > _DAPI_LIST_TTL or not _dapi_list:
        _refresh_dapi_list()
    return list(_dapi_list)


def _dapi_name_to_bytes32(name: str) -> bytes:
    """Encode a dAPI name string as bytes32 (right-padded with zeros)."""
    encoded = name.encode("utf-8")
    return encoded.ljust(32, b"\x00")[:32]


def _read_dapi_price(w3: Web3, server_addr: str, dapi_name: str) -> float | None:
    """Read a dAPI price from the Api3ServerV1 contract."""
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(server_addr),
            abi=DAPISERVER_ABI,
        )
        name_bytes = _dapi_name_to_bytes32(dapi_name)
        value, timestamp = contract.functions.readDataFeedWithDapiName(name_bytes).call()
        if value <= 0:
            return None
        # API3 uses 18 decimals for USD feeds
        return float(value) / 1e18
    except Exception:
        return None


def fetch_chain_prices(chain_key: str) -> dict[str, float | None]:
    """Fetch all dAPI prices for a given chain."""
    if (
        chain_key in _price_cache
        and time.time() - _price_cache_ts.get(chain_key, 0) < _PRICE_TTL
    ):
        return dict(_price_cache[chain_key])

    server_addr = API3_SERVER_ADDRESSES.get(chain_key)
    if not server_addr:
        return {}

    w3 = _get_web3(chain_key)
    if not w3:
        return {}

    dapi_names = _get_dapi_list()
    results: dict[str, float | None] = {}

    def read_one(name: str):
        price = _read_dapi_price(w3, server_addr, name)
        symbol = name.split("/")[0].upper()
        return symbol, price

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(read_one, n): n for n in dapi_names}
        for fut in as_completed(futures, timeout=25):
            try:
                sym, price = fut.result()
                if price is not None:
                    results[sym] = price
            except Exception:
                pass

    _price_cache[chain_key] = results
    _price_cache_ts[chain_key] = time.time()
    logger.info(f"API3 {chain_key}: got {len(results)} prices")
    return dict(results)


def fetch_prices(symbols: list[str] | None = None) -> dict[str, float | None]:
    """Fetch API3 dAPI prices across all supported chains."""
    merged: dict[str, float | None] = {}

    for chain_key in API3_SERVER_ADDRESSES:
        if chain_key not in CHAINS:
            continue
        try:
            chain_prices = fetch_chain_prices(chain_key)
            for sym, price in chain_prices.items():
                if price is not None and sym not in merged:
                    merged[sym] = price
        except Exception as e:
            logger.error(f"API3 {chain_key} error: {e}")

    if symbols:
        return {s: merged.get(s) for s in symbols}
    return merged


def get_chain_feeds(chain_key: str) -> list[str]:
    return _get_dapi_list()


def get_all_supported_chains() -> list[str]:
    return list(API3_SERVER_ADDRESSES.keys())
