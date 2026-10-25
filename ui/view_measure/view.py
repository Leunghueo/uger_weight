"""测量主页：左侧测量记录栏 + 3 坑位图形化台位 + 结果区.

布局（见手绘图）:
    坑1: 台 1-6   （下排 1,3,5 / 上排 2,4,6）
    坑2: 台 7-14  （下排 7,9,11,13 / 上排 8,10,12,14）
    坑3: 台 15-18 （下排 15,17 / 上排 16,18）
车型下拉来自 maps.json；高亮的是「当前车型 + 当前进车方向」所解析出的台位
（一轴向西取"正向称台"，一轴向东取"反向称台"）。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
)
from results_table import clear_results_table, fill_results_table, make_results_table
from measure import (
    DIRECTIONS,
    WheelRef,
    apply_tare,
    calculate,
    read_platforms,
    report_skeleton,
    resolve_wheels,
    results_from_report,
    to_report_data,
)

from .platform_scene import PlatformSceneView

logger = logging.getLogger(__name__)

ALL_PLATFORMS = list(range(1, 19))

# 进车方向固定选项（存入 direction 列），取自 measure.DIRECTIONS：
#   一轴向西 -> 正向（读 maps.json 的 "正向称台"）
#   一轴向东 -> 反向（读 maps.json 的 "反向称台"）


def _set_combo_value(combo: QComboBox, value: str) -> None:
    """设置下拉框的值；不在固定选项中（如旧记录的历史文本）时临时加入以便显示。"""
    idx = combo.findText(value)
    if idx < 0 and value:
        combo.addItem(value)
        idx = combo.count() - 1
    if idx >= 0:
        combo.setCurrentIndex(idx)


class RecordEditDialog(QDialog):
    """新建/编辑记录：车型 / 车号 / 进车方向 / 备注。"""

    def __init__(self, models: list[str], record: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑测量记录" if record else "创建测量记录")
        self.resize(360, 240)

        self.model_combo = QComboBox()
        self.model_combo.addItems(models)
        self.car_edit = QLineEdit()
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(DIRECTIONS)
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(60)

        if record:
            idx = self.model_combo.findText(str(record.get("model", "")))
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            self.car_edit.setText(str(record.get("car_no", "")))
            _set_combo_value(self.direction_combo, str(record.get("direction", "")))
            self.note_edit.setPlainText(str(record.get("note", "")))

        form = QFormLayout(self)
        form.addRow("车型", self.model_combo)
        form.addRow("车号", self.car_edit)
        form.addRow("进车方向", self.direction_combo)
        form.addRow("备注", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self) -> dict:
        return {
            "model": self.model_combo.currentText().strip(),
            "car_no": self.car_edit.text().strip(),
            "direction": self.direction_combo.currentText().strip(),
            "note": self.note_edit.toPlainText().strip(),
        }


class MeasureView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._db_path = self.runtime["paths"]["db"]
        self._maps: dict[str, dict] = self._load_maps()
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
        """maps.json: {车型: {轴名: {轮别: {正向称台/反向称台/...}}}}。

        只读取到内存，测量值（轮重/轮重差）不回写配置文件。
        """
        path = Path(self.runtime["paths"]["maps_config"])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            maps: dict[str, dict] = {}
            for model, axles in data.items():
                if not isinstance(axles, dict):
                    continue
                parsed: dict[str, dict] = {}
                for axle_name, wheels in axles.items():
                    if not isinstance(wheels, dict):
                        continue
                    parsed[str(axle_name)] = {
                        str(side): dict(wheel)
                        for side, wheel in wheels.items()
                        if isinstance(wheel, dict)
                    }
                if parsed:
                    maps[str(model)] = parsed
            return maps
        except Exception:
            logger.exception("读取车型台位配置失败: %s", path)
            return {}

    # ---------- 车型 / 方向 -> 车轮映射 ----------
    def _current_model(self) -> str:
        return self.model_combo.currentText().strip()

    def _current_direction(self) -> str:
        return self.direction_combo.currentText().strip()

    def _wheel_refs(self) -> list[WheelRef]:
        """当前 车型 + 进车方向 对应的有序车轮列表（含各自台号）。"""
        return resolve_wheels(self._maps, self._current_model(), self._current_direction())

    def _enabled_platforms(self) -> list[int]:
        """本次测量实际使用的台号（随进车方向变化）。"""
        return [ref.platform for ref in self._wheel_refs()]

    # ---------- 界面 ----------
    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(6, 6, 6, 6)
        main.setSpacing(6)

        # ---- 顶部：称重台示意图（页面一级元素，占整宽） ----
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(2)

        # 称重台俯视示意图（唯一视图，旧版卡片视图已移除）
        self.pits_scene = PlatformSceneView()
        self.pits_scene.setObjectName("pitsScene")
        top_layout.addWidget(self.pits_scene, 1)
        main.addWidget(top, 2)

        # ---- 底部：左侧测量记录栏 + 右侧测量结果 ----
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        left = QWidget()
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._apply_highlight)
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("手动输入")
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(DIRECTIONS)
        # 进车方向改变 -> 每个轮子读的台号改变 -> 高亮台位随之改变
        self.direction_combo.currentTextChanged.connect(self._apply_highlight)
        form.addRow("车型", self.model_combo)
        form.addRow("车号", self.car_edit)
        form.addRow("进车方向", self.direction_combo)
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
        self.btn_measure = QPushButton("开始测量")
        font = self.btn_measure.font()
        font.setBold(True)
        self.btn_measure.setFont(font)
        self.btn_measure.clicked.connect(self._on_measure)
        btn_row2.addWidget(self.btn_measure)
        left_layout.addLayout(btn_row2)

        left_layout.addWidget(QLabel("测量记录"))
        self.record_list = QListWidget()
        self.record_list.itemClicked.connect(self._on_record_clicked)
        left_layout.addWidget(self.record_list, 1)
        bottom_layout.addWidget(left)

        result_box = QGroupBox("测量结果")
        result_layout = QVBoxLayout(result_box)
        self.summary_label = QLabel("整车重: -- kg　|　轴重差: -- kg　|　不平衡: -- kg")
        font = self.summary_label.font()
        font.setPointSize(11)
        font.setBold(True)
        self.summary_label.setFont(font)
        result_layout.addWidget(self.summary_label)

        self.result_table = make_results_table()
        result_layout.addWidget(self.result_table, 1)
        bottom_layout.addWidget(result_box, 1)

        main.addWidget(bottom, 3)

    # ---------- 记录栏 ----------
    def _refresh_models(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(sorted(self._maps.keys()) or ["默认"])
        self.model_combo.blockSignals(False)
        self._apply_highlight()

    def _refresh_records(self) -> None:
        """只列出当天的记录（历史记录到「工具-测量记录」页查询）。"""
        today = date.today().isoformat()
        try:
            records = list_measures(
                self._db_path, date_from=today, date_to=today, limit=200
            )
        except Exception:
            logger.exception("读取测量记录失败")
            records = []
        self.record_list.clear()
        for r in records:
            text = f"#{r['id']} {r['model']} {r['car_no']} {r['direction']}".strip()
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
        _set_combo_value(self.direction_combo, record["direction"])
        tare = record.get("tare") or {}
        self._tare = {int(k): float(v) for k, v in tare.items()}
        results = results_from_report(record.get("wheels"))
        if results:
            self._show_results(results)
        else:
            self._clear_results()

    def _on_create(self) -> None:
        """用左栏当前的 车型/车号/进车方向 直接创建记录（不弹窗）。"""
        model = self._current_model()
        car_no = self.car_edit.text().strip()
        direction = self._current_direction()
        if not model or not car_no:
            QMessageBox.warning(self, "提示", "车型和车号不能为空")
            return
        refs = resolve_wheels(self._maps, model, direction)
        if not refs:
            QMessageBox.warning(self, "提示", "当前车型/进车方向未配置任何车轮台位，无法创建")
            return
        skeleton = report_skeleton(refs)
        rid = insert_measure(
            self._db_path, model=model, car_no=car_no,
            direction=direction, note="",
            platforms=[ref.platform for ref in refs],
            wheels=skeleton["wheels"], axles=skeleton["axles"],
        )
        self._current_id = rid
        self._tare = {}
        self._clear_results()
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
                            direction=d["direction"], note=d["note"])
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
        self.pits_scene.set_highlight(enabled)

    # ---------- 实时值 ----------
    def _read_live(self) -> dict[int, float | None]:
        vsp = self.runtime.get("vsp")
        try:
            return read_platforms(vsp, ALL_PLATFORMS)
        except Exception:
            logger.exception("读取称重值失败")
            return {p: None for p in ALL_PLATFORMS}

    def _refresh_values(self) -> None:
        # 所有称重台一律刷新并显示数据；车型启用的台位仅通过边框高亮提示
        self._last_values = self._read_live()
        shown = apply_tare(self._last_values, self._tare)
        self.pits_scene.set_values(shown)

    # ---------- 测量 ----------
    def _on_measure(self) -> None:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.warning(self, "提示", "请先创建或选择一条测量记录，再开始测量")
            return
        refs = self._wheel_refs()
        if not refs:
            QMessageBox.warning(self, "提示", "当前车型/进车方向未配置任何车轮台位，无法测量")
            return
        enabled = [ref.platform for ref in refs]
        # 只采集本次车型+进车方向真正用到的台位（由 maps.json 决定）
        vals = read_platforms(self.runtime.get("vsp"), enabled)
        tared = apply_tare(vals, self._tare)
        results = calculate(tared, refs)
        missing = sorted(set(results["missing"]))
        self._show_results(results)

        # 本地时间且 4 位年份：与新建记录一致，便于按日期检索/当天过滤
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = to_report_data(results)
        save_measure_result(
            self._db_path, rid,
            measure_time=now,
            operator=str(get_runtime().get("current_user", "") or ""),
            platforms=enabled,
            tare={str(k): v for k, v in self._tare.items()},
            wheels=data["wheels"],
            axles=data["axles"],
            total_kg=data["total_kg"],
            balance_kg=data["balance_kg"],
        )
        self._refresh_records()
        if missing:
            QMessageBox.warning(self, "测量完成", f"以下台位无数据，已如实记录：{missing}")
        else:
            QMessageBox.information(self, "测量完成", "测量结果已保存")

    # ---------- 结果区 ----------
    def _clear_results(self) -> None:
        clear_results_table(self.result_table)
        self.summary_label.setText("整车重: -- kg　|　轴重差: -- kg　|　不平衡: -- kg")

    def _kg(self, value: Any) -> Any:
        """展示值 kg（VSP 输出即 kg，不做换算）。"""
        return round(float(value), 1) if isinstance(value, (int, float)) else "--"

    def _show_results(self, results: dict) -> None:
        fill_results_table(self.result_table, results)
        self.summary_label.setText(
            f"整车重: {self._kg(results.get('total'))} kg　|　"
            f"轴重差: {self._kg(results.get('axle_diff'))} kg　|　"
            f"不平衡: {self._kg(results.get('balance'))} kg"
        )
