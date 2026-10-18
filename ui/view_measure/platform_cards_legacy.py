"""旧版称重台卡片实现（备份，勿删）。

2026-10-18 起测量主页默认使用 2.5D 场景视图（platform_scene.py），
本模块保留旧版卡片实现，用于回退对比。样式仍由同目录 platform.qss 控制。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlatformWidget(QWidget):
    """单个称重台卡片：称重台X / 数值(1位小数) / kN。

    样式由同目录 platform.qss 控制（独立文件，方便后期调整）。
    """

    def __init__(self, platform: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.platform = platform
        self.setObjectName("platformCard")
        # QWidget 默认不按样式表绘制背景，需要这个属性
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumSize(92, 104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(2)

        self.title_label = QLabel(f"称重台{platform}")
        self.title_label.setObjectName("platTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.value_label = QLabel("--")
        self.value_label.setObjectName("platValue")
        self.value_label.setAlignment(Qt.AlignCenter)

        unit_label = QLabel("kN")
        unit_label.setObjectName("platUnit")
        unit_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(unit_label)
        self.set_highlight(False)

    def set_value(self, value: float | None) -> None:
        self.value_label.setText("--" if value is None else f"{value:.1f}")

    def set_highlight(self, on: bool) -> None:
        self.setProperty("highlighted", "true" if on else "false")
        # 动态属性变化后需要重新 polish 才能刷新样式
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()
