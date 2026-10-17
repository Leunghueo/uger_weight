from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _runtime import get_runtime

LOGPATH = ""
LOG_SYS = ""
LOG_FLOW = ""

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def configure_application_logging(base_dir: str | Path | None = None) -> Path:
    global LOGPATH, LOG_SYS, LOG_FLOW

    LOGPATH = base_dir
    LOG_SYS = LOGPATH / "logs/daily"
    LOG_FLOW = LOGPATH / "logs/flows"
    LOG_SYS.mkdir(parents=True, exist_ok=True)
    LOG_FLOW.mkdir(parents=True, exist_ok=True)

    syslog = LOG_SYS / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    root_logger = logging.getLogger()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(syslog, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return syslog


def _safe_filename_part(value: Any, fallback: str) -> str:
    text = _INVALID_FILENAME_CHARS.sub("_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip(" ._")
    return text or fallback
