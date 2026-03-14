from __future__ import annotations
import asyncio, json, uuid
import websockets

WS_URL = "wss://api.upbit.com/websocket/v1"

class UpbitWSClient:
    def __init__(self, markets: list[str], logger):
        self.markets = markets
        self.log = logger

    async def run(self, on_trade, on_candle) -> None:
        backoff = 1.0
        while True:
            try:
                await self._run_once(on_trade, on_candle)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception(f"[WS_ERR] {e} (reconnect in {backoff}s)")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _run_once(self, on_trade, on_candle) -> None:
        ticket = str(uuid.uuid4())
        req = [
            {"ticket": ticket},
            {"type": "trade", "codes": self.markets, "isOnlyRealtime": True},
            {"type": "candle.1m", "codes": self.markets, "isOnlyRealtime": True},
            {"format": "DEFAULT"},
        ]

        async with websockets.connect(
            WS_URL, ping_interval=20, ping_timeout=20, max_queue=4096
        ) as ws:
            await ws.send(json.dumps(req))
            self.log.info(f"[WS] subscribed markets={len(self.markets)}")

            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    msg = json.loads(raw.decode("utf-8"))
                    ty = msg.get("type")
                    if ty == "trade":
                        await on_trade(msg["code"], msg)
                    elif ty and ty.startswith("candle"):  # <== 수정됨!
                        await on_candle(msg["code"], msg)