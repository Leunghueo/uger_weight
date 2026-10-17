from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .base import WorkflowError
from _runtime import get_runtime
import logging
import math
from datetime import datetime

if TYPE_CHECKING:
    from .node import Node
    from .workflow import Workflow

AlgoActor = Callable[["Node", "Workflow", Any], Awaitable[Any]]
ALGO_REGISTRY: dict[str, AlgoActor] = {}


def register_algo(*algo_names: str) -> Callable[[AlgoActor], AlgoActor]:
    def decorator(func: AlgoActor) -> AlgoActor:
        for algo_name in algo_names:
            ALGO_REGISTRY[algo_name] = func
        return func

    return decorator

async def run_registered_algo(algo_name: str, node: "Node", workflow: "Workflow", data: Any) -> Any:
    actor = ALGO_REGISTRY.get(algo_name)
    if actor is None:
        raise WorkflowError(f"sys node {node.node_id} references unknown algo: {algo_name}")
    return await actor(node, workflow, data)

def _normalize_path(path_value: Any) -> list[str]:
    if isinstance(path_value, str):
        path = [part.strip() for part in path_value.split(".") if part.strip()]
    elif isinstance(path_value, (list, tuple)):
        path = [str(part).strip() for part in path_value if str(part).strip()]
    else:
        path = []
    if not path:
        raise WorkflowError("set_business_value algo requires a non-empty path")
    return path

def _ensure_dict_path(root: dict[str, Any], path: list[str]) -> dict[str, Any]:
    current = root
    for key in path[:-1]:
        next_value = current.get(key)
        if next_value is None:
            next_value = {}
            current[key] = next_value
        if not isinstance(next_value, dict):
            raise WorkflowError(f"set_business_value cannot descend into non-dict key: {key}")
        current = next_value
    return current

def _resolve_seconds(workflow: "Workflow", seconds: Any) -> float:
    if isinstance(seconds, (int, float)) or seconds is None:
        return float(seconds if seconds is not None else 0)
    if isinstance(seconds, str):
        key = seconds.strip()
        if not key:
            return 0.0
        try:
            return float(key)
        except ValueError:
            params = workflow.data.get("试验参数", {})
            if isinstance(params, dict) and key in params:
                return float(params[key])
            raise WorkflowError(f"wait seconds cannot resolve: {seconds!r}")
    return float(seconds)

def calc_each(workflow: "Workflow"):
    for k,v in workflow.data["结果数据"].items():
        try:
            val = round(v["测量值"], 2)
            v["结论"] =  "合格" if float(v["最小值"]) <= val <= float(v["最大值"]) else "不合格"
        except:
            logging.warning(f"计算判定过程报错: {k}")

# 等待算法
@register_algo("wait")
async def run_wait(node: "Node", workflow: "Workflow", data: Any) -> Any:
    if isinstance(data, dict):
        seconds = data.get("seconds", data.get("delay", 0))
    elif data is None:
        seconds = 0
    else:
        seconds = data

    trial_names = {
        "空簧保压流程": "空簧保压",
        "差压1>2": "差压1->2",
        "差压2>1": "差压2->1",
    }
    if node.node_name in trial_names:
        workflow.flags["气压试验类型"] = trial_names[node.node_name]

    trial_type = workflow.flags.get("气压试验类型")
    if node.node_name == "保压等待" and trial_type:
        params = workflow.data.get("试验参数", {})
        seconds = float(params.get(f"{trial_type}@保压时间", seconds))

    seconds_value = _resolve_seconds(workflow, seconds)
    await node._sleep(workflow, seconds_value)
    return None

