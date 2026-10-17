from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from _runtime import get_runtime
from logger import append_workflow_log_entries, get_workflow_log_path, initialize_workflow_log
from .base import EventEmitter, NodeStoppedError, WorkflowError, WorkflowState, utc_now
from .node import ConfirmHandler, LoopHandler, Node, ResultHandler, SelectHandler


logger = logging.getLogger(__name__)


class Workflow:
    def __init__(
        self,
        config: dict[str, Any],
        rawdata: dict[str,Any], 
        *,
        select_handler: SelectHandler | None = None,
        loop_handler: LoopHandler | None = None,
        confirm_handler: ConfirmHandler | None = None,
        result_handler: ResultHandler | None = None,
    ) -> None:
        self.id = ""
        self.name = ""
        self.ctime = ""
        self.desc = ""
        self.broker = None
        self.meta: dict[str, Any] = {}
        self.nodes: dict[str, Node] = {}

        self.cur_node: Node | None = None
        self.state = WorkflowState.IDLE
        self.config_path: Path | None = None
        self.events = EventEmitter()
        self._stop_requested = False
        self._stop_event = threading.Event()
        self._skip_wait_event = threading.Event()
        self._running_loop: asyncio.AbstractEventLoop | None = None
        self._running_task: asyncio.Task[Any] | None = None
        self.select_handler = select_handler
        self.loop_handler = loop_handler
        self.confirm_handler = confirm_handler
        self.result_handler = result_handler

        self._rawdata = rawdata
        self.data = self._rawdata
        self.load_flow(config)
        self._incoming_edges: dict[str, list[str]] = {}
        self.logs: list[dict[str, Any]] = []
        self._log_path: Path | None = None
        self._log_active = False
        self.flags = {
            "循环起点": None,
            "循环次数": None,
            "循环计数": 0,
            "分支节点": None,
        }

    def load_flow(self, data: dict[str, Any]) -> "Workflow":
        self.id = str(data.get("id") or uuid4())
        self.name = data["name"]
        self.ctime = data["ctime"]
        self.desc = data.get("desc", "")
        self.meta = dict(data.get("meta") or {})
        self.nodes = {
            node_id: Node.from_dict(node_id, config)
            for node_id, config in data["nodes"].items()
        }
        self._validate_graph()
        self.reset(force=True)
        return self

    def save(self, json_path: str | Path | None = None) -> Path:
        path = Path(json_path or self.config_path or f"{self.name or 'workflow'}.json").resolve()
        payload = {
            "id": self.id,
            "name": self.name,
            "ctime": self.ctime,
            "desc": self.desc,
            "meta": self.meta,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.config_path = path
        return path

    def reset(self, *, force: bool = False) -> None:
        if not force and self.state == WorkflowState.RUNNING:
            raise WorkflowError("cannot reset a running workflow")
        self.cur_node = None
        self.state = WorkflowState.IDLE
        self.data = self._rawdata
        self._stop_requested = False
        self._stop_event.clear()
        self._skip_wait_event.clear()
        for node in self.nodes.values():
            node.reset()
        if not force:
            self._append_workflow_log("evt_wf_reset")

    def stop(self) -> None:
        if self.state == WorkflowState.RUNNING:
            self._stop_requested = True
            self._stop_event.set()
            try:
                plc = get_runtime().get("plc")
            except Exception:
                plc = None
            if plc is not None and hasattr(plc, "cancel_pending_actions"):
                try:
                    plc.cancel_pending_actions()
                except Exception:
                    logger.exception("failed to cancel plc actions")
            if self._running_loop is not None and self._running_task is not None:
                self._running_loop.call_soon_threadsafe(self._running_task.cancel)

    def skip_wait(self) -> None:
        if self.state == WorkflowState.RUNNING:
            self._skip_wait_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_requested

    def check_stopped(self) -> None:
        if self._stop_requested:
            raise NodeStoppedError("workflow stopped")

    async def wait_for_stop(self, timeout: float | None = None) -> bool:
        self.check_stopped()
        try:
            await asyncio.to_thread(self._stop_event.wait, timeout)
        except asyncio.CancelledError:
            self.check_stopped()
            raise
        self.check_stopped()
        return self._stop_event.is_set()

    async def wait_for_stop_or_skip(self, timeout: float | None = None) -> bool:
        self.check_stopped()

        def wait_any() -> str | None:
            interval = 0.05
            remaining = timeout
            while remaining is None or remaining > 0:
                if self._skip_wait_event.is_set():
                    return "skip"
                if self._stop_event.wait(0):
                    return "stop"
                step = interval if remaining is None else min(interval, remaining)
                if self._stop_event.wait(step):
                    return "stop"
                if remaining is not None:
                    remaining -= step
            return "skip" if self._skip_wait_event.is_set() else None

        try:
            result = await asyncio.to_thread(wait_any)
        except asyncio.CancelledError:
            self.check_stopped()
            raise
        if result == "skip":
            self._skip_wait_event.clear()
            return True
        self.check_stopped()
        return False

    async def start(self) -> WorkflowState:
        if self.state == WorkflowState.RUNNING:
            raise WorkflowError("workflow is already running")

        self._validate_graph()
        self.reset(force=True)
        self.logs.clear()
        self._stop_requested = False
        self._stop_event.clear()
        self._skip_wait_event.clear()
        self.state = WorkflowState.RUNNING
        self.cur_node = self.nodes["head"]
        self._running_loop = asyncio.get_running_loop()
        self._running_task = asyncio.current_task()
        self._initialize_workflow_log()
        self._append_workflow_log("evt_wf_start")

        try:
            while self.cur_node is not None:
                self.check_stopped()

                current_node = self.cur_node
                current_node.begin(self)
                try:
                    await self._run_common_node_args(current_node)
                    next_node_id = await current_node.act(self)
                    current_node.finish_done(self)
                except NodeStoppedError:
                    current_node.finish_stopped()
                    raise
                except Exception as exc:
                    current_node.finish_error(self, exc)
                    raise
                finally:
                    self._extend_logs(current_node.node_logs)

                if current_node.node_id == "end":
                    self.state = WorkflowState.DONE
                    self._append_workflow_log("evt_wf_done")
                    return self.state

                resolved_node_id = self._resolve_next(current_node, next_node_id)
                if resolved_node_id not in self.nodes:
                    raise WorkflowError(
                        f"node {current_node.node_id} points to missing node {resolved_node_id}"
                    )
                self.cur_node = self.nodes[resolved_node_id]

            raise WorkflowError("workflow terminated without reaching end")
        except asyncio.CancelledError:
            if self._stop_requested:
                self.state = WorkflowState.STOPPED
                self._append_workflow_log("evt_wf_stop")
                return self.state
            raise
        except NodeStoppedError:
            self.state = WorkflowState.STOPPED
            self._append_workflow_log("evt_wf_stop")
            return self.state
        except Exception as exc:
            self.state = WorkflowState.ERROR
            self._append_workflow_log("evt_wf_error", error=str(exc))
            return self.state
        finally:
            self._log_active = False
            self._running_task = None
            self._running_loop = None

    async def _run_common_node_args(self, node: Node) -> None:
        delay = float(node.args.get("delay", 0.0) or 0.0)
        if delay > 0:
            await node._sleep(self, delay)

        algo_name = str(node.args.get("algo") or "").strip().lower()
        skip_confirm = node.node_type == "sys" and algo_name == "wait"
        if bool(node.args.get("confirm")) and not skip_confirm:
            confirmed = await wait_for_confirmation(node, self)
            if not confirmed:
                raise NodeStoppedError("workflow stopped")

    def dump_log(self, *, pretty: bool = True) -> str:
        payload = {
            "workflow": {
                "流程ID": self.id,
                "流程名称": self.name,
                "创建时间": self.ctime,
                "最终状态": self.state.value,
                "最终节点": self.cur_node.node_id if self.cur_node else None,
            },
            "data": self.data,
            "logs": self.logs,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)

    def export_log(self, output_dir: str | Path | None = None) -> Path:
        directory = Path(output_dir or self.config_path.parent if self.config_path else Path.cwd()).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        date_part = datetime.now().strftime("%Y-%m%d")
        filename = f"{date_part}-{self.id}.log"
        path = directory / filename
        path.write_text(self.dump_log(pretty=True), encoding="utf-8")
        return path

    def _append_workflow_log(self, event_name: str, **extra: Any) -> None:
        entry = {
            "消息源": "流程",
            "event": event_name,
            "timestamp": utc_now(),
            "state": self.state.value,
            "cur_node": self.cur_node.node_id if self.cur_node else None,
        }
        entry.update(extra)
        self._extend_logs([entry])
        self.events.emit(event_name, workflow=self, **extra)

    def _initialize_workflow_log(self) -> None:
        workflow_type = str(self.meta.get("流程") or "")
        self._log_path = get_workflow_log_path(
            self.id,
            self.name,
            self.ctime,
            workflow_type,
        )
        metadata = {
            "消息源": "元信息",
            "id": self.id,
            "user": str(self.meta.get("用户") or ""),
            "工作流名称": self.name,
            "创建时间": self.ctime,
            "流程类型": workflow_type,
            "meta": self.meta,
        }
        try:
            initialize_workflow_log(self._log_path, metadata)
            self._log_active = True
        except Exception:
            self._log_active = False
            logger.exception("failed to initialize workflow log: workflow=%s", self.name)

    def _extend_logs(self, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        self.logs.extend(entries)
        if not self._log_active or self._log_path is None:
            return
        try:
            append_workflow_log_entries(self._log_path, entries)
        except Exception:
            logger.exception("failed to write workflow logs: workflow=%s", self.name)

    def _resolve_next(self, current_node: Node, act_next_node_id: str | None) -> str:
        if act_next_node_id is not None:
            return act_next_node_id

        if current_node.node_type == "loop_end":
            return self._resolve_loop_end_next(current_node)

        if len(current_node.next_nodes) == 1:
            return current_node.next_nodes[0]

        if len(current_node.next_nodes) > 1:
            raise WorkflowError(
                f"node {current_node.node_id} returned no route but has multiple next nodes"
            )

        select_node_id = self._find_owner_select(current_node.node_id)
        if select_node_id is None:
            raise WorkflowError(
                f"node {current_node.node_id} has no next node and no owning select node"
            )
        return select_node_id

    def _resolve_loop_end_next(self, loop_end_node: Node) -> str:
        begin_id = self.flags["循环起点"]
        total = self.flags["循环次数"]
        current = self.flags["循环计数"]
        if begin_id is None or total is None:
            raise WorkflowError(f"loop_end node {loop_end_node.node_id} is missing loop context")

        if current < total:
            return begin_id

        self.flags["循环次数"] = None
        self.flags["循环计数"] = 0
        self.flags["循环起点"] = None

        if len(loop_end_node.next_nodes) == 1:
            return loop_end_node.next_nodes[0]
        if len(loop_end_node.next_nodes) > 1:
            raise WorkflowError(f"loop_end node {loop_end_node.node_id} must have at most one next node")

        select_node_id = self._find_owner_select(loop_end_node.node_id)
        if select_node_id is None:
            raise WorkflowError(
                f"loop_end node {loop_end_node.node_id} has no next node and no owning select node"
            )
        return select_node_id

    def get_node_list(self) -> list[dict[str, Any]]:
        """
        获取按执行顺序排列的节点列表（排除 head 和 end）

        Returns:
            节点信息列表，每个元素包含 node_id, node_name, node_type
        """
        if "head" not in self.nodes:
            return []

        result = []
        visited: set[str] = set()
        queue: deque[str] = deque(self.nodes["head"].next_nodes)

        while queue:
            node_id = queue.popleft()
            if node_id in visited or node_id not in self.nodes:
                continue
            visited.add(node_id)
            node = self.nodes[node_id]

            if node_id != "end":
                result.append({
                    "node_id": node_id,
                    "node_name": node.node_name,
                    "node_type": node.node_type,
                    "desc": node.desc,
                })

            # 继续遍历
            for next_node_id in node.next_nodes:
                if next_node_id in self.nodes and next_node_id not in visited:
                    queue.append(next_node_id)

        return result

    def _validate_graph(self) -> None:
        if "head" not in self.nodes or "end" not in self.nodes:
            raise WorkflowError("workflow must contain head and end nodes")
        if self.nodes["end"].next_nodes:
            raise WorkflowError("end node must not point to other nodes")
        if len(self.nodes["head"].next_nodes) != 1:
            raise WorkflowError("head node must point to exactly one next node")

        incoming_edges = {node_id: [] for node_id in self.nodes}
        for node in self.nodes.values():
            for next_node_id in node.next_nodes:
                if next_node_id not in self.nodes and next_node_id != "end":
                    raise WorkflowError(f"node {node.node_id} references missing node {next_node_id}")
                if next_node_id in self.nodes:
                    incoming_edges[next_node_id].append(node.node_id)

        for node_id, parents in incoming_edges.items():
            if node_id != "head" and not parents:
                raise WorkflowError(f"node {node_id} must be referenced by at least one parent node")

        reachable = self._collect_reachable_nodes("head")
        unreachable_nodes = sorted(node_id for node_id in self.nodes if node_id not in reachable)
        if unreachable_nodes:
            raise WorkflowError(f"unreachable nodes found: {', '.join(unreachable_nodes)}")

        for node in self.nodes.values():
            if node.node_type == "select":
                if len(node.next_nodes) < 2:
                    raise WorkflowError(f"select node {node.node_id} must have at least two next nodes")
            elif len(node.next_nodes) > 1:
                raise WorkflowError(f"node {node.node_id} must not have multiple next nodes")

            if node.node_type == "loop_begin" and len(node.next_nodes) != 1:
                raise WorkflowError(f"loop_begin node {node.node_id} must have exactly one next node")
            if node.node_type == "loop_end" and len(node.next_nodes) > 1:
                raise WorkflowError(f"loop_end node {node.node_id} must have at most one next node")

            if node.node_id != "end" and not node.next_nodes and self._find_owner_select(node.node_id, incoming_edges) is None:
                raise WorkflowError(
                    f"node {node.node_id} has no next node and cannot trace back to a select node"
                )

        self._validate_non_nested_selects()
        self._validate_non_nested_loops()
        self._incoming_edges = incoming_edges

    def _collect_reachable_nodes(self, start_node_id: str) -> set[str]:
        visited: set[str] = set()
        queue: deque[str] = deque([start_node_id])
        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            for next_node_id in self.nodes[node_id].next_nodes:
                if next_node_id in self.nodes and next_node_id not in visited:
                    queue.append(next_node_id)
        return visited

    def _validate_non_nested_selects(self) -> None:
        for node in self.nodes.values():
            if node.node_type != "select":
                continue
            nested_select_id = self._find_descendant_of_type(node.next_nodes, "select", exclude={node.node_id})
            if nested_select_id is not None:
                raise WorkflowError(
                    f"select node {node.node_id} must not contain nested select node {nested_select_id}"
                )

    def _validate_non_nested_loops(self) -> None:
        for node in self.nodes.values():
            if node.node_type != "loop_begin":
                continue
            nested_loop_id = self._find_descendant_of_type(node.next_nodes, "loop_begin", exclude={node.node_id})
            if nested_loop_id is not None:
                raise WorkflowError(
                    f"loop_begin node {node.node_id} must not contain nested loop_begin node {nested_loop_id}"
                )
            loop_end_id = self._find_descendant_of_type(node.next_nodes, "loop_end")
            if loop_end_id is None:
                raise WorkflowError(f"loop_begin node {node.node_id} must reach a loop_end node")

    def _find_descendant_of_type(
        self,
        start_node_ids: list[str],
        target_type: str,
        *,
        exclude: set[str] | None = None,
    ) -> str | None:
        visited: set[str] = set()
        queue: deque[str] = deque(node_id for node_id in start_node_ids if node_id in self.nodes)
        excluded = exclude or set()

        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = self.nodes[node_id]
            if node_id not in excluded and node.node_type == target_type:
                return node_id
            for next_node_id in node.next_nodes:
                if next_node_id in self.nodes and next_node_id not in visited:
                    queue.append(next_node_id)
        return None

    def _find_owner_select(
        self,
        node_id: str,
        incoming_edges: dict[str, list[str]] | None = None,
    ) -> str | None:
        edges = incoming_edges or self._incoming_edges
        visited: set[str] = set()
        queue: deque[str] = deque(edges.get(node_id, []))
        while queue:
            parent_id = queue.popleft()
            if parent_id in visited:
                continue
            visited.add(parent_id)
            parent = self.nodes[parent_id]
            if parent.node_type == "select":
                return parent_id
            for grand_parent_id in edges.get(parent_id, []):
                if grand_parent_id not in visited:
                    queue.append(grand_parent_id)
        return None


async def show_result_dialog(node: Node, workflow: "Workflow", result_data: list) -> bool:
    """显示试验结果对话框并等待用户确认"""
    while True:
        if workflow.result_handler is not None:
            response = workflow.result_handler(node, result_data)
            if inspect.isawaitable(response):
                response = await response
        else:
            print(f"[{node.node_id}] result dialog not available, auto-confirm")
            response = True

        workflow.check_stopped()

        if isinstance(response, bool):
            return response

        answer = str(response).strip().lower()
        if answer in {"y", "yes", "1", "true"}:
            return True
        if answer in {"n", "no", "0", "false", ""}:
            return False


async def wait_for_confirmation(node: Node, workflow: "Workflow") -> bool:
    while True:
        if workflow.confirm_handler is not None:
            response = workflow.confirm_handler(node)
            if inspect.isawaitable(response):
                response = await response
        else:
            prompt = f"[{node.node_id}] confirm continue? (y/N): "
            response = await asyncio.to_thread(input, prompt)

        workflow.check_stopped()

        if isinstance(response, bool):
            return response

        answer = str(response).strip().lower()
        if answer in {"y", "yes", "1", "true"}:
            return True
        if answer in {"n", "no", "0", "false", ""}:
            return False
