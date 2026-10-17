'''
安全检查子方法示例
'''
from .core import GuardBase, GuardResult, register_guard


@register_guard("demo", level="HIGH")
class DemoGuard(GuardBase):
    """演示用安全检查"""
    desc = "演示安全检查"
    enabled = False  # 默认关闭

    def check(self) -> GuardResult | None:
        dp = self.plc.read("加载压力1")- self.data.get("加载压力1")
        p_lim = self.workflow.data.get("安全检查").get('压力波动上限')
        if abs(dp)>p_lim:
            return GuardResult(
                name=self.name,
                level=self.level,
                message=f"保压过程中压力超限:{dp}",
                data=None
            )
        return None