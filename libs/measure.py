"""称重测量：VSP 采集 + 去皮 + 六项结果计算.

坑位布局（固定硬件，见 UI 手绘图）::
    坑1: 台 1-6    （下排奇数 1,3,5 / 上排偶数 2,4,6）
    坑2: 台 7-14   （下排奇数 7,9,11,13 / 上排偶数 8,10,12,14）
    坑3: 台 15-18  （下排奇数 15,17 / 上排偶数 16,18）

轴 = 同一轴左右两轮，即 (奇数, 偶数) 配对：(1,2),(3,4),...,(17,18)。

计算项（暂定，后续可扩展）:
    轮重, 轮重差, 轴重, 轴重差, 整车重, 不平衡检测
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

# 判定阈值（kN）。暂定值，后续可移到配置文件。
THRESHOLDS: dict[str, float] = {
    "wheel_diff": 10.0,  # 轮重差超限阈值
    "axle_diff": 20.0,   # 轴重差超限阈值
}

UNIT = "kN"


def platform_point_name(platform: int) -> str:
    """台号 -> VSP 点位名（对应 vsp.json 的 pts 键）。"""
    return f"称重台{platform}"


def read_platforms(vsp_table: Any, platforms: list[int], sim: bool = False) -> dict[int, float | None]:
    """读取一组台号的当前称重值（kN）。

    sim=True 或 vsp_table 为空时返回仿真数据（用于无硬件调试）。
    """
    values: dict[int, float | None] = {}
    if sim or vsp_table is None:
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


def _axle_key(a: int, b: int) -> str:
    return f"{a}-{b}"


def calculate(values: dict[int, float | None], enabled: list[int]) -> dict[str, Any]:
    """六项计算。只统计 enabled 台号；缺数的台/轴如实记录。"""
    enabled_set = set(enabled)

    wheels: dict[str, float | None] = {str(p): values.get(p) for p in sorted(enabled_set)}
    missing: list[int] = [p for p in sorted(enabled_set) if values.get(p) is None]

    wheel_diff: dict[str, float] = {}
    axles: dict[str, float] = {}
    for a, b in AXLES:
        if a not in enabled_set or b not in enabled_set:
            continue
        va, vb = values.get(a), values.get(b)
        if va is None or vb is None:
            continue
        key = _axle_key(a, b)
        wheel_diff[key] = round(abs(va - vb), 3)
        axles[key] = round(va + vb, 3)

    axle_values = list(axles.values())
    axle_diff = round(max(axle_values) - min(axle_values), 3) if len(axle_values) >= 2 else 0.0
    total = round(sum(v for v in wheels.values() if v is not None), 3)

    issues: list[dict[str, str]] = []
    for p in missing:
        issues.append({"type": "采集异常", "detail": f"称重台{p}无数据"})
    for key, d in wheel_diff.items():
        if d > THRESHOLDS["wheel_diff"]:
            issues.append({"type": "轮重差超限", "detail": f"轴{key}轮重差{d}{UNIT}（阈值{THRESHOLDS['wheel_diff']}{UNIT}）"})
    if len(axle_values) >= 2 and axle_diff > THRESHOLDS["axle_diff"]:
        issues.append({"type": "轴重差超限", "detail": f"轴重差{axle_diff}{UNIT}（阈值{THRESHOLDS['axle_diff']}{UNIT}）"})

    return {
        "wheels": wheels,            # 台号 -> 轮重(kN)
        "wheel_diff": wheel_diff,    # "a-b" -> 轮重差(kN)
        "axles": axles,              # "a-b" -> 轴重(kN)
        "axle_diff": axle_diff,      # 轴重差(kN)
        "total": total,              # 整车重(kN)
        "imbalance": issues,         # 不平衡检测问题列表
        "balanced": not issues,
        "missing": missing,
        "unit": UNIT,
    }
