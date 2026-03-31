import requests
import logging
from datetime import datetime
from database import (
    save_price, record_depeg_event, get_all_subscribers,
    get_latest_prices
)

logger = logging.getLogger(__name__)

STABLECOINS = [
    {"id": "tether",        "symbol": "USDT", "peg": 1.0},
    {"id": "usd-coin",      "symbol": "USDC", "peg": 1.0},
    {"id": "dai",           "symbol": "DAI",  "peg": 1.0},
    {"id": "frax",          "symbol": "FRAX", "peg": 1.0},
    {"id": "true-usd",      "symbol": "TUSD", "peg": 1.0},
    {"id": "paypal-usd",    "symbol": "PYUSD", "peg": 1.0},
    {"id": "cngn",          "symbol": "cNGN", "peg": None},
    {"id": "binance-ngn",   "symbol": "bNGN", "peg": None},
]

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"

_depeg_state = {}
_last_prices = {}
_fetch_error = None


def fetch_prices():
    global _fetch_error
    ids = ",".join(c["id"] for c in STABLECOINS)
    try:
        resp = requests.get(
            COINGECKO_API,
            params={"ids": ids, "vs_currencies": "usd"},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        _fetch_error = None
        return data
    except Exception as e:
        _fetch_error = str(e)
        logger.error(f"CoinGecko fetch error: {e}")
        return None


def get_ngn_rate():
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "tether", "vs_currencies": "ngn"},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("tether", {}).get("ngn")
    except Exception as e:
        logger.error(f"NGN rate fetch error: {e}")
        return None


def check_prices():
    global _last_prices
    data = fetch_prices()
    if not data:
        return [], None

    ngn_rate = get_ngn_rate()
    alerts = []
    results = []

    for coin in STABLECOINS:
        cid = coin["id"]
        price_usd = data.get(cid, {}).get("usd")
        if price_usd is None:
            continue

        peg = coin["peg"]

        if peg is None:
            if ngn_rate and ngn_rate > 0:
                peg = 1.0 / ngn_rate
            else:
                peg = price_usd if price_usd else 0.0001

        deviation = abs(price_usd - peg) / peg if peg > 0 else 0
        is_depegged = deviation >= 0.01

        save_price(cid, coin["symbol"], price_usd, peg, deviation, is_depegged)

        _last_prices[cid] = {
            "id": cid,
            "symbol": coin["symbol"],
            "price": price_usd,
            "peg": peg,
            "deviation": deviation,
            "is_depegged": is_depegged,
            "checked_at": datetime.utcnow().isoformat(),
        }

        was_depegged = _depeg_state.get(cid, False)

        if is_depegged and not was_depegged:
            direction = "below" if price_usd < peg else "above"
            record_depeg_event(cid, coin["symbol"], price_usd, peg, deviation, direction)
            alerts.append({
                "symbol": coin["symbol"],
                "price": price_usd,
                "peg": peg,
                "deviation": deviation,
                "direction": direction,
            })
            _depeg_state[cid] = True
        elif not is_depegged:
            _depeg_state[cid] = False

        results.append(_last_prices[cid])

    return results, alerts


def get_current_prices():
    if _last_prices:
        return list(_last_prices.values())
    return get_latest_prices()


def get_fetch_error():
    return _fetch_error
