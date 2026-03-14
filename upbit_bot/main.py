from __future__ import annotations
import asyncio
import aiohttp

from .config import Settings
from .log import setup_logging, get_logger
from .rest_client import UpbitREST
from .state import State
from .market_select import select_krw_markets
from .notifier import TelegramNotifier
from .strategy import BurstEntryStrategy
from .ws_client import UpbitWSClient
from .ledger import TradeLedger

async def main():
    cfg = Settings()
    setup_logging(cfg.log_dir, cfg.log_level)
    log = get_logger("main")

    if (not cfg.dry_run) and (not cfg.upbit_access_key or not cfg.upbit_secret_key):
        raise SystemExit("UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY 필요 (또는 DRY_RUN=1)")

    async with aiohttp.ClientSession() as session:
        rest = UpbitREST(session, cfg.upbit_access_key, cfg.upbit_secret_key)

        markets = await select_krw_markets(rest, cfg.top_n)
        log.info(f"[INIT] selected={len(markets)} TOP_N={cfg.top_n} DRY_RUN={cfg.dry_run} DYNAMIC_TP={cfg.use_dynamic_tp}")

        notifier = TelegramNotifier(
            session=session,
            enabled=cfg.telegram_enabled,
            bot_token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
        )
        await notifier.start()

        st = State()
        ledger = TradeLedger(cfg.paper_dir)

        strat = BurstEntryStrategy(
            rest=rest, st=st, notifier=notifier, logger=get_logger("strategy"),
            dry_run=cfg.dry_run,
            krw_per_trade=cfg.krw_per_trade,
            max_positions=cfg.max_positions,
            cooldown_sec=cfg.cooldown_sec,
            buy_pressure_th=cfg.buy_pressure_th,
            vol_spike_mult=cfg.vol_spike_mult,
            min_amt=cfg.min_amt,
            tp_pct=cfg.tp_pct,
            sl_pct=cfg.sl_pct,
            paper_mode=cfg.paper_mode,
            ledger=ledger,
            fee_rate=cfg.fee_rate,
            slip_rate=cfg.slip_rate,
            timeout_sec=cfg.timeout_sec,
            use_dynamic_tp=cfg.use_dynamic_tp,        # [추가]
            dynamic_tp_sec=cfg.dynamic_tp_sec,        # [추가]
            dynamic_tp_ratio=cfg.dynamic_tp_ratio     # [추가]
        )

        ws = UpbitWSClient(markets, get_logger("ws"))
        
        try:
            await ws.run(on_trade=strat.on_trade, on_candle=strat.on_candle)
        except asyncio.CancelledError:
            log.info("종료 신호 수신됨 (Cancelled)")
        except KeyboardInterrupt:
            log.info("사용자에 의한 강제 종료 (Ctrl+C) 요청됨")
        finally:
            log.info("🚨 종료 프로세스 시작: 보유 종목 강제 청산 및 알림 종료...")
            # === [추가된 부분] 봇이 닫히기 전에 모든 포지션을 던집니다! ===
            await strat.close_all_positions()
            # ==============================================================
            await notifier.close()

if __name__ == "__main__":
    import platform
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 윈도우 환경에서 강제 종료 시 발생하는 에러 메시지를 숨기기 위한 처리
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass