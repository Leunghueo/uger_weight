"""称重测量：VSP 采集 + 去皮 + 结果计算.

坑位布局（固定硬件，见 UI 手绘图）::
    坑1: 台 1-6    （下排奇数 1,3,5 / 上排偶数 2,4,6）
    坑2: 台 7-14   （下排奇数 7,9,11,13 / 上排偶数 8,10,12,14）
    坑3: 台 15-18  （下排奇数 15,17 / 上排偶数 16,18）

轴 = 同一轴左右两轮，即 (奇数, 偶数) 配对：(1,2),(3,4),...,(17,18)。

计算规则:
    轮重   = 传感器读数（经 segs 分段标定 + add 偏移换算后）
    轴重   = 相邻两轮重之和（1+2 / 3+4 / ...）
    整车重 = 所有轮重之和
    偏差   = (轮重 - 本轴平均轮重) / 本轴平均轮重 * 100%（每轮一个值，
             本轴平均轮重 = 轴重 / 2；对应 GB/T 3317 的轮重偏差口径）
    整车不平衡 = 最大轮重 - 最小轮重
另保留轮重差/轴重差供结果表使用。本系统只计算与呈现数值，
不做合格/不合格判定（无结果检验）。
"""
from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

PLATFORM_COUNT = 18

# 坑位 -> 台号列表（固定硬件布局）
PITS: dict[int, list[int]] = {
    1: [1, 2, 3, 4, 5, 6],
    2: [7, 8, 9, 10, 11, 12, 13, 14],
    3: [15, 16, 17, 18],
}

# 轴配对：(左轮台号, 右轮台号)
AXLES: list[tuple[int, int]] = [(i, i + 1) for i in range(1, PLATFORM_COUNT, 2)]

# 采集值为 kN；测量时换算为 kg，结果/存储/报告统一为 kg
UNIT = "kg"

KN_TO_KG = 1000.0 / 9.80665


def platform_point_name(platform: int) -> str:
    """台号 -> VSP 点位名（对应 vsp.json 的 pts 键）。"""
    return f"称重台{platform}"


