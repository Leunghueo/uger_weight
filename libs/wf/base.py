from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


class WorkflowError(RuntimeError):
    pass


class NodeStoppedError(RuntimeError):
    pass


class WorkflowState(StrEnum):
    IDLE = "待执行"
    RUNNING = "执行中"
    DONE = "完成"
    ERROR = "故障"
    STOPPED = "停止"


class EventEmitter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def on(self, event_name: str, callback: Callable[..., Any]) -> None:
        self._handlers.setdefault(event_name, []).append(callback)

    def emit(self, event_name: str, **payload: Any) -> None:
        for callback in self._handlers.get(event_name, []):
            callback(**payload)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%y-%m-%d %H:%M:%S")
