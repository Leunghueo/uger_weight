'''
自定义安全保护器
- 举升轨高度差保护
- 加载缸压力/位移差保护
- 称重台载荷差保护
'''
import logging
from .core import GuardBase, GuardResult, register_guard


@register_guard("lift_rail", level="HIGH")
class LiftRailGuard(GuardBase):
    """举升轨高度差保护器"""
    desc = "监控四个举升轨高度,最大差值不允许超过配置限值"
    enabled = False

    def check(self) -> GuardResult | None:
        plc = self.plc
        if plc is None:
            return None

        values = [
            plc.read("举升轨高度1"),
            plc.read("举升轨高度2"),
            plc.read("举升轨高度3"),
            plc.read("举升轨高度4"),
        ]
        valid_values = [v for v in values if v is not None]
        if len(valid_values) < 2:
            return None

        diff = max(valid_values) - min(valid_values)

        wf = self.workflow
        if wf is None:
            return None
        limits = wf.data.get("安全检查", {})
        limit = limits.get("举升轨高度差限值", 50)

        if abs(diff) > limit:
            msg = f"举升轨高度差超限: {abs(diff):.2f} (限值: {limit})"
            logging.critical(msg)
            return GuardResult(
                name=self.name,
                level=self.level,
                message=msg,
                data={"values": values, "diff": abs(diff), "limit": limit},
            )
        return None


@register_guard("load_cylinder", level="HIGH")
class LoadCylinderGuard(GuardBase):
    """加载缸保护器"""
    desc = "监控加载压力与加载头位移差值,不允许超过配置限值"
    enabled = False

    def check(self) -> GuardResult | None:
        plc = self.plc
        if plc is None:
            return None

        p1 = plc.read("加载压力1")
        p2 = plc.read("加载压力2")
        d1 = plc.read("加载头垂向位移1")
        d2 = plc.read("加载头垂向位移2")

        wf = self.workflow
        if wf is None:
            return None
        limits = wf.data.get("安全检查", {})
        p_limit = limits.get("加载缸压差限值", 100)
        d_limit = limits.get("加载缸位移限值", 50)

        if p1 is not None and p2 is not None:
            p_diff = abs(p1 - p2)
            if p_diff > p_limit:
                msg = f"加载缸压力差超限: {p_diff:.2f} (限值: {p_limit})"
                logging.critical(msg)
                return GuardResult(
                    name=self.name,
                    level=self.level,
                    message=msg,
                    data={"p1": p1, "p2": p2, "diff": p_diff, "limit": p_limit},
                )

        if d1 is not None and d2 is not None:
            d_diff = abs(d1 - d2)
            if d_diff > d_limit:
                msg = f"加载缸位移差超限: {d_diff:.2f} (限值: {d_limit})"
                logging.critical(msg)
                return GuardResult(
                    name=self.name,
                    level=self.level,
                    message=msg,
                    data={"d1": d1, "d2": d2, "diff": d_diff, "limit": d_limit},
                )

        return None


@register_guard("weigh_load", level="HIGH")
class WeighLoadGuard(GuardBase):
    """称重台载荷保护器"""
    desc = "监控四个轮重测量数据,最大差值不允许超过配置限值"
    enabled = False

    def check(self) -> GuardResult | None:
        plc = self.plc
        if plc is None:
            return None

        values = [
            plc.read("轮重测量1"),
            plc.read("轮重测量2"),
            plc.read("轮重测量3"),
            plc.read("轮重测量4"),
        ]
        valid_values = [v for v in values if v is not None]
        if len(valid_values) < 2:
            return None

        diff = max(valid_values) - min(valid_values)

        wf = self.workflow
        if wf is None:
            return None
        limits = wf.data.get("安全检查", {})
        limit = limits.get("称重台载荷限值", 20)

        if abs(diff) > limit:
            msg = f"称重台载荷差超限: {abs(diff):.2f} (限值: {limit})"
            logging.critical(msg)
            return GuardResult(
                name=self.name,
                level=self.level,
                message=msg,
                data={"values": values, "diff": abs(diff), "limit": limit},
            )
        return None
