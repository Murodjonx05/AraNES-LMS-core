from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.config import AppConfig

_CONFIGURED = False
_METHOD_TO_LEVEL = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "exception": logging.ERROR,
    "critical": logging.CRITICAL,
    "fatal": logging.CRITICAL,
}


class _FilteringBoundLogger(structlog.stdlib.BoundLogger):
    def _proxy_to_logger(
        self,
        method_name: str,
        event: str | None = None,
        *event_args: str,
        **event_kw: Any,
    ) -> Any:
        level = _METHOD_TO_LEVEL.get(method_name)
        logger = self._logger
        if level is not None and (logger.disabled or level < logger.getEffectiveLevel()):
            return None
        return super()._proxy_to_logger(method_name, event, *event_args, **event_kw)


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
        wrapper_class=_FilteringBoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def configure_structured_logging(config_or_level: AppConfig | str | int | None = None) -> None:
    setup_logging(config_or_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