# 切换到指定页面
@register_algo("switch_tab")
async def switch_tab(node: "Node", workflow: "Workflow", data: Any) -> Any:
    tab_id = data.get("tab") if isinstance(data, dict) else None
    runtime = get_runtime()
    views = runtime["ui_registry"]["views"]
    if not isinstance(tab_id, str) or tab_id not in views:
        raise WorkflowError(f"switch_tab requires a registered tab id: {tab_id!r}")
    broker = runtime.get("broker")
    if broker is None:
        raise WorkflowError("switch_tab requires a message broker")
    broker.publish(topic="switch_tab", tab=tab_id)
    return None

# 展示结果算法
@register_algo("show_result")
async def show_result(node: "Node", workflow: "Workflow", data: Any) -> Any:
    from .workflow import show_result_dialog
    orders = [
        "1-3位轴距",
        "2-4位轴距",
        "轴距差",

        "1位轮重",
        "2位轮重",
        "3位轮重",
        "4位轮重",
        "1-2位轴重",
        "3-4位轴重",
        "1位轮重差",
        "2位轮重差",
        "3位轮重差",
        "4位轮重差",
        "转向架载重",
        "转向架自重",

        "1位二系悬挂高度",
        "2位二系悬挂高度",

        "空气弹簧1初始气压",
        "空气弹簧1保压后气压",
        "空气弹簧1漏气量",
        "空气弹簧2初始气压",
        "空气弹簧2保压后气压",
        "空气弹簧2漏气量",
        "差压阀试验值1",
        "差压阀试验值2",

        "1位-电机侧联轴节高度",
        "1位-齿轮箱侧联轴节高度",
        "联轴节高度差1",
        "2位-电机侧联轴节高度",
        "2位-齿轮箱侧联轴节高度",
        "联轴节高度差2",
        "1位四角高度",
        "2位四角高度",
        "3位四角高度",
        "4位四角高度"
    ]
    result_list = [(name, workflow.data["结果数据"][name]) for name in orders]
    confirmed = await show_result_dialog(node, workflow, result_list)
    node.result = confirmed
    if not confirmed:
        from .base import NodeStoppedError
        raise NodeStoppedError("workflow stopped by user")
    return None

