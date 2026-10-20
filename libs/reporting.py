"""测量报告：把测量记录填充到 xlsx 报告模板，再转 PDF。

报告模板为 runtime/pdf/abc.xlsx（用户提供），工作表 "report"，版式：
    B2:E2      标题：称重测量报告
    B3/C3      操作者 | D3/E3 时间
    B4/C4      车型   | D4/E4 车号
    B5         进车方向（值填 C5，C5:E5 合并）
    B6:E6      表头：轮号 | 轮重(kg) | 偏差(%) | 轴重(kg)
    B7:B24     轮号 1-18；C 列轮重(kg)；D 列偏差(%)；
               E 列轴重(kg)（E7:E8、E9:E10 … 两行合并为一轴）
    B25        整车重(kg)（值填 D25，D25:E25 合并）
    B26        不平衡检测(kg)（值填 D26，D26:E26 合并；= 最大轮重-最小轮重）

模板缺失时用 openpyxl 按同一版式生成（兜底，版式与 abc.xlsx 一致）。
数值单位换算：系统内轮重为 kN，报告按模板以 kg 呈现，
kg = kN * 1000 / 9.80665。偏差为相对量，不受单位影响。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATE_SHEET = "report"

KN_TO_KG = 1000.0 / 9.80665


def _kg(v: float | None) -> float | str:
    return "" if v is None else round(v * KN_TO_KG, 1)


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

    ws.merge_cells("B2:E2")
    c = ws["B2"]
    c.value = "称重测量报告"
    c.font = title_font
    c.alignment = center

    for coord, label in [("B3", "操作者"), ("D3", "时间"),
                         ("B4", "车型"), ("D4", "车号"),
                         ("B5", "进车方向")]:
        ws[coord].value = label
        ws[coord].font = head_font
    ws.merge_cells("C5:E5")

    for coord, label in [("B6", "轮号"), ("C6", "轮重(kg)"),
                         ("D6", "偏差(%)"), ("E6", "轴重(kg)")]:
        ws[coord].value = label
        ws[coord].font = head_font
        ws[coord].alignment = center

    for i in range(18):  # B7:B24 轮号
        r = 7 + i
        ws[f"B{r}"].value = i + 1
        ws[f"B{r}"].alignment = center
    for k in range(9):  # 轴重两行合并
        ws.merge_cells(f"E{7 + 2 * k}:E{8 + 2 * k}")

    ws["B25"].value = "整车重(kg)"
    ws["B25"].font = head_font
    ws.merge_cells("B25:C25")
    ws.merge_cells("D25:E25")
    ws["B26"].value = "不平衡检测(kg)"
    ws["B26"].font = head_font
    ws.merge_cells("B26:C26")
    ws.merge_cells("D26:E26")

    for row in ws["B2:E26"]:
        for cell in row:
            cell.border = border

    for col, width in zip("ABCDE", [2, 14, 16, 14, 16]):
        ws.column_dimensions[col].width = width

    wb.save(template_path)
    logger.info("生成测量报告模板: %s", template_path)
    return template_path


def _results_of(record: dict[str, Any]) -> dict[str, Any]:
    results = record.get("results_json") or {}
    if isinstance(results, str):
        results = json.loads(results)
    return results


def _deviations(wheels: dict[str, Any]) -> dict[str, float]:
    """由轮重现算每轮偏差(%)（旧记录未存 deviations 时兜底）。"""
    devs: dict[str, float] = {}
    for k in range(9):
        a, b = str(2 * k + 1), str(2 * k + 2)
        va, vb = wheels.get(a), wheels.get(b)
        if va is None or vb is None:
            continue
        avg = (float(va) + float(vb)) / 2.0
        if avg:
            devs[a] = round((float(va) - avg) / avg * 100.0, 2)
            devs[b] = round((float(vb) - avg) / avg * 100.0, 2)
    return devs


def build_measure_cells(record: dict[str, Any], operator: str = "") -> dict[str, Any]:
    """记录 -> {单元格引用: 值}，供 PdfReport.set_cells 使用（abc.xlsx 版式）。"""
    results = _results_of(record)
    wheels: dict[str, Any] = results.get("wheels", {}) or {}
    axles: dict[str, Any] = results.get("axles", {}) or {}
    deviations: dict[str, Any] = results.get("deviations") or _deviations(wheels)

    cells: dict[str, Any] = {
        "C3": operator,
        "E3": record.get("measure_time", ""),
        "C4": record.get("model", ""),
        "E4": record.get("car_no", ""),
        "C5": record.get("serial_no", ""),  # 进车方向
    }
    for i in range(18):
        p = str(i + 1)
        r = 7 + i
        v = wheels.get(p)
        cells[f"C{r}"] = _kg(float(v)) if v is not None else ""
        d = deviations.get(p)
        cells[f"D{r}"] = round(float(d), 2) if d is not None else ""
    for k in range(9):
        key = f"{2 * k + 1}-{2 * k + 2}"
        v = axles.get(key)
        cells[f"E{7 + 2 * k}"] = _kg(float(v)) if v is not None else ""

    total = results.get("total")
    cells["D25"] = _kg(float(total)) if total is not None else ""
    # 不平衡检测 = 最大轮重 - 最小轮重；优先由轮重现算，保证口径一致
    present = [float(v) for v in wheels.values() if v is not None]
    if len(present) >= 2:
        balance = max(present) - min(present)
    else:
        balance = results.get("balance")
    cells["D26"] = _kg(float(balance)) if balance is not None else ""
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
