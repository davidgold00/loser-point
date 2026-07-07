"""Structured logging shared by every pipeline module.

A full pipeline run should read like a narrative a stranger could follow:
INFO for milestones with row counts, WARNING for reconciliation issues that
don't halt the run, ERROR with concrete remediation instructions for anything
that does.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger, configuring the root handler once.

    Args:
        name: Usually `__name__` of the calling module.

    Returns:
        A `logging.Logger` writing to stderr with a consistent format
        `<timestamp> <level> <logger name> - <message>`.
    """
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            stream=sys.stderr,
        )
        _CONFIGURED = True
    return logging.getLogger(name)
