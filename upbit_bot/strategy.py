from __future__ import annotations
import asyncio
from datetime import timedelta

from .models import Candle1m, Position, now_kst, iso_to_kst, trade_ts_to_minute_kst
from .price_utils import round_to_tick
from .state import State
from .rest_client import UpbitREST
from .notifier import TelegramNotifier
from .ledger import TradeLedger


class BurstEntryStrategy:
    def __init__(self, rest: UpbitREST, st: State, notifier: TelegramNotifier, logger, all_krw_markets: list[str],
                 dry_run: bool, krw_per_trade: int, max_positions: int, cooldown_sec: int,
                 buy_pressure_th: float, vol_spike_mult: float, min_amt: float,
                 tp_pct: float, sl_pct: float, paper_mode: bool, 
                 ledger: TradeLedger, fee_rate: float, slip_rate: float, timeout_sec: int,
                 use_dynamic_tp: bool, dynamic_tp_sec: int, dynamic_tp_ratio: float, safe_tp_pct: float): # [추가]

        self.paper_mode = paper_mode
        self.ledger = ledger
        self.fee_rate = fee_rate
        self.slip_rate = slip_rate
        self._pending_entry = set()

        self.rest = rest
        self.st = st
        self.notifier = notifier
        self.log = logger

        self.dry_run = dry_run
        self.krw_per_trade = krw_per_trade
        self.max_positions = max_positions
        self.buy_pressure_th = buy_pressure_th
        self.vol_spike_mult = vol_spike_mult
        self.min_amt = min_amt
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.timeout_sec = timeout_sec
        self.cooldown_sec = cooldown_sec
        # [추가] 실험 기능 변수
        self.use_dynamic_tp = use_dynamic_tp
        self.dynamic_tp_sec = dynamic_tp_sec
        self.dynamic_tp_ratio = dynamic_tp_ratio
        self.safe_tp_pct = safe_tp_pct

        self._task = asyncio.create_task(self._tp_check_loop())
        self.all_krw_markets = all_krw_markets  # 전체 KRW 마켓 리스트 저장
        # [추가] 시장 판단 엔진 배경 실행
        asyncio.create_task(self._market_judgment_loop())


    async def on_trade(self, market: str, msg: dict) -> None:
        if msg.get("ask_bid") == "BID":
            minute = trade_ts_to_minute_kst(int(msg["trade_timestamp"]))
            krw = float(msg["trade_price"]) * float(msg["trade_volume"])
            self.st.add_buy(market, minute, krw)

        # [추가] Dynamic TP 켜져있고 보유 중인 종목이면 초단기 체결 데이터 저장
        if self.use_dynamic_tp and market in self.st.positions:
            ts = msg["trade_timestamp"] / 1000.0
            krw = float(msg["trade_price"]) * float(msg["trade_volume"])
            self.st.add_short_tick(market, ts, msg.get("ask_bid"), krw, self.dynamic_tp_sec)

        self.st.set_last_price(market, float(msg["trade_price"]))
        await self._check_stoploss(market, float(msg["trade_price"]))

    async def on_candle(self, market: str, msg: dict) -> None:
        minute = iso_to_kst(msg["candle_date_time_kst"])
        candle = Candle1m(
            minute=minute,
            open=float(msg["opening_price"]),
            close=float(msg["trade_price"]),
            total_amt=float(msg["candle_acc_trade_price"])
        )
        
        prev = self.st.last_candle.get(market)
        self.st.last_candle[market] = candle

        if prev and candle.minute != prev.minute:
            self.st.prev5[market].append(prev.total_amt)

        await self._check_realtime_breakout(market, minute, candle)

    async def _check_realtime_breakout(self, market: str, minute, candle: Candle1m) -> None:
        if market in self.st.positions or market in self._pending_entry: return
        if len(self.st.positions) >= self.max_positions: return

        if market in self.st.cooldown_until:
            if now_kst() < self.st.cooldown_until[market]:
                return

        # === [수정 및 보완된 눌림목 로직] ===
        if market in self.st.waiting_pullback:
            wait_info = self.st.waiting_pullback[market]
            spike_time = wait_info['spike_time']
            pump_vol = wait_info['pump_vol']
            
            time_diff = (minute - spike_time).total_seconds()
            
            # 60초 전후로 유연하게 체크 (네트워크 지연 대비)
            if 55 <= time_diff <= 65:
                body_pct = (candle.close - candle.open) / candle.open * 100
                
                # [4번 필터: KeyError 방지 처리]
                current_buy_amt = self.st.buy_amt[market].get(minute, 0)
                current_sell_amt = candle.total_amt - current_buy_amt
                
                # 필터 조건: 눌림 중 매도세가 직전 급등 거래대금의 50%를 초과하면 즉시 포기
                if current_sell_amt > (pump_vol * 0.5):
                    self.log.info(f"[{market}] 🚨 설거지(매도세 과다) 포착! 진입 취소 (매도: {current_sell_amt:,.0f} > 기준: {pump_vol*0.5:,.0f})")
                    del self.st.waiting_pullback[market]
                    return

                # 1. 저장된 가변 타점 가져오기 (없으면 기본값 -0.3%)
                target = wait_info.get('target_rate', -0.3)

                # 2. 가변 타점 조건 검사 (-1.0% ~ target 사이일 때 진입)
                if -1.0 <= body_pct <= target:
                    self.log.info(f"[{market}] 🎯 필터 통과! 가변 타점 진입 (기준:{target}% / 현재:{body_pct:.2f}%)")
                    
                    # 중복 진입 방지를 위해 대기열에서 즉시 제거
                    self.st.waiting_pullback.pop(market, None)
                    
                    # 이미 주문 처리 중인 종목인지 확인
                    if market in self._pending_entry:
                        return
                    
                    # 주문 대기 상태로 등록 후 매수 실행
                    self._pending_entry.add(market)
                    asyncio.create_task(self._open_position(market, candle.close))
                    
            elif time_diff > 65: # 시간이 너무 지남
                del self.st.waiting_pullback[market]
            # ==============================================================

        # --- [기존 로직: 새로운 급등(돌파) 캔들 포착] ---
        buy = self.st.buy_amt[market][minute]
        total = candle.total_amt
        prev5 = self.st.prev5[market]

        if len(prev5) < 5: return
        avg5 = sum(prev5) / 5.0

        buy_ok = (total > 0) and (buy / total >= self.buy_pressure_th)
        spike_ok = (avg5 > 0) and (total >= avg5 * self.vol_spike_mult)
        bull_ok = candle.close > candle.open
        liq_ok = total >= self.min_amt

        if buy_ok and spike_ok and bull_ok and liq_ok:
            # === [가변 타점 로직이 적용된 명단 등록] ===
            if market not in self.st.waiting_pullback:
                # 💡 [핵심] 10분마다 갱신된 전역 변수를 그대로 읽어옵니다.
                current_score = self.st.market_score
                current_target = self.st.market_target_rate 
                
                self.st.waiting_pullback[market] = {
                    'spike_time': minute,
                    'pump_vol': total,
                    'target_rate': current_target # 이미 결정된 타점 저장
                }
                
                # [수정된 메시지]
                msg = f"✋[PULLBACK_WAIT] 🚀 {market} 포착! 현재시장점수:{current_score}점 -> 적용타점:{current_target}% 대기"
                
                self.log.info(msg)
                await self.notifier.send(msg)

    async def _market_judgment_loop(self):
        """10분마다 시장의 '날씨'를 확정하는 핵심 엔진"""
        # 시작 시 main.py에서 설정한 초기값 로드
        last_btc_total_vol = getattr(self.st, 'initial_btc_total_vol', 0.0)
        
        while True:
            try:
                # 1. 전체 마켓 Ticker 정보 수신
                tickers = await self.rest.tickers(self.all_krw_markets)
                if not tickers:
                    await asyncio.sleep(10); continue

                # --- [Step 1] AD Ratio & 전일 종가 갱신 (가중치 4) ---
                up_count = 0
                for t in tickers:
                    m = t['market']
                    px = t['trade_price']
                    prev_px = t['prev_closing_price']
                    self.st.prev_day_close[m] = prev_px # 매번 최신화
                    if px > prev_px: up_count += 1
                
                ad_ratio = (up_count / len(tickers)) * 100
                # 💡 [수정] 백테스트(CSV)와 실시간의 차이를 반영한 현실적 타점 (전체 243종목 기준)
                s1 = 4 if ad_ratio >= 40 else (2 if ad_ratio >= 25 else 0)

                # --- [Step 2] BTC 10분 유량 배수 (가중치 3) ---
                btc_t = next(t for t in tickers if t['market'] == "KRW-BTC")
                # 💡 [수정] 24h 롤링값이 아니라 당일(09시 리셋) 누적값 사용
                curr_btc_vol = float(btc_t['acc_trade_price'])
                
                # 💡 [수정] 09시 리셋으로 누적액이 0이 될 때 음수가 나오는 현상 방어
                if curr_btc_vol < last_btc_total_vol: 
                    ten_min_vol = curr_btc_vol
                else:
                    ten_min_vol = curr_btc_vol - last_btc_total_vol if last_btc_total_vol > 0 else 0
                last_btc_total_vol = curr_btc_vol
                
                # --- [Step 2] BTC 10분 유량 배수 (가중치 3) ---
                # (이전 코드 동일...)
                if ten_min_vol > 0:
                    self.st.btc_vol_history.append(ten_min_vol)
                
                s2 = 1 # 데이터 부족 시 중립
                btc_detail = f"10분:{ten_min_vol:,.0f} / 데이터수집중({len(self.st.btc_vol_history)}/3)"
                
                if len(self.st.btc_vol_history) == 3:
                    avg_30m = sum(self.st.btc_vol_history) / 3
                    mult = ten_min_vol / avg_30m if avg_30m > 0 else 1.0
                    s2 = 3 if mult >= 1.3 else (1 if mult >= 0.9 else 0)
                    btc_detail = f"10분:{ten_min_vol:,.0f} / 30분평균:{avg_30m:,.0f} (배수:{mult:.2f})"

                # --- [Step 3] 시장 전체 매수 비중 (가중치 3) ---
                # (이전 코드 동일...)
                now_m = now_kst().replace(second=0, microsecond=0)
                past_5mins = [now_m - timedelta(minutes=i) for i in range(1, 6)]
                
                total_m_vol = sum(sum(deq) for deq in self.st.prev5.values())
                total_m_buy = 0
                for m_dict in self.st.buy_amt.values():
                    total_m_buy += sum(m_dict.get(tm, 0) for tm in past_5mins)
                
                buy_ratio = (total_m_buy / total_m_vol) * 100 if total_m_vol > 0 else 50
                s3 = 3 if buy_ratio >= 52 else (1 if buy_ratio >= 49 else 0)

                # --- [결과 확정 및 상세 로깅] ---
                self.st.market_score = s1 + s2 + s3
                self.st.market_target_rate = self._get_dynamic_target(self.st.market_score)
                
                log_msg = (
                    f"🌤️ [MARKET_WEATHER] 총점:{self.st.market_score}점 -> 적용타점:{self.st.market_target_rate}%\n"
                    f" ┣ 📈 [S1:AD비율] 상승 {up_count}/{len(tickers)} ({ad_ratio:.1f}%) -> {s1}점\n"
                    f" ┣ 🪙 [S2:BTC유량] {btc_detail} -> {s2}점\n"
                    f" ┗ 🛒 [S3:매수비중] 매수:{total_m_buy:,.0f} / 전체:{total_m_vol:,.0f} ({buy_ratio:.1f}%) -> {s3}점"
                )
                self.log.info(log_msg)
                
                # 💡 10분봉 마감 시점(0분, 10분, 20분...)까지 남은 시간 계산 후 대기
                now = now_kst()
                passed_seconds = (now.minute % 10) * 60 + now.second
                sleep_sec = 600 - passed_seconds
                
                await asyncio.sleep(sleep_sec)
            except Exception as e:
                self.log.error(f"[_market_judgment_loop error] {e}")
                await asyncio.sleep(30)

    def _get_dynamic_target(self, score: int) -> float:
        """합산 점수에 따른 타점 결정 논리"""
        if score >= 8: return -0.1  # 강세
        if score >= 4: return -0.3  # 중립
        return -0.5                # 약세

    async def _open_position(self, market: str, px: float) -> None:
        try:
            mode = "PAPER" if self.paper_mode else "REAL"
            
            if self.paper_mode:
                entry = px * (1.0 + self.slip_rate)
                vol = self.krw_per_trade / entry
                tp_str = round_to_tick(entry * (1.0 + self.tp_pct), up=False)
                sl_str = round_to_tick(entry * (1.0 - self.sl_pct), up=False)
                tp_uuid = "paper_tp_uuid"
            else:
                if self.dry_run: return
                res = await self.rest.post_order({
                    "market": market, "side": "bid", "ord_type": "price", "price": str(self.krw_per_trade)
                })
                await asyncio.sleep(0.5)
                o = await self.rest.get_order(res["uuid"])
                
                trades = o.get("trades", [])
                if not trades:
                    self.log.warning(f"[{mode}_OPEN] {market} 매수 체결 안됨")
                    return
                    
                sum_vol = sum(float(t["volume"]) for t in trades)
                sum_fund = sum(float(t["funds"]) for t in trades)
                entry = sum_fund / sum_vol
                vol = sum_vol
                
                tp_str = round_to_tick(entry * (1.0 + self.tp_pct), up=False)
                sl_str = round_to_tick(entry * (1.0 - self.sl_pct), up=False)
                safe_vol = f"{vol:.8f}"
                
                # [추가] Dynamic TP가 켜져있으면 업비트에 지정가 매도를 걸지 않음!
                if self.use_dynamic_tp:
                    tp_uuid = None
                else:
                    tp_res = await self.rest.post_order({
                        "market": market, "side": "ask", "ord_type": "limit", "price": tp_str, "volume": safe_vol
                    })
                    tp_uuid = tp_res["uuid"]

            self.st.positions[market] = Position(
                market=market, entry=entry, volume=vol,
                tp=float(tp_str), sl=float(sl_str),
                tp_uuid=tp_uuid, opened_at=now_kst()
            )
            
            msg = f"🧨[{mode}_OPEN] {market}\n진입가: {entry:,.2f}원\n수량: {vol:.4f}\nTP: {tp_str} / SL: {sl_str}"
            self.log.info(msg)
            await self.notifier.send(msg)

        except Exception as e:
            self.log.exception(f"[_open_position error] {e}")
        finally:
            self._pending_entry.discard(market)

    async def _check_stoploss(self, market: str, px: float) -> None:
        pos = self.st.positions.get(market)
        if not pos: return

        if (now_kst() - pos.opened_at).total_seconds() >= self.timeout_sec:
            await self._stop_out(market, pos, px, reason="TIMEOUT")
            return

        # === [수정된 Dynamic TP 스위치 ON 분기] ===
        if self.use_dynamic_tp:
            # 1. 아직 감시 모드가 켜지지 않았을 때
            if not pos.trailing_active:
                if px >= pos.tp:
                    pos.trailing_active = True
                    # 💡 [핵심 수정 1] 돌파하는 찰나의 가격을 즉시 최고점으로 기록!
                    pos.tp = max(pos.tp, px)

                    msg = f"🧨[DYNAMIC_TP] 🚀 {market} 1차 목표가({pos.tp}) 돌파! 세력 이탈 감시 시작"
                    self.log.info(msg)
                    await self.notifier.send(msg)
            
            # 2. 감시 모드가 이미 켜져 있을 때 (가격이 떨어지든 오르든 무조건 매도 조건을 검사함!)
            else:
                # 🚀 [핵심 추가] 가격이 오르면 목표가(안전선)도 최고점 가격으로 계속 끌어올린다!
                if px > pos.tp:
                    pos.tp = px

                buy_vol, sell_vol = self.st.get_short_volume(market)
                
                # 시나리오 A: 매도세 터짐
                if sell_vol > (buy_vol * self.dynamic_tp_ratio) and sell_vol > 0:
                    await self._stop_out(market, pos, px, reason="DYNAMIC_TP")
                    return
                
                # 시나리오 B: 안전 커트라인 이탈 (이제 정상 작동함!)
                safe_price_line = pos.tp * (1 - (self.safe_tp_pct / 100.0))

                if px < safe_price_line: 
                    await self._stop_out(market, pos, px, reason="SAFE_TP")
                    return

        else:
            # 기존 고정 익절 모드
            if self.paper_mode and (px >= pos.tp):
                await self._stop_out(market, pos, pos.tp, reason="TP")
                return
        # ========================================

        if px <= pos.sl:
            await self._stop_out(market, pos, px, reason="SL")

    async def _stop_out(self, market: str, pos: Position, px: float, reason: str) -> None:
        mode = "PAPER" if self.paper_mode else "REAL"
        time_exit = now_kst()
        
        if self.paper_mode:
            # 🛠️ [수정됨] 고정 익절(TP)만 지정가이므로 면제, 나머지는 모두 시장가 매도 취급
            if reason == "TP":
                exit_px = px
            else:  # SL, TIMEOUT, DYNAMIC_TP, SAFE_TP 모두 슬리피지(손해) 깎고 계산
                exit_px = px * (1.0 - self.slip_rate)
            
            net = self.ledger.close_trade(mode, pos.opened_at, time_exit, market, reason, pos.entry, exit_px, pos.volume, self.fee_rate)
            self.st.positions.pop(market, None)
        else:
            if self.dry_run: return
            if pos.tp_uuid:
                try: 
                    await self.rest.cancel_order(pos.tp_uuid)
                    await asyncio.sleep(0.3)
                except: pass
            
            safe_volume = f"{pos.volume:.8f}"
            # 1. 시장가 매도 주문을 넣고, 그 영수증 번호(uuid)를 받습니다.
            res = await self.rest.post_order({
                "market": market, "side": "ask", "ord_type": "market", "volume": safe_volume
            })
            
            # === [추가 및 수정된 부분: 실제 체결가 확인] ===
            await asyncio.sleep(0.5)  # 업비트 서버에서 체결이 완료될 때까지 0.5초 대기
            try:
                o = await self.rest.get_order(res["uuid"])  # 영수증 번호로 상세 내역 조회
                # 업비트가 계산해준 실제 '평균 매도 단가(avg_price)'를 가져옴. (데이터가 없으면 기존 px 사용)
                exit_px = float(o.get("avg_price") or px) 
            except Exception as e:
                self.log.warning(f"[REAL_영수증_조회_실패] 신호 가격으로 대체합니다: {e}")
                exit_px = px
            # ================================================
            net = self.ledger.close_trade(mode, pos.opened_at, time_exit, market, reason, pos.entry, exit_px, pos.volume, self.fee_rate)
            self.st.positions.pop(market, None)

        self.st.cooldown_until[market] = now_kst() + timedelta(seconds=self.cooldown_sec)
        
        msg = f"🧨[{mode}_{reason}] {market} 청산\n탈출가: {exit_px:,.2f}원\n순수익: {net:,.0f}원"
        self.log.warning(msg)
        await self.notifier.send(msg)

    async def _tp_check_loop(self) -> None:
        while True:
            try:
                if self.dry_run or not self.st.positions or self.paper_mode:
                    await asyncio.sleep(1.5)
                    continue

                for m, pos in list(self.st.positions.items()):
                    if not pos.tp_uuid: continue  # Dynamic TP 모드일 땐 여기를 무시하고 지나감
                    
                    o = await self.rest.get_order(pos.tp_uuid)
                    if o.get("state") == "done":
                        exit_px = float(o.get("avg_price", pos.tp))
                        net = self.ledger.close_trade("REAL", pos.opened_at, now_kst(), m, "TP", pos.entry, exit_px, pos.volume, self.fee_rate)
                        
                        self.st.cooldown_until[m] = now_kst() + timedelta(seconds=self.cooldown_sec)
                        
                        msg = f"🧨[REAL_TP] {m} 목표가 도달!\n익절가: {exit_px:,.2f}원\n순수익: +{net:,.0f}원"
                        self.log.info(msg)
                        await self.notifier.send(msg)
                        self.st.positions.pop(m, None)

                await asyncio.sleep(1.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"[TP_LOOP_ERR] {e}")
                await asyncio.sleep(5.0)

    async def close_all_positions(self) -> None:
        if not self.st.positions:
            self.log.info("[SHUTDOWN] 보유 중인 포지션이 없습니다. 안전하게 종료합니다.")
            return

        self.log.warning(f"[SHUTDOWN] 프로그램 종료 요청됨! 보유 중인 {len(self.st.positions)}개 종목을 즉시 시장가로 매도합니다!")
        
        # 딕셔너리 크기가 변하는 것을 막기 위해 list()로 감싸서 반복합니다.
        for market, pos in list(self.st.positions.items()):
            # 가장 마지막으로 확인된 현재 가격을 가져옵니다. (없으면 진입가)
            px = self.st.last_price.get(market, pos.entry)
            try:
                # 이유(reason)를 "SHUTDOWN"으로 달아서 강제 손절(_stop_out) 실행
                await self._stop_out(market, pos, px, reason="SHUTDOWN")
                await asyncio.sleep(0.5)  # API 제한 방지를 위해 청산 간격 0.5초 부여
            except Exception as e:
                self.log.error(f"[SHUTDOWN_ERR] {market} 청산 실패: {e}")
        
        self.log.info("[SHUTDOWN] 모든 포지션 청산 완료! 프로그램을 종료합니다.")