"""Small vector icons drawn with QPainter (no external image files)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

PRIMARY = "#1f5f8b"
SOFT = "#cfe2f1"


def _pen(painter: QPainter, width: float = 2.0, color: str = PRIMARY) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _draw(painter: QPainter, kind: str, color: str) -> None:
    """Draw one icon inside a 48 x 48 box."""
    if kind == "consumers":
        _pen(painter, 2.0, color)
        painter.drawEllipse(QPointF(18.5, 16.5), 4.8, 4.8)
        painter.drawArc(QRectF(9.5, 23.0, 18.0, 18.0), 0, 180 * 16)
        painter.drawEllipse(QPointF(31.5, 19.5), 3.7, 3.7)
        painter.drawArc(QRectF(25.0, 26.0, 13.0, 14.0), 0, 180 * 16)

    elif kind == "bill":
        _pen(painter, 2.0, color)
        painter.drawRoundedRect(QRectF(13.0, 6.5, 22.0, 35.0), 3.0, 3.0)
        for y in (16.0, 21.0, 26.0):
            painter.drawLine(QPointF(18.0, y), QPointF(30.0, y))
        _pen(painter, 2.6, color)
        painter.drawLine(QPointF(18.0, 32.0), QPointF(27.0, 32.0))

    elif kind == "payments":
        _pen(painter, 2.0, color)
        painter.drawRoundedRect(QRectF(7.5, 13.0, 33.0, 23.0), 3.0, 3.0)
        painter.drawLine(QPointF(7.5, 20.5), QPointF(40.5, 20.5))
        painter.drawLine(QPointF(12.5, 29.0), QPointF(23.0, 29.0))
        painter.drawLine(QPointF(12.5, 32.0), QPointF(18.5, 32.0))

    elif kind == "unitrate":
        path = QPainterPath()
        path.moveTo(27.0, 6.0)
        path.lineTo(14.0, 27.0)
        path.lineTo(22.5, 27.0)
        path.lineTo(20.0, 42.0)
        path.lineTo(35.0, 20.0)
        path.lineTo(26.0, 20.0)
        path.closeSubpath()
        _pen(painter, 2.0, color)
        painter.drawPath(path)

    elif kind == "reports":
        _pen(painter, 2.0, color)
        painter.drawLine(QPointF(9.5, 10.0), QPointF(9.5, 38.0))
        painter.drawLine(QPointF(9.5, 38.0), QPointF(40.0, 38.0))
        painter.setBrush(QColor(SOFT))
        _pen(painter, 1.7, color)
        painter.drawRoundedRect(QRectF(15.0, 26.0, 5.5, 12.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(23.5, 19.0, 5.5, 19.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(32.0, 12.0, 5.5, 26.0), 1.0, 1.0)

    elif kind == "masters":
        _pen(painter, 2.0, color)
        painter.drawEllipse(QRectF(11.0, 7.0, 26.0, 9.0))
        painter.drawLine(QPointF(11.0, 11.5), QPointF(11.0, 36.5))
        painter.drawLine(QPointF(37.0, 11.5), QPointF(37.0, 36.5))
        painter.drawArc(QRectF(11.0, 32.0, 26.0, 9.0), 180 * 16, 180 * 16)
        painter.drawArc(QRectF(11.0, 23.0, 26.0, 9.0), 180 * 16, 180 * 16)

    elif kind == "dashboard":
        _pen(painter, 1.7, color)
        painter.setBrush(QColor(SOFT))
        painter.drawRoundedRect(QRectF(10.0, 10.0, 12.0, 12.0), 2.0, 2.0)
        painter.drawRoundedRect(QRectF(26.0, 10.0, 12.0, 12.0), 2.0, 2.0)
        painter.drawRoundedRect(QRectF(10.0, 26.0, 12.0, 12.0), 2.0, 2.0)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(26.0, 26.0, 12.0, 12.0), 2.0, 2.0)

    elif kind == "excel":
        _pen(painter, 2.0, color)
        painter.drawRoundedRect(QRectF(10.0, 7.0, 28.0, 34.0), 2.5, 2.5)
        painter.drawLine(QPointF(10.0, 15.0), QPointF(38.0, 15.0))
        painter.drawLine(QPointF(19.0, 15.0), QPointF(19.0, 41.0))
        painter.drawLine(QPointF(28.0, 15.0), QPointF(28.0, 41.0))
        painter.drawLine(QPointF(10.0, 24.0), QPointF(38.0, 24.0))
        painter.drawLine(QPointF(10.0, 32.0), QPointF(38.0, 32.0))

    elif kind == "home":
        _pen(painter, 2.0, color)
        roof = QPainterPath()
        roof.moveTo(8.0, 23.0)
        roof.lineTo(24.0, 9.0)
        roof.lineTo(40.0, 23.0)
        painter.drawPath(roof)
        painter.drawRoundedRect(QRectF(13.0, 22.0, 22.0, 18.0), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(21.0, 31.0, 6.0, 9.0), 1.0, 1.0)

    elif kind == "settings":
        _pen(painter, 1.8, color)
        painter.drawEllipse(QPointF(24.0, 24.0), 5.0, 5.0)
        painter.drawEllipse(QPointF(24.0, 24.0), 10.5, 10.5)
        _pen(painter, 2.4, color)
        for index in range(8):
            angle = math.radians(index * 45)
            painter.drawLine(
                QPointF(24.0 + math.cos(angle) * 10.5, 24.0 + math.sin(angle) * 10.5),
                QPointF(24.0 + math.cos(angle) * 14.0, 24.0 + math.sin(angle) * 14.0),
            )


def make_icon(kind: str, size: int = 48, color: str = PRIMARY) -> QIcon:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 48.0 * ratio, size / 48.0 * ratio)
    _draw(painter, kind, color)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)
