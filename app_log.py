#!/usr/bin/env python3
"""
Application log for DynaMix: what the GUI's Log tab shows.

The GUI runs under pythonw.exe on Windows, which has no console: without this
module every print() and every error raised in a worker thread is lost.
install() routes them all to the "dynamix" logger, which keeps the last lines
in memory (LogBuffer, read by the Log tab) and writes a rotating file under
<DynaMix home>/logs/.
"""

import collections
import datetime as _dt
import logging
import logging.handlers
import os
import sys
import threading
from typing import Dict, List

LOGGER_NAME = "dynamix"
LOG_FILENAME = "dynamix.log"
_STATE: Dict = {}


class LogBuffer(logging.Handler):
    """Keeps the most recent records; drain() hands the new ones to the GUI."""

    def __init__(self, max_lines: int = 5000):
        super().__init__(level=logging.DEBUG)
        self._records = collections.deque(maxlen=max_lines)
        self._pending = collections.deque(maxlen=max_lines)
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        with self._guard:
            self._records.append(record)
            self._pending.append(record)

    def records(self, min_level: int = logging.DEBUG) -> List[logging.LogRecord]:
        with self._guard:
            return [r for r in self._records if r.levelno >= min_level]

    def drain(self) -> List[logging.LogRecord]:
        with self._guard:
            out = list(self._pending)
            self._pending.clear()
        return out

    def clear(self) -> None:
        with self._guard:
            self._records.clear()
            self._pending.clear()


def format_record(record: logging.LogRecord) -> str:
    """'HH:MM:SS LEVEL message' plus the traceback when there is one."""
    when = _dt.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
    text = f"{when} {record.levelname:<7} {record.getMessage()}"
    if record.exc_text:
        text += "\n" + record.exc_text
    return text


class _StreamToLog:
    """File-like object: complete lines go to a logger, text also to the original stream."""

    def __init__(self, logger: logging.Logger, level: int, original):
        self.logger = logger
        self.level = level
        self.original = original
        self._pending = ""
        self._guard = threading.Lock()
        self._local = threading.local()

    def write(self, text: str) -> int:
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        if getattr(self._local, "busy", False):
            return len(text)  # a handler is itself writing to this stream: do not loop
        self._local.busy = True
        try:
            with self._guard:
                self._pending += text
                lines = self._pending.split("\n")
                self._pending = lines.pop()
            for line in lines:
                if line.strip():
                    self.logger.log(self.level, line.rstrip())
        finally:
            self._local.busy = False
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        value = getattr(self.original, "encoding", None)
        return value if isinstance(value, str) else "utf-8"

    @property
    def errors(self) -> str:
        value = getattr(self.original, "errors", None)
        return value if isinstance(value, str) else "strict"


def log_exception(exc_type, exc_value, exc_traceback, where: str = "Unhandled error") -> None:
    logging.getLogger(LOGGER_NAME).error("%s: %s", where, exc_value, exc_info=(exc_type, exc_value, exc_traceback))


def _sys_excepthook(exc_type, exc_value, exc_traceback) -> None:
    log_exception(exc_type, exc_value, exc_traceback)


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    log_exception(args.exc_type, args.exc_value, args.exc_traceback, f"Error in thread {name}")


def install(log_dir: str, max_lines: int = 5000) -> LogBuffer:
    """Route logging, stdout, stderr, warnings and uncaught exceptions to the buffer and the log file."""
    if _STATE:
        return _STATE["buffer"]
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    buffer = LogBuffer(max_lines)
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, LOG_FILENAME), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(buffer)
    logger.addHandler(file_handler)
    warnings_logger = logging.getLogger("py.warnings")  # warnings.warn(...) -> WARNING, not stderr
    warnings_logger.propagate = False
    warnings_logger.addHandler(buffer)
    warnings_logger.addHandler(file_handler)
    logging.captureWarnings(True)
    _STATE.update(buffer=buffer, file_handler=file_handler, log_dir=log_dir,
                  stdout=sys.stdout, stderr=sys.stderr,
                  excepthook=sys.excepthook, threading_excepthook=threading.excepthook)
    sys.stdout = _StreamToLog(logging.getLogger(LOGGER_NAME + ".stdout"), logging.INFO, _STATE["stdout"])
    sys.stderr = _StreamToLog(logging.getLogger(LOGGER_NAME + ".stderr"), logging.ERROR, _STATE["stderr"])
    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
    return buffer


def uninstall() -> None:
    """Restore the streams and hooks and detach the handlers (tests)."""
    if not _STATE:
        return
    sys.stdout = _STATE["stdout"]
    sys.stderr = _STATE["stderr"]
    sys.excepthook = _STATE["excepthook"]
    threading.excepthook = _STATE["threading_excepthook"]
    logging.captureWarnings(False)
    logger = logging.getLogger(LOGGER_NAME)
    warnings_logger = logging.getLogger("py.warnings")
    for handler in (_STATE["buffer"], _STATE["file_handler"]):
        logger.removeHandler(handler)
        warnings_logger.removeHandler(handler)
        handler.close()
    warnings_logger.propagate = True
    _STATE.clear()


def log_dir() -> str:
    """Folder of the log files (valid after install)."""
    return _STATE.get("log_dir", "")
