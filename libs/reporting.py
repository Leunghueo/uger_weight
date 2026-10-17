"""测量报告：用 openpyxl 代码生成 xlsx 模板（仓库中不存二进制），
再经 libs.pdf.PdfReport 填充并转 PDF。

模板版式（工作表 "report"）:
    A1:H1      标题：称重测量报告
    A2/B2      车型 | D2/E2 车号 | G2/H2 编号
    A3/B3      测量时间 | D3/E3 整车重 | G3/H3 轴重差
    A5/B5      台号 | 轮重(kN)                      （18 行：A6:B23）
    D5:H5      轴 | 左轮 | 右轮 | 轮重差(kN) | 轴重(kN)（9 行：D6:H14）
    A25/B25    不平衡检测 | 结论
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATE_SHEET = "report"


def ensure_measure_template(template_path: str | Path) -> Path:
    """模板不存在时用 openpyxl 生成。返回模板路径。"""
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

    ws.merge_cells("A1:H1")
    c = ws["A1"]
    c.value = "称重测量报告"
    c.font = title_font
    c.alignment = center

    for coord, label in [("A2", "车型"), ("D2", "车号"), ("G2", "编号"),
                         ("A3", "测量时间"), ("D3", "整车重(kN)"), ("G3", "轴重差(kN)")]:
        ws[coord].value = label
        ws[coord].font = head_font

    ws["A5"].value = "台号"
    ws["B5"].value = "轮重(kN)"
    for coord, label in [("D5", "轴"), ("E5", "左轮(kN)"), ("F5", "右轮(kN)"),
                         ("G5", "轮重差(kN)"), ("H5", "轴重(kN)")]:
        ws[coord].value = label
    for row in ws["A5:H5"][0]:
        row.font = head_font
        row.alignment = center
        row.border = border

    for i in range(18):  # A6:B23 台号/轮重
        r = 6 + i
        ws[f"A{r}"].value = i + 1
        ws[f"A{r}"].alignment = center
        ws[f"A{r}"].border = border
        ws[f"B{r}"].border = border
    for k in range(9):  # D6:H14 轴表
        r = 6 + k
        for col in "DEFGH":
            ws[f"{col}{r}"].border = border
            ws[f"{col}{r}"].alignment = center

    ws["A25"].value = "不平衡检测"
    ws["A25"].font = head_font
    ws.merge_cells("B25:H25")

    for col, width in zip("ABCDEFGH", [10, 14, 14, 10, 12, 12, 14, 14]):
        ws.column_dimensions[col].width = width

    wb.save(template_path)
    logger.info("生成测量报告模板: %s", template_path)
    return template_path


def _fmt(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float):
        return round(v, 3)
    return v


def build_measure_cells(record: dict[str, Any]) -> dict[str, Any]:
    """记录 -> {单元格引用: 值}，供 PdfReport.set_cells 使用。"""
    results = record.get("results_json") or {}
    if isinstance(results, str):
        import json
        results = json.loads(results)
    wheels: dict[str, Any] = results.get("wheels", {}) or {}
    wheel_diff: dict[str, Any] = results.get("wheel_diff", {}) or {}
    axles: dict[str, Any] = results.get("axles", {}) or {}
    issues: list[dict[str, str]] = results.get("imbalance", []) or []

    cells: dict[str, Any] = {
        "B2": record.get("model", ""),
        "E2": record.get("car_no", ""),
        "H2": record.get("serial_no", ""),
        "B3": record.get("measure_time", ""),
        "E3": _fmt(results.get("total")),
        "H3": _fmt(results.get("axle_diff")),
    }
    for i in range(18):
        cells[f"B{6 + i}"] = _fmt(wheels.get(str(i + 1)))
    for k in range(9):
        a, b = 2 * k + 1, 2 * k + 2
        key = f"{a}-{b}"
        r = 6 + k
        cells[f"D{r}"] = key
        cells[f"E{r}"] = _fmt(wheels.get(str(a)))
        cells[f"F{r}"] = _fmt(wheels.get(str(b)))
        cells[f"G{r}"] = _fmt(wheel_diff.get(key))
        cells[f"H{r}"] = _fmt(axles.get(key))

    if issues:
        conclusion = "不平衡：" + "；".join(
            f"{it.get('type')}-{it.get('detail')}" for it in issues
        )
    else:
        conclusion = "平衡"
    cells["B25"] = conclusion
    return cells


def export_measure_pdf(
    record: dict[str, Any],
    template_path: str | Path,
    output_dir: str | Path,
    filename: str | None = None,
) -> Path:
    """导出单条测量记录的 PDF 报告，返回 PDF 路径。"""
    from pdf import PdfReport

    template_path = ensure_measure_template(template_path)
    report = PdfReport(template_path, output_dir)
    report.load_template(TEMPLATE_SHEET)
    report.set_cells(build_measure_cells(record))
    if filename is None:
        rid = record.get("id", "0")
        car = str(record.get("car_no", "")).strip() or "nocar"
        filename = f"称重报告_{car}_{rid}.pdf"
    return report.export_pdf(filename=filename, title="称重测量报告")
