from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QVBoxLayout

from _runtime import get_runtime

from .dialog_about.view import Window as AboutDialog
from .dialog_plc.view import Window as DataView
from .view_history.view import Window as HistoryView
from .wgt_jsoner import JsonEditorWidget
from .dialog_user.view import Window as UserDialog


class BogieSetting(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["bogie_config"])
        layout.addWidget(self.json_editor)


class VspSetting(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["vsp_config"])
        layout.addWidget(self.json_editor)

class BedSetting(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["bed_config"])
        layout.addWidget(self.json_editor)

class PushSetting(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.json_editor = JsonEditorWidget(source=get_runtime()["paths"]["push_config"])
        layout.addWidget(self.json_editor)

VIEWS = {
    # "view_ai": {"title": "AI助手", "obj": AiView},
    # "view_home": {"title": "试验流程", "obj": HomeView},
    # "view_flow": {"title": "流程浏览器", "obj": FlowView},
    "view_plc": {"title": "输入数据表", "obj": DataView},
    "view_history": {"title": "历史记录", "obj": HistoryView},
    # "view_dyn_dims": {"title": "实时数据", "obj": DynDimsView},
    # "view_airplot": {"title": "气压曲线", "obj": AirplotView},
    "dialog_bogie_setting": {"title": "转向架设置", "obj": BogieSetting},
    "dialog_bed_setting": {"title": "实验台设置", "obj": BedSetting},
    # "dialog_plc_setting": {"title": "PLC设置", "obj": PlcSetting},
    # "dialog_vsp_setting": {"title": "VSP设置", "obj": VspSetting},
    "dialog_push_setting": {"title": "信息化设置", "obj": PushSetting},
    "dialog_user_admin": {"title": "用户管理", "obj": UserDialog},
    "dialog_about": {"title": "关于", "obj": AboutDialog},
}

MENUS = {
    "设置": [
        {
            "title": "转向架设置",
            "icon": "setting.png",
            "view_id": "dialog_bogie_setting",
            "pop": False,
            "fixed": False,
            "admin": True,
        },
        {
            "title": "静载试验台设置",
            "icon": "setting.png",
            "view_id": "dialog_bed_setting",
            "pop": False,
            "fixed": False,
            "admin": True,
        },
        # {
        #     "title": "PLC设置",
        #     "icon": "setting.png",
        #     "view_id": "dialog_plc_setting",
        #     "pop": False,
        #     "fixed": False,
        #     "admin": True,
        # },
        # {
        #     "title": "VSP设置",
        #     "icon": "setting.png",
        #     "view_id": "dialog_vsp_setting",
        #     "pop": False,
        #     "fixed": False,
        #     "admin": True,
        # },
        {
            "title": "信息化设置",
            "icon": "setting.png",
            "view_id": "dialog_push_setting",
            "pop": False,
            "fixed": False,
            "admin": True,
        },
    ],
    "工具": [
        {
            "title": "历史记录",
            "icon": "info.png",
            "view_id": "view_history",
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
        "window_title": "XLT 转向架静载程序",
        "default_view_id": "view_plc",
        "views": VIEWS,
        "menus": MENUS,
    }
