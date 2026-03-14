from __future__ import annotations
import logging, os
from logging.handlers import RotatingFileHandler

def setup_logging(log_dir: str, level: str = "INFO") -> None:
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(
        os.path.join(log_dir, "bot.log"),
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)