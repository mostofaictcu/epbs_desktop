"""Animated SVG logo widget.

Qt's SVG renderer understands the CSS keyframes embedded in
``static/images/logo.svg``.  A QLabel/QPixmap freezes the image on its first
frame, so this widget drives the renderer frame by frame and repaints itself.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


class AnimatedLogo(QWidget):
    """Plays the animation stored in an SVG file once, then holds the last frame.

    ``height`` is the drawn logo height in pixels; ``plate`` adds a white
    rounded background (used on the blue Home banner).
    """

    def __init__(self, path=None, height: int = 48, plate: bool = False, parent=None):
        super().__init__(parent)
        self._renderer = QSvgRenderer(self)
        self._renderer.setAnimationEnabled(True)
        self._fallback = QPixmap()
        self._path = ""
        self._valid = False
        self._plate = plate
        self._logo_height = max(8, int(height))
        self._frame = 0
        self._finished = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if path:
            self.set_source(path)
        else:
            self._update_size()

    # -- public ---------------------------------------------------------
    def set_source(self, path) -> bool:
        text = str(path) if path else ""
        if text and text == self._path:
            return self._valid
        self._path = text
        self._valid = False
        if text and Path(text).is_file():
            self._valid = bool(self._renderer.load(text))
        if self._valid:
            self._renderer.setAnimationEnabled(True)
            self._renderer.setCurrentFrame(0)
            self._frame = 0
            self._finished = False
        self._update_size()
        self.update()
        return self._valid

    def set_fallback(self, pixmap: QPixmap) -> None:
        self._fallback = pixmap
        self.update()

    def is_valid(self) -> bool:
        return self._valid

    def play(self) -> None:
        if not self._valid:
            return
        self._frame = 0
        self._finished = False
        self._renderer.setCurrentFrame(0)
        self._timer.setInterval(max(10, int(1000 / self._fps())))
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    # -- internals ------------------------------------------------------
    def _fps(self) -> int:
        try:
            return max(1, int(self._renderer.framesPerSecond() or 30))
        except Exception:
            return 30

    def _total_frames(self) -> int:
        duration = max(0, int(self._renderer.animationDuration()))
        return max(1, int(round(duration / 1000.0 * self._fps())))

    def _update_size(self) -> None:
        size = self._renderer.defaultSize() if self._valid else None
        if size is not None and size.isValid() and size.height() > 0:
            width = max(8, round(self._logo_height * size.width() / size.height()))
        elif not self._fallback.isNull() and self._fallback.height() > 0:
            width = max(8, round(self._logo_height * self._fallback.width()
                                 / self._fallback.height()))
        else:
            width = self._logo_height
        pad = 12 if self._plate else 0
        self.setFixedSize(width + pad, self._logo_height + pad)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._finished:
            self.play()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.stop()

    def _tick(self) -> None:
        total = self._total_frames()
        self._frame += 1
        if self._frame >= total:
            self._frame = total - 1
            self._timer.stop()
            self._finished = True
        self._renderer.setCurrentFrame(self._frame)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        if self._plate:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(rect, 10, 10)
            rect = rect.adjusted(6, 6, -6, -6)

        if not self._valid or self._renderer.defaultSize().isEmpty():
            if not self._fallback.isNull():
                pixmap = self._fallback.scaled(
                    rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(
                    int(rect.x() + (rect.width() - pixmap.width()) / 2),
                    int(rect.y() + (rect.height() - pixmap.height()) / 2),
                    pixmap)
            return

        size = self._renderer.defaultSize()
        scale = min(rect.width() / size.width(), rect.height() / size.height())
        width = size.width() * scale
        height = size.height() * scale
        target = QRectF(
            rect.x() + (rect.width() - width) / 2,
            rect.y() + (rect.height() - height) / 2,
            width, height)
        self._renderer.render(painter, target)


def logo_pixmap(path, height: int | None = None) -> QPixmap:
    """Static logo image, rendered on the last animation frame.

    ``QPixmap``/``QIcon`` freeze an animated SVG on a nearly empty first frame,
    so previews and window icons use the finished artwork instead.
    """
    text = str(path) if path else ""
    if not text:
        return QPixmap()
    if Path(text).suffix.lower() != ".svg":
        return QPixmap(text)
    renderer = QSvgRenderer(text)
    if not renderer.isValid():
        return QPixmap(text)
    renderer.setAnimationEnabled(True)
    fps = renderer.framesPerSecond() or 30
    total = max(1, round(renderer.animationDuration() / 1000 * fps))
    renderer.setCurrentFrame(total - 1)
    size = renderer.defaultSize()
    if not size.isValid() or size.height() <= 0:
        return QPixmap(text)
    target_height = int(height) if height else size.height()
    target_width = max(1, round(target_height * size.width() / size.height()))
    image = QImage(target_width, target_height,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, target_width, target_height))
    painter.end()
    return QPixmap.fromImage(image)
