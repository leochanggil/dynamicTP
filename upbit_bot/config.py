from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def env_int(k: str, d: int) -> int:
    try: return int(os.getenv(k, str(d)))
    except: return d

def env_float(k: str, d: float) -> float:
    try: return float(os.getenv(k, str(d)))
    except: return d

def env_str(k: str, d: str = "") -> str:
    return os.getenv(k, d)

@dataclass(frozen=True)
class Settings:
    upbit_access_key: str = env_str("UPBIT_ACCESS_KEY")
    upbit_secret_key: str = env_str("UPBIT_SECRET_KEY")

    telegram_enabled: bool = env_int("TELEGRAM_ENABLED", 0) == 1
    telegram_bot_token: str = env_str("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = env_str("TELEGRAM_CHAT_ID")

    paper_mode: bool = env_int("PAPER_MODE", 0) == 1
    fee_rate: float = env_float("FEE_RATE", 0.0005)
    slip_rate: float = env_float("SLIP_RATE", 0.0005)
    paper_dir: str = env_str("PAPER_DIR", "logs")
    log_dir: str = env_str("LOG_DIR", "logs")
    log_level: str = env_str("LOG_LEVEL", "INFO")

    dry_run: bool = env_int("DRY_RUN", 1) == 1
    top_n: int = env_int("TOP_N", 70)
    krw_per_trade: int = env_int("KRW_PER_TRADE", 100000)
    max_positions: int = env_int("MAX_POSITIONS", 3)
    cooldown_sec: int = env_int("COOLDOWN_SEC", 300)
    
    buy_pressure_th: float = env_float("BUY_PRESSURE_TH", 0.65)
    vol_spike_mult: float = env_float("VOL_SPIKE_MULT", 4.0)
    min_amt: float = env_float("MIN_AMT", 50000000.0)
    tp_pct: float = env_float("TP_PCT", 0.03)
    sl_pct: float = env_float("SL_PCT", 0.015)
    timeout_sec: int = env_int("TIMEOUT_SEC", 3600)

    # === [추가] 실험적 기능 스위치 ===
    use_dynamic_tp: bool = env_int("USE_DYNAMIC_TP", 0) == 1
    dynamic_tp_sec: int = env_int("DYNAMIC_TP_SEC", 10)
    dynamic_tp_ratio: float = env_float("DYNAMIC_TP_RATIO", 2.0)

    # [추가] 안전 방어선 퍼센트를 가져옵니다. 값이 없으면 기본값 1.0을 사용합니다.
    safe_tp_pct: float = env_float("SAFE_TP_PCT", 1.0)