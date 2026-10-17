'''
guard 模块 - 设备运行安全模块
'''
from .core import (
    GuardBase,
    GuardResult,
    register_guard,
    init,
    get_guard,
    list_guards,
    set_guard,
    is_guard_enabled,
    guard_check,
)

# 自动加载所有子模块
import importlib
import pkgutil

for _importer, modname, _ispkg in pkgutil.iter_modules(__path__):
    if modname != "core" and modname != "__init__":
        importlib.import_module(f".{modname}", __package__)

__all__ = [
    "GuardBase",
    "GuardResult",
    "register_guard",
    "init",
    "get_guard",
    "list_guards",
    "enable_guard",
    "disable_guard",
    "is_guard_enabled",
    "msg_guard",
]