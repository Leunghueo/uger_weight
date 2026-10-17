from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime

logger = logging.getLogger(__name__)

# 日志文件名格式: YYYYMMDD-HHMMSS_type_name_id.log
_LOG_FILENAME_RE = re.compile(
    r"^(\d{8}-\d{6})_(.+?)_(.+?)_([a-f0-9]+)\.log$"
)

_RESULT_KEYS = ["测量值", "最小值", "最大值", "单位", "结论", "测量值"]
_RESULT_HEADERS = ["项目", "测量值", "最小值", "最大值", "单位", "结论", "实际值"]

_LOG_LIST_HEADERS = ["文件名", "日期", "类型", "名称", "ID"]


def _parse_log_filename(filename: str) -> dict[str, str] | None:
    """从日志文件名解析日期、类型、名称和ID."""
    match = _LOG_FILENAME_RE.match(filename)
    if not match:
        return None
    date_raw, type_text, name_text, id_text = match.groups()
    try:
        date_obj = datetime.strptime(date_raw, "%Y%m%d-%H%M%S")
        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        date_str = date_raw
    return {
        "filename": filename,
        "date_raw": date_raw,
        "date": date_str,
        "type": type_text,
        "name": name_text,
        "id": id_text,
    }


def _extract_summary_extra(path: Path) -> list[dict[str, Any]]:
    """读取工作流日志, 返回所有 'event': 'summary' 行的 extra 数据列表.

    每个 summary 的 extra 是一个 dict, 形如:
    {"1位轮重": {"测量值": 300, "最小值": 250, ...}, ...}
    本函数将其展开为列表, 方便表格展示.
    """
    results: list[dict[str, Any]] = []
    if not path.exists():
        return results
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") != "summary":
                    continue
                extra = record.get("extra")
                if not isinstance(extra, dict):
                    continue
                # extra 的每个键是一个测量项, 值是该测量项的数据字典
                for item_name, item_data in extra.items():
                    if not isinstance(item_data, dict):
                        continue
                    row: dict[str, Any] = {"项目": item_name}
                    for key in _RESULT_KEYS:
                        row[key] = item_data.get(key, "-")
                    results.append(row)
                # 通常一个日志只有一个 summary, 但为了健壮性读取所有 summary
    except Exception as exc:
        logger.exception("failed to read workflow log: %s", path)
    return results


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._log_dir: Path = self._resolve_log_dir()
        self._all_logs: list[dict[str, str]] = []
        self._build_ui()
        self._refresh_logs()

    def _resolve_log_dir(self) -> Path:
        base_dir = Path(self.runtime.get("base_dir", "."))
        return base_dir / "logs" / "flows"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 顶部搜索框区域
        root.addWidget(self._build_search_bar())

        # 中部与底部的分割器
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._build_log_list_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([240, 480])
        root.addWidget(splitter, 1)

    def _build_search_bar(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historySearchBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel("日期:", panel)
        layout.addWidget(label)

        self.date_input = QLineEdit(panel)
        self.date_input.setPlaceholderText("例如 2026-09-27 或 20260927")
        self.date_input.setClearButtonEnabled(True)
        self.date_input.returnPressed.connect(self._on_search)
        layout.addWidget(self.date_input, 1)

        self.search_button = QPushButton("搜索", panel)
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.clicked.connect(self._on_search)
        layout.addWidget(self.search_button)

        self.refresh_button = QPushButton("刷新", panel)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self._refresh_logs)
        layout.addWidget(self.refresh_button)

        return panel

    def _build_log_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historyLogListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("搜索结果列表", panel)
        title.setObjectName("cardTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        self.log_table = QTableWidget(0, len(_LOG_LIST_HEADERS), panel)
        self.log_table.setHorizontalHeaderLabels(_LOG_LIST_HEADERS)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.itemSelectionChanged.connect(self._on_log_selected)
        layout.addWidget(self.log_table, 1)

        return panel

    def _build_result_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historyResultPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("所选日志结果列表", panel)
        title.setObjectName("cardTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        self.result_table = QTableWidget(0, len(_RESULT_HEADERS), panel)
        self.result_table.setHorizontalHeaderLabels(_RESULT_HEADERS)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.verticalHeader().setVisible(False)
        layout.addWidget(self.result_table, 1)

        return panel

    def _refresh_logs(self) -> None:
        """扫描日志目录, 加载所有日志文件信息."""
        self._all_logs.clear()
        if self._log_dir.is_dir():
            for path in sorted(self._log_dir.glob("*.log"), key=lambda p: p.name, reverse=True):
                info = _parse_log_filename(path.name)
                if info is not None:
                    info["path"] = str(path)
                    self._all_logs.append(info)
        self._on_search()

    def _on_search(self) -> None:
        """根据日期搜索框内容过滤日志列表."""
        keyword = self.date_input.text().strip()
        filtered = self._all_logs
        if keyword:
            # 支持模糊匹配: 只要日期字符串中包含关键字即可
            filtered = [log for log in self._all_logs if keyword in log.get("date", "") or keyword in log.get("date_raw", "")]
        self._render_log_table(filtered)

    def _render_log_table(self, logs: list[dict[str, str]]) -> None:
        self.log_table.setRowCount(0)
        for row_index, log_info in enumerate(logs):
            self.log_table.insertRow(row_index)
            values = [
                log_info.get("filename", ""),
                log_info.get("date", ""),
                log_info.get("type", ""),
                log_info.get("name", ""),
                log_info.get("id", ""),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.log_table.setItem(row_index, col_index, item)
        # 自动调整列宽
        self.log_table.resizeColumnsToContents()
        self.result_table.setRowCount(0)

    def _on_log_selected(self) -> None:
        """用户选中某行日志后, 加载并显示该日志的 summary 结果."""
        selected = self.log_table.selectedItems()
        if not selected:
            self.result_table.setRowCount(0)
            return

        row = selected[0].row()
        filename_item = self.log_table.item(row, 0)
        if filename_item is None:
            return

        filename = filename_item.text()
        path = self._log_dir / filename
        results = _extract_summary_extra(path)
        self._render_result_table(results)

    def _render_result_table(self, results: list[dict[str, Any]]) -> None:
        self.result_table.setRowCount(0)
        for row_index, result in enumerate(results):
            self.result_table.insertRow(row_index)
            values = [
                result.get("项目", ""),
                str(result.get("测量值", "-")),
                str(result.get("最小值", "-")),
                str(result.get("最大值", "-")),
                str(result.get("单位", "-")),
                str(result.get("结论", "-")),
                str(result.get("测量值", "-")),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.result_table.setItem(row_index, col_index, item)
        self.result_table.resizeColumnsToContents()
