"""Safe structured service logging, independent of the server's access-log setup."""

import json
import logging
from datetime import UTC, datetime


class ServiceFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        try:
            event = json.loads(message)
            if not isinstance(event, dict):
                event = {"event": message}
        except (ValueError, TypeError):
            event = {"event": message}
        event.update(time=datetime.now(UTC).isoformat(), level=record.levelname, logger=record.name)
        return json.dumps(event, ensure_ascii=False)


def configure_logging() -> None:
    for name in ("escala", "escala_analyzer"):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(ServiceFormatter())
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
