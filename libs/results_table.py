"""测量结果表：每轴一行，与报告模板 abc.xlsx 同版式（测量页与记录详情共用）。

结构（列）：轴号 | 轴重/kg | 轮重(左)/kg | 轮重偏差(左) | 轮重(右)/kg |
轮重偏差(右)。行数由 maps.json 的车型决定，未测量或缺数留空。
计算与展示全程单位统一为 kg（VSP 输出即 kg），不做 kN↔kg 换算。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from measure import axis_rows_kg, to_report_data

_COLUMNS = ["轴号", "轴重/kg", "轮重(左)/kg", "轮重偏差(左)", "轮重(右)/kg", "轮重偏差(右)"]

#: 各列的小数位：轮重/轴重(kg) 1 位，轮重偏差(%) 2 位
_COLUMN_DIGITS = [0, 1, 1, 2, 1, 2]

_ROW_HEIGHT = 20


def make_results_table() -> QTableWidget:
    """创建测量结果表（每轴一行）。"""
    table = QTableWidget(0, len(_COLUMNS))
    table.setHorizontalHeaderLabels(list(_COLUMNS))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def clear_results_table(table: QTableWidget) -> None:
    table.setRowCount(0)


def format_value(value: Any, digits: int) -> str:
    """数值按指定小数位格式化；空值/空串保持空白。"""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def fill_results_table_kg(
    table: QTableWidget,
    wheels: list[dict[str, Any]] | None,
    axles: list[dict[str, Any]] | None,
) -> None:
    """用存储结构（kg，见 measure.to_report_data）填充结果表。"""
    rows = axis_rows_kg(wheels, axles)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        values = [
            row["轴号"], row["轴重(kg)"], row["轮重(左)/kg"],
            row["轮重偏差(左)"], row["轮重(右)/kg"], row["轮重偏差(右)"],
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(format_value(value, _COLUMN_DIGITS[col]))
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row_index, col, item)
        table.setRowHeight(row_index, _ROW_HEIGHT)


def fill_results_table(table: QTableWidget, results: dict[str, Any] | None) -> None:
    """把 calculate() 形状的结果（kg）填入结果表（1:1 展示）。"""
    data = to_report_data(results or {})
    fill_results_table_kg(table, data.get("wheels"), data.get("axles"))
