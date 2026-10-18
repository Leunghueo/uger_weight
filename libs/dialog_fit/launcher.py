"""标定设置入口：先选点位，再打开该点位的分段标定弹窗。"""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

from _runtime import get_runtime

from .view import Window


def _sort_key(name: str) -> tuple:
    m = re.search(r"\d+", name)
    return (int(m.group()), name) if m else (10**9, name)


class FitLauncher(QDialog):
    """点位选择器；确定后打开对应点位的标定弹窗。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("标定设置")
        self.resize(280, 420)

        runtime = get_runtime()
        table = runtime.get("vsp")
        names = sorted(table.points.keys(), key=_sort_key) if table else []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要标定的称重台点位："))
        self.list = QListWidget(self)
        self.list.addItems(names)
        if names:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_point(self) -> str | None:
        item = self.list.currentItem()
        return item.text() if item else None

    def accept(self) -> None:  # type: ignore[override]
        pt_name = self.selected_point()
        super().accept()
        if pt_name:
            dlg = Window(pt_name, parent=self.parent())
            dlg.exec()
