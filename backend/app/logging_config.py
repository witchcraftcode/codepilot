import json
import logging
from contextvars import ContextVar
from datetime import datetime

from app.config import get_settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
REQUEST_ID_HEADER = "X-Request-ID"

STANDARD_LOG_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "unknown"
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record_message = record.getMessage()
        record_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record_message,
            "request_id": getattr(record, "request_id", None),
        }

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in STANDARD_LOG_RECORD_ATTRS and not key.startswith("_")
        }
        record_data.update(extra)

        if record.exc_info:
            record_data["exception"] = self.formatException(record.exc_info)

        return json.dumps({k: v for k, v in record_data.items() if v is not None}, default=str)


def configure_logging() -> None:
    settings = get_settings()
    level = settings.log_level.upper() if getattr(settings, "log_level", None) else "INFO"

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(level)
        logger.propagate = False
