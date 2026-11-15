"""测量报告：把测量记录填充到 xlsx 报告模板，再转 PDF。

报告模板为 runtime/pdf/abc.xlsx（用户提供），工作表 "report"，版式
（每轴一行，与界面结果表、库结构一致，单位 kg）：
    B2:H2      标题：称重测量报告
    B3 操作者（值 C3，C3:E3 合并） | F3 时间（值 G3，G3:H3 合并）
    B4 车型  （值 C4，C4:E4 合并） | F4 车号（值 G4，G4:H4 合并）
    B5         进车方向（值填 C5，C5:H5 合并）
    B6:H6      表头：轴号 | 轴重/kg | 轴重差/% | 轮重(左)/kg |
                     轮重偏差(左)/% | 轮重(右)/kg | 轮重偏差(右)/%
    B7:B15     轴号 1-9；C 轴重(kg)；D 轴重差(%)；
               E/F 左轮重(kg)/偏差(%)；G/H 右轮重(kg)/偏差(%)
    B16        整车重(kg)（值填 E16，B16:C16、E16:H16 合并）
    B17        平均轮重(kg)（值填 E17，B17:C17、E17:H17 合并）
    B18        平均轴重(kg)（值填 E18，B18:C18、E18:H18 合并）
    B19        不平衡检测(kg)（值填 E19，B19:C19、E19:H19 合并）

轴重差 = (轴重 - 平均轴重) / 平均轴重 × 100%，填数时由各轴轴重
现算（不存库）；平均轮重/平均轴重为有数轮/轴的均值。
合格范围：轴重差 ±2%，轮重偏差 ±4%，超出者字体标红（绝对值
大于限值才标红，恰好等于限值不标红）。

模板缺失时用 openpyxl 按同一版式生成（兜底，版式与 abc.xlsx 一致）。
数据库存储结构与模板一致（见 dbstore），轮/轴/整车重/不平衡均以 kg
存库，导出时直接填入，不再做结构转换与单位换算。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from measure import axis_rows_kg

logger = logging.getLogger(__name__)

TEMPLATE_SHEET = "report"

#: 模板数据区固定的轴行数（B7:B15）
AXIS_ROW_COUNT = 9
_AXIS_FIRST_ROW = 7

#: 偏差合格范围（%，绝对值大于限值标红，等于限值合格）
AXLE_DIFF_LIMIT = 2.0   # 轴重差
WHEEL_DIFF_LIMIT = 4.0  # 轮重偏差

#: 超差单元格字体颜色（红色，6 位 RGB）
ALERT_FONT_COLOR = "FF0000"


def ensure_measure_template(template_path: str | Path) -> Path:
    """模板不存在时按 abc.xlsx 版式生成兜底模板。返回模板路径。"""
    template_path = Path(template_path)
    if template_path.exists():
        return template_path
    template_path.parent.mkdir(parents=True, exist_ok=True)

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side

    wb = Workbook()
    ws = wb.active
    ws.title = TEMPLATE_SHEET
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    title_font = Font(size=16, bold=True)
    head_font = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells("B2:H2")
    c = ws["B2"]
    c.value = "称重测量报告"
    c.font = title_font
    c.alignment = center

    for coord, label in [("B3", "操作者"), ("F3", "时间"),
                         ("B4", "车型"), ("F4", "车号"),
                         ("B5", "进车方向")]:
        ws[coord].value = label
        ws[coord].font = head_font
    for span in ("C3:E3", "G3:H3", "C4:E4", "G4:H4", "C5:H5"):
        ws.merge_cells(span)

    for coord, label in [("B6", "轴号"), ("C6", "轴重/kg"),
                         ("D6", "轴重差 /%"), ("E6", "轮重(左)/kg"),
                         ("F6", "轮重偏差(左) /%"), ("G6", "轮重(右)/kg"),
                         ("H6", "轮重偏差(右) /%")]:
        ws[coord].value = label
        ws[coord].font = head_font
        ws[coord].alignment = center

    for i in range(AXIS_ROW_COUNT):  # B7:B15 轴号 1-9
        r = _AXIS_FIRST_ROW + i
        ws[f"B{r}"].value = i + 1
        ws[f"B{r}"].alignment = center

    for row, label in [(16, "整车重(kg)"), (17, "平均轮重(kg)"),
                       (18, "平均轴重(kg)"), (19, "不平衡检测(kg)")]:
        ws[f"B{row}"].value = label
        ws[f"B{row}"].font = head_font
        ws.merge_cells(f"B{row}:C{row}")
        ws.merge_cells(f"E{row}:H{row}")

    for row in ws["B2:H19"]:
        for cell in row:
            cell.border = border

    for col, width in zip("ABCDEFGH", [2, 10, 12, 12, 14, 14, 14, 14]):
        ws.column_dimensions[col].width = width

    wb.save(template_path)
    logger.info("生成测量报告模板: %s", template_path)
    return template_path


def _num(v: Any) -> float | str:
    """存储值 -> 单元格值：数值原样，空串/None 保持空白。"""
    return round(float(v), 2) if isinstance(v, (int, float)) else ""


def _is_num(v: Any) -> bool:
    """是否为可参与均值/偏差计算的数值（不含 bool）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _axis_report_rows(
    record: dict[str, Any],
) -> tuple[list[dict[str, Any]], float | None, float | None]:
    """每轴一行 + 平均轮重/平均轴重（有数轮/轴的均值，kg）。

    每行在 axis_rows_kg 基础上增加 "轴重差"：
    (轴重 - 平均轴重) / 平均轴重 × 100%，保留 2 位小数；
    无轴重或平均轴重为 0 时留空。均值无数据时为 None。
    """
    rows = axis_rows_kg(record.get("wheels"), record.get("axles"))
    axle_weights = [e["轴重(kg)"] for e in rows if _is_num(e["轴重(kg)"])]
    wheel_weights = [
        e[key] for e in rows for key in ("轮重(左)/kg", "轮重(右)/kg")
        if _is_num(e[key])
    ]
    mean_axle = sum(axle_weights) / len(axle_weights) if axle_weights else None
    mean_wheel = sum(wheel_weights) / len(wheel_weights) if wheel_weights else None
    for entry in rows:
        weight = entry["轴重(kg)"]
        if _is_num(weight) and mean_axle:
            entry["轴重差"] = round((weight - mean_axle) / mean_axle * 100.0, 2)
        else:
            entry["轴重差"] = ""
    return rows, mean_wheel, mean_axle


