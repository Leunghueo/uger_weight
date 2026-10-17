from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime


class Window(QWidget):
    """输入数据表页面: 数据源为 vsp 列表(VSPTable)中的全部传感器点位."""

    _poll_signal = Signal(dict)

    # 简洁模式下隐藏的列: 分段系数(3)
    _HIDDEN_COLUMNS = (3,)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self.table = self.runtime.get("vsp")

        self._poll_signal.connect(self._apply_poll_update)

        self.setObjectName("plcDialog")
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)

        self._setup_ui()
        if self.table is not None:
            self._populate_pt_table()
            self._refresh_values()

        self._broker_subscriptions: list[object] = []
        self._subscribe()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh_values()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header_card = QFrame(self)
        header_card.setObjectName("homeStatusBar")
        status_row = QHBoxLayout(header_card)
        status_row.setContentsMargins(8, 6, 8, 6)
        status_row.setSpacing(6)

        self._status_label = QLabel("状态: 连接中", header_card)
        self._last_poll_label = QLabel("最后轮询: -", header_card)
        self._full_mode_checkbox = QCheckBox("完整模式", header_card)
        self._full_mode_checkbox.setToolTip("勾选后显示“分段系数”列")
        self._full_mode_checkbox.setChecked(False)
        self._full_mode_checkbox.toggled.connect(self._on_full_mode_toggled)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._full_mode_checkbox)
        status_row.addWidget(self._last_poll_label)
        root.addWidget(header_card)

        self._pt_table_in = QTableWidget(self)
        self._pt_table_in.setColumnCount(7)
        self._pt_table_in.setHorizontalHeaderLabels(["名称", "地址", "单位", "分段系数", "原始值", "计算值", "状态"])
        self._pt_table_in.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._pt_table_in.horizontalHeader().setStretchLastSection(True)
        self._pt_table_in.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pt_table_in.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pt_table_in.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pt_table_in.customContextMenuRequested.connect(self._show_pt_context_menu)
        self._pt_table_in.setAlternatingRowColors(True)
        self._pt_table_in.setStyleSheet("QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5; }")
        root.addWidget(self._pt_table_in, 1)

    def _populate_pt_table(self) -> None:
        if self.table is None:
            return
        self._pt_table_in.clearContents()
        self._pt_table_in.setRowCount(len(self.table.points))
        self._pt_row_map_in: dict[str, int] = {}
        for row, (name, pt) in enumerate(self.table.points.items()):
            addr = f"{pt.endpoint.host}@{pt.endpoint.port}"
            segs_obj = getattr(pt.config, "segs", None)
            segs_str = ";".join(f"{seg.source}@{seg.target}" for seg in segs_obj.segments) if segs_obj and segs_obj.segments else ""
            texts = [name, addr, pt.unit or "", segs_str, "-", "-", "-"]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._pt_table_in.setItem(row, col, item)
            self._pt_row_map_in[name] = row

        self._apply_column_visibility()

    def _apply_column_visibility(self) -> None:
        """按当前模式设置表格列可见性(简洁模式隐藏 分段系数 列)。"""
        full_mode = self._full_mode_checkbox.isChecked()
        header = self._pt_table_in.horizontalHeader()
        for col in self._HIDDEN_COLUMNS:
            header.setSectionHidden(col, not full_mode)

    def _on_full_mode_toggled(self, checked: bool) -> None:
        del checked
        self._apply_column_visibility()

    def _refresh_values(self) -> None:
        if self.table is None:
            return
        self._pt_table_in.setUpdatesEnabled(False)
        try:
            for name, row in list(self._pt_row_map_in.items()):
                calc_item = self._pt_table_in.item(row, 5)
                if calc_item is None:
                    continue
                pt = self.table.points.get(name)
                if pt is None:
                    continue

                raw_item = self._pt_table_in.item(row, 4)
                state_item = self._pt_table_in.item(row, 6)

                if raw_item is not None:
                    raw_text = str(pt.raw_value) if pt.raw_value is not None else "-"
                    if raw_item.text() != raw_text:
                        raw_item.setText(raw_text)

                if pt.value is None:
                    calc_text = "ERR"
                    calc_item.setForeground(QColor("#de4258"))
                else:
                    calc_text = str(pt.value)
                    calc_item.setForeground(self.palette().text().color())
                if calc_item.text() != calc_text:
                    calc_item.setText(calc_text)

                if state_item is not None:
                    state_text = "在线" if pt.alive else f"离线: {pt.error}" if pt.error else "离线"
                    if state_item.text() != state_text:
                        state_item.setText(state_text)
                        state_item.setForeground(QColor("#2e9e5b") if pt.alive else QColor("#de4258"))
        finally:
            self._pt_table_in.setUpdatesEnabled(True)

    def _show_pt_context_menu(self, pos) -> None:
        index = self._pt_table_in.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        name_item = self._pt_table_in.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        menu = QMenu(self)
        copy_action = QAction("复制点名", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(pt_name))
        menu.addAction(copy_action)
        reload_action = QAction("重载配置", menu)
        reload_action.triggered.connect(self._reload)
        menu.addAction(reload_action)
        menu.exec(self._pt_table_in.viewport().mapToGlobal(pos))

    @Slot(object)
    def _on_poll(self, **payload) -> None:
        # broker 在轮询线程上同步调用，emit Signal 让 Qt auto-queue 到主线程
        self._poll_signal.emit(dict(payload))

    @Slot(dict)
    def _apply_poll_update(self, payload: dict) -> None:
        connected = bool(payload.get("alive"))
        self._status_label.setText("状态: 在线" if connected else f'状态: 断开  {payload.get("error", "")}')
        ts = payload.get("last_poll_at")
        self._last_poll_label.setText(
            "最后轮询: " + datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "最后轮询: -"
        )
        self._refresh_values()

    def _reload(self) -> None:
        if self.table is None:
            return
        try:
            self.table.reload()
        except Exception:
            return
        self._populate_pt_table()
        self._refresh_values()

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("vsp_poll", self._on_poll),
        ]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
