"""
Shared configuration: chains, coin mappings, RPC endpoints.
"""

CHAINS = {
    "ethereum": {
        "name": "Ethereum",
        "chain_id": 1,
        "rpc": "https://eth.llamarpc.com",
        "chainlink_net": "mainnet",
        "color": "#627EEA",
        "native": "ETH",
    },
    "bsc": {
        "name": "BNB Chain",
        "chain_id": 56,
        "rpc": "https://bsc-dataseed1.defibit.io",
        "chainlink_net": "bsc-mainnet",
        "color": "#F0B90B",
        "native": "BNB",
    },
    "polygon": {
        "name": "Polygon",
        "chain_id": 137,
        "rpc": "https://polygon-rpc.com",
        "chainlink_net": "polygon-mainnet",
        "color": "#8247E5",
        "native": "MATIC",
    },
    "avalanche": {
        "name": "Avalanche",
        "chain_id": 43114,
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "chainlink_net": "avalanche-mainnet",
        "color": "#E84142",
        "native": "AVAX",
    },
    "arbitrum": {
        "name": "Arbitrum",
        "chain_id": 42161,
        "rpc": "https://arb1.arbitrum.io/rpc",
        "chainlink_net": "arbitrum-mainnet",
        "color": "#28A0F0",
        "native": "ETH",
    },
    "optimism": {
        "name": "Optimism",
        "chain_id": 10,
        "rpc": "https://mainnet.optimism.io",
        "chainlink_net": "optimism-mainnet",
        "color": "#FF0420",
        "native": "ETH",
    },
    "base": {
        "name": "Base",
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "chainlink_net": "base-mainnet",
        "color": "#0052FF",
        "native": "ETH",
    },
    "fantom": {
        "name": "Fantom",
        "chain_id": 250,
        "rpc": "https://rpc.ankr.com/fantom",
        "chainlink_net": "fantom-mainnet",
        "color": "#1969FF",
        "native": "FTM",
    },
    "celo": {
        "name": "Celo",
        "chain_id": 42220,
        "rpc": "https://forno.celo.org",
        "chainlink_net": "celo-mainnet",
        "color": "#35D07F",
        "native": "CELO",
    },
    "gnosis": {
        "name": "Gnosis",
        "chain_id": 100,
        "rpc": "https://rpc.gnosischain.com",
        "chainlink_net": None,
        "color": "#04795B",
        "native": "xDAI",
    },
    "solana": {
        "name": "Solana",
        "chain_id": None,
        "rpc": None,
        "chainlink_net": None,
        "color": "#9945FF",
        "native": "SOL",
        "pyth_only": True,
    },
}

# CoinGecko coin IDs
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SEI": "sei-network",
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "FRAX": "frax",
    "PYUSD": "paypal-usd",
    "TUSD": "true-usd",
    "cNGN": "cngn",
    "bNGN": "binance-ngn",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "FTM": "fantom",
}

# Binance trading pairs (symbol → USDT pair)
BINANCE_PAIRS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "SOL": "SOLUSDT",
    "AVAX": "AVAXUSDT",
    "MATIC": "MATICUSDT",
    "ARB": "ARBUSDT",
    "OP": "OPUSDT",
    "SEI": "SEIUSDT",
    "USDC": "USDCUSDT",
    "DAI": "DAIUSDT",
    "FRAX": "FRAXUSDT",
    "TUSD": "TUSDUSDT",
    "LINK": "LINKUSDT",
    "UNI": "UNIUSDT",
    "AAVE": "AAVEUSDT",
    "FTM": "FTMUSDT",
}

# Pyth price feed IDs (canonical USD feeds)
PYTH_FEED_IDS = {
    "BTC": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "BNB": "0x2f95862b045670cd22bee3114c39763a4a08beeb663b145d283c31d7d1101c4f",
    "SOL": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "AVAX": "0x93da3352f9f1d105fdfe4971cfa80e9dd777bfc5d0f683ebb98162d55d7e8a3e",
    "MATIC": "0x5de33a9112c2b700b8d30b8a3402c103578ccfa2765696471cc672bd5cf6ac52",
    "ARB": "0x3fa4252848f9f0a1480be62745a4629d9eb1322aebab8a791e344b3b9c1adcf5",
    "OP": "0x385f64d993f7b77d8182ed5003d97c60aa3361f3cecfe711544d2d59165e9bdf",
    "SEI": "0x53614f1cb0c031d4af66c04cb9c756234adad0e1cee85303795091499a4084eb",
    "USDT": "0x2b89b9dc8fdf9f34709a5b106b472f0f39bb6ca9ce04b0fd7f2e971688e2e53b",
    "USDC": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
    "DAI": "0xb0948a5e5313200c632b51bb5ca32f6de0d36e9950a942d19751e833f70dabfd",
    "FRAX": "0xfaa28c91c80f6835ea1e50f5a8e6b4bd1adef86ae4a83a83421a91bfcd53a42c",
    "PYUSD": "0xc1da1b73d7f01e7ddd54b3766cf7fcd644395ad14f70aa706ec5384c59e76692",
    "LINK": "0x8ac0c70fff57e9aefdf5edf44b51d62c2d433653cbb2cf5cc06bb115af04d221",
    "TUSD": "0x1a3344f52946bcd999b3b72a5b8eb0083c24d63ac35ed5e36f3fb38dac863b11",
}

# Stablecoins with $1 peg target
STABLECOIN_SYMBOLS = {
    "USDT", "USDC", "DAI", "FRAX", "PYUSD", "TUSD", "cNGN", "bNGN", "BUSD", "USDD"
}

# Default disagreement threshold (0.5%)
DEFAULT_DISAGREEMENT_THRESHOLD = 0.005
DEFAULT_DEPEG_THRESHOLD = 0.01
