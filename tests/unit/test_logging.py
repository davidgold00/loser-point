"""Unit tests for loserpoint.utils.logging."""

from __future__ import annotations

import logging

from loserpoint.utils.logging import get_logger


def test_get_logger_returns_named_logger() -> None:
    logger = get_logger("loserpoint.some.module")
    assert logger.name == "loserpoint.some.module"
    assert isinstance(logger, logging.Logger)


def test_get_logger_configures_root_handler_once() -> None:
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    get_logger("loserpoint.a")
    handlers_after_first = list(root.handlers)

    get_logger("loserpoint.b")
    handlers_after_second = list(root.handlers)

    # Root handlers must not accumulate across repeated get_logger calls.
    assert len(handlers_after_first) == len(handlers_after_second)
    assert len(handlers_after_first) >= len(handlers_before)
