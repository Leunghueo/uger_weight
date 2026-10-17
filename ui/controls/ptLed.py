from __future__ import annotations

from PySide6.QtCore import Qt, Signal

from typing import Callable
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from _runtime import get_runtime


class PtLed(QFrame):
    """
    兼容 BOOL 和数值型(INT/REAL/WORD)的 PLC 点位状态显示器。

    + BOOL: 显示方式为 `名称 | LED灯 | ON/OFF` (红色=ON, 灰色=OFF)
    + 其他: 显示方式为 `名称 | 数字 | 单位`
    + 读取失败: 显示 ERR (黄色)
    """

    _COLOR_ON = "#ff0000"
    _COLOR_OFF = "#808080"
    _COLOR_ERR = "#ffd700"

    afterUpdate = Signal(str)

    def __init__(
        self,
        pt_name: str,
        layout: str = "上下",
        parent: QWidget | None = None,
        title: str = "",
    ) -> None:
        super().__init__(parent)
        self._pt_name = pt_name
        self._title_text = title or pt_name
        self._layout_dir = layout
        self._overridden = False

        self._setup_ui()
        self._set_err_state()

    def _setup_ui(self) -> None:
        self.setObjectName("ptLed")

        if self._layout_dir in ("左右", "horizontal", "h"):
            root = QHBoxLayout(self)
        else:
            root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignCenter)

        # 点位名称标签
        self._title_label = QLabel(self._title_text, self)
        self._title_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title_label)

        # BOOL 专用的 LED 圆点
        self._led = QLabel(self)
        self._led.setFixedSize(16, 16)
        self._led.setObjectName("ptLedIndicator")
        self._led.setVisible(False)
        root.addWidget(self._led, 0, Qt.AlignCenter)

        # BOOL 专用的状态文字 ON/OFF
        self._status_label = QLabel("ERR", self)
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        # 数值类型专用的数值+单位显示
        self._value_label = QLabel("ERR", self)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setVisible(False)
        root.addWidget(self._value_label)

    # ------------------------------------------------------------------ #
    # 状态切换
    # ------------------------------------------------------------------ #
    def _switch_mode(self, mode: str) -> None:
        """切换显示模式: bool | numeric"""
        is_bool = mode == "bool"
        self._led.setVisible(is_bool)
        self._status_label.setVisible(is_bool)
        self._value_label.setVisible(not is_bool)

    def _set_bool_state(self, is_on: bool) -> None:
        """更新 BOOL 状态外观"""
        self._switch_mode("bool")
        color = self._COLOR_ON if is_on else self._COLOR_OFF
        self._led.setStyleSheet(
            f"QLabel#ptLedIndicator {{"
            f"  border-radius: 8px;"
            f"  border: 1px solid rgba(0, 0, 0, 0.2);"
            f"  background-color: {color};"
            f"}}"
        )
        self._status_label.setText("ON" if is_on else "OFF")
        self._status_label.setStyleSheet(
            f"color: {color}; font-weight: bold;"
        )
        self._title_label.setText(self._title_text)
        self._title_label.setStyleSheet("")

    def _set_numeric_state(self, value_str: str) -> None:
        """更新数值状态外观"""
        self._switch_mode("numeric")
        self._value_label.setText(value_str)
        self._value_label.setStyleSheet("font-weight: bold;")
        self._title_label.setText(self._title_text)
        self._title_label.setStyleSheet("")

    def _set_err_state(self) -> None:
        """更新错误状态外观"""
        # 默认切换到布尔型布局来显示 ERR，保持外观统一
        self._switch_mode("bool")
        self._led.setStyleSheet(
            f"QLabel#ptLedIndicator {{"
            f"  border-radius: 8px;"
            f"  border: 1px solid rgba(0, 0, 0, 0.2);"
            f"  background-color: {self._COLOR_ERR};"
            f"}}"
        )
        self._status_label.setText("ERR")
        self._status_label.setStyleSheet(
            f"color: {self._COLOR_ERR}; font-weight: bold;"
        )
        self._title_label.setText(self._title_text)
        self._title_label.setStyleSheet("")

    # ------------------------------------------------------------------ #
    # 公共方法
    # ------------------------------------------------------------------ #
    def set_display(self, text: str) -> None:
        """
        外部可调用此方法强制覆盖显示内容。
        常用于 afterUpdate 信号的槽函数中进行数据转换后再显示。
        """
        self._overridden = True
        if text == "ON":
            self._set_bool_state(True)
        elif text == "OFF":
            self._set_bool_state(False)
        elif text == "ERR":
            self._set_err_state()
        else:
            self._set_numeric_state(text)

    def _handle_display(self, display_text: str, default_action: Callable[[], None]) -> None:
        """发射 afterUpdate 信号，并在未被槽函数覆盖时执行默认显示动作。"""
        self._overridden = False
        self.afterUpdate.emit(display_text)
        if not self._overridden:
            default_action()

    def update(self) -> None:
        """读取 PLC 点位，自动判断类型并更新控件外观。"""
        runtime = get_runtime()
        plc = runtime.get("plc")
        if plc is None:
            self._handle_display("ERR", self._set_err_state)
            return

        try:
            point = plc.points.get(self._pt_name)
            if point is None:
                self._handle_display("ERR", self._set_err_state)
                return

            value = plc.read(self._pt_name)
            if value is None:
                self._handle_display("ERR", self._set_err_state)
                return

            if point.point_type == "BOOL":
                display_text = "ON" if bool(value) else "OFF"
                self._handle_display(display_text, lambda: self._set_bool_state(bool(value)))
            else:
                # INT/REAL/WORD 统一按数值格式化
                if isinstance(value, float):
                    display_val = f"{value:.1f}"
                else:
                    display_val = str(value)
                unit = point.unit or ""
                full_text = f"{display_val} {unit}".strip()
                self._handle_display(full_text, lambda: self._set_numeric_state(full_text))
        except Exception:
            self._handle_display("ERR", self._set_err_state)
