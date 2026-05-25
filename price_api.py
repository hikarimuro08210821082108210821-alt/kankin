import aiohttp

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

async def get_ltc_jpy_rate() -> float:
    params = {
        "ids": "litecoin",
        "vs_currencies": "jpy"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                rate = data.get("litecoin", {}).get("jpy", 0)
                return float(rate)
    except Exception as e:
        print(f"[PRICE] レート取得エラー: {e}")
        return 0.0

def jpy_to_ltc(jpy_amount: float, rate: float, fee_percent: float = 0.0) -> float:
    if rate == 0:
        return 0.0
    ltc = jpy_amount / rate
    ltc_after_fee = ltc * (1 - fee_percent / 100)
    return round(ltc_after_fee, 8)
