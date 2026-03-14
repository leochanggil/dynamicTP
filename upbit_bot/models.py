from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

def now_kst() -> datetime:
    return datetime.now(tz=KST)

def iso_to_kst(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str)
    return dt.replace(tzinfo=KST)

def trade_ts_to_minute_kst(ts_ms: int) -> datetime:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(KST)
    return dt.replace(second=0, microsecond=0)

@dataclass
class Candle1m:
    minute: datetime
    open: float
    close: float
    total_amt: float

@dataclass
class Position:
    market: str
    entry: float
    volume: float
    tp: float
    sl: float
    tp_uuid: str | None
    opened_at: datetime
    trailing_active: bool = False  # [추가] 매도세 감시 모드 켜짐 여부