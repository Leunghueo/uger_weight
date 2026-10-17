"""
Excel 转 PDF 报告生成模块:

基于 openpyxl 填充数据 + LibreOffice 导出 PDF
完全保留 Excel 格式，包括字体、颜色、边框、合并单元格等
"""
from __future__ import annotations

import logging
import subprocess
import shutil
import os
import platform
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell import Cell

logger = logging.getLogger(__name__)


class PdfReport:
    """
    PDF 报告生成器

    使用 openpyxl 填充 xlsx 模板数据，
    通过 LibreOffice 导出为 PDF，完全保留格式。
    """

    def __init__(self, template_path: str | Path, output_dir: str | Path) -> None:
        """
        初始化 PDF 报告生成器

        Args:
            template_path: xlsx 模板文件路径
            output_dir: PDF 输出目录
        """
        self._template_path = Path(template_path)
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._cells: dict[str, Any] = {}
        self._wb = None
        self._ws = None

        # 检查 LibreOffice 是否可用
        self._libreoffice_path = self._find_libreoffice()
        if self._libreoffice_path:
            logger.info(f"使用LibreOffice: {self._libreoffice_path}")
        else:
            logger.warning(f"LibreOffice初始化失败!")

    def _find_libreoffice(self) -> str | None:
        """查找系统中可用的 LibreOffice"""
        # 可能的路径
        paths: list[str] = []

        if platform.system() == "Windows":
            # Windows 常见安装路径
            paths.extend([
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                r"C:\Program Files\LibreOffice 7\program\soffice.exe",
                r"C:\Program Files\LibreOffice 8\program\soffice.exe",
            ])
        elif platform.system() == "Darwin":
            # macOS
            paths.extend([
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "/Applications/LibreOffice.app/Contents/MacOS/soffice.bin",
            ])
        else:
            # Linux
            paths.extend([
                "/usr/bin/soffice",
                "/usr/bin/libreoffice",
                "/opt/libreoffice7.6/program/soffice",
                "/opt/libreoffice8.0/program/soffice",
            ])

        # 添加 PATH 中的 soffice
        for cmd in ["soffice", "libreoffice"]:
            paths.append(cmd)

        for path in paths:
            if os.path.exists(path) if not cmd_in_path(path) else True:
                if self._check_libreoffice(path):
                    return path

        # 尝试通过 which/where 查找
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["where", "soffice"],
                                       capture_output=True, text=True, timeout=5)
            else:
                result = subprocess.run(["which", "soffice"],
                                       capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                lo_path = result.stdout.strip().split('\n')[0]
                if self._check_libreoffice(lo_path):
                    return lo_path
        except Exception:
            pass

        return None

    def _check_libreoffice(self, path: str) -> bool:
        """检查 LibreOffice 是否可用"""
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.debug(f"LibreOffice 版本: {version}")
                return True
        except Exception as e:
            logger.debug(f"检查 LibreOffice 失败: {e}")
        return False

    def load_template(self, sheet_name: str | None = None) -> "PdfReport":
        """
        加载 xlsx 模板文件

        Args:
            sheet_name: 工作表名称，None 则使用活动工作表

        Returns:
            self
        """
        if not self._template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {self._template_path}")

        self._wb = load_workbook(str(self._template_path))
        self._ws = self._wb[sheet_name] if sheet_name else self._wb.active
        self._extract_cells()
        logger.info(f"加载模板成功: {self._template_path}, 工作表: {self._ws.title}")
        return self

    def _extract_cells(self) -> None:
        """提取模板中的所有单元格数据"""
        self._cells = {}
        for row in self._ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    self._cells[cell.coordinate] = {
                        "value": cell.value,
                        "font": cell.font,
                        "fill": cell.fill,
                        "alignment": cell.alignment,
                        "border": cell.border,
                        "number_format": cell.number_format,
                    }

    def set_cell(self, cell_ref: str, value: Any) -> "PdfReport":
        """
        设置指定单元格的值

        Args:
            cell_ref: 单元格引用，如 "A1", "B2"
            value: 要设置的值

        Returns:
            self
        """
        self._cells[cell_ref.upper()] = {"value": value, "is_custom": True}
        return self

    def set_cells(self, data: dict[str, Any]) -> "PdfReport":
        """
        批量设置单元格的值

        Args:
            data: 字典，key 为单元格引用，value 为值

        Returns:
            self
        """
        for cell_ref, value in data.items():
            self.set_cell(cell_ref, value)
        return self

    def fill_from_workbook(self, source_wb) -> "PdfReport":
        """
        从另一个工作簿填充数据到当前模板

        Args:
            source_wb: openpyxl 工作簿对象

        Returns:
            self
        """
        if self._ws is None:
            raise RuntimeError("请先调用 load_template()")

        source_ws = source_wb.active
        for row in source_ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    coord = cell.coordinate
                    if coord in self._cells:
                        self._cells[coord]["value"] = cell.value
        return self

    def get_cell(self, cell_ref: str) -> Any:
        """获取指定单元格的值"""
        return self._cells.get(cell_ref.upper(), {}).get("value")

    def save_xlsx(self, filename: str | None = None) -> Path:
        """
        保存填充后的 xlsx 文件

        Args:
            filename: 文件名，None 则自动生成

        Returns:
            保存的文件路径
        """
        if self._wb is None:
            raise RuntimeError("请先调用 load_template()")

        if filename is None:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        output_path = self._output_dir / filename

        # 将数据写回工作簿
        for coord, data in self._cells.items():
            try:
                cell = self._ws[coord]
                cell.value = data.get("value")
            except Exception:
                pass

        self._wb.save(output_path)
        logger.info(f"Excel 报告已保存: {output_path}")
        return output_path

    def export_pdf(
        self,
        filename: str | None = None,
        title: str = "试验报告",
    ) -> Path:
        """
        通过 LibreOffice 将填充后的 xlsx 导出为 PDF

        Args:
            filename: PDF 文件名，None 则自动生成
            title: PDF 标题（仅用于日志）

        Returns:
            保存的 PDF 文件路径
        """
        if self._wb is None:
            raise RuntimeError("请先调用 load_template()")

        if self._libreoffice_path is None:
            raise RuntimeError("LibreOffice 未安装或不可用，无法导出 PDF")

        if filename is None:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        output_path = self._output_dir / filename

        # 写回数据到工作簿
        for coord, data in self._cells.items():
            try:
                cell = self._ws[coord]
                cell.value = data.get("value")
            except Exception:
                pass

        # 创建临时目录用于 LibreOffice 输出
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 保存临时 xlsx 文件
            temp_xlsx = tmp_path / "temp_report.xlsx"
            self._wb.save(str(temp_xlsx))
            logger.debug(f"临时文件已保存: {temp_xlsx}")

            # 使用 LibreOffice 转换为 PDF
            # --headless: 无头模式
            # --convert-to pdf: 转换为 PDF
            # --outdir: 输出目录
            try:
                cmd = [
                    self._libreoffice_path,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(tmp_path),
                    str(temp_xlsx)
                ]

                logger.debug(f"执行命令: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120  # 2 分钟超时
                )

                if result.returncode != 0:
                    logger.error(f"LibreOffice 转换失败: {result.stderr}")
                    raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")

                logger.debug(f"LibreOffice 输出: {result.stdout}")

                # 查找生成的 PDF 文件
                # LibreOffice 会将输出文件放在 outdir 中，文件名与源文件相同
                temp_pdf = tmp_path / "temp_report.pdf"

                if temp_pdf.exists():
                    # 移动到目标位置
                    shutil.move(str(temp_pdf), str(output_path))
                    logger.info(f"PDF 报告已生成: {output_path}")
                else:
                    # 尝试查找可能的输出文件名
                    pdf_files = list(tmp_path.glob("*.pdf"))
                    if pdf_files:
                        shutil.move(str(pdf_files[0]), str(output_path))
                        logger.info(f"PDF 报告已生成: {output_path}")
                    else:
                        raise RuntimeError(f"LibreOffice 未生成 PDF 文件")

            except subprocess.TimeoutExpired:
                raise RuntimeError("LibreOffice 转换超时（超过 2 分钟）")
            except Exception as e:
                raise RuntimeError(f"LibreOffice 转换出错: {e}")

        return output_path

    def preview(self) -> dict[str, Any]:
        """
        预览当前填充后的数据

        Returns:
            包含所有单元格数据的字典
        """
        return {k: v.get("value") for k, v in self._cells.items()}

    @property
    def template_path(self) -> Path:
        """模板文件路径"""
        return self._template_path

    @property
    def output_dir(self) -> Path:
        """输出目录路径"""
        return self._output_dir

    @property
    def libreoffice_available(self) -> bool:
        """LibreOffice 是否可用"""
        return self._libreoffice_path is not None


def cmd_in_path(cmd: str) -> bool:
    """检查命令是否在 PATH 中"""
    if os.path.exists(cmd):
        return True
    for path in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.exists(os.path.join(path, cmd)):
            return True
    return False


def create_pdf_report(
    template_path: str | Path,
    output_dir: str | Path,
    data: dict[str, Any] | None = None,
) -> PdfReport:
    """
    快捷函数：创建并初始化 PDF 报告生成器

    Args:
        template_path: xlsx 模板文件路径
        output_dir: PDF 输出目录
        data: 初始填充数据

    Returns:
        PdfReport 实例
    """
    report = PdfReport(template_path, output_dir)
    report.load_template()
    if data:
        report.set_cells(data)
    return report