def build_measure_cells(record: dict[str, Any], operator: str = "") -> dict[str, Any]:
    """记录 -> {单元格引用: 值}，供 PdfReport.set_cells 使用（abc.xlsx 版式）。

    记录的存储结构与模板一致（每轴一行：轴重/轴重差/左轮重/左偏差/
    右轮重/右偏差；整车重/平均轮重/平均轴重/不平衡均为 kg），除轴重
    差与均值由本函数现算外只做单元格定位，不做结构转换与单位换算。
    操作者优先用记录自带的（测量时落库），为空时用调用方传入的当前
    用户兜底。
    """
    cells: dict[str, Any] = {
        "C3": record.get("operator") or operator,
        "G3": record.get("measure_time", ""),
        "C4": record.get("model", ""),
        "G4": record.get("car_no", ""),
        "C5": record.get("direction", ""),  # 进车方向
    }

    rows, mean_wheel, mean_axle = _axis_report_rows(record)
    if len(rows) > AXIS_ROW_COUNT:
        logger.warning(
            "车型轴数(%s)超过模板行数(%s)，超出部分未写入报告",
            len(rows), AXIS_ROW_COUNT,
        )
    for entry in rows[:AXIS_ROW_COUNT]:
        try:
            axle_no = int(entry["轴号"])
        except (TypeError, ValueError):
            continue
        if not 1 <= axle_no <= AXIS_ROW_COUNT:
            continue
        r = _AXIS_FIRST_ROW + axle_no - 1
        cells[f"B{r}"] = axle_no
        cells[f"C{r}"] = _num(entry["轴重(kg)"])
        cells[f"D{r}"] = _num(entry["轴重差"])
        cells[f"E{r}"] = _num(entry["轮重(左)/kg"])
        cells[f"F{r}"] = _num(entry["轮重偏差(左)"])
        cells[f"G{r}"] = _num(entry["轮重(右)/kg"])
        cells[f"H{r}"] = _num(entry["轮重偏差(右)"])

    total = record.get("total_kg")
    cells["E16"] = round(float(total), 1) if isinstance(total, (int, float)) else ""
    cells["E17"] = round(mean_wheel, 1) if mean_wheel is not None else ""
    cells["E18"] = round(mean_axle, 1) if mean_axle is not None else ""
    balance = record.get("balance_kg")
    cells["E19"] = round(float(balance), 1) if isinstance(balance, (int, float)) else ""
    return cells


def build_measure_alert_cells(cells: dict[str, Any]) -> set[str]:
    """填数值中超出合格范围的偏差单元格（字体标红）。

    轴重差（D 列）绝对值大于 AXLE_DIFF_LIMIT（±2%），轮重偏差（F/H
    列）绝对值大于 WHEEL_DIFF_LIMIT（±4%）；恰好等于限值不标红。
    按填入后的打印值判定，与报表所见一致。
    """
    alerts: set[str] = set()
    for i in range(AXIS_ROW_COUNT):
        r = _AXIS_FIRST_ROW + i
        value = cells.get(f"D{r}")
        if _is_num(value) and abs(value) > AXLE_DIFF_LIMIT:
            alerts.add(f"D{r}")
        for col in ("F", "H"):
            value = cells.get(f"{col}{r}")
            if _is_num(value) and abs(value) > WHEEL_DIFF_LIMIT:
                alerts.add(f"{col}{r}")
    return alerts


def export_measure_pdf(
    record: dict[str, Any],
    template_path: str | Path,
    output_dir: str | Path,
    filename: str | None = None,
    operator: str = "",
) -> Path:
    """导出单条测量记录的 PDF 报告，返回 PDF 路径。"""
    from pdf import PdfReport

    template_path = ensure_measure_template(template_path)
    report = PdfReport(template_path, output_dir)
    report.load_template(TEMPLATE_SHEET)
    cells = build_measure_cells(record, operator=operator)
    report.set_cells(cells)
    alerts = build_measure_alert_cells(cells)
    if alerts:
        report.set_cell_font_colors({coord: ALERT_FONT_COLOR for coord in alerts})
    if filename is None:
        rid = record.get("id", "0")
        car = str(record.get("car_no", "")).strip() or "nocar"
        filename = f"称重报告_{car}_{rid}.pdf"
    return report.export_pdf(filename=filename, title="称重测量报告")