def read_platforms(vsp_table: Any, platforms: list[int]) -> dict[int, float | None]:
    """读取一组台号的当前称重值（kN）。

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


def values_to_kg(values: dict[int, float | None]) -> dict[int, float | None]:
    """采集值 kN -> kg（测量时换算，结果与记录统一为 kg）。"""
    return {
        p: (None if v is None else round(float(v) * KN_TO_KG, 3))
        for p, v in values.items()
    }


def _axle_key(a: int, b: int) -> str:
    return f"{a}-{b}"


def calculate(
    values: dict[int, float | None],
    enabled: list[int],
) -> dict[str, Any]:
    """结果计算。只统计 enabled 台号；缺数的台/轴如实记录。

    只做数值计算，不做合格/不合格判定（本系统无结果检验）。
    """
    enabled_set = set(enabled)

    wheels: dict[str, float | None] = {str(p): values.get(p) for p in sorted(enabled_set)}
    missing: list[int] = [p for p in sorted(enabled_set) if values.get(p) is None]

    wheel_diff: dict[str, float] = {}
    axles: dict[str, float] = {}
    deviations: dict[str, float] = {}
    for a, b in AXLES:
        if a not in enabled_set or b not in enabled_set:
            continue
        va, vb = values.get(a), values.get(b)
        if va is None or vb is None:
            continue
        key = _axle_key(a, b)
        wheel_diff[key] = round(abs(va - vb), 3)
        axles[key] = round(va + vb, 3)
        # 偏差(%)：每轮相对本轴平均轮重（轴重/2）的偏差
        avg = (va + vb) / 2.0
        if avg:
            deviations[str(a)] = round((va - avg) / avg * 100.0, 2)
            deviations[str(b)] = round((vb - avg) / avg * 100.0, 2)

    axle_values = list(axles.values())
    axle_diff = round(max(axle_values) - min(axle_values), 3) if len(axle_values) >= 2 else 0.0
    total = round(sum(v for v in wheels.values() if v is not None), 3)
    # 整车不平衡 = 最大轮重 - 最小轮重
    present = [v for v in wheels.values() if v is not None]
    balance_value = round(max(present) - min(present), 3) if len(present) >= 2 else 0.0

    return {
        "wheels": wheels,            # 台号 -> 轮重(kg)
        "wheel_diff": wheel_diff,    # "a-b" -> 轮重差(kg)
        "axles": axles,              # "a-b" -> 轴重(kg)
        "axle_diff": axle_diff,      # 轴重差(kg)
        "deviations": deviations,    # 台号 -> 偏差(%)，相对本轴平均轮重
        "total": total,              # 整车重(kg)
        "balance": balance_value,    # 整车不平衡 = 最大轮重 - 最小轮重(kg)
        "missing": missing,
        "unit": UNIT,
    }


# ---------------------------------------------------------------------------
# 存储结构（与报告模板 abc.xlsx 1:1 对应，单位 kg）
#   轮数据: [{"轮号": 1..18, "轮重(kg)": 数值或"", "偏差(%)": 数值或""}, ...]
#   轴数据: [{"轴号": 1..9,  "轴重(kg)": 数值或""}, ...]
#   整车重(kg) / 不平衡检测(kg): 数值或 None
# ---------------------------------------------------------------------------

def report_skeleton() -> dict[str, Any]:
    """未测量记录的空结构：18 轮 / 9 轴占位，数值为空串。"""
    return {
        "wheels": [{"轮号": i, "轮重(kg)": "", "偏差(%)": ""}
                   for i in range(1, PLATFORM_COUNT + 1)],
        "axles": [{"轴号": k, "轴重(kg)": ""} for k in range(1, len(AXLES) + 1)],
        "total_kg": None,
        "balance_kg": None,
    }


def to_report_data(results: dict[str, Any] | None) -> dict[str, Any]:
    """calculate() 的结果（kg，测量时已换算）-> 存储/报告结构。

    仅做结构转换，不再换算单位。未启用或缺数的轮/轴数值留空串；
    无结果时等同 report_skeleton()。
    """
    results = results or {}
    wheels_in: dict[str, Any] = results.get("wheels") or {}
    deviations: dict[str, Any] = results.get("deviations") or {}
    axles_in: dict[str, Any] = results.get("axles") or {}

    wheels = []
    for p in range(1, PLATFORM_COUNT + 1):
        v = wheels_in.get(str(p))
        wheels.append({
            "轮号": p,
            "轮重(kg)": round(float(v), 1) if v is not None else "",
            "偏差(%)": deviations.get(str(p), ""),
        })
    axles = []
    for k, (a, b) in enumerate(AXLES, start=1):
        v = axles_in.get(_axle_key(a, b))
        axles.append({
            "轴号": k,
            "轴重(kg)": round(float(v), 1) if v is not None else "",
        })
    total = results.get("total")
    balance = results.get("balance")
    return {
        "wheels": wheels,
        "axles": axles,
        "total_kg": round(float(total), 1) if wheels_in and total is not None else None,
        "balance_kg": round(float(balance), 1) if wheels_in and balance is not None else None,
    }


def results_from_report(
    wheels: list[dict[str, Any]] | None,
    platforms: list[int] | None = None,
) -> dict[str, Any] | None:
    """存储结构（kg）-> calculate() 结果形状（kg），供页面结果表展示。

    由轮重还原各台数值后走 calculate()，保证派生量（轮重差/轴重差/
    偏差）与测量当时的口径一致。无任何轮重数据时返回 None。
    """
    values: dict[int, float | None] = {}
    for entry in wheels or []:
        v = entry.get("轮重(kg)")
        if isinstance(v, (int, float)):
            values[int(entry["轮号"])] = round(float(v), 3)
    if not values:
        return None
    enabled = list(platforms) if platforms else sorted(values)
    return calculate(values, enabled)
