from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass
class DynamicRectState:
    corner_offsets: list[QPointF]
    box_offsets_y: list[float]


class DynamicRectWidget(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margin: float = 0.1,
        min_width: int = 360,
        min_height: int = 280,
        interval_ms: int = 500,
        map_range: float = 2.0,
    ) -> None:
        super().__init__(parent)
        self._margin = margin
        self._map_range = map_range
        self._interval_ms = interval_ms
        self._state = DynamicRectState(
            corner_offsets=[QPointF(0.0, 0.0) for _ in range(4)],
            box_offsets_y=[0.0, 0.0],
        )

        self.setMinimumSize(min_width, min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._update_dynamic_rect)
        self._timer.start()

        self._update_dynamic_rect()

    def cal_pos(self) -> DynamicRectState:
        corner_offsets: list[QPointF] = []
        for _ in range(4):
            dx = random.randint(10, 100)
            dy = random.randint(10, 100)
            corner_offsets.append(
                QPointF(
                    self._map_offset(dx) * random.choice((-1, 1)),
                    self._map_offset(dy) * random.choice((-1, 1)),
                )
            )
        box_offsets_y = [
            self._map_offset(random.randint(10, 100)) * random.choice((-1, 1))
            for _ in range(2)
        ]
        return DynamicRectState(corner_offsets=corner_offsets, box_offsets_y=box_offsets_y)

    def _map_offset(self, value: int) -> float:
        return (value / 100.0) * self._map_range

    def _update_dynamic_rect(self) -> None:
        self._state = self.cal_pos()
        self.update()

    def refresh_now(self) -> None:
        self._update_dynamic_rect()

    def reset_state(self) -> None:
        self._state = DynamicRectState(
            corner_offsets=[QPointF(0.0, 0.0) for _ in range(4)],
            box_offsets_y=[0.0, 0.0],
        )
        self.update()

    def _anchor_points(self) -> list[QPointF]:
        rect = self.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return []

        margin_x = rect.width() * self._margin
        margin_y = rect.height() * self._margin
        anchor = QRectF(
            rect.left() + margin_x,
            rect.top() + margin_y,
            rect.width() - 2 * margin_x,
            rect.height() - 2 * margin_y,
        )
        return [
            anchor.topLeft(),
            anchor.topRight(),
            anchor.bottomRight(),
            anchor.bottomLeft(),
        ]

    def _dynamic_points(self) -> list[QPointF]:
        anchor_points = self._anchor_points()
        return [
            self._clamp_point(point + offset)
            for point, offset in zip(anchor_points, self._state.corner_offsets, strict=False)
        ]

    def _clamp_point(self, point: QPointF) -> QPointF:
        padding = 12.0
        x = min(max(point.x(), padding), max(self.width() - padding, padding))
        y = min(max(point.y(), padding), max(self.height() - padding, padding))
        return QPointF(x, y)

    def _anchor_rect(self) -> QRectF:
        points = self._anchor_points()
        if not points:
            return QRectF()
        return QRectF(points[0], points[2]).normalized()

    def _center_axis(self) -> tuple[QPointF, QPointF]:
        anchor_rect = self._anchor_rect()
        center_x = anchor_rect.center().x()
        return QPointF(center_x, anchor_rect.top()), QPointF(center_x, anchor_rect.bottom())

    def _box_rects(self) -> list[QRectF]:
        anchor_rect = self._anchor_rect()
        if anchor_rect.isNull():
            return []

        center_x = anchor_rect.center().x()
        base_ys = [
            anchor_rect.top() + anchor_rect.height() * 0.33,
            anchor_rect.top() + anchor_rect.height() * 0.67,
        ]
        box_width = max(anchor_rect.width() * 0.12, 24.0)
        box_height = max(anchor_rect.height() * 0.08, 18.0)

        rects: list[QRectF] = []
        for base_y, offset_y in zip(base_ys, self._state.box_offsets_y, strict=False):
            center_y = min(
                max(base_y + offset_y, anchor_rect.top() + box_height / 2.0),
                anchor_rect.bottom() - box_height / 2.0,
            )
            rects.append(
                QRectF(
                    center_x - box_width / 2.0,
                    center_y - box_height / 2.0,
                    box_width,
                    box_height,
                )
            )
        return rects

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._paint_background(painter)
        self._paint_grid(painter)

        anchor_points = self._anchor_points()
        if not anchor_points:
            return

        dynamic_points = self._dynamic_points()
        self._paint_polygon(painter, anchor_points, dashed=True)
        self._paint_center_axis(painter)
        self._paint_polygon(painter, dynamic_points, dashed=False)
        self._paint_connectors(painter, anchor_points, dynamic_points)
        self._paint_axis_boxes(painter)
        self._paint_points(painter, anchor_points, dynamic_points)
        self._paint_center_label(painter)

    def _paint_background(self, painter: QPainter) -> None:
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor("#04131f"))
        gradient.setColorAt(0.55, QColor("#0b2032"))
        gradient.setColorAt(1.0, QColor("#051018"))
        painter.fillRect(self.rect(), gradient)

    def _paint_grid(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QPen(QColor(76, 173, 255, 28), 1))
        step = 28
        for x in range(0, self.width(), step):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            painter.drawLine(0, y, self.width(), y)
        painter.restore()

    def _paint_polygon(self, painter: QPainter, points: list[QPointF], *, dashed: bool) -> None:
        path = QPainterPath()
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()

        painter.save()
        if dashed:
            painter.setPen(QPen(QColor("#58d1ff"), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
        else:
            painter.setPen(QPen(QColor("#00ffd0"), 2.4))
            painter.setBrush(QColor(0, 255, 208, 34))
        painter.drawPath(path)
        painter.restore()

    def _paint_connectors(
        self, painter: QPainter, anchor_points: list[QPointF], dynamic_points: list[QPointF]
    ) -> None:
        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.DotLine))
        for anchor_point, dynamic_point in zip(anchor_points, dynamic_points, strict=False):
            painter.drawLine(anchor_point, dynamic_point)
        painter.restore()

    def _paint_center_axis(self, painter: QPainter) -> None:
        start, end = self._center_axis()
        painter.save()
        painter.setPen(QPen(QColor(120, 210, 255, 110), 1.5, Qt.DashLine))
        painter.drawLine(start, end)
        painter.restore()

    def _paint_axis_boxes(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QPen(QColor("#8ce8ff"), 1.2))
        painter.setBrush(QColor(104, 241, 255, 50))
        for rect in self._box_rects():
            painter.drawRoundedRect(rect, 4, 4)
        painter.restore()

    def _paint_points(
        self, painter: QPainter, anchor_points: list[QPointF], dynamic_points: list[QPointF]
    ) -> None:
        painter.save()
        for index, point in enumerate(anchor_points, start=1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#58d1ff"))
            painter.drawEllipse(point, 4, 4)
            painter.setPen(QColor("#b8f3ff"))
            painter.drawText(point + QPointF(8, -8), f"A{index}")

        for index, point in enumerate(dynamic_points, start=1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#00ffd0"))
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QColor("#d8fff7"))
            painter.drawText(point + QPointF(8, 16), f"D{index}")
        painter.restore()

    def _paint_center_label(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QColor(220, 228, 235, 92))
        painter.drawText(self.rect(), Qt.AlignCenter, "转向架实时数据")
        painter.restore()
