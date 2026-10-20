"""称重台俯视示意图：QGraphicsScene 自绘。

替代旧版卡片式示意图（见 platform_cards_legacy.py）。俯视正投影风格
（原等距 2.5D 已按需求改为俯视图），配色沿用 platform.qss 的深色工业
色板（方案B）。

布局（与 measure.PITS 一致）：
    坑1: 台 1-6   （上排偶数 2,4,6 / 下排奇数 1,3,5）
    坑2: 台 7-14  （上排偶数 / 下排奇数）
    坑3: 台 15-18 （上排偶数 / 下排奇数）

对外接口（与旧卡片对齐，最小侵入）：
    view.set_values({台号: kN值或None})   # None 表示离线，显示灰色"离线"
    view.set_highlight([台号, ...])        # 车型启用的台位，深橙高亮

本系统不做结果判定，示意图只有 正常/高亮/离线 三种状态。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from measure import PITS

logger = logging.getLogger(__name__)

# ---------- 配色（与 platform.qss 深色工业色板一致） ----------
_BG = "#22262d"
_BALLAST = "#242931"
_BALLAST_BORDER = "#39404b"
_RAIL_DARK = "#5b616b"
_RAIL_LIGHT = "#9aa2ac"
_PIT_LABEL_C = "#cfd6dd"

_TILE_TOP_A = "#3d434e"
_TILE_TOP_B = "#2f3540"
_TILE_BORDER = "#484f5a"
_TITLE_C = "#9aa4b0"
_VALUE_C = "#eef1f4"
_UNIT_C = "#79828d"

_HL_TOP_A = "#4d3d20"   # 车型高亮：深橙（同方案B选中态）
_HL_TOP_B = "#3d2f18"
_HL_BORDER = "#e8912d"
_HL_TEXT = "#ffb84d"

_OFF_TOP_A = "#2b3038"    # 离线灰
_OFF_TOP_B = "#262b32"
_OFF_BORDER = "#3a4049"
_OFF_TEXT = "#79828d"

# ---------- 俯视正投影 ----------
_CW = 124.0     # 网格列宽（场景 px）
_CH = 104.0     # 网格行高（场景 px）
_PIT_GAP = 1.0  # 坑间距（格）


def _proj(gx: float, gy: float) -> tuple[float, float]:
    """网格坐标 -> 场景坐标（俯视正投影）。"""
    return (gx * _CW, gy * _CH)


def _pit_layout() -> dict[int, dict]:
    """坑号 -> {"x0": 起始格x, "cols": 列数, "pos": {台号: (gx, gy)}}。

    偶数号在上排（gy=0.5），奇数号在下排（gy=1.5）。
    """
    layout: dict[int, dict] = {}
    x = 0.0
    for pit_no in sorted(PITS):
        plats = sorted(PITS[pit_no])
        evens = [p for p in plats if p % 2 == 0]
        odds = [p for p in plats if p % 2 == 1]
        cols = max(len(evens), len(odds))
        pos: dict[int, tuple[float, float]] = {}
        for col, p in enumerate(evens):
            pos[p] = (x + col + 0.5, 0.5)
        for col, p in enumerate(odds):
            pos[p] = (x + col + 0.5, 1.5)
        layout[pit_no] = {"x0": x, "cols": cols, "pos": pos}
        x += cols + _PIT_GAP
    return layout


class PlatformTile(QGraphicsItem):
    """单个称重台台体（俯视圆角矩形）。本地坐标以台体中心为原点。"""

    _W2 = 56.0   # 台体半宽
    _H2 = 44.0   # 台体半高
    _RADIUS = 10.0  # 圆角半径

    def __init__(self, platform: int) -> None:
        super().__init__()
        self.platform = platform
        self._value: float | None = None
        self._state = "normal"  # normal/highlight/offline

    # -- 数据接口 --
    @property
    def value(self) -> float | None:
        return self._value

    def set_value(self, value: float | None) -> bool:
        """返回 True 表示发生变化（需要重绘）。"""
        if value == self._value:
            return False
        self._value = value
        return True

    def set_state(self, state: str) -> bool:
        if state == self._state:
            return False
        self._state = state
        return True

    # -- 绘制 --
    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return QRectF(-64, -52, 128, 104)

    def _palette(self) -> tuple[str, str, str, str, str, str]:
        """(渐变起, 渐变止, 边框, 标题色, 数值色, 单位色)。"""
        s = self._state
        if s == "offline":
            return (_OFF_TOP_A, _OFF_TOP_B, _OFF_BORDER,
                    _OFF_TEXT, _OFF_TEXT, _OFF_TEXT)
        if s == "highlight":
            return (_HL_TOP_A, _HL_TOP_B, _HL_BORDER,
                    _HL_TEXT, _HL_TEXT, _UNIT_C)
        return (_TILE_TOP_A, _TILE_TOP_B, _TILE_BORDER,
                _TITLE_C, _VALUE_C, _UNIT_C)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hw, hh, r = self._W2, self._H2, self._RADIUS
        top_a, top_b, border_c, title_c, value_c, unit_c = self._palette()

        # 台体：纵向渐变圆角矩形
        grad = QLinearGradient(0, -hh, 0, hh)
        grad.setColorAt(0.0, QColor(top_a))
        grad.setColorAt(1.0, QColor(top_b))
        painter.setBrush(QBrush(grad))

        # 边框：状态色，高亮时加粗
        pen = QPen(QColor(border_c))
        pen.setWidthF(2.0 if self._state == "highlight" else 1.2)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(-hw, -hh, hw * 2, hh * 2), r, r)

        # 顶部 1px 高光线
        hi_pen = QPen(QColor(255, 255, 255, 28))
        hi_pen.setWidthF(1.0)
        painter.setPen(hi_pen)
        painter.drawLine(int(-hw) + r, int(-hh) + 2, int(hw) - r, int(-hh) + 2)

        # 文字
        painter.setPen(Qt.PenStyle.NoPen)
        if self._state == "offline":
            f = QFont()
            f.setPixelSize(14)
            painter.setFont(f)
            painter.setPen(QColor(_OFF_TEXT))
            painter.drawText(QRectF(-hw, -12, hw * 2, 24),
                             Qt.AlignmentFlag.AlignCenter, "离线")
            return
        f_title = QFont()
        f_title.setPixelSize(11)
        painter.setFont(f_title)
        painter.setPen(QColor(title_c))
        painter.drawText(QRectF(-hw, -hh + 4, hw * 2, 16),
                         Qt.AlignmentFlag.AlignCenter, f"称重台{self.platform}")

        f_value = QFont()
        f_value.setPixelSize(20)
        f_value.setBold(True)
        painter.setFont(f_value)
        painter.setPen(QColor(value_c))
        text = "--" if self._value is None else f"{self._value:.1f}"
        painter.drawText(QRectF(-hw, -hh + 20, hw * 2, 28),
                         Qt.AlignmentFlag.AlignCenter, text)

        f_unit = QFont()
        f_unit.setPixelSize(10)
        painter.setFont(f_unit)
        painter.setPen(QColor(unit_c))
        painter.drawText(QRectF(-hw, hh - 18, hw * 2, 14),
                         Qt.AlignmentFlag.AlignCenter, "kN")


class PlatformSceneView(QGraphicsView):
    """2.5D 称重台示意图视图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"QGraphicsView {{ background: {_BG}; border: none; }}")

        self._tiles: dict[int, PlatformTile] = {}
        self._values: dict[int, float | None] = {}
        self._highlight: set[int] = set()

        self._build_static()
        layout = _pit_layout()
        for pit_no in sorted(layout):
            for p, (gx, gy) in layout[pit_no]["pos"].items():
                tile = PlatformTile(p)
                sx, sy = _proj(gx, gy)
                tile.setPos(sx, sy)
                self._scene.addItem(tile)
                self._tiles[p] = tile
        rect = self._scene.itemsBoundingRect().adjusted(-12, -12, 12, 12)
        self._scene.setSceneRect(rect)

    # ---------- 静态背景：道砟 / 钢轨 / 坑位标签（俯视） ----------
    def _build_static(self) -> None:
        layout = _pit_layout()
        for pit_no in sorted(layout):
            x0 = layout[pit_no]["x0"]
            cols = layout[pit_no]["cols"]
            x1 = x0 + cols

            # 道砟底座：圆角矩形（收紧轨道外侧留空）
            bx0, by0 = _proj(x0 - 0.4, -0.32)
            bx1, by1 = _proj(x1 + 0.4, 2.32)
            self._scene.addRect(
                QRectF(bx0, by0, bx1 - bx0, by1 - by0),
                QPen(QColor(_BALLAST_BORDER), 2),
                QBrush(QColor(_BALLAST)),
            )

            # 两条钢轨（沿行进方向 gx 的水平线），先画宽深色底再画窄亮色面
            for gy in (0.5, 1.5):
                x1s, y1s = _proj(x0 - 0.3, gy)
                x2s, y2s = _proj(x1 + 0.3, gy)
                for width, color in ((10, _RAIL_DARK), (4, _RAIL_LIGHT)):
                    line = QGraphicsLineItem(x1s, y1s, x2s, y2s)
                    pen = QPen(QColor(color))
                    pen.setWidthF(width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    line.setPen(pen)
                    self._scene.addItem(line)

            # 坑位标签
            label = QGraphicsSimpleTextItem(f"坑{pit_no}")
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            label.setFont(font)
            label.setBrush(QBrush(QColor(_PIT_LABEL_C)))
            lx, ly = _proj(x0 + cols / 2.0, -0.24)
            label.setPos(lx - label.boundingRect().width() / 2, ly)
            self._scene.addItem(label)

    # ---------- 自适应 ----------
    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ---------- 数据接口 ----------
    def _effective_state(self, p: int) -> str:
        if self._values.get(p) is None and p in self._tiles:
            # 值缺失即离线（从未收到值也按离线处理，保证首屏语义明确）
            return "offline"
        if p in self._highlight:
            return "highlight"
        return "normal"

    def _apply_states(self, platforms) -> None:
        for p in platforms:
            tile = self._tiles.get(p)
            if tile is None:
                continue
            if tile.set_state(self._effective_state(p)):
                tile.update()

    def set_values(self, values: dict[int, float | None]) -> None:
        """刷新全部台位数值；None 表示离线。"""
        for p, tile in self._tiles.items():
            if tile.set_value(values.get(p)):
                tile.update()  # 数值变化必须请求重绘，否则画面停留旧值
        self._values = {p: values.get(p) for p in self._tiles}
        self._apply_states(set(self._tiles))

    def set_highlight(self, platforms) -> None:
        """设置车型启用的台位高亮集合。"""
        new = set(platforms)
        if new == self._highlight:
            return
        old = self._highlight
        self._highlight = new
        self._apply_states(old | new)
