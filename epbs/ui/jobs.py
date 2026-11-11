"""Dockable log for the background export queue."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)


class JobLogDock(QDockWidget):
    """Shows queued / running / finished background jobs."""

    def __init__(self, jobs, parent=None):
        super().__init__("Job log", parent)
        self.jobs = jobs
        self._last_path = ""
        self.setObjectName("jobLogDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea |
                             Qt.DockWidgetArea.TopDockWidgetArea)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.status = QLabel("Queue idle.")
        self.status.setObjectName("muted")
        self.status.setMinimumWidth(120)
        row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setMaximumWidth(140)
        self.progress.setVisible(False)
        row.addWidget(self.progress)
        self.open_btn = QPushButton("Open last file")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_last)
        row.addWidget(self.open_btn)
        clear_btn = QPushButton("Clear log")
        clear_btn.clicked.connect(self._clear)
        row.addWidget(clear_btn)
        lay.addLayout(row)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(2000)
        self.view.setMinimumHeight(96)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self.view.setFont(font)
        self.view.setPlaceholderText("Exports are queued here, one at a time. "
                                     "You can keep working while a job runs.")
        lay.addWidget(self.view)
        self.setWidget(body)
        self.setMinimumHeight(190)

        jobs.log.connect(self._append)
        jobs.queued.connect(self._queued)
        jobs.started.connect(self._started)
        jobs.finished.connect(self._finished)
        jobs.pending_changed.connect(self._pending)

    # ------------------------------------------------------------------
    def _append(self, line: str) -> None:
        self.view.appendPlainText(line)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _queued(self, name: str) -> None:
        self.show()
        self.raise_()

    def _started(self, name: str) -> None:
        self.status.setText(f"Running: {name}")
        self.progress.setVisible(True)
        self.show()

    def _finished(self, name: str, summary: str, ok: bool, path: str, seconds: str) -> None:
        self.progress.setVisible(False)
        if ok:
            self.status.setText(f"Last: {name} ({seconds} s)")
            if path:
                self._last_path = path
                self.open_btn.setEnabled(Path(path).exists())
        else:
            self.status.setText(f"Last: {name} — failed")
        self.status.setToolTip(summary or name)

    def _pending(self, count: int) -> None:
        if count:
            current = self.jobs.current
            self.status.setText(
                f"{count} job(s) in queue" + (f" · running: {current}" if current else ""))
            self.progress.setVisible(True)
        elif not self.progress.isVisible():
            self.status.setText("Queue idle.")
            self.status.setToolTip("")

    def _open_last(self) -> None:
        if self._last_path and Path(self._last_path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_path))

    def _clear(self) -> None:
        self.view.clear()
        self._append("Log cleared.")
