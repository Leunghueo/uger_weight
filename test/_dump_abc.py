来那个"""临时脚本：dump abc.xlsx 的单元格内容，用于确认模板版式。"""
from pathlib import Path

from openpyxl import load_workbook

path = Path(r"c:/_NOW/XLT/乌鲁木齐/CODE/uger_weight/runtime/pdf/abc.xlsx")
wb = load_workbook(path)
print("sheets:", wb.sheetnames)
for ws in wb.worksheets:
    print(f"\n=== sheet={ws.title} dims={ws.dimensions} ===")
    for row in ws.iter_rows():
        cells = [(c.coordinate, c.value) for c in row if c.value is not None]
        if cells:
            print(cells)
    print("merged:", [str(r) for r in ws.merged_cells.ranges])
