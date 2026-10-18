"""VSP 点位分段标定设置弹窗。

功能：为单个 VSP 点位设置分段线性标定（segs）与偏移（add）。

- 标定点表：每行一个标定点 "采集值 -> 计算值"，对应 vsp.json 中
  该点位的 segs 列表（格式 "采集值@计算值"）。
- 分段标定图：把标定点连成折线，直观展示换算曲线。
- 偏移(add)：换算后的整体偏移，真值 = segs(采集值) + add。
- 标零：读取当前真值，预填可将其清零的 add（仅预填，需点保存生效）。
- 保存：校验后经 VSPTable.update_by_id 写回 vsp.json，并即时更新
  运行中的点位对象（下一次轮询即按新参数换算）。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QRectF, QLocale
from PySide6.QtGui import QColor, QDoubleValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime


class SegChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[tuple[float, float]] = []
        self.setMinimumSize(320, 240)

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self._points = list(points)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        plot = self.rect().adjusted(24, 16, -16, -24)
        painter.setPen(QPen(QColor("#d9d9d9"), 1))
        painter.drawRect(plot)

        axis_pen = QPen(QColor("#9aa3ad"), 1)
        painter.setPen(axis_pen)
        painter.drawLine(plot.left(), plot.bottom(), plot.right(), plot.bottom())
        painter.drawLine(plot.left(), plot.top(), plot.left(), plot.bottom())

        if not self._points:
            painter.setPen(QColor("#6b7280"))
            painter.drawText(plot, Qt.AlignCenter, "标定点")
            return

        points = sorted(self._points, key=lambda item: item[0])
        x_values = [0.0] + [item[0] for item in points]
        y_values = [0.0] + [item[1] for item in points]
        min_x, max_x = min(x_values), max(x_values)
        min_y, max_y = min(y_values), max(y_values)

        if min_x == max_x:
            max_x = min_x + 1.0
        if min_y == max_y:
            max_y = min_y + 1.0

        def map_point(x_value: float, y_value: float) -> QPointF:
            x_ratio = (x_value - min_x) / (max_x - min_x)
            y_ratio = (y_value - min_y) / (max_y - min_y)
            return QPointF(
                plot.left() + x_ratio * plot.width(),
                plot.bottom() - y_ratio * plot.height(),
            )

        painter.setPen(QPen(QColor("#2563eb"), 2))
        anchors = [(0.0, 0.0)] + points
        for left, right in zip(anchors, anchors[1:], strict=False):
            painter.drawLine(map_point(*left), map_point(*right))

        painter.setPen(QPen(QColor("#dc2626"), 6))
        for point in points:
            painter.drawPoint(map_point(*point))

        painter.setPen(QColor("#374151"))
        painter.drawText(QRectF(plot.left(), 0, 120, 16), "采集值")
        painter.save()
        painter.translate(10, plot.top() + 60)
        painter.rotate(-90)
        painter.drawText(QRectF(0, 0, 120, 16), "计算值")
        painter.restore()


class Window(QDialog):
    """单个 VSP 点位的分段标定弹窗。pt_name 如 "台1"。"""

    def __init__(self, pt_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self.pt_name = pt_name
        self._raw_point: dict | None = None
        self._point_obj = None
        self._config_path: Path | None = None
        self._build_target_context()
        self._build_ui()
        self._load_table()
        self._refresh_chart()

    def _build_target_context(self) -> None:
        table = self.runtime.get("vsp")
        if table is None:
            raise RuntimeError("VSP 未启用，无法标定")
        config_path = Path(self.runtime["paths"]["vsp_config"]).resolve()
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        raw_points = payload.get("pts") or {}
        raw_point = raw_points.get(self.pt_name)
        if raw_point is None:
            raise KeyError(f"vsp.{self.pt_name} not found")
        if raw_point.get("segs") is None:
            raise ValueError(f"vsp.{self.pt_name} does not support segs editing")

        point_obj = table.points.get(self.pt_name)
        if point_obj is None:
            raise KeyError(f"vsp.{self.pt_name} not loaded")

        self._raw_point = raw_point
        self._point_obj = point_obj
        self._config_path = config_path

    def _build_ui(self) -> None:
        self.setWindowTitle(f"标定设置 - {self.pt_name}")
        self.setModal(True)
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        info_card = QFrame(self)
        info_card.setFrameShape(QFrame.StyledPanel)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(6)

        info_title = QLabel("标定点位信息", info_card)
        info_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        info_layout.addWidget(info_title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(6)
        self.source_label = QLabel("VSP", info_card)
        self.name_label = QLabel(self.pt_name, info_card)
        self.addr_label = QLabel(self._point_address(), info_card)
        self.unit_label = QLabel(self._point_obj.unit or "-", info_card)
        self.add_edit = QLineEdit(info_card)
        self.add_edit.setPlaceholderText("0")
        self.add_validator = QDoubleValidator(-100000.0, 100000.0, 3, self.add_edit)
        self.add_validator.setNotation(QDoubleValidator.StandardNotation)
        self.add_validator.setLocale(QLocale.c())
        self.add_edit.setValidator(self.add_validator)

        add_layout = QHBoxLayout()
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(self.add_edit)
        self.zero_btn = QPushButton("标零", info_card)
        self.zero_btn.clicked.connect(self._on_zero_btn_clicked)
        add_layout.addWidget(self.zero_btn)

        form.addRow("来源:", self.source_label)
        form.addRow("名称:", self.name_label)
        form.addRow("地址:", self.addr_label)
        form.addRow("单位:", self.unit_label)
        form.addRow("偏移(add):", add_layout)
        info_layout.addLayout(form)
        root.addWidget(info_card)

        body = QSplitter(Qt.Horizontal, self)
        body.setChildrenCollapsible(False)

        table_card = QFrame(body)
        table_card.setFrameShape(QFrame.StyledPanel)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(8)

        table_title = QLabel("标定点", table_card)
        table_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        table_layout.addWidget(table_title)

        self.table = QTableWidget(0, 2, table_card)
        self.table.setHorizontalHeaderLabels(["采集值", "计算值"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._on_table_changed)
        table_layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        self.add_btn = QPushButton("添加标定点", table_card)
        self.remove_btn = QPushButton("删除标定点", table_card)
        self.add_btn.clicked.connect(self._add_seg)
        self.remove_btn.clicked.connect(self._remove_seg)
        action_row.addWidget(self.add_btn)
        action_row.addWidget(self.remove_btn)
        action_row.addStretch(1)
        table_layout.addLayout(action_row)
        body.addWidget(table_card)

        chart_card = QFrame(body)
        chart_card.setFrameShape(QFrame.StyledPanel)
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(10, 10, 10, 10)
        chart_layout.setSpacing(8)

        chart_title = QLabel("分段标定图", chart_card)
        chart_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        chart_layout.addWidget(chart_title)

        self.chart = SegChartWidget(chart_card)
        chart_layout.addWidget(self.chart, 1)
        body.addWidget(chart_card)
        body.setSizes([280, 520])
        root.addWidget(body, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_btn = QPushButton("保存", self)
        self.save_btn.clicked.connect(self._save)
        footer.addWidget(self.save_btn)
        root.addLayout(footer)

    def _point_address(self) -> str:
        assert self._raw_point is not None
        return str(self._raw_point.get("port") or self._raw_point.get("addr") or "-")

    def _load_table(self) -> None:
        assert self._raw_point is not None
        segs = self._raw_point.get("segs") or []
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for seg in segs:
            source_text, target_text = str(seg).split("@", 1)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(source_text))
            self.table.setItem(row, 1, QTableWidgetItem(target_text))
        self.table.blockSignals(False)

        add_value = self._raw_point.get("add") or 0
        self.add_edit.setText(f"{float(add_value):g}")

    def _table_points(self) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for row in range(self.table.rowCount()):
            source_item = self.table.item(row, 0)
            target_item = self.table.item(row, 1)
            source_text = "" if source_item is None else source_item.text().strip()
            target_text = "" if target_item is None else target_item.text().strip()
            if not source_text and not target_text:
                continue
            points.append((float(source_text), float(target_text)))
        return sorted(points, key=lambda item: item[0])

    def _segs_payload(self) -> list[str]:
        return [f"{source:g}@{target:g}" for source, target in self._table_points()]

    def _refresh_chart(self) -> None:
        try:
            points = self._table_points()
        except ValueError:
            points = []
        self.chart.set_points(points)

    def _current_point_add(self) -> float:
        return float(self._point_obj.config.add or 0.0)

    def _on_zero_btn_clicked(self) -> None:
        table = self.runtime["vsp"]
        true_value = table.read(self.pt_name)  # read() 返回的已是 真值 = segs(raw) + add
        if true_value is None:
            QMessageBox.warning(self, "标零失败", "无法读取当前值")
            return
        # 标零只是把 -真值 预填进输入框, 不落盘; 是否生效取决于后续是否点击保存
        self.add_edit.setText(f"{-(true_value - self._current_point_add()):g}")

    def _on_table_changed(self, item: QTableWidgetItem) -> None:
        del item
        self._refresh_chart()

    def _add_seg(self) -> None:
        row = self.table.rowCount()
        raw_value = self._point_obj.raw_value if self._point_obj.raw_value is not None else 0
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(raw_value)))
        self.table.setItem(row, 1, QTableWidgetItem("0"))
        self.table.setCurrentCell(row, 0)
        self._refresh_chart()

    def _remove_seg(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row < 0:
            return
        self.table.removeRow(row)
        self._refresh_chart()

    def _save(self) -> None:
        try:
            segs = self._segs_payload()
        except ValueError:
            QMessageBox.warning(self, "保存失败", "segs存在无法转换为数字的值")
            return

        add_text = self.add_edit.text().strip()
        try:
            add_value = float(add_text) if add_text else 0.0
        except ValueError:
            QMessageBox.warning(self, "保存失败", "偏移(add)不是合法数字")
            return

        table = self.runtime["vsp"]
        try:
            table.update_by_id(self.pt_name, segs=segs, add=add_value)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return

        # update_by_id 会替换点位换算参数, 刷新引用避免后续标零用旧参数
        self._point_obj = table.points.get(self.pt_name, self._point_obj)

        QMessageBox.information(self, "保存成功", "segs 已写回配置文件并更新全局对象。")
        self.accept()
