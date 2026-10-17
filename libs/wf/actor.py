from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _runtime import get_runtime

from .algo import run_registered_algo
from .base import WorkflowError
from .node import Node, register_node_actor


if TYPE_CHECKING:
    from .workflow import Workflow


logger = logging.getLogger(__name__)

DONE_WAIT_PROGRESS_INTERVAL = 5.0
DEFAULT_WAIT_BEFORE_WATCH_MS = 500
PLC_CONFIG_PATH = Path(__file__).resolve().parents[2] / "runtime" / "hardware" / "plc.json"


def rnd() -> float:
    return random.uniform(100, 500)


def _get_plc_table() -> Any:
    runtime = get_runtime()
    try:
        return runtime["plc"]
    except KeyError as exc:
        raise WorkflowError("runtime plc is not initialized") from exc


def _get_vsp_table() -> Any:
    runtime = get_runtime()
    try:
        return runtime["vsp"]
    except KeyError as exc:
        raise WorkflowError("runtime vsp is not initialized") from exc


def _get_workflow_mid_data(workflow: "Workflow") -> dict[str, Any]:
    payload = workflow.data.get("试验参数")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise WorkflowError("workflow.data['试验参数'] must be a dict")
    return payload


def _normalize_action_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        merged: dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise WorkflowError(f"invalid plc action args item: {item!r}")
            merged.update(item)
        return merged
    raise WorkflowError(f"invalid plc action args: {raw!r}")


