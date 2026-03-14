from __future__ import annotations
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

def krw_tick_unit(price: Decimal) -> Decimal:
    p = price
    # 업비트 최신 원화마켓 호가 단위 (2024 기준)
    if p >= Decimal("2000000"): return Decimal("1000")
    if p >= Decimal("1000000"): return Decimal("500")
    if p >= Decimal("500000"):  return Decimal("100")
    if p >= Decimal("100000"):  return Decimal("50")
    if p >= Decimal("10000"):   return Decimal("10")
    if p >= Decimal("1000"):    return Decimal("1")
    if p >= Decimal("100"):     return Decimal("1")
    if p >= Decimal("10"):      return Decimal("0.1")
    if p >= Decimal("1"):       return Decimal("0.01")
    if p >= Decimal("0.1"):     return Decimal("0.001")
    if p >= Decimal("0.01"):    return Decimal("0.0001")
    if p >= Decimal("0.001"):   return Decimal("0.00001")
    if p >= Decimal("0.0001"):  return Decimal("0.000001")
    return Decimal("0.0000001")

def round_to_tick(price: float, up: bool = False) -> str:
    p = Decimal(str(price))
    tick = krw_tick_unit(p)
    if up:
        res = (p / tick).quantize(Decimal("1"), rounding=ROUND_CEILING) * tick
    else:
        res = (p / tick).quantize(Decimal("1"), rounding=ROUND_FLOOR) * tick
    
    res_str = f"{res:f}"
    if "." in res_str:
        res_str = res_str.rstrip("0").rstrip(".")
    return res_str