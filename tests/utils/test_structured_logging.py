import importlib
import logging

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
