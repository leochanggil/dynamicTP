from __future__ import annotations
from collections import defaultdict, deque
from datetime import datetime

from .models import Candle1m, Position

class State:
    def __init__(self):
        self.buy_amt = defaultdict(lambda: defaultdict(float))
        self.prev5 = defaultdict(lambda: deque(maxlen=5))
        self.last_candle: dict[str, Candle1m] = {}
        self.last_price: dict[str, float] = {}
        self.positions: dict[str, Position] = {}
        self.cooldown_until: dict[str, datetime] = {}
        self.short_ticks = defaultdict(lambda: deque(maxlen=2000))
        self.waiting_pullback: dict[str, datetime] = {}  # 눌림목 대기 명단

    def add_buy(self, market: str, minute: datetime, krw: float) -> None:
        self.buy_amt[market][minute] += krw
        if len(self.buy_amt[market]) > 30:
            keys = sorted(self.buy_amt[market].keys())
            for k in keys[:-30]:
                self.buy_amt[market].pop(k, None)

    def set_last_price(self, market: str, px: float) -> None:
        self.last_price[market] = px

    # [추가] 실시간 틱 데이터 저장 및 오래된 데이터 버리기
    def add_short_tick(self, market: str, ts: float, ask_bid: str, krw: float, keep_sec: int) -> None:
        q = self.short_ticks[market]
        q.append((ts, ask_bid, krw))
        cutoff = ts - keep_sec
        while q and q[0][0] < cutoff:
            q.popleft()

    # [추가] 최근 N초 동안의 매수 대금 vs 매도 대금 계산
    def get_short_volume(self, market: str) -> tuple[float, float]:
        buy_vol = sum(krw for t, ab, krw in self.short_ticks[market] if ab == "BID")
        sell_vol = sum(krw for t, ab, krw in self.short_ticks[market] if ab == "ASK")
        return buy_vol, sell_vol