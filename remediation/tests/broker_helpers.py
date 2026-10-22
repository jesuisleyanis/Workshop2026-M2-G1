"""Capture des logs JSON du contrat (le logger resilience_common ne propage pas -> pas de caplog)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from resilience_common.logging import JsonFormatter


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter("remediation"))
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@contextmanager
def capture_logs(logger_name: str = "remediation-test") -> Iterator[list[dict]]:
    handler = _ListHandler()
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.lines
    finally:
        logger.removeHandler(handler)
