"""中间展示用结果表：与报告结构对齐的分段表（测量页与记录详情共用）。

结构：先「轮数据」18 行（轮号/轮重/偏差%），再「轴数据」9 行
（轴号/轴重）。未启用或缺数的轮/轴保留行、值留空，与报告一致。
程序内单位为 kN；报告（abc.xlsx）为 kg。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

WHEEL_COUNT = 18
AXLE_COUNT = 9
_ROW_HEIGHT = 20


def make_results_table() -> QTableWidget:
    """创建分段结果表（3 列：编号/重量(kN)/偏差(%)）。"""
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["编号", "重量(kN)", "偏差(%)"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def clear_results_table(table: QTableWidget) -> None:
    table.setRowCount(0)


def _section_row(table: QTableWidget, title: str) -> None:
    row = table.rowCount()
    table.insertRow(row)
    item = QTableWidgetItem(title)
    font = QFont()
    font.setBold(True)
    item.setFont(font)
    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.setItem(row, 0, item)
    table.setSpan(row, 0, 1, 3)


def _data_row(table: QTableWidget, no: int, weight: Any, dev: Any = "") -> None:
    row = table.rowCount()
    table.insertRow(row)
    for col, v in enumerate([no, weight, dev]):
        item = QTableWidgetItem("" if v is None else str(v))
        item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, col, item)
    table.setRowHeight(row, _ROW_HEIGHT)


def fill_results_table(table: QTableWidget, results: dict[str, Any] | None) -> None:
    """把 calculate() 形状的结果填入分段表；无结果时整表留空结构。"""
    results = results or {}
    wheels: dict = results.get("wheels") or {}
    deviations: dict = results.get("deviations") or {}
    axles: dict = results.get("axles") or {}

    table.setRowCount(0)
    _section_row(table, "轮数据")
    for p in range(1, WHEEL_COUNT + 1):
        v = wheels.get(str(p))
        _data_row(table, p, "" if v is None else v, deviations.get(str(p), ""))
    _section_row(table, "轴数据")
    for k in range(1, AXLE_COUNT + 1):
        key = f"{2 * k - 1}-{2 * k}"
        v = axles.get(key)
        _data_row(table, k, "" if v is None else v)