# 计算称重台纵向位移并--->试验参数
@register_algo("cal_pos")
async def cal_pos(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # 暂不需要
    return None

# 位移工进模式下计算压磅位移--->试验参数
@register_algo("cal_press")
async def cal_press(node: "Node", workflow: "Workflow", data: Any) -> Any:

    plc = get_runtime()["plc"]
    # vsp = get_runtime()["vsp"]

    workflow.data["试验参数"]["TEMP@压磅位移"] = plc.read("加载头垂向位移1")-15.0
    return None

# 自动计算横向位移并执行
@register_algo("autofit_x")
async def autofit_x(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # plc = get_runtime()["plc"]
    # vsp = get_runtime()["vsp"]

    # DT = 0.5
    # ITV = 0.2

    # _d12 = vsp.read("#1称重台激光") - vsp.read("#2称重台激光") 
    # if _d12>DT:
    #     plc.write("1位称重单元横向移动启动", True)
    #     while vsp.read("#1称重台激光") - vsp.read("#2称重台激光")>DT:
    #         print(f"*推1*:{vsp.read("#1称重台激光") - vsp.read("#2称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("1位称重单元横向移动启动", False)

    # if _d12<-DT:
    #     plc.write("2位称重单元横向移动启动", True)
    #     while vsp.read("#1称重台激光") - vsp.read("#2称重台激光")<-DT:
    #         print(f"*推2*:{vsp.read("#1称重台激光") - vsp.read("#2称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("2位称重单元横向移动启动", False) 

    # _d34 = vsp.read("#3称重台激光") - vsp.read("#4称重台激光") 
    # if _d34>DT:
    #     plc.write("3位称重单元横向移动启动", True)
    #     while vsp.read("#3称重台激光") - vsp.read("#4称重台激光")>DT:
    #         print(f"*推3*:{vsp.read("#3称重台激光") - vsp.read("#4称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("3位称重单元横向移动启动", False)

    # if _d34<-DT:
    #     plc.write("4位称重单元横向移动启动", True)
    #     while vsp.read("#3称重台激光") - vsp.read("#4称重台激光")<-DT:
    #         print(f"*推4*:{vsp.read("#3称重台激光") - vsp.read("#4称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("4位称重单元横向移动启动", False)
      
    return None

# 计算初始自重--->试验参数
@register_algo("init_weight")
async def init_weight(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime()["plc"]

    # 转向架自重
    workflow.data["结果数据"]["转向架自重"]["测量值"] = plc.read("轮重测量1") \
    + plc.read("轮重测量2") \
    + plc.read("轮重测量3") \
    + plc.read("轮重测量4")

    return None

# 气压绘图开关--->试验参数
@register_algo("plot_air")
async def plot_air(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime()["plc"]
    cmd = data.get("enabled")
    trial_type = data.get("trail_type")
    if cmd is True and trial_type == "空簧保压":
        workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] = plc.read("气压采集1")
        workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] = plc.read("气压采集2")
        logging.info(f"空簧保压模块开始")
    elif cmd is False and trial_type == "空簧保压":
        workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"] = plc.read("气压采集1")
        workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"] = plc.read("气压采集2")
        # 计算
        workflow.data["结果数据"]["空气弹簧1漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"]
        workflow.data["结果数据"]["空气弹簧2漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"]
        logging.info(f"空簧保压模块结束,泄漏量计算完毕")
    elif cmd not in (True, False):
        logging.error(f"空簧启动保压参数错误")

    broker = get_runtime()["broker"]
    if broker is not None:
        broker.publish(
            topic = "enable_plot",
            enabled = cmd,
            trial_type = trial_type,
            workflow_id = workflow.id,
        )
    else:
        logging.error(f"保压绘图消息发送失败")

    return None

# 换算空载/满载/偏载的plc数值--->试验参数
@register_algo("init_cal")
async def init_cal(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # 用不着
    return None

# 计算--->载荷试验
@register_algo("cal_press_trail")
async def cal_press_trail(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    cur_flow_data = get_runtime().get("wf")
    if cur_flow_data:
        base_pos = cur_flow_data.data["原点位置"]
        bogie_spec = cur_flow_data.data["转向架数据"]
    else:
        logging.error("工作流数据缺失!")

    # 加载力
    workflow.data["结果数据"]["1位加载力"]["测量值"] = plc.read("加载压力1")
    workflow.data["结果数据"]["2位加载力"]["测量值"] = plc.read("加载压力2")

    # 轮重
    workflow.data["结果数据"]["1位轮重"]["测量值"] = plc.read("轮重测量1")
    workflow.data["结果数据"]["2位轮重"]["测量值"] = plc.read("轮重测量2")
    workflow.data["结果数据"]["3位轮重"]["测量值"] = plc.read("轮重测量3")
    workflow.data["结果数据"]["4位轮重"]["测量值"] = plc.read("轮重测量4")

    # 轴重
    workflow.data["结果数据"]["1-2位轴重"]["测量值"] = workflow.data["结果数据"]["1位轮重"]["测量值"] + workflow.data["结果数据"]["2位轮重"]["测量值"]
    workflow.data["结果数据"]["3-4位轴重"]["测量值"] = workflow.data["结果数据"]["3位轮重"]["测量值"] + workflow.data["结果数据"]["4位轮重"]["测量值"]
 
    # 轮重差
    w12 = workflow.data["结果数据"]["1-2位轴重"]["测量值"]/2 + 1e-4
    w34 = workflow.data["结果数据"]["3-4位轴重"]["测量值"]/2 + 1e-4
    workflow.data["结果数据"]["1位轮重差"]["测量值"] = (workflow.data["结果数据"]["1位轮重"]["测量值"]-w12)/w12
    workflow.data["结果数据"]["2位轮重差"]["测量值"] = (workflow.data["结果数据"]["2位轮重"]["测量值"]-w12)/w12
    workflow.data["结果数据"]["3位轮重差"]["测量值"] = (workflow.data["结果数据"]["3位轮重"]["测量值"]-w34)/w34
    workflow.data["结果数据"]["4位轮重差"]["测量值"] = (workflow.data["结果数据"]["4位轮重"]["测量值"]-w34)/w34

    # 转向架载重
    workflow.data["结果数据"]["转向架载重"]["测量值"] = workflow.data["结果数据"]["1位轮重"]["测量值"] \
    + workflow.data["结果数据"]["2位轮重"]["测量值"] \
    + workflow.data["结果数据"]["3位轮重"]["测量值"] \
    + workflow.data["结果数据"]["4位轮重"]["测量值"]

    # 12内侧距(不计算)

    # 34内侧距(不计算)

    # 13轴距
    _data = workflow.data["结果数据"]["1-3位轴距"]
    _d1 = plc.read("称重台X位移1")-base_pos["1位X位移"]
    _d2 = plc.read("称重台X位移3")-base_pos["3位X位移"]
    _cal = bogie_spec["轴距"]+(_d1+_d2)
    workflow.data["结果数据"]["1-3位轴距"]["测量值"] = round(_cal, 2)

    # 24轴距
    _data = workflow.data["结果数据"]["2-4位轴距"]
    _d1 = plc.read("称重台X位移2")-base_pos["2位X位移"]
    _d2 = plc.read("称重台X位移4")-base_pos["4位X位移"]
    _cal = bogie_spec["轴距"]+(_d1+_d2)
    workflow.data["结果数据"]["2-4位轴距"]["测量值"] = round(_cal, 2)

    # 轴距差
    workflow.data["结果数据"]['轴距差']["测量值"]=abs(workflow.data["结果数据"]["1-3位轴距"]["测量值"]-workflow.data["结果数据"]["2-4位轴距"]["测量值"])

    # 13位二系悬挂高度 H0 + d0 - d1 + r + R - (r+R)^2-L^2/4)^0.5
    d=plc.read("加载头垂向位移1")
    H=bogie_spec["H13"]
    D=bogie_spec["D13"]
    r=bogie_spec["R"]
    L=bogie_spec["L"]
    R=workflow.data["转向架数据"]["平均轮径"]
    _cal = H + D - d + r + R - math.sqrt((r + R)**2 - L**2/4)
    workflow.data["结果数据"]["1位二系悬挂高度"]["测量值"] = round(_cal, 2)

    # 24位二系悬挂高度
    d=plc.read("加载头垂向位移2")
    H=bogie_spec["H24"]
    D=bogie_spec["D24"]
    r=bogie_spec["R"]
    L=bogie_spec["L"]
    R=workflow.data["转向架数据"]["平均轮径"]
    _cal = H + D - d + r + R - math.sqrt((r + R)**2 - L**2/4)
    workflow.data["结果数据"]["2位二系悬挂高度"]["测量值"] = round(_cal, 2)

    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "空载试验计算", extra = workflow.data["结果数据"])

    return None

# 计算--->空气试验
@register_algo("cal_air_trail")
async def cal_air_trail(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] = workflow.data["试验数据"]["TEMP@初始气压1"]
    workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"] = plc.read("气压采集1")
    workflow.data["结果数据"]["空气弹簧1漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"]

    workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] = workflow.data["试验数据"]["TEMP@初始气压2"]
    workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"] = plc.read("气压采集2")
    workflow.data["结果数据"]["空气弹簧2漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"]

    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "空簧保压试验计算", extra = workflow.data["结果数据"])

    return None

# 计算--->差压阀12
@register_algo("cal_air_12")
async def cal_air_12(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    workflow.data["结果数据"]["差压阀试验值1"]["测量值"] = plc.read("气压采集1") - plc.read("气压采集2")
    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "差压阀试验1->2计算", extra = workflow.data["结果数据"])
    return None

# 计算--->差压阀21
@register_algo("cal_air_21")
async def cal_air_21(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    workflow.data["结果数据"]["差压阀试验值2"]["测量值"] = plc.read("气压采集2") - plc.read("气压采集1")
    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "差压阀试验2->1计算", extra = workflow.data["结果数据"])
    return None


# 计算--->汇总结果
@register_algo("summary")
async def summary(node: "Node", workflow: "Workflow", data: Any) -> Any:
    workflow._append_workflow_log(event_name = "summary", extra = workflow.data["结果数据"])
    return None


# 保存PDF
@register_algo("excel2pdf")
async def excel2pdf(node: "Node", workflow: "Workflow", data: Any) -> Any:
    final_data = {
        "C3": workflow.meta["车型"],
        "F3": workflow.meta["位号"],
        "C4": workflow.meta["车号"],
        "E4": workflow.meta["编号"],
        "I3": datetime.now().strftime("%Y-%m-%d-%H-%M"),
        "I4": get_runtime()["current_user"],
        "D6": workflow.data["结果数据"]["1位轮重"]["测量值"],
        "D7": workflow.data["结果数据"]["2位轮重"]["测量值"],
        "D8": workflow.data["结果数据"]["3位轮重"]["测量值"],
        "D9": workflow.data["结果数据"]["4位轮重"]["测量值"],
        "D10": workflow.data["结果数据"]["1-2位轴重"]["测量值"],
        "D11": workflow.data["结果数据"]["3-4位轴重"]["测量值"],
        "D12": workflow.data["结果数据"]["1位轮重差"]["测量值"],
        "D13": workflow.data["结果数据"]["2位轮重差"]["测量值"],
        "D14": workflow.data["结果数据"]["3位轮重差"]["测量值"],
        "D15": workflow.data["结果数据"]["4位轮重差"]["测量值"],
        "D16": workflow.data["结果数据"]["转向架载重"]["测量值"],
        "D17": workflow.data["结果数据"]["转向架自重"]["测量值"],
        "D18": workflow.data["结果数据"]["12内侧距"]["测量值"],
        "D19": workflow.data["结果数据"]["34内侧距"]["测量值"],
        "D20": workflow.data["结果数据"]["1-3位轴距"]["测量值"],
        "D21": workflow.data["结果数据"]["2-4位轴距"]["测量值"],
        "D22": workflow.data["结果数据"]["1位二系悬挂高度"]["测量值"],
        "D23": workflow.data["结果数据"]["2位二系悬挂高度"]["测量值"],
        "D24": abs(workflow.data["结果数据"]["1-3位轴距"]["测量值"]-workflow.data["结果数据"]["2-4位轴距"]["测量值"]),
        "D25": workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"],
        "D26": workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"],
        "D27": workflow.data["结果数据"]["空气弹簧1漏气量"]["测量值"],
        "D28": workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"],
        "D29": workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"],
        "D30": workflow.data["结果数据"]["空气弹簧2漏气量"]["测量值"],
        "D31": "-",
        "D32": "-",
        "D33": "-",
        "D34": "-",
    }
    # breakpoint() # 查看结果数据
    pdf_handler = get_runtime()["pdf_report"]
    pdf_handler.load_template()
    pdf_handler.set_cells(final_data)
    pdf_handler.export_pdf(f"{workflow.id}.pdf")

# 安全检查
@register_algo("guard")
async def guard(node: "Node", workflow: "Workflow", data: Any) -> Any:
    guard_handler = get_runtime()["guard"]
    if guard_handler:
        plc = get_runtime()["plc"]
        payload = {
            "加载压力1": plc.read("加载压力1"),
            "加载压力2": plc.read("加载压力2")
        }
        guard_handler.set_guard(data.get("name", None), data.get("enable",False), payload)
    
@register_algo("clear_plc")
async def clear_plc(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    plc.clear()
    return None

