from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.config import AppConfig

_CONFIGURED = False


def _coerce_log_level(config_or_level: AppConfig | str | int | None) -> int:
    if hasattr(config_or_level, "LOG_LEVEL"):
        config_or_level = getattr(config_or_level, "LOG_LEVEL")
    if isinstance(config_or_level, int):
        return config_or_level
    if isinstance(config_or_level, str):
        return getattr(logging, config_or_level.upper(), logging.INFO)
    return logging.INFO


def setup_logging(config_or_level: AppConfig | str | int | None = None) -> None:
    global _CONFIGURED
    log_level = _coerce_log_level(config_or_level)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(level=log_level, format="%(message)s")
    else:
        root_logger.setLevel(log_level)

    if _CONFIGURED:
        return

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def configure_structured_logging(config_or_level: AppConfig | str | int | None = None) -> None:
    setup_logging(config_or_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
