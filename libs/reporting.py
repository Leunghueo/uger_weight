"""测量报告：把测量记录填充到 xlsx 报告模板，再转 PDF。

报告模板为 runtime/pdf/abc.xlsx（用户提供），工作表 "report"，版式
（每轴一行，与界面结果表、库结构一致，单位 kg）：
    B2:G2      标题：称重测量报告
    B3 操作者（值 C3，C3:D3 合并） | E3 时间（值 F3，F3:G3 合并）
    B4 车型  （值 C4，C4:D4 合并） | E4 车号（值 F4，F4:G4 合并）
    B5         进车方向（值填 C5）
    B6:G6      表头：轴号 | 轴重/kg | 轮重(左)/kg | 轮重偏差(左) |
                     轮重(右)/kg | 轮重偏差(右)
    B7:B15     轴号 1-9；C 轴重(kg)；D/E 左轮重(kg)/偏差(%)；
               F/G 右轮重(kg)/偏差(%)
    B16        整车重(kg)（值填 D16，B16:C16、D16:G16 合并）
    B17        不平衡检测(kg)（值填 D17，B17:C17、D17:G17 合并）

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

    ws.merge_cells("B2:G2")
    c = ws["B2"]
    c.value = "称重测量报告"
    c.font = title_font
    c.alignment = center

    for coord, label in [("B3", "操作者"), ("E3", "时间"),
                         ("B4", "车型"), ("E4", "车号"),
                         ("B5", "进车方向")]:
        ws[coord].value = label
        ws[coord].font = head_font
    for span in ("C3:D3", "F3:G3", "C4:D4", "F4:G4"):
        ws.merge_cells(span)

    for coord, label in [("B6", "轴号"), ("C6", "轴重/kg"),
                         ("D6", "轮重(左)/kg"), ("E6", "轮重偏差(左)"),
                         ("F6", "轮重(右)/kg"), ("G6", "轮重偏差(右)")]:
        ws[coord].value = label
        ws[coord].font = head_font
        ws[coord].alignment = center

    for i in range(AXIS_ROW_COUNT):  # B7:B15 轴号 1-9
        r = _AXIS_FIRST_ROW + i
        ws[f"B{r}"].value = i + 1
        ws[f"B{r}"].alignment = center

    ws["B16"].value = "整车重(kg)"
    ws["B16"].font = head_font
    ws.merge_cells("B16:C16")
    ws.merge_cells("D16:G16")
    ws["B17"].value = "不平衡检测(kg)"
    ws["B17"].font = head_font
    ws.merge_cells("B17:C17")
    ws.merge_cells("D17:G17")

    for row in ws["B2:G17"]:
        for cell in row:
            cell.border = border

    for col, width in zip("ABCDEFG", [2, 10, 12, 14, 14, 14, 14]):
        ws.column_dimensions[col].width = width

    wb.save(template_path)
    logger.info("生成测量报告模板: %s", template_path)
    return template_path


def _num(v: Any) -> float | str:
    """存储值 -> 单元格值：数值原样，空串/None 保持空白。"""
    return round(float(v), 2) if isinstance(v, (int, float)) else ""


def build_measure_cells(record: dict[str, Any], operator: str = "") -> dict[str, Any]:
    """记录 -> {单元格引用: 值}，供 PdfReport.set_cells 使用（abc.xlsx 版式）。

    记录的存储结构与模板一致（每轴一行：轴重/左轮重/左偏差/右轮重/右
    偏差；整车重/不平衡均为 kg），本函数只做单元格定位，不做结构转换
    与单位换算。操作者优先用记录自带的（测量时落库），为空时用调用方
    传入的当前用户兜底。
    """
    cells: dict[str, Any] = {
        "C3": record.get("operator") or operator,
        "F3": record.get("measure_time", ""),
        "C4": record.get("model", ""),
        "F4": record.get("car_no", ""),
        "C5": record.get("direction", ""),  # 进车方向
    }

    rows = axis_rows_kg(record.get("wheels"), record.get("axles"))
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
        cells[f"D{r}"] = _num(entry["轮重(左)/kg"])
        cells[f"E{r}"] = _num(entry["轮重偏差(左)"])
        cells[f"F{r}"] = _num(entry["轮重(右)/kg"])
        cells[f"G{r}"] = _num(entry["轮重偏差(右)"])

    total = record.get("total_kg")
    cells["D16"] = round(float(total), 1) if isinstance(total, (int, float)) else ""
    balance = record.get("balance_kg")
    cells["D17"] = round(float(balance), 1) if isinstance(balance, (int, float)) else ""
    return cells


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
    report.set_cells(build_measure_cells(record, operator=operator))
    if filename is None:
        rid = record.get("id", "0")
        car = str(record.get("car_no", "")).strip() or "nocar"
        filename = f"称重报告_{car}_{rid}.pdf"
    return report.export_pdf(filename=filename, title="称重测量报告")
