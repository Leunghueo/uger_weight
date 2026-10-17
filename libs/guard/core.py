'''
设备运行安全模块 `guard`
核心功能：负责全局安全模块的注册/加载/运行等管理
'''
from dataclasses import dataclass
from typing import Any, Callable

_runtime: dict[str, Any] | None = None


@dataclass
class GuardResult:
    """安全检查结果"""
    name: str           # 子方法名称
    level: str          # 异常等级: critical/warning/info
    message: str | None = None  # 异常详情
    data: dict | None = None    # 附加数据


class GuardBase:
    """
    安全检查子方法基类
    所有安全检查子方法必须继承此类
    """
    name: str = ""
    level: str = "warning"
    enabled: bool = True
    desc: str = ""
    data: dict = {}

    @property
    def runtime(self) -> dict[str, Any] | None:
        """获取 runtime 全局变量"""
        return _runtime

    @property
    def plc(self):
        """获取 PLC 实例"""
        if _runtime is None:
            return None
        return _runtime.get("plc")

    @property
    def vsp(self):
        """获取 VSP 实例"""
        if _runtime is None:
            return None
        return _runtime.get("vsp")

    @property
    def broker(self):
        """获取消息总线实例"""
        if _runtime is None:
            return None
        return _runtime.get("broker")

    @property
    def workflow(self):
        """获取当前 workflow 实例"""
        if _runtime is None:
            return None
        return _runtime.get("wf")

    def check(self) -> GuardResult | None:
        """
        执行安全检查（无参数版本）
        通过 self.plc / self.vsp / self.broker / self.workflow 访问运行时数据

        返回 None 表示安全
        返回 GuardResult 表示异常
        """
        raise NotImplementedError


# 内部注册表
_GUARD_REGISTRY: dict[str, GuardBase] = {}

def init(runtime: dict[str, Any]) -> None:
    """
    初始化 guard 模块，传入 runtime
    应在程序启动后、主循环前调用
    """
    global _runtime
    _runtime = runtime


def register_guard(name: str, level: str = "warning") -> Callable:
    """
    装饰器：注册安全子方法
    用法：
        @register_guard("demo", level="critical")
        class DemoGuard(GuardBase):
            def check(self):
                ...
    """
    def decorator(cls: type[GuardBase]) -> type[GuardBase]:
        instance = cls()
        instance.name = name
        instance.level = level
        _GUARD_REGISTRY[name] = instance
        return cls
    return decorator


def get_guard(name: str) -> GuardBase | None:
    """获取指定安全检查子方法"""
    return _GUARD_REGISTRY.get(name)


def list_guards() -> dict[str, GuardBase]:
    """列出所有已注册的安全检查子方法"""
    return _GUARD_REGISTRY.copy()


def set_guard(name: str, enable: bool, data:dict) -> bool:
    """开启指定安全检查子方法"""
    guard = _GUARD_REGISTRY.get(name)
    if guard is None:
        return False
    guard.enabled = enable
    guard.data = data
    return True


def is_guard_enabled(name: str) -> bool:
    """检查指定安全检查子方法是否启用"""
    guard = _GUARD_REGISTRY.get(name)
    if guard is None:
        return False
    return guard.enabled


def guard_check() -> None:
    """
    核心方法：执行所有安全检查
    遍历所有已启用的安全子方法，收集检查结果

    调用点：src/libs/plc/core.py 的 poll_loop 中

    返回:
        GuardResult 列表（仅包含异常结果）
    """
    risks: list[GuardResult] = []

    for name, guard in _GUARD_REGISTRY.items():
        if not guard.enabled:
            continue
        result = guard.check()
        if result is not None:
            risks.append(result)
            # 此处已经上报警告, 如果是HIGH,则立马把自己disable,避免上层一直记录,日志爆炸,
            if result.level=="HIGH":
                guard.enabled=False 

    if len(risks)>0:
        _runtime.get("broker").publish(
            topic="msg_guard",
            risks=risks
        )
