from __future__ import annotations

import logging

import structlog

_CONFIGURED = False


def _resolve_log_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        resolved = getattr(logging, level.upper(), logging.INFO)
        return resolved if isinstance(resolved, int) else logging.INFO
    return logging.INFO


def configure_structured_logging(level: str | int | None = None) -> None:
    global _CONFIGURED
    resolved_level = _resolve_log_level(level)

    if not logging.getLogger().handlers:
        logging.basicConfig(level=resolved_level, format="%(message)s")
    else:
        logging.getLogger().setLevel(resolved_level)

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


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_structured_logging()
    return structlog.get_logger(name)
