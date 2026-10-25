"""称重测量：VSP 采集 + 去皮 + 结果计算.

坑位布局（固定硬件，见 UI 手绘图）::
    坑1: 台 1-6    （下排奇数 1,3,5 / 上排偶数 2,4,6）
    坑2: 台 7-14   （下排奇数 7,9,11,13 / 上排偶数 8,10,12,14）
    坑3: 台 15-18  （下排奇数 15,17 / 上排偶数 16,18）

车型-轴-轮-台位映射（runtime/device/maps.json）::
    车型 -> 车轴(轴1..轴N) -> 车轮(左轮/右轮)
          -> {"正向称台": 台号, "反向称台": 台号, "轮重": -1, "轮重差": -1}

    进车方向决定本次测量读哪一组台号：
        一轴向西 -> 正向 -> 取 "正向称台"
        一轴向东 -> 反向 -> 取 "反向称台"

    因此同一个台号在不同进车方向下隶属于不同的轴/轮，"轴 = 固定的
    奇偶相邻两台" 这一旧假设不再成立：轴/轮/台的关系全部由 maps.json
    决定，代码不再内置任何轴配对规则。每轮只允许从唯一台号读数。

计算规则（单位统一为 kg，全程不做 kN↔kg 换算）:
    轮重   = 该轮对应台号的传感器读数（kg，已去皮）
    轴重   = 同一轴左右两轮轮重之和
    轮重差 = (轮重 - 轴重/2) / 轴重 * 100%
             （左右两轮互为相反数，均衡时均为 0）
    整车重 = 所有轮重之和（= 所有轴重之和）
    不平衡 = 最大轮重 - 最小轮重
    VSP 点位经 parser + segs + add 换算后输出的即 kg，采集层不再处理单位。
无效值统一用 INVALID(-1)。本系统只计算与呈现数值，不做合格/不合格判定。
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

PLATFORM_COUNT = 18

# 坑位 -> 台号列表（固定硬件布局）
PITS: dict[int, list[int]] = {
    1: [1, 2, 3, 4, 5, 6],
    2: [7, 8, 9, 10, 11, 12, 13, 14],
    3: [15, 16, 17, 18],
}

UNIT = "kg"

# 报告（abc.xlsx 模板）以 kg 呈现，存储结构与模板一致。
# VSP 点位输出即 kg，采集 -> 计算 -> 存储 -> 展示全程不再做单位换算。

#: maps.json 中的无效占位值（未测量/无数据）
INVALID = -1.0

FORWARD = "正向"
REVERSE = "反向"

#: 进车方向 -> 正/反向（界面下拉框的可选项即为此表的键）
DIRECTION_ALIASES: dict[str, str] = {
    "一轴向西": FORWARD,
    "一轴向东": REVERSE,
}

#: 正/反向 -> maps.json 中取台号的字段名
PLATFORM_FIELDS: dict[str, str] = {
    FORWARD: "正向称台",
    REVERSE: "反向称台",
}

#: 界面可选的进车方向（顺序即下拉框顺序）
DIRECTIONS: list[str] = list(DIRECTION_ALIASES)

#: 轴内车轮的固定顺序
SIDES: tuple[str, ...] = ("左轮", "右轮")


# ---------------------------------------------------------------------------
# 映射解析
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WheelRef:
    """一次测量中的"一个车轮"：所属轴 + 左右 + 本次读数的台号。"""

    axle: str        # 轴名，如 "轴1"
    side: str        # "左轮" / "右轮"
    platform: int    # 本次（按进车方向解析出的）台号

    @property
    def label(self) -> str:
        return f"{self.axle}{self.side}"


def _axle_sort_key(name: str) -> tuple:
    """轴名排序：按其中的数字升序（轴2 < 轴10）。"""
    match = re.search(r"\d+", str(name))
    return (int(match.group()), str(name)) if match else (10 ** 9, str(name))


def normalize_direction(direction: str | None) -> str:
    """进车方向 -> 正向/反向。未知或被叫法时按正向处理。"""
    text = str(direction or "").strip()
    if text in (FORWARD, REVERSE):
        return text
    return DIRECTION_ALIASES.get(text, FORWARD)


def platform_field(direction: str | None) -> str:
    """进车方向 -> maps.json 中取台号的字段名。"""
    return PLATFORM_FIELDS[normalize_direction(direction)]


def resolve_wheels(
    maps: dict[str, dict] | None,
    model: str,
    direction: str | None,
) -> list[WheelRef]:
    """按 车型 + 进车方向 解析出有序的车轮列表。

    maps 结构: {车型: {轴名: {轮别: {"正向称台": n, "反向称台": n, ...}}}}
    返回顺序: 轴号升序（按轴名数字），轴内 左轮 -> 右轮。
    缺少对应方向台号的车轮直接跳过（不参与本次测量）。
    """
    model_cfg = (maps or {}).get(str(model).strip()) or {}
    if not isinstance(model_cfg, dict):
        return []
    field = platform_field(direction)

    refs: list[WheelRef] = []
    for axle_name in sorted(model_cfg, key=_axle_sort_key):
        wheels = model_cfg.get(axle_name)
        if not isinstance(wheels, dict):
            continue
        for side in SIDES:
            wheel = wheels.get(side)
            if not isinstance(wheel, dict):
                continue
            platform = wheel.get(field)
            if platform is None:
                continue
            refs.append(WheelRef(str(axle_name), side, int(platform)))
    return refs


def resolve_platforms(
    maps: dict[str, dict] | None,
    model: str,
    direction: str | None,
) -> list[int]:
    """本次测量实际使用的台号（有序，与 resolve_wheels 一一对应）。"""
    return [ref.platform for ref in resolve_wheels(maps, model, direction)]


def resolve_axles(
    maps: dict[str, dict] | None,
    model: str,
) -> list[str]:
    """该车型的轴名列表（升序）。"""
    model_cfg = (maps or {}).get(str(model).strip()) or {}
    if not isinstance(model_cfg, dict):
        return []
    return [str(name) for name in sorted(model_cfg, key=_axle_sort_key)]


def platform_point_name(platform: int) -> str:
    """台号 -> VSP 点位名（对应 vsp.json 的 pts 键）。"""
    return f"称重台{platform}"


def read_platforms(vsp_table: Any, platforms: list[int]) -> dict[int, float | None]:
    """读取一组台号的当前称重值（kg）。

    有 VSP 时走真实采集（含 sim 模式：VSP 内部已把地址替换为
    localhost@10000，走本地模拟器）；vsp_table 为空（VSP 未启用）
    时返回仿真数据，用于无硬件调试。
    """
    values: dict[int, float | None] = {}
    if vsp_table is None:
        base = 75.0
        for p in platforms:
            values[p] = round(base + random.uniform(-4.0, 4.0), 3)
        return values
    for p in platforms:
        try:
            values[p] = vsp_table.read(platform_point_name(p))
        except Exception:
            logger.exception("读取称重台 %s 失败", p)
            values[p] = None
    return values


def apply_tare(values: dict[int, float | None], tare: dict[int, float] | None) -> dict[int, float | None]:
    """去皮：测量值 - 去皮值。"""
    tare = tare or {}
    result: dict[int, float | None] = {}
    for p, v in values.items():
        t = tare.get(p, 0.0) or 0.0
        result[p] = round(v - t, 3) if v is not None else None
    return result


# ---------------------------------------------------------------------------
# 结果计算
# ---------------------------------------------------------------------------

def calculate(
    values: dict[int, float | None],
    wheel_refs: list[WheelRef],
) -> dict[str, Any]:
    """按 车轮->台号 映射计算结果。单位 kg（VSP 输出即 kg），缺数如实记录。

    wheel_refs 来自 resolve_wheels()（已按进车方向解析过台号）。
    只做数值计算，不做合格/不合格判定（本系统无结果检验）。
    """
    wheel_values: dict[int, float | None] = {}
    missing: list[int] = []
    for ref in wheel_refs:
        value = values.get(ref.platform)
        if value is None and ref.platform not in missing:
            missing.append(ref.platform)
        wheel_values[ref.platform] = value

    # 按出现顺序分组（保持 maps.json 的轴序）
    axle_order: list[str] = []
    axle_refs: dict[str, list[WheelRef]] = {}
    for ref in wheel_refs:
        if ref.axle not in axle_refs:
            axle_order.append(ref.axle)
            axle_refs[ref.axle] = []
        axle_refs[ref.axle].append(ref)

    axles: dict[str, float | None] = {}
    for name in axle_order:
        parts = [wheel_values.get(ref.platform) for ref in axle_refs[name]]
        axles[name] = round(sum(parts), 3) if parts and all(p is not None for p in parts) else None

    # 轮重差(%) = (轮重 - 轴重/2) / 轴重 * 100，左右两轮互为相反数
    deviations: dict[str, float | None] = {}
    for ref in wheel_refs:
        value = wheel_values.get(ref.platform)
        axle = axles.get(ref.axle)
        if value is None or not axle:
            deviations[str(ref.platform)] = None
        else:
            deviations[str(ref.platform)] = round((value - axle / 2.0) / axle * 100.0, 2)

    wheel_present = [v for v in wheel_values.values() if v is not None]
    axle_present = [v for v in axles.values() if v is not None]

    return {
        "wheels": {str(p): v for p, v in wheel_values.items()},  # 台号 -> 轮重(kg)
        "wheel_refs": list(wheel_refs),                          # 有序的 轴/轮/台
        "axle_order": axle_order,                                # 轴名顺序
        "axles": axles,                                          # 轴名 -> 轴重(kg)
        "axle_diff": round(max(axle_present) - min(axle_present), 3) if len(axle_present) >= 2 else 0.0,
        "deviations": deviations,                                # 台号 -> 轮重差(%)
        "total": round(sum(wheel_present), 3),                   # 整车重(kg)
        "balance": round(max(wheel_present) - min(wheel_present), 3) if len(wheel_present) >= 2 else 0.0,
        "missing": missing,
        "unit": UNIT,
    }


# ---------------------------------------------------------------------------
# 存储结构（与报告模板 abc.xlsx 对应，单位 kg）
#   轮数据: [{"轮号", "轴号", "台号", "轮别", "轮重(kg)", "偏差(%)"}, ...]
#   轴数据: [{"轴号", "轴重(kg)"}, ...]
#   整车重(kg) / 不平衡检测(kg): 数值或 None
#
# 轮/轴行数由车型（maps.json）决定，不再固定 18/9。
# 为兼容旧数据：无 "台号" 时按 轮号 当台号；无 "轴号" 时按 (台号+1)//2 归轴。
# ---------------------------------------------------------------------------

def report_skeleton(wheel_refs: list[WheelRef] | None = None) -> dict[str, Any]:
    """未测量记录的空结构：按车型轮/轴数占位，数值为空串。"""
    refs = list(wheel_refs or [])
    axle_order = list(dict.fromkeys(ref.axle for ref in refs))
    axle_index = {name: i for i, name in enumerate(axle_order, start=1)}
    return {
        "wheels": [
            {
                "轮号": i,
                "轴号": axle_index.get(ref.axle, ""),
                "台号": ref.platform,
                "轮别": ref.side,
                "轮重(kg)": "",
                "偏差(%)": "",
            }
            for i, ref in enumerate(refs, start=1)
        ],
        "axles": [{"轴号": k, "轴重(kg)": ""} for k in range(1, len(axle_order) + 1)],
        "total_kg": None,
        "balance_kg": None,
    }


def _legacy_refs(wheels_kg: dict, axles_kg: dict) -> list[WheelRef]:
    """旧结果（无 wheel_refs）兜底：按奇偶台号反推轴/轮。"""
    platform_axle: dict[int, str] = {}
    for key in sorted(axles_kg, key=lambda k: int(str(k).split("-")[0])):
        try:
            left, right = (int(x) for x in str(key).split("-", 1))
        except ValueError:
            continue
        platform_axle[left] = platform_axle[right] = str(key)
    refs: list[WheelRef] = []
    for platform in sorted(int(k) for k in wheels_kg):
        refs.append(
            WheelRef(
                platform_axle.get(platform, f"轴{(platform + 1) // 2}"),
                SIDES[0] if platform % 2 else SIDES[1],
                platform,
            )
        )
    return refs


def to_report_data(results: dict[str, Any] | None) -> dict[str, Any]:
    """calculate() 的结果（kg）-> 存储/报告结构（kg），1:1 直通。

    VSP 输出即 kg，此处不再做 kN->kg 换算。
    未启用或缺数的轮/轴数值留空串；无结果时等同空的 report_skeleton()。
    """
    results = results or {}
    wheels_kg: dict[str, Any] = results.get("wheels") or {}
    deviations: dict[str, Any] = results.get("deviations") or {}
    axles_kg: dict[str, Any] = results.get("axles") or {}

    refs: list[WheelRef] = list(results.get("wheel_refs") or [])
    axle_order: list[str] = list(results.get("axle_order") or [])
    if not refs and wheels_kg:
        refs = _legacy_refs(wheels_kg, axles_kg)
        axle_order = list(dict.fromkeys(ref.axle for ref in refs))
    if not axle_order and axles_kg:
        axle_order = [str(k) for k in axles_kg]

    axle_index = {name: i for i, name in enumerate(axle_order, start=1)}

    axles = []
    for name in axle_order:
        value = axles_kg.get(name)
        axles.append({
            "轴号": axle_index[name],
            "轴重(kg)": round(float(value), 1) if value is not None else "",
        })

    wheels = []
    for index, ref in enumerate(refs, start=1):
        value = wheels_kg.get(str(ref.platform))
        deviation = deviations.get(str(ref.platform))
        wheels.append({
            "轮号": index,
            "轴号": axle_index.get(ref.axle, ""),
            "台号": ref.platform,
            "轮别": ref.side,
            "轮重(kg)": round(float(value), 1) if value is not None else "",
            "偏差(%)": deviation if deviation is not None else "",
        })

    total = results.get("total")
    balance = results.get("balance")
    has_data = bool(wheels_kg)
    return {
        "wheels": wheels,
        "axles": axles,
        "total_kg": round(float(total), 1) if has_data and total is not None else None,
        "balance_kg": round(float(balance), 1) if has_data and balance is not None else None,
    }


def axis_rows_kg(
    wheels: list[dict[str, Any]] | None,
    axles: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """存储结构（kg）-> 每轴一行（界面结果表与 abc.xlsx 报告共用的版式）。

    返回 [{"轴号", "轴重(kg)", "轮重(左)/kg", "轮重偏差(左)",
           "轮重(右)/kg", "轮重偏差(右)"}, ...]，按轴号升序；
    缺数或未测量的单元格为空串。轮别非 左轮/右轮 时按出现顺序补位。
    """
    axle_weights: dict[int, Any] = {}
    for entry in axles or []:
        try:
            axle_weights[int(entry.get("轴号"))] = entry.get("轴重(kg)")
        except (TypeError, ValueError):
            continue

    order: list[int] = []
    sides: dict[int, dict[str, tuple[Any, Any]]] = {}
    free: dict[int, list[str]] = {}
    for entry in wheels or []:
        try:
            axle = int(entry.get("轴号"))
        except (TypeError, ValueError):
            continue
        if axle not in sides:
            sides[axle] = {}
            free[axle] = list(SIDES)
            order.append(axle)
        side = str(entry.get("轮别") or "").strip()
        if side not in SIDES:  # 非标准轮别：按出现顺序补左/右位
            side = free[axle].pop(0) if free[axle] else SIDES[0]
        elif side in free[axle]:
            free[axle].remove(side)
        sides[axle][side] = (entry.get("轮重(kg)"), entry.get("偏差(%)"))

    axle_nos = order + [a for a in sorted(axle_weights) if a not in order]
    rows: list[dict[str, Any]] = []
    for axle in sorted(axle_nos):
        pair = sides.get(axle) or {}
        left = pair.get("左轮", ("", ""))
        right = pair.get("右轮", ("", ""))
        weight = axle_weights.get(axle)
        rows.append({
            "轴号": axle,
            "轴重(kg)": weight if weight is not None else "",
            "轮重(左)/kg": left[0] if left[0] is not None else "",
            "轮重偏差(左)": left[1] if left[1] is not None else "",
            "轮重(右)/kg": right[0] if right[0] is not None else "",
            "轮重偏差(右)": right[1] if right[1] is not None else "",
        })
    return rows


def results_from_report(
    wheels: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """存储结构（kg）-> calculate() 结果形状（kg），供页面结果表展示。

    由轮重反算各台读数后走 calculate()，保证派生量（轴重/轮重差/不平衡）
    与测量当时的口径一致。无任何轮重数据时返回 None。
    """
    values: dict[int, float | None] = {}
    refs: list[WheelRef] = []
    for entry in wheels or []:
        raw = entry.get("轮重(kg)")
        if not isinstance(raw, (int, float)):
            continue
        try:
            platform = int(entry.get("台号") or entry.get("轮号"))
        except (TypeError, ValueError):
            continue
        values[platform] = round(float(raw), 3)
        side = str(entry.get("轮别") or "").strip()
        axle_no = entry.get("轴号")
        axle = f"轴{axle_no}" if isinstance(axle_no, int) and axle_no else ""
        refs.append(WheelRef(axle, side, platform))

    if not values:
        return None

    if not all(ref.axle for ref in refs):  # 旧记录无轴号：按奇偶台号归轴
        refs = [
            WheelRef(
                ref.axle or f"轴{(ref.platform + 1) // 2}",
                ref.side or (SIDES[0] if ref.platform % 2 else SIDES[1]),
                ref.platform,
            )
            for ref in refs
        ]
    return calculate(values, refs)
