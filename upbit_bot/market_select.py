from __future__ import annotations
from .rest_client import UpbitREST

async def select_krw_markets(rest: UpbitREST, top_n: int) -> list[str]:
    allm = await rest.markets_all()
    krw = [x["market"] for x in allm if x["market"].startswith("KRW-")]
    if top_n <= 0 or top_n >= len(krw):
        return krw

    ticks = await rest.tickers(krw)
    ticks.sort(key=lambda x: float(x.get("acc_trade_price_24h", 0.0)), reverse=True)
    return [t["market"] for t in ticks[:top_n]]