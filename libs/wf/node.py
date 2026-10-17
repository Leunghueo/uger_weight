from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from _runtime import get_runtime
from .base import WorkflowError, WorkflowState, utc_now

if TYPE_CHECKING:
    from .workflow import Workflow


SCHEMA_PATH = get_runtime()["paths"]["node_config"]
with SCHEMA_PATH.open(encoding="utf-8") as f:
    NODES_SCHEMA = json.load(f)

NODE_TYPES = [node["type"] for node in NODES_SCHEMA.values()]
NodeActor = Callable[["Node", "Workflow"], Awaitable[str | None]]
SelectHandler = Callable[["Node", list[str]], str | Awaitable[str]]
LoopHandler = Callable[["Node"], int | Awaitable[int]]
ConfirmHandler = Callable[["Node"], bool | Awaitable[bool]]
ResultHandler = Callable[["Node", dict], bool | Awaitable[bool]]
NODE_ACT_REGISTRY: dict[str, NodeActor] = {}


def register_node_actor(*node_types: str) -> Callable[[NodeActor], NodeActor]:
    def decorator(func: NodeActor) -> NodeActor:
        for node_type in node_types:
            if node_type not in NODE_TYPES:
                raise WorkflowError(f"unsupported node type for actor registration: {node_type}")
            NODE_ACT_REGISTRY[node_type] = func
        return func
    return decorator


@dataclass
class Node:
    node_id: str
    node_name: str
    node_type: str
    args: dict[str, Any] = field(default_factory=dict)
    next_nodes: list[str] = field(default_factory=list)
    desc: str = ""
    gnode: str = ""
    state: WorkflowState = WorkflowState.IDLE
    stime: str | None = None
    etime: str | None = None
    result: Any = None
    error: str | None = None
    node_logs: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, node_id: str, data: dict[str, Any]) -> "Node":
        node_type = data["type"]
        if node_type not in NODE_TYPES:
            raise WorkflowError(f"unsupported node type for {node_id}: {node_type}")
        return cls(
            node_id=node_id,
            node_type=node_type,
            node_name=data["node_name"],
            args=dict(data.get("args") or {}),
            next_nodes=list(data.get("next") or []),
            desc=data.get("desc", ""),
            gnode=data.get("gnode", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.node_type,
            "args": self.args,
            "next": self.next_nodes,
            "desc": self.desc,
            "gnode": self.gnode,
        }

    def reset(self) -> None:
        self.state = WorkflowState.IDLE
        self.stime = None
        self.etime = None
        self.result = None
        self.error = None
        self.node_logs = []

    def begin(self, workflow: "Workflow") -> None:
        self.state = WorkflowState.RUNNING
        self.stime = utc_now()
        self.etime = None
        self.result = None
        self.error = None
        self.node_logs = []
        workflow.events.emit("evt_node_begin", workflow=workflow, node=self)
        # self._append_log("begin")

    async def act(self, workflow: "Workflow") -> str | None:
        actor = NODE_ACT_REGISTRY.get(self.node_type)
        if actor is None:
            raise WorkflowError(f"no actor registered for node type {self.node_type}")
        return await actor(self, workflow)

    def finish_done(self, workflow: "Workflow") -> None:
        self.state = WorkflowState.DONE
        self.etime = utc_now()
        self._append_log("done")
        workflow.events.emit("evt_node_done", workflow=workflow, node=self, result=self.result)

    def finish_stopped(self) -> None:
        self.state = WorkflowState.STOPPED
        self.etime = utc_now()
        self.error = "stopped"
        self._append_log("stopped")

    def finish_error(self, workflow: "Workflow", exc: Exception) -> None:
        self.state = WorkflowState.ERROR
        self.etime = utc_now()
        self.error = str(exc)
        self._append_log("error")
        workflow.events.emit("evt_node_error", workflow=workflow, node=self, error=exc)

    async def _sleep(self, workflow: "Workflow", seconds: int) -> None:
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            workflow.check_stopped()
            step = min(1.0, remaining)
            skipped = await workflow.wait_for_stop_or_skip(step)
            if skipped:
                remaining = 0.0
                if workflow.broker:
                    workflow.broker.publish("node_wait", total=seconds, remaining=remaining)
                break
            remaining = max(0.0, remaining - step)
            if workflow.broker:
                workflow.broker.publish("node_wait", total=seconds, remaining=remaining)
        workflow.check_stopped()

    def _append_log(self, stage: str) -> None:
        self.node_logs.append(
            {
                "消息源": "节点",
                "消息阶段": stage,
                "节点": f"{self.node_name}({self.node_id})",
                "类型": self.node_type,
                "状态": self.state.value,
                "结果": self.result,
                "错误": self.error,
                "执行时间": self.stime,
                "完成时间": self.etime,
            }
        )

from . import actor as _actor  # noqa: E402,F401
