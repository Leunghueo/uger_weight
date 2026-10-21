"""测量记录：检索 / 查看 / 导出PDF / 打印。"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime
from dbstore import get_measure, list_measures
from measure import KN_TO_KG, results_from_report
from reporting import export_measure_pdf
from results_table import fill_results_table, make_results_table

logger = logging.getLogger(__name__)


class RecordDetailDialog(QDialog):
    """记录详情查看。"""

    def __init__(self, record: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"测量记录 #{record.get('id')}")
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        info = QFormLayout()
        info.addRow("车型", QLabel(str(record.get("model", ""))))
        info.addRow("车号", QLabel(str(record.get("car_no", ""))))
        info.addRow("进车方向", QLabel(str(record.get("direction", ""))))
        info.addRow("测量时间", QLabel(str(record.get("measure_time", ""))))
        info.addRow("备注", QLabel(str(record.get("note", ""))))
        layout.addLayout(info)

        results = results_from_report(record.get("wheels"), record.get("platforms")) or {}

        wt = make_results_table()
        fill_results_table(wt, results)
        layout.addWidget(wt, 1)

        summary = QLabel(
            f"整车重: {results.get('total', '--')} kN　|　"
            f"轴重差: {results.get('axle_diff', '--')} kN　|　"
            f"不平衡: {results.get('balance', '--')} kN"
        )
        font = summary.font()
        font.setBold(True)
        summary.setFont(font)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class RecordsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._db_path = self.runtime["paths"]["db"]
        self._build_ui()
        self._search()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("车型")
        self.model_edit.setMaximumWidth(140)
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("车号")
        self.car_edit.setMaximumWidth(140)
        self.use_date_filter = QCheckBox("按日期")
        self.use_date_filter.setChecked(False)
        self.date_from = QDateEdit(date.today())
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to = QDateEdit(date.today())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")

        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self._search)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear_search)

        search_row.addWidget(QLabel("车型"))
        search_row.addWidget(self.model_edit)
        search_row.addWidget(QLabel("车号"))
        search_row.addWidget(self.car_edit)
        search_row.addWidget(self.use_date_filter)
        search_row.addWidget(QLabel("日期从"))
        search_row.addWidget(self.date_from)
        search_row.addWidget(QLabel("到"))
        search_row.addWidget(self.date_to)
        search_row.addWidget(self.btn_search)
        search_row.addWidget(self.btn_clear)
        search_row.addStretch(1)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "车型", "车号", "进车方向", "测量时间", "整车重(kN)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemDoubleClicked.connect(lambda _i: self._on_view())
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.btn_view = QPushButton("查看")
        self.btn_pdf = QPushButton("导出PDF")
        self.btn_print = QPushButton("打印")
        self.btn_view.clicked.connect(self._on_view)
        self.btn_pdf.clicked.connect(self._on_export_pdf)
        self.btn_print.clicked.connect(self._on_print)
        btn_row.addWidget(self.btn_view)
        btn_row.addWidget(self.btn_pdf)
        btn_row.addWidget(self.btn_print)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _clear_search(self) -> None:
        self.model_edit.clear()
        self.car_edit.clear()
        self.date_from.setDate(date.today())
        self.date_to.setDate(date.today())
        self._search()

    def _search(self) -> None:
        try:
            use_date = self.use_date_filter.isChecked()
            records = list_measures(
                self._db_path,
                model=self.model_edit.text().strip(),
                car_no=self.car_edit.text().strip(),
                date_from=self.date_from.date().toString("yyyy-MM-dd") if use_date else "",
                date_to=self.date_to.date().toString("yyyy-MM-dd") if use_date else "",
            )
        except Exception:
            logger.exception("检索测量记录失败")
            records = []
        self.table.setRowCount(len(records))
        for row, r in enumerate(records):
            total_kg = r.get("total_kg")
            total = round(total_kg / KN_TO_KG, 2) if isinstance(total_kg, (int, float)) else ""
            for col, v in enumerate(
                [r["id"], r["model"], r["car_no"], r["direction"],
                 r["measure_time"], total]
            ):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, r["id"])
                self.table.setItem(row, col, item)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _selected_record(self) -> dict | None:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先选择一条记录")
            return None
        return get_measure(self._db_path, rid)

    def _on_view(self) -> None:
        record = self._selected_record()
        if record:
            RecordDetailDialog(record, self).exec()

    def _report_paths(self) -> tuple[Path, Path]:
        paths = self.runtime["paths"]
        return Path(paths["report_template"]), Path(paths["report_path"])

    def _on_export_pdf(self) -> None:
        record = self._selected_record()
        if not record:
            return
        if record.get("total_kg") is None:
            QMessageBox.warning(self, "提示", "该记录尚未测量，无结果可导出")
            return
        try:
            template, outdir = self._report_paths()
            pdf_path = export_measure_pdf(
                record, template, outdir,
                operator=str(self.runtime.get("current_user", "") or ""),
            )
        except Exception as exc:
            logger.exception("导出PDF失败")
            QMessageBox.warning(self, "导出PDF", f"导出失败：{exc}")
            return
        QMessageBox.information(self, "导出PDF", f"已导出：\n{pdf_path}")

    def _on_print(self) -> None:
        record = self._selected_record()
        if not record:
            return
        if record.get("total_kg") is None:
            QMessageBox.warning(self, "提示", "该记录尚未测量，无内容可打印")
            return
        try:
            template, _ = self._report_paths()
            tmpdir = Path(tempfile.gettempdir())
            pdf_path = export_measure_pdf(
                record, template, tmpdir, filename=f"measure_{record['id']}.pdf",
                operator=str(self.runtime.get("current_user", "") or ""),
            )
        except Exception as exc:
            logger.exception("生成打印PDF失败")
            QMessageBox.warning(self, "打印", f"生成PDF失败：{exc}")
            return

        dlg = QPrintDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        printer_name = dlg.printer().printerName()
        try:
            subprocess.run(["lp", "-d", printer_name, str(pdf_path)],
                           check=True, timeout=30)
        except FileNotFoundError:
            QMessageBox.warning(
                self, "打印",
                f"系统未找到 lp 打印命令，请手动打印：\n{pdf_path}")
        except subprocess.CalledProcessError as exc:
            QMessageBox.warning(self, "打印", f"打印失败：{exc}")
        else:
            QMessageBox.information(self, "打印", f"已发送到打印机：{printer_name}")
