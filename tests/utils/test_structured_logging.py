import importlib
import logging
from types import SimpleNamespace

from src.utils import structured_logging


def test_get_logger_does_not_mutate_root_logging_state():
    module = importlib.reload(structured_logging)
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    root_logger.setLevel(logging.WARNING)

    try:
        logger = module.get_logger("aranes.test")

        assert logger is not None
        assert root_logger.handlers == []
        assert root_logger.level == logging.WARNING
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_setup_logging_sets_root_level_from_string():
    module = importlib.reload(structured_logging)
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    try:
        module.setup_logging("ERROR")
        assert root_logger.level == logging.ERROR
        assert root_logger.handlers
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_disabled_level_skips_structlog_event_processing(monkeypatch):
    module = importlib.reload(structured_logging)
    module.setup_logging("WARNING")
    logger = module.get_logger("aranes.test")

    def _boom(method_name, event=None, **event_kw):
        raise AssertionError(f"_process_event should not run for disabled level: {method_name}")

    monkeypatch.setattr(logger, "_process_event", _boom)

    assert logger.info("suppressed", expensive="payload") is None


def test_enabled_level_still_processes_structlog_events(monkeypatch):
    fake_stdlib_logger = SimpleNamespace(
        disabled=False,
        name="aranes.test",
        getEffectiveLevel=lambda: logging.INFO,
        info=lambda *args, **kwargs: (args, kwargs),
    )
    logger = structured_logging._FilteringBoundLogger(fake_stdlib_logger, (), {})
    seen: list[tuple[str, str | None, dict[str, object]]] = []

    def _capture(method_name, event=None, event_kw=None):
        seen.append((method_name, event, dict(event_kw or {})))
        return (("ok",), {})

    monkeypatch.setattr(logger, "_process_event", _capture)

    result = logger.info("kept", answer=42)

    assert result == (("ok",), {})
    assert seen == [("info", "kept", {"answer": 42})]
