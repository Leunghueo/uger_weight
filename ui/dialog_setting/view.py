from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

from _runtime import get_runtime
from ui.theme import THEME_NAMES, apply_theme


class Window(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self.setMinimumWidth(360)
        self._buttons: dict[str, QRadioButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(QLabel("主题设置", self))
        layout.addWidget(QLabel("切换后立即作用于当前程序，并写回 app.ini。", self))

        group = QButtonGroup(self)
        current_theme = str(self.runtime.get("theme", "light"))
        labels = {"light": "浅色主题", "dark": "深色主题"}

        for theme_name in THEME_NAMES:
            button = QRadioButton(labels[theme_name], self)
            button.setChecked(theme_name == current_theme)
            group.addButton(button)
            self._buttons[theme_name] = button
            layout.addWidget(button)

        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        actions.accepted.connect(self._apply_and_accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def _selected_theme(self) -> str:
        for theme_name, button in self._buttons.items():
            if button.isChecked():
                return theme_name
        return "light"

    def _apply_and_accept(self) -> None:
        app = QApplication.instance()
        if app is None:
            self.reject()
            return

        active_theme = apply_theme(app, self._selected_theme())
        self.runtime["theme"] = active_theme
        self.accept()
