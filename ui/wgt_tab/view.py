from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabBar, QTabWidget


class TabWidget(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view_states: list[dict[str, object]] = []
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.tabBar().setSelectionBehaviorOnRemove(QTabBar.SelectPreviousTab)
        self.tabCloseRequested.connect(self.close_tab)

    def find_view(self, view_id: str) -> int:
        for index, item in enumerate(self.view_states):
            if item["view_id"] == view_id:
                return index
        return -1

    def create_tab(self, *, widget, title: str, view_id: str, fixed: bool) -> int:
        index = self.addTab(widget, title)
        self.view_states.insert(index, {"view_id": view_id, "fixed": fixed})
        if fixed:
            self.tabBar().setTabButton(index, QTabBar.RightSide, None)
        self.setCurrentIndex(index)
        return index

    def close_tab(self, index: int) -> None:
        if index < 0 or index >= len(self.view_states):
            return
        if bool(self.view_states[index]["fixed"]):
            return
        widget = self.widget(index)
        self.removeTab(index)
        self.view_states.pop(index)
        if widget is not None:
            widget.deleteLater()
