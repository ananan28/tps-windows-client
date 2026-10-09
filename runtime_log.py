"""Local rotating diagnostics. Only fixed event codes and numeric metadata are allowed."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

EVENTS = frozenset('evidence_saved app_start app_close browser_start browser_ready browser_close homepage_load tab_wait tab_retry tab_ready field_wait field_ready input_fill submit_click navigation_wait navigation_done control_timeout navigation_timeout access_pause resume_request command_start command_done operation_error result_saved export_done export_error cache_error input_rejected stop_request unhandled_error resource_failed network_error resource_http document_http challenge_code diagnostic_error browser_dialog popup_open challenge_failure'.split())
OUTCOMES = frozenset('start ok failed challenge rate_limit phone email search resume home collect proxy direct already_submitted not_submitted timeout proxy_auth proxy_connection dns browser_missing browser_closed unknown cloudflare site pat tls extension_block manual'.split())
_logger = None
_lock = threading.Lock()


class SafeRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        pass  # A missing or full log directory must not print tracebacks.


def close_logging():
    global _logger
    with _lock:
        if _logger is not None:
            for handler in _logger.handlers[:]:
                _logger.removeHandler(handler)
                handler.close()
        _logger = None


def log_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TPSWindowsClient' / 'logs'


def setup_logging(directory=None, max_bytes=1024 * 1024, backups=3):
    global _logger
    with _lock:
        if _logger is not None and directory is None:
            return _logger
        logger = logging.getLogger('tps.runtime')
        logger.propagate = False
        logger.setLevel(logging.INFO)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        try:
            dest = Path(directory) if directory is not None else log_dir()
            dest.mkdir(parents=True, exist_ok=True)
            handler = SafeRotatingHandler(dest / 'runtime.log', maxBytes=max_bytes,
                                          backupCount=backups, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
        except OSError:
            logger.addHandler(logging.NullHandler())
        _logger = logger
        return logger


def event(code, outcome=None, *, http_status=None, elapsed_ms=None, count=None, submitted=None, error_code=None):
    # Never accept arbitrary messages, URLs, exceptions, credentials or page text.
    if code not in EVENTS or outcome is not None and outcome not in OUTCOMES:
        return
    row = {'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'event': code}
    if outcome is not None:
        row['outcome'] = outcome
    for key, value in [('http_status', http_status), ('elapsed_ms', elapsed_ms), ('count', count)]:
        if type(value) is int and 0 <= value <= 100000000:
            row[key] = value
    if type(error_code) is int and 100000 <= error_code <= 999999:
        row['error_code'] = error_code
    if type(submitted) is bool:
        row['submitted'] = submitted
    try:
        setup_logging().info(json.dumps(row, ensure_ascii=False))
    except (OSError, ValueError):
        pass  # A disk/logging error must not terminate the browser worker.

