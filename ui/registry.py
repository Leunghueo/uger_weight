"""页面注册中心.

约定:
    VIEWS[view_id] = {"title": 标题, "obj": 无参构造的 QWidget/QDialog 子类}
    MENUS[菜单名]  = [{"title", "icon", "view_id", "pop", "fixed", "admin"}]
    pop=True  -> 以对话框形式打开；pop=False -> 以标签页形式打开
    admin=True -> 仅管理员可见/可开
"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QVBoxLayout

from _runtime import get_runtime
from dialog_fit import FitLauncher

from .dialog_about.view import Window as AboutDialog
from .view_measure.view import MeasureView
from .view_records.view import RecordsView
from .wgt_jsoner import JsonEditorWidget
from .dialog_user.view import Window as UserDialog


class VspSetting(QDialog):
    """VSP 采集点位配置（jsoneditor）。"""

    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["vsp_config"])
        layout.addWidget(self.json_editor)


class MapsSetting(QDialog):
    """车型-称重台映射配置（jsoneditor）。"""

    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["maps_config"])
        layout.addWidget(self.json_editor)


VIEWS = {
    "view_measure": {"title": "称重测量", "obj": MeasureView},
    "view_records": {"title": "测量记录", "obj": RecordsView},
    "dialog_vsp_setting": {"title": "VSP配置", "obj": VspSetting},
    "dialog_maps_setting": {"title": "车型台位配置", "obj": MapsSetting},
    "dialog_fit_setting": {"title": "标定设置", "obj": FitLauncher},
    "dialog_user_admin": {"title": "用户管理", "obj": UserDialog},
    "dialog_about": {"title": "关于", "obj": AboutDialog},
}

MENUS = {
    "设置": [
        {
            "title": "VSP配置",
            "icon": "setting.png",
            "view_id": "dialog_vsp_setting",
            "pop": False,
            "fixed": False,
            "admin": True,
        },
        {
            "title": "车型台位配置",
            "icon": "setting.png",
            "view_id": "dialog_maps_setting",
            "pop": False,
            "fixed": False,
            "admin": True,
        },
        {
            "title": "标定设置",
            "icon": "setting.png",
            "view_id": "dialog_fit_setting",
            "pop": True,
            "fixed": False,
            "admin": True,
        },
    ],
    "工具": [
        {
            "title": "测量记录",
            "icon": "info.png",
            "view_id": "view_records",
            "pop": False,
            "fixed": False,
            "admin": False,
        },
        {
            "title": "用户管理",
            "icon": "info.png",
            "view_id": "dialog_user_admin",
            "pop": True,
            "fixed": False,
            "admin": True,
        },
    ],
    "帮助": [
        {
            "title": "关于",
            "icon": "about.png",
            "view_id": "dialog_about",
            "pop": True,
            "fixed": False,
            "admin": False,
        },
    ],
}


def load_ui_registry() -> dict[str, Any]:
    return {
        "window_title": "称重测量系统",
        "default_view_id": "view_measure",
        "views": VIEWS,
        "menus": MENUS,
    }
