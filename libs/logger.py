from __future__ import annotations

import configparser
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

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


def get_workflow_log_path(
    workflow_id: str,
    workflow_name: str,
    created_at: str,
    workflow_type: str,
) -> Path:
    try:
        created_text = datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%Y%m%d-%H%M%S")
    except (AttributeError, TypeError, ValueError):
        created_text = _safe_filename_part(created_at, "unknown-time")

    type_text = _safe_filename_part(workflow_type, "unknown-type")
    name_text = _safe_filename_part(workflow_name, "workflow")
    id_text = _safe_filename_part(workflow_id, "no-id")[:8]
    return LOG_FLOW / f"{created_text}_{type_text}_{name_text}_{id_text}.log"


def initialize_workflow_log(path: Path, metadata: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def append_workflow_log_entries(
    path: Path,
    entries: Iterable[dict[str, Any]],
) -> Path:
    lines = [json.dumps(entry, ensure_ascii=False) for entry in entries]
    if not lines:
        return path
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line)
            handle.write("\n")

    return path
