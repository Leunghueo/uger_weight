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


def _axle_key(a: int, b: int) -> str:
    return f"{a}-{b}"


def _spec_range(spec: dict | None, key: str) -> tuple[float, float] | None:
    """取校验数据 [min, max]；缺失或格式不对返回 None（跳过该项校验）。"""
    if not spec:
        return None
    raw = spec.get(key)
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        return float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None


def calculate(
    values: dict[int, float | None],
    enabled: list[int],
    spec: dict | None = None,
) -> dict[str, Any]:
    """六项计算。只统计 enabled 台号；缺数的台/轴如实记录。

    spec 为 maps.json 中车型的"校验数据"，格式如
    {"轮重": [100,200], "轮重差": [10,20], "轴重": [200,400],
     "轴重差": [10,20], "车重": [200,400], "平衡": [10,20]}。
    判定规则：
      轮重/轴重/车重：实测值须落在 [min, max] 内，否则记"超范围"；
      轮重差/轴重差/平衡：[warn, limit] 两级——超过 limit 记"超限"
        （不合格），介于 warn 与 limit 之间记"偏大"（预警，不判不合格）；
      平衡值 = |左侧(单数号台)总重 - 右侧(偶数号台)总重|。
    spec 为 None 或某项缺失时，退回 THRESHOLDS 旧规则。

    依据 GB/T 3317-2006 4.2.4（机车全整备状态）：
      d) 每轮轮重与该轴两轮平均轮重之差 ≤ 轴平均轮重的 ±4%
         → 轮重差(|左-右|) ≤ 轴平均轮重的 8%；
      b) 每轴实际轴重与平均轴重之差 ≤ 平均轴重的 ±2%
         → 轴重差(max-min) ≤ 平均轴重的 4%；
      a) 机车总重允差 ±3%。
    国标给出的是百分比准则；本函数采用 maps.json 校验数据的绝对
    [min, max] 作为工程判定参数。
    """
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
    # 平衡值 = |左侧(单数号台)总重 - 右侧(偶数号台)总重|
    left_total = sum(v for p, v in values.items()
                     if p in enabled_set and p % 2 == 1 and v is not None)
    right_total = sum(v for p, v in values.items()
                      if p in enabled_set and p % 2 == 0 and v is not None)
    balance_value = round(abs(left_total - right_total), 3)

    issues: list[dict[str, str]] = []
    failed = False

    def _flag(fail: bool, issue_type: str, detail: str) -> None:
        nonlocal failed
        issues.append({"type": issue_type, "detail": detail})
        if fail:
            failed = True

    def _check_range(name: str, value: float, spec_key: str, label: str) -> None:
        """[min, max] 范围校验。"""
        rng = _spec_range(spec, spec_key)
        if rng is None:
            return
        lo, hi = rng
        if not (lo <= value <= hi):
            _flag(True, f"{name}超范围",
                  f"{label}{value}{UNIT}超出[{lo:g},{hi:g}]{UNIT}")

    def _check_diff(name: str, value: float, spec_key: str, label: str,
                    legacy_key: str) -> None:
        """差值两级校验；无 spec 时用 THRESHOLDS 单阈值。"""
        rng = _spec_range(spec, spec_key)
        if rng is None:
            limit = THRESHOLDS[legacy_key]
            if value > limit:
                _flag(True, f"{name}超限", f"{label}{value}{UNIT}（阈值{limit:g}{UNIT}）")
            return
        warn, limit = rng
        if value > limit:
            _flag(True, f"{name}超限", f"{label}{value}{UNIT}（超限{limit:g}{UNIT}）")
        elif value > warn:
            _flag(False, f"{name}偏大", f"{label}{value}{UNIT}（预警{warn:g}{UNIT}）")

    for p in missing:
        _flag(True, "采集异常", f"称重台{p}无数据")

    for p in sorted(enabled_set):
        v = values.get(p)
        if v is not None:
            _check_range("轮重", v, "轮重", f"称重台{p}轮重")
    for key, d in wheel_diff.items():
        _check_diff("轮重差", d, "轮重差", f"轴{key}轮重差", "wheel_diff")
    for key, a_val in axles.items():
        _check_range("轴重", a_val, "轴重", f"轴{key}轴重")
    if len(axle_values) >= 2:
        _check_diff("轴重差", axle_diff, "轴重差", "轴重差", "axle_diff")
    _check_range("车重", total, "车重", "整车重")
    _check_diff("平衡", balance_value, "平衡", "平衡值(|左-右|)", "axle_diff")

    return {
        "wheels": wheels,            # 台号 -> 轮重(kN)
        "wheel_diff": wheel_diff,    # "a-b" -> 轮重差(kN)
        "axles": axles,              # "a-b" -> 轴重(kN)
        "axle_diff": axle_diff,      # 轴重差(kN)
        "total": total,              # 整车重(kN)
        "balance": balance_value,    # 平衡值 = |左侧(单数号)总重 - 右侧(偶数号)总重|(kN)
        "imbalance": issues,         # 不平衡检测问题列表
        "balanced": not failed,
        "missing": missing,
        "unit": UNIT,
    }
