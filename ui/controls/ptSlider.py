from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QWidget

from _runtime import get_runtime


class PtSlider(QFrame):
    """
    用于将整数写入 Int 类型的 PLC 点位。
    使用 QLineEdit 进行数值输入，带有 min/max 校验，
    失去焦点（或回车）时触发写入动作。
    """

    _COLOR_ERR = "#ffd700"

    def __init__(
        self,
        pt_name: str,
        min: int = 0,
        max: int = 100,
        step: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pt_name = pt_name
        self._min_val = min
        self._max_val = max
        self._step = step

        self._setup_ui()
        self._set_err_state()

    def _setup_ui(self) -> None:
        self.setObjectName("ptSlider")

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignVCenter)

        # 点位名称标签
        self._title_label = QLabel(self._pt_name, self)
        root.addWidget(self._title_label)

        # 数值输入框
        self._input = QLineEdit(self)
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setValidator(QIntValidator(self._min_val, self._max_val, self))
        self._input.setFixedWidth(80)
        self._input.editingFinished.connect(self._on_editing_finished)
        root.addWidget(self._input)

    def _set_err_state(self) -> None:
        """将输入框置为 ERR 状态（黄色文字）。"""
        self._input.setText("ERR")
        self._input.setStyleSheet(f"color: {self._COLOR_ERR}; font-weight: bold;")

    def _clear_err_state(self, text: str) -> None:
        """清除错误样式并恢复显示文本。"""
        self._input.setText(text)
        self._input.setStyleSheet("")

    def _on_editing_finished(self) -> None:
        """失去焦点或回车时触发写入。"""
        text = self._input.text().strip()

        # 空值时取消写入，恢复当前 PLC 值
        if not text:
            self.update()
            return

        val: int | None = None
        if self._input.hasAcceptableInput():
            try:
                val = int(text)
            except ValueError:
                pass
        else:
            # 可能超出范围，尝试解析并 clamp 到边界
            try:
                raw = int(text)
                val = max(self._min_val, min(raw, self._max_val))
                self._input.setText(str(val))
            except ValueError:
                pass

        if val is None:
            self.update()
            return

        runtime = get_runtime()
        plc = runtime.get("plc")
        if plc is None:
            self._set_err_state()
            return

        try:
            plc.write(self._pt_name, val)
        except Exception:
            self._set_err_state()

    def update(self) -> None:
        """读取 PLC 点位并更新输入框显示值。"""
        runtime = get_runtime()
        plc = runtime.get("plc")
        if plc is None:
            self._set_err_state()
            return

        try:
            raw = plc.read(self._pt_name)
            if raw is None:
                self._set_err_state()
            else:
                val = int(round(float(raw)))
                self._clear_err_state(str(val))
        except Exception:
            self._set_err_state()