def _coerce_reset_flag(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    return bool(raw)


def _build_plc_confirm_handler(node: Node, workflow: "Workflow"):
    if workflow.confirm_handler is None:
        return None

    def _confirm(pt_name: str, step: str) -> bool:
        del pt_name, step
        response = workflow.confirm_handler(node)
        if inspect.isawaitable(response):
            raise WorkflowError("async workflow confirm_handler is unsupported in plc action thread")
        return bool(response)

    return _confirm


def _resolve_runtime_value(raw: Any, workflow: "Workflow") -> Any:
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return raw
    if text == "随机数":
        return rnd()
    mid_data = _get_workflow_mid_data(workflow)
    if text in mid_data:
        return mid_data[text]
    return raw


def _resolve_done_expression(raw: Any, workflow: "Workflow") -> str | None:
    if raw is None:
        return None

    text = str(raw).strip()
    if not text:
        return None

    for operator in ("=", ">", "<"):
        if operator not in text:
            continue
        left, right = text.split(operator, 1)
        pt_name = left.strip()
        rhs = right.strip()
        if not pt_name or not rhs:
            raise WorkflowError(f"invalid done expression: {raw!r}")

        mid_data = _get_workflow_mid_data(workflow)
        if rhs in mid_data:
            rhs = str(mid_data[rhs])
        return f"{pt_name}{operator}{rhs}"

    raise WorkflowError(f"invalid done expression: {raw!r}")


def _coerce_done_target(raw: str) -> Any:
    text = str(raw).strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def _resolve_done_source(pt_name: str) -> str:
    plc = _get_plc_table()
    vsp = _get_vsp_table()
    if pt_name in getattr(plc, "points", {}):
        return "plc"
    if pt_name in getattr(vsp, "points", {}):
        return "vsp"
    raise WorkflowError(f"done point not found in plc/vsp: {pt_name}")


def _build_done_condition(expression: str, trigger_pt_name: str) -> dict[str, Any]:
    text = str(expression).strip()
    for operator in ("=", ">", "<"):
        if operator not in text:
            continue
        left, right = text.split(operator, 1)
        pt_name = left.strip()
        rhs = right.strip()
        if not pt_name or not rhs:
            break
        source=_resolve_done_source(pt_name)
        coe = _coerce_done_target(rhs)
        fn = {
            "source": source,
            "pt_name": pt_name,
            "operator": operator,
            "target": coe,
            "trigger_pt_name": trigger_pt_name,
        }
        return fn
    raise WorkflowError(f"invalid done expression: {expression!r}")


def _done_condition_matched(actual: Any, operator: str, target: Any) -> bool:
    if operator == "=":
        if isinstance(target, bool):
            return actual is target
        if isinstance(target, (int, float)) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
            return math.isclose(float(actual), float(target), rel_tol=1e-9, abs_tol=1e-6)
        return str(actual).strip() == str(target).strip()

    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise WorkflowError(f"done operator {operator!r} requires numeric target")
    if operator == ">":
        return float(actual) > float(target)
    if operator == "<":
        return float(actual) < float(target)
    raise WorkflowError(f"unsupported done operator: {operator}")


def _evaluate_done_expression(expression: str) -> bool:
    condition = _build_done_condition(expression, "")
    actual = _read_runtime_point_sync(condition["source"], condition["pt_name"])
    fk = _done_condition_matched(actual, condition["operator"], condition["target"])
    return fk


def _read_runtime_point_sync(source: str, pt_name: str) -> Any:
    if source == "plc":
        table = _get_plc_table()
    elif source == "vsp":
        table = _get_vsp_table()
    else:
        raise WorkflowError(f"unsupported done source: {source}")
    return table.read(pt_name)


async def _read_runtime_point(source: str, pt_name: str) -> Any:
    return await asyncio.to_thread(_read_runtime_point_sync, source, pt_name)


def _get_wait_before_watch_seconds() -> float:
    try:
        with PLC_CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
        connection = config.get("connection") if isinstance(config, dict) else None
        if isinstance(connection, dict) and "wait_before_watch" in connection:
            raw = connection["wait_before_watch"]
        elif isinstance(config, dict) and "wait_before_watch" in config:
            raw = config["wait_before_watch"]
        else:
            raw = DEFAULT_WAIT_BEFORE_WATCH_MS
        wait_ms = float(raw)
        if wait_ms < 0:
            raise ValueError("wait_before_watch must be >= 0")
        return wait_ms / 1000
    except Exception as exc:
        return DEFAULT_WAIT_BEFORE_WATCH_MS / 1000


def _describe_done_condition(condition: dict[str, Any]) -> str:
    return (
        f"{condition.get('source')}::{condition.get('pt_name')} "
        f"{condition.get('operator')} {condition.get('target')!r}"
        f" (trigger={condition.get('trigger_pt_name')!r})"
    )


def _describe_pending(
    pending: list[tuple[dict[str, Any], Any]],
    with_value: bool = False,
) -> list[str]:
    if not with_value:
        return [_describe_done_condition(condition) for condition, _ in pending]
    return [
        f"{_describe_done_condition(condition)} 当前值={actual!r}"
        for condition, actual in pending
    ]


async def _read_condition_point(
    condition: dict[str, Any],
    source: str,
    pt_name: str,
    rounds: int,
    previous: Any,
) -> Any:
    """读取单个点位，失败时打印完整堆栈后再抛出，便于定位原因。"""
    try:
        return await _read_runtime_point(source, pt_name)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise


async def _wait_done_conditions(
    workflow: "Workflow",
    conditions: list[dict[str, Any]],
    poll_interval: float = 0.2,
) -> None:
    if not conditions:
        return

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    last_report = started_at
    rounds = 0
    pending: list[tuple[dict[str, Any], Any]] = [
        (condition, None) for condition in conditions
    ]

    while pending:
        try:
            workflow.check_stopped()
        except BaseException:
            raise

        rounds += 1
        remained: list[tuple[dict[str, Any], Any]] = []

        for condition, previous in pending:
            actual = await _read_condition_point(
                condition, condition["source"], condition["pt_name"], rounds, previous
            )
            try:
                matched = _done_condition_matched(
                    actual, condition["operator"], condition["target"]
                )
            except Exception:
                raise
            if matched:
                continue

            trigger_pt_name = str(condition.get("trigger_pt_name") or "").strip()
            if trigger_pt_name:
                trigger_value = await _read_condition_point(
                    condition, "plc", trigger_pt_name, rounds, actual
                )
                if trigger_value is False:
                    continue
            else:
                trigger_value = None

            remained.append((condition, actual))

        if not remained:
            return

        pending = remained
        now = loop.time()
        if now - last_report >= DONE_WAIT_PROGRESS_INTERVAL:
            last_report = now

        await asyncio.sleep(poll_interval)


async def _run_plc_action(
    node: Node,
    workflow: "Workflow",
    action: str,
    actlist: list[dict[str, Any]],
) -> None:
    del node, workflow, action
    plc = _get_plc_table()
    await asyncio.to_thread(plc.act, actlist, watch_done=False)

@register_node_actor("plc_batch")
async def run_plc_start(node: Node, workflow: "Workflow") -> str | None:
    actlist = node.args.get("actlist")
    done_list = node.args.get("done_list") or []

    if not actlist and not done_list:
        raise WorkflowError(f"{node.node_name} has no actlist or done_list")

    plc = _get_plc_table()
    plc.done_evaluator = _evaluate_done_expression

    actlist_executed = False
    normalized_actlist: list[dict[str, Any]] = []
    reset_actlist: list[dict[str, Any]] = []
    if actlist:
        for raw_act in actlist:
            if not isinstance(raw_act, dict):
                raise WorkflowError(f"invalid plc action: {raw_act!r}")
            act = dict(raw_act)
            act.pop("done", None)
            pt_name = str(act.get("pt_name") or "").strip()
            if not pt_name:
                continue
            act["pt_name"] = pt_name
            reset = act.get("reset", False)
            if type(reset) is not bool:
                raise WorkflowError(f"invalid plc action reset: {reset!r}")
            # 复位统一推迟到 done_list 全部满足之后执行。
            act["reset"] = False
            if reset:
                reset_actlist.append({"pt_name": pt_name, "value": False, "reset": False})
            if "value" in act:
                act["value"] = _resolve_runtime_value(act["value"], workflow)
            normalized_actlist.append(act)

        if normalized_actlist:
            await _run_plc_action(node, workflow, "start", normalized_actlist)
            actlist_executed = True

    resolved_dones: list[tuple[str, str]] = []
    for raw_done in done_list:
        resolved_done = _resolve_done_expression(raw_done, workflow)
        if not resolved_done:
            continue
        left_expr = resolved_done.split("=", 1)[0].split(">", 1)[0].split("<", 1)[0].strip()
        resolved_dones.append((left_expr, resolved_done))

    if resolved_dones:
        wait_conditions: list[dict[str, Any]] = []
        for left_expr, resolved_done in resolved_dones:
            try:
                cond = _build_done_condition(resolved_done, "")
                wait_conditions.append(cond)
            except WorkflowError as exc:
                continue
        if wait_conditions:
            wait_before_watch = _get_wait_before_watch_seconds()
            if actlist_executed and wait_before_watch > 0:
                await asyncio.sleep(wait_before_watch)
                workflow.check_stopped()
            await _wait_done_conditions(workflow, wait_conditions)

    if reset_actlist:
        await _run_plc_action(node, workflow, "reset", reset_actlist)
    return None


@register_node_actor("sys")
async def run_sys(node: Node, workflow: "Workflow") -> str | None:
    if node.args.get("force_error"):
        raise RuntimeError(node.args.get("error_message", f"{node.node_id} failed"))

    algo_name = str(node.args.get("algo") or "wait")
    algo_data = node.args.get("data")
    result = await run_registered_algo(algo_name, node, workflow, algo_data)
    # 不再使用 node_type:node_id 作为默认值，保持为空让 view 层处理显示"无故障"
    node.result = result if result is not None else ""
    return None


@register_node_actor("select")
async def run_select(node: Node, workflow: "Workflow") -> str:
    if not node.next_nodes:
        raise WorkflowError(f"select node {node.node_id} has no choices")
    selected = await _wait_for_selection(node, workflow)
    node.result = selected
    return selected


@register_node_actor("loop_begin")
async def run_loop_begin(node: Node, workflow: "Workflow") -> str | None:
    if workflow.flags["循环起点"] != node.node_id or workflow.flags["循环次数"] is None:
        total = await _resolve_loop_count(node, workflow)
        workflow.flags["循环起点"] = node.node_id
        workflow.flags["循环次数"] = total
        workflow.flags["循环计数"] = 0

    node.result = {
        "target": workflow.flags["循环次数"],
        "current": workflow.flags["循环计数"],
    }
    return None


@register_node_actor("loop_end")
async def run_loop_end(node: Node, workflow: "Workflow") -> str | None:
    begin_id = workflow.flags["循环起点"]
    total = workflow.flags["循环次数"]
    if begin_id is None or total is None:
        raise WorkflowError("loop_end is missing loop context")

    workflow.flags["循环计数"] += 1
    node.result = {
        "target": total,
        "current": workflow.flags["循环计数"],
    }
    return None

async def _wait_for_selection(node: Node, workflow: "Workflow") -> str:
    while True:
        if workflow.select_handler is not None:
            response = workflow.select_handler(node, list(node.next_nodes))
            if inspect.isawaitable(response):
                response = await response
        else:
            prompt = f"[{node.node_id}] choose next node {node.next_nodes}: "
            response = await asyncio.to_thread(input, prompt)

        selected_node = str(response).strip()
        workflow.check_stopped()
        if selected_node in node.next_nodes:
            workflow.data["分支节点"] = node.node_id
            return selected_node


async def _resolve_loop_count(node: Node, workflow: "Workflow") -> int:
    try:
        count = int(node.args.get("count", 1))
    except (TypeError, ValueError) as exc:
        raise WorkflowError(
            f"{node.node_id} invalid loop count args.count: {node.args.get('count')!r}"
        ) from exc

    if count < 1:
        raise WorkflowError(f"{node.node_id} loop count must be >= 1")
    return count
