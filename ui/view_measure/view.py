"""测量主页：左侧测量记录栏 + 3 坑位图形化台位 + 结果区.

布局（见手绘图）:
    坑1: 台 1-6   （下排 1,3,5 / 上排 2,4,6）
    坑2: 台 7-14  （下排 7,9,11,13 / 上排 8,10,12,14）
    坑3: 台 15-18 （下排 15,17 / 上排 16,18）
车型下拉来自 maps.json；当前车型的台号高亮显示。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime
from dbstore import (
    delete_measure,
    get_measure,
    insert_measure,
    list_measures,
    save_measure_result,
    update_measure_meta,
    update_measure_tare,
)
from measure import PITS, apply_tare, calculate, read_platforms

logger = logging.getLogger(__name__)

ALL_PLATFORMS = list(range(1, 19))


class PlatformWidget(QFrame):
    """单个称重台：编号 + 实时值。"""

    def __init__(self, platform: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.platform = platform
        self.setFrameShape(QFrame.Box)
        self.setMinimumSize(88, 66)

        num = QLabel(str(platform))
        num.setAlignment(Qt.AlignCenter)
        font = num.font()
        font.setPointSize(15)
        font.setBold(True)
        num.setFont(font)

        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(num)
        layout.addWidget(self.value_label)
        self.set_highlight(False)

    def set_value(self, value: float | None) -> None:
        self.value_label.setText("--" if value is None else f"{value:.2f}")

    def set_highlight(self, on: bool) -> None:
        if on:
            self.setStyleSheet(
                "QFrame { border: 2px solid #e8912d; border-radius: 6px; background: #fff7e6; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { border: 1px solid #b9c2cc; border-radius: 6px; background: #eef1f4; color: #8a939e; }"
            )


class RecordEditDialog(QDialog):
    """新建/编辑记录：车型 / 车号 / 编号 / 备注。"""

    def __init__(self, models: list[str], record: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑测量记录" if record else "创建测量记录")
        self.resize(360, 240)

        self.model_combo = QComboBox()
        self.model_combo.addItems(models)
        self.car_edit = QLineEdit()
        self.serial_edit = QLineEdit()
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(60)

        if record:
            idx = self.model_combo.findText(str(record.get("model", "")))
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            self.car_edit.setText(str(record.get("car_no", "")))
            self.serial_edit.setText(str(record.get("serial_no", "")))
            self.note_edit.setPlainText(str(record.get("note", "")))

        form = QFormLayout(self)
        form.addRow("车型", self.model_combo)
        form.addRow("车号", self.car_edit)
        form.addRow("编号", self.serial_edit)
        form.addRow("备注", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self) -> dict:
        return {
            "model": self.model_combo.currentText().strip(),
            "car_no": self.car_edit.text().strip(),
            "serial_no": self.serial_edit.text().strip(),
            "note": self.note_edit.toPlainText().strip(),
        }


class MeasureView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._db_path = self.runtime["paths"]["db"]
        self._maps: dict[str, dict] = self._load_maps()
        self._platform_widgets: dict[int, PlatformWidget] = {}
        self._tare: dict[int, float] = {}
        self._current_id: int | None = None
        self._last_values: dict[int, float | None] = {}

        self._build_ui()
        self._refresh_models()
        self._refresh_records()
        self._apply_highlight()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_values)
        self._timer.start(500)
        self._refresh_values()

    # ---------- 配置 ----------
    def _load_maps(self) -> dict[str, dict]:
        """maps.json: {车型: {"称重台": [...], "校验数据": {...}}}。"""
        path = Path(self.runtime["paths"]["maps_config"])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            maps: dict[str, dict] = {}
            for model, cfg in data.items():
                if isinstance(cfg, dict):
                    maps[str(model)] = {
                        "称重台": [int(x) for x in cfg.get("称重台", [])],
                        "校验数据": cfg.get("校验数据") or {},
                    }
                elif isinstance(cfg, list):  # 兼容旧格式 {车型: [台号...]}
                    maps[str(model)] = {"称重台": [int(x) for x in cfg], "校验数据": {}}
            return maps
        except Exception:
            logger.exception("读取车型台位配置失败: %s", path)
            return {}

    def _enabled_platforms(self) -> list[int]:
        model = self.model_combo.currentText().strip()
        return list(self._maps.get(model, {}).get("称重台", ALL_PLATFORMS))

    def _model_spec(self, model: str) -> dict:
        """取车型的校验数据（用于不平衡判定）。"""
        return self._maps.get(model, {}).get("校验数据", {}) or {}

    # ---------- 界面 ----------
    def _build_ui(self) -> None:
        main = QHBoxLayout(self)

        # ---- 左侧：测量记录栏 ----
        left = QWidget()
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)

        form = QFormLayout()
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._apply_highlight)
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("手动输入")
        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText("手动输入")
        form.addRow("车型", self.model_combo)
        form.addRow("车号", self.car_edit)
        form.addRow("编号", self.serial_edit)
        left_layout.addLayout(form)

        btn_row1 = QHBoxLayout()
        self.btn_create = QPushButton("创建")
        self.btn_edit = QPushButton("编辑")
        self.btn_delete = QPushButton("删除")
        self.btn_create.clicked.connect(self._on_create)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        for b in (self.btn_create, self.btn_edit, self.btn_delete):
            btn_row1.addWidget(b)
        left_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_tare = QPushButton("去皮")
        self.btn_measure = QPushButton("开始测量")
        font = self.btn_measure.font()
        font.setBold(True)
        self.btn_measure.setFont(font)
        self.btn_tare.clicked.connect(self._on_tare)
        self.btn_measure.clicked.connect(self._on_measure)
        btn_row2.addWidget(self.btn_tare)
        btn_row2.addWidget(self.btn_measure)
        left_layout.addLayout(btn_row2)

        left_layout.addWidget(QLabel("测量记录"))
        self.record_list = QListWidget()
        self.record_list.itemClicked.connect(self._on_record_clicked)
        left_layout.addWidget(self.record_list, 1)
        main.addWidget(left)

        # ---- 右侧：坑位图形 + 结果 ----
        right = QVBoxLayout()

        pits_row = QHBoxLayout()
        for pit_no, platforms in PITS.items():
            box = QGroupBox(f"坑{pit_no}")
            grid = QGridLayout(box)
            grid.setSpacing(6)
            evens = sorted(p for p in platforms if p % 2 == 0)
            odds = sorted(p for p in platforms if p % 2 == 1)
            for col, p in enumerate(evens):
                w = PlatformWidget(p)
                grid.addWidget(w, 0, col)
                self._platform_widgets[p] = w
            for col, p in enumerate(odds):
                w = PlatformWidget(p)
                grid.addWidget(w, 1, col)
                self._platform_widgets[p] = w
            pits_row.addWidget(box, len(platforms))
        right.addLayout(pits_row, 3)

        result_box = QGroupBox("测量结果")
        result_layout = QVBoxLayout(result_box)
        self.summary_label = QLabel("整车重: -- kN　|　轴重差: -- kN　|　结论: --")
        font = self.summary_label.font()
        font.setPointSize(11)
        font.setBold(True)
        self.summary_label.setFont(font)
        result_layout.addWidget(self.summary_label)

        self.result_table = QTableWidget(0, 7)
        self.result_table.setHorizontalHeaderLabels(
            ["轴", "左轮台", "右轮台", "轮重左(kN)", "轮重右(kN)", "轮重差(kN)", "轴重(kN)"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        result_layout.addWidget(self.result_table, 1)
        right.addWidget(result_box, 2)

        main.addLayout(right, 1)

    # ---------- 记录栏 ----------
    def _refresh_models(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(sorted(self._maps.keys()) or ["默认"])
        self.model_combo.blockSignals(False)
        self._apply_highlight()

    def _refresh_records(self) -> None:
        try:
            records = list_measures(self._db_path, limit=200)
        except Exception:
            logger.exception("读取测量记录失败")
            records = []
        self.record_list.clear()
        for r in records:
            text = f"#{r['id']} {r['model']} {r['car_no']} {r['serial_no']}".strip()
            if r.get("measure_time"):
                text += f"  {r['measure_time']}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, r["id"])
            self.record_list.addItem(item)
            if r["id"] == self._current_id:
                self.record_list.setCurrentItem(item)

    def _selected_id(self) -> int | None:
        item = self.record_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _on_record_clicked(self, item: QListWidgetItem) -> None:
        record = get_measure(self._db_path, item.data(Qt.UserRole))
        if not record:
            return
        self._current_id = record["id"]
        idx = self.model_combo.findText(record["model"])
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.car_edit.setText(record["car_no"])
        self.serial_edit.setText(record["serial_no"])
        tare = record.get("tare_json") or {}
        self._tare = {int(k): float(v) for k, v in tare.items()}
        results = record.get("results_json") or {}
        if results:
            self._show_results(results)
        else:
            self._clear_results()

    def _on_create(self) -> None:
        dlg = RecordEditDialog(sorted(self._maps.keys()) or ["默认"], parent=self)
        # 预填当前栏位
        if self.model_combo.currentText():
            idx = dlg.model_combo.findText(self.model_combo.currentText())
            if idx >= 0:
                dlg.model_combo.setCurrentIndex(idx)
        dlg.car_edit.setText(self.car_edit.text())
        dlg.serial_edit.setText(self.serial_edit.text())
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        if not d["model"] or not d["car_no"]:
            QMessageBox.warning(self, "提示", "车型和车号不能为空")
            return
        rid = insert_measure(
            self._db_path, model=d["model"], car_no=d["car_no"],
            serial_no=d["serial_no"], note=d["note"],
        )
        self._current_id = rid
        self._tare = {}
        self._refresh_records()

    def _on_edit(self) -> None:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先在列表中选择一条记录")
            return
        record = get_measure(self._db_path, rid)
        dlg = RecordEditDialog(sorted(self._maps.keys()) or ["默认"], record=record, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        update_measure_meta(self._db_path, rid, model=d["model"], car_no=d["car_no"],
                            serial_no=d["serial_no"], note=d["note"])
        self._refresh_records()

    def _on_delete(self) -> None:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先在列表中选择一条记录")
            return
        if QMessageBox.question(self, "确认", f"删除记录 #{rid}？") != QMessageBox.Yes:
            return
        delete_measure(self._db_path, rid)
        if self._current_id == rid:
            self._current_id = None
            self._tare = {}
            self._clear_results()
        self._refresh_records()

    # ---------- 高亮 ----------
    def _apply_highlight(self) -> None:
        enabled = set(self._enabled_platforms())
        for p, w in self._platform_widgets.items():
            w.set_highlight(p in enabled)

    # ---------- 实时值 ----------
    def _read_live(self) -> dict[int, float | None]:
        vsp = self.runtime.get("vsp")
        try:
            return read_platforms(vsp, ALL_PLATFORMS)
        except Exception:
            logger.exception("读取称重值失败")
            return {p: None for p in ALL_PLATFORMS}

    def _refresh_values(self) -> None:
        self._last_values = self._read_live()
        shown = apply_tare(self._last_values, self._tare)
        for p, w in self._platform_widgets.items():
            w.set_value(shown.get(p))

    # ---------- 去皮 / 测量 ----------
    def _on_tare(self) -> None:
        """去皮：向每个启用的台位发送硬件清零指令（无需解析返回数据）。

        硬件清零后，软件去皮量清零（避免重复扣除）。
        无 VSP 时退回软件去皮（记录当前值）。
        """
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先创建或选择一条测量记录，再去皮")
            return
        enabled = self._enabled_platforms()
        vsp = self.runtime.get("vsp")
        if vsp is None:
            vals = self._read_live()
            tare = {p: v for p, v in vals.items() if v is not None}
            if not tare:
                QMessageBox.warning(self, "提示", "当前无有效称重数据，无法去皮")
                return
            self._tare = tare
            update_measure_tare(self._db_path, rid, {str(k): v for k, v in tare.items()})
            QMessageBox.information(self, "去皮", f"已记录 {len(tare)} 个台位的去皮值")
            return

        failed: list[int] = []
        for p in enabled:
            try:
                ok = vsp.zero(f"称重台{p}")
            except Exception:
                logger.exception("称重台%s 清零指令发送失败", p)
                ok = False
            if not ok:
                failed.append(p)
        # 硬件已清零：软件去皮量清零，避免重复扣除
        self._tare = {}
        update_measure_tare(self._db_path, rid, {})
        self._refresh_values()
        if failed:
            QMessageBox.warning(self, "去皮", f"以下台位清零失败：{failed}")
        else:
            QMessageBox.information(self, "去皮", f"已向 {len(enabled)} 个台位发送清零指令")

    def _on_measure(self) -> None:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先创建或选择一条测量记录，再开始测量")
            return
        model = self.model_combo.currentText().strip()
        enabled = self._enabled_platforms()
        vals = self._read_live()
        missing = [p for p in enabled if vals.get(p) is None]
        tared = apply_tare(vals, self._tare)
        results = calculate(tared, enabled, spec=self._model_spec(model))
        self._show_results(results)

        now = datetime.now().isoformat(timespec="seconds")
        save_measure_result(
            self._db_path, rid,
            measure_time=now,
            platforms=enabled,
            tare={str(k): v for k, v in self._tare.items()},
            values={str(k): (None if v is None else v) for k, v in tared.items()},
            results=results,
        )
        self._refresh_records()
        if missing:
            QMessageBox.warning(self, "测量完成", f"以下台位无数据，已如实记录：{missing}")
        else:
            QMessageBox.information(self, "测量完成", "测量结果已保存")

    # ---------- 结果区 ----------
    def _clear_results(self) -> None:
        self.result_table.setRowCount(0)
        self.summary_label.setText("整车重: -- kN　|　轴重差: -- kN　|　结论: --")

    def _show_results(self, results: dict) -> None:
        axles: dict = results.get("axles", {}) or {}
        wheel_diff: dict = results.get("wheel_diff", {}) or {}
        wheels: dict = results.get("wheels", {}) or {}
        self.result_table.setRowCount(len(axles))
        for row, key in enumerate(sorted(axles.keys(), key=lambda k: int(k.split("-")[0]))):
            a, b = key.split("-")
            vals = [key, a, b,
                    f"{wheels.get(a, '')}", f"{wheels.get(b, '')}",
                    f"{wheel_diff.get(key, '')}", f"{axles[key]}"]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                self.result_table.setItem(row, col, item)
        issues = results.get("imbalance", []) or []
        if issues:
            conclusion = "不平衡(" + "；".join(i.get("type", "") for i in issues) + ")"
            color = "#c0392b"
        else:
            conclusion = "平衡"
            color = "#1e8e3e"
        self.summary_label.setText(
            f"整车重: {results.get('total', '--')} kN　|　"
            f"轴重差: {results.get('axle_diff', '--')} kN　|　"
            f"结论: {conclusion}"
        )
        self.summary_label.setStyleSheet(f"color: {color};")
