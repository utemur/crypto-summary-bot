import requests
from datetime import datetime, timezone

BASE_URL = "https://api.coingecko.com/api/v3"
HEADERS = {"User-Agent": "CryptoSummaryBot/1.0 (+https://t.me/your_bot_name)"}


def _get(url: str, params: dict | None = None) -> dict:
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"CoinGecko fetch failed → {e}")


def get_top_coins(limit: int = 10, currency: str = "usd") -> list[dict]:
    params = {
        "vs_currency": currency,
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "price_change_percentage": "24h",
    }
    return _get(f"{BASE_URL}/coins/markets", params)


def get_global_market(currency: str = "usd") -> dict:
    raw = _get(f"{BASE_URL}/global", {"vs_currency": currency})
    return raw.get("data", {})


def get_market_summary(limit: int = 10, currency: str = "usd") -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    g = get_global_market(currency)
    total = f"${g.get('total_market_cap', {}).get(currency, 0):,.0f}"
    change = g.get("market_cap_change_percentage_24h_usd", 0)
    btc_dom = g.get("market_cap_percentage", {}).get("btc", 0)

    lines = [
        f"{now}",
        f"Global cap: {total} ({change:+.1f} %) | BTC dom: {btc_dom:.1f} %",
    ]
    for idx, coin in enumerate(get_top_coins(limit, currency), start=1):
        price = f"${coin['current_price']:,.0f}"
        chg = f"{coin['price_change_percentage_24h']:+.1f} %"
        mc = f"${coin['market_cap']:,.0f}"
        lines.append(f"{idx}. {coin['symbol'].upper():<4} {price:<9} ({chg}) mc:{mc}")
    return "\n".join(lines)


def get_top_gainers_losers(
    limit: int = 5, currency: str = "usd"
) -> tuple[list[dict], list[dict]]:
    data = _get(
        f"{BASE_URL}/coins/markets",
        {
            "vs_currency": currency,
            "order": "market_cap_desc",
            "per_page": 250,
            "price_change_percentage": "24h",
        },
    )
    sorted_ = sorted(
        data, key=lambda c: c["price_change_percentage_24h"] or 0, reverse=True
    )
    return sorted_[:limit], sorted_[-limit:][::-1]


def lookup_coin(symbol: str, currency: str = "usd") -> dict | None:
    res = _get(
        f"{BASE_URL}/coins/markets",
        {
            "vs_currency": currency,
            "ids": symbol.lower(),
            "order": "market_cap_desc",
            "per_page": 1,
        },
    )
    if res:
        return res[0]
    data = _get(
        f"{BASE_URL}/coins/markets",
        {"vs_currency": currency, "order": "market_cap_desc", "per_page": 250},
    )
    symbol = symbol.lower()
    for coin in data:
        if coin["symbol"].lower() == symbol:
            return coin
    return None


def get_coin_price(symbol: str, currency: str = "usd") -> float | None:
    """Получает текущую цену монеты по символу"""
    coin = lookup_coin(symbol, currency)
    if coin:
        return coin["current_price"]
    return None


def check_alerts(alerts: list[dict]) -> list[dict]:
    """Проверяет уведомления и возвращает сработавшие"""
    triggered = []
    
    for alert in alerts:
        current_price = get_coin_price(alert["coin"])
        if current_price is None:
            continue
            
        target = alert["target"]
        above = alert["above"]
        
        # Проверяем условие уведомления
        if above and current_price >= target:  # Цена выше или равна цели
            triggered.append(alert)
        elif not above and current_price <= target:  # Цена ниже или равна цели
            triggered.append(alert)
    
    return triggered