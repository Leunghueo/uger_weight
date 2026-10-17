from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from _runtime import get_runtime


class PtToggle(QFrame):
    """
    用于显示 Bool 类型且 io 为输出的 PLC 点位状态，并可进行写入操作。
    灰色=False, 红色=True; 点击切换时触发写入，写入后延时回读并更新控件状态。
    """

    _COLOR_ON = "#ff0000"
    _COLOR_OFF = "#808080"
    _COLOR_ERR = "#ffd700"
    _READBACK_DELAY_MS = 1000

    def __init__(
        self,
        pt_name: str,
        update: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pt_name = pt_name
        self._update = update

        self._setup_ui()
        self._set_state("err")
        self.setCursor(Qt.PointingHandCursor)

    def _setup_ui(self) -> None:
        self.setObjectName("ptToggle")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignCenter)

        # 点位名称标签
        self._title_label = QLabel(self._pt_name, self)
        self._title_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title_label)

        # 圆形状态指示灯
        self._indicator = QLabel(self)
        self._indicator.setFixedSize(24, 24)
        self._indicator.setObjectName("ptToggleIndicator")
        root.addWidget(self._indicator, 0, Qt.AlignCenter)

        # 状态文字 ON/OFF/ERR
        self._status_label = QLabel("ERR", self)
        self._status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._status_label)

    def _set_state(self, state: str) -> None:
        """更新控件状态外观。state: on | off | err"""
        if state == "on":
            color = self._COLOR_ON
            text = "ON"
        elif state == "off":
            color = self._COLOR_OFF
            text = "OFF"
        else:
            color = self._COLOR_ERR
            text = "ERR"

        self._indicator.setStyleSheet(
            f"QLabel#ptToggleIndicator {{"
            f"  border-radius: 12px;"
            f"  border: 1px solid rgba(0, 0, 0, 0.2);"
            f"  background-color: {color};"
            f"}}"
        )
        self._status_label.setText(text)

        if state == "on":
            self._status_label.setStyleSheet(
                f"color: {self._COLOR_ON}; font-weight: bold;"
            )
        elif state == "off":
            self._status_label.setStyleSheet(
                f"color: {self._COLOR_OFF}; font-weight: bold;"
            )
        else:
            self._status_label.setStyleSheet(
                f"color: {self._COLOR_ERR}; font-weight: bold;"
            )

    def update(self) -> None:
        """读取 PLC 点位并更新控件外观。"""
        runtime = get_runtime()
        plc = runtime.get("plc")
        if plc is None:
            self._set_state("err")
            return

        try:
            value = plc.read(self._pt_name)
            if value is None:
                self._set_state("err")
            else:
                self._set_state("on" if bool(value) else "off")
        except Exception:
            self._set_state("err")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """点击时触发状态翻转写入。"""
        self._on_toggle()
        super().mousePressEvent(event)

    def _on_toggle(self) -> None:
        """内部写入逻辑：读取当前值 -> 取反 -> 写入 -> 延时回读。"""
        runtime = get_runtime()
        plc = runtime.get("plc")
        if plc is None:
            self._set_state("err")
            return

        try:
            current = plc.read(self._pt_name)
            current_bool = bool(current) if current is not None else False
            new_value = not current_bool

            plc.write(self._pt_name, new_value)

            if self._update:
                QTimer.singleShot(self._READBACK_DELAY_MS, self.update)
            else:
                self.update()
        except Exception:
            self._set_state("err")
