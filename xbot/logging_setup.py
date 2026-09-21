"""Log kurulumu.

Loglar hem dosyaya (UTF-8) hem terminale yazilir. Gizli bilgi loglanmaz;
tweet metinlerinin loglanmasi config.yaml -> logging.log_tweet_text ile
kapatilabilir.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "xbot"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(levelname)-8s %(message)s"


def get_logger(suffix: str = "") -> logging.Logger:
    """Ana logger veya alt logger dondurur."""
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}" if suffix else LOGGER_NAME)


def setup_logging(
    log_dir: str | Path | None = None,
    *,
    level: str = "INFO",
    file_name: str = "xbot.log",
    console: bool = True,
) -> logging.Logger:
    """Logger'i hazirlar (tekrar cagrilirsa eski baglayicilar temizlenir)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        logger.addHandler(stream)

    if log_dir is not None:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / file_name,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(file_handler)

    return logger


def setup_logging_from_config(config, *, console: bool = True) -> logging.Logger:
    """AppConfig icindeki ayarlarla log kurar."""
    log_dir = config.paths.log_dir if config.paths else None
    return setup_logging(log_dir, level=config.logging.level, console=console)
