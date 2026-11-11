"""Shared UI helpers: cards, tables, the consumer search box, dialogs."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import services
from ..printing import fmt_date, money


def qdate(value: date | None) -> QDate:
    value = value or date.today()
    return QDate(value.year, value.month, value.day)


def to_date(widget: QDateEdit) -> date:
    d = widget.date()
    return date(d.year(), d.month(), d.day())


def date_edit(value: date | None = None) -> QDateEdit:
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd-MM-yyyy")
    w.setDate(qdate(value))
    return w


def money_spin(value: float = 0.0, maximum: float = 10_000_000.0) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setDecimals(2)
    w.setRange(0, maximum)
    w.setSingleStep(1.0)
    w.setGroupSeparatorShown(True)
    w.setValue(float(value or 0))
    return w


def info(parent, message: str, title: str = "EPBS") -> None:
    QMessageBox.information(parent, title, str(message))


def warn(parent, message: str, title: str = "EPBS") -> None:
    QMessageBox.warning(parent, title, str(message))


def error(parent, message: str, title: str = "Error") -> None:
    QMessageBox.critical(parent, title, str(message))


def confirm(parent, message: str, title: str = "Please confirm") -> bool:
    return _ask(parent, title, message, QMessageBox.Icon.Question)


def confirm_save(parent, message: str) -> bool:
    """Safety check before any insert/update is written to the database."""
    return _ask(parent, "Confirm save", message, QMessageBox.Icon.Question)


def confirm_delete(parent, message: str) -> bool:
    """Safety check before anything is removed."""
    return _ask(parent, "Confirm delete", message, QMessageBox.Icon.Warning)


def _ask(parent, title: str, message: str, icon) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(icon)
    box.setText(str(message))
    yes = box.addButton(QMessageBox.StandardButton.Yes)
    no = box.addButton(QMessageBox.StandardButton.No)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


class KpiCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)
        self.value = QLabel("-")
        self.value.setObjectName("kpiValue")
        caption = QLabel(label)
        caption.setObjectName("kpiLabel")
        lay.addWidget(self.value)
        lay.addWidget(caption)

    def set(self, value) -> None:
        self.value.setText(str(value))


class Table(QTableWidget):
    # words that get a colour so status columns are easy to scan
    STATUS_TONES = {
        "paid": "#15803d",
        "active": "#15803d",
        "unpaid": "#b91c1c",
        "inactive": "#6b7280",
        "left": "#6b7280",
        "overdue": "#b45309",
        "punishment": "#b45309",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)

    def load(self, headers: list[str], rows: list[list], money_cols: set[int] | None = None,
             right_cols: set[int] | None = None) -> None:
        money_cols = money_cols or set()
        right_cols = right_cols or set()
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if c in money_cols:
                    text = money(value)
                elif isinstance(value, Decimal):
                    text = str(value)
                else:
                    text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                if c in money_cols or c in right_cols:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c not in money_cols:
                    tone = self.STATUS_TONES.get(text.strip().lower())
                    if tone:
                        item.setForeground(QColor(tone))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                if isinstance(value, (int, float, Decimal)):
                    item.setData(Qt.ItemDataRole.UserRole, float(value))
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        for c in range(self.columnCount()):
            if self.columnWidth(c) > 320:
                self.setColumnWidth(c, 320)


class Pager(QWidget):
    """Cursor pager: Previous / Next with a page number.

    The owner keeps the data cursor; the pager only stores the history of
    cursors so Previous can return to an earlier page.
    """

    page_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack: list[object] = [None]
        self._next_cursor = None
        self._has_next = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.label = QLabel("Page 1")
        self.label.setObjectName("muted")
        row.addWidget(self.label)
        row.addStretch(1)
        self.prev = QPushButton("‹ Previous")
        self.next = QPushButton("Next ›")
        self.prev.clicked.connect(self._prev)
        self.next.clicked.connect(self._next)
        row.addWidget(self.prev)
        row.addWidget(self.next)
        self._update()

    def reset(self) -> None:
        self._stack = [None]
        self._next_cursor = None
        self._has_next = False
        self._update()

    def current(self):
        return self._stack[-1]

    def set_result(self, has_next: bool, next_cursor) -> None:
        self._has_next = bool(has_next and next_cursor is not None)
        self._next_cursor = next_cursor
        self._update()

    def _next(self) -> None:
        if not self._has_next:
            return
        self._stack.append(self._next_cursor)
        self._next_cursor = None
        self._has_next = False
        self._update()
        self.page_changed.emit()

    def _prev(self) -> None:
        if len(self._stack) <= 1:
            return
        self._stack.pop()
        self._next_cursor = None
        self._has_next = False
        self._update()
        self.page_changed.emit()

    def _update(self) -> None:
        self.label.setText(f"Page {len(self._stack)}")
        self.prev.setEnabled(len(self._stack) > 1)
        self.next.setEnabled(self._has_next)


class PagedTable(QWidget):
    """A table with its own cursor pager, used by the detail dialogs."""

    page_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = Table()
        self.pager = Pager()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pager)
        self.pager.page_changed.connect(self.page_changed)

    def reset(self) -> None:
        self.pager.reset()

    def load(self, headers: list[str], rows: list[list], money_cols: set[int] | None = None,
             right_cols: set[int] | None = None, has_next: bool = False,
             next_cursor=None) -> None:
        self.table.load(headers, rows, money_cols, right_cols)
        self.pager.set_result(has_next, next_cursor)


class ConsumerPicker(QWidget):
    """Search box for account number / meter number / name."""

    consumer_selected = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._current: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Account no, meter no or consumer name...")
        self.edit.setClearButtonEnabled(True)
        self.button = QPushButton("Search")
        self.button.setObjectName("primary")
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        self.results = QListWidget()
        self.results.setVisible(False)
        self.results.setMaximumHeight(150)
        self.hint = QLabel("Type an account number or meter number. Results appear below.")
        self.hint.setObjectName("muted")
        lay.addLayout(row)
        lay.addWidget(self.results)
        lay.addWidget(self.hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._search)
        self.edit.textEdited.connect(lambda _t: self._timer.start())
        self.edit.returnPressed.connect(self._accept_typed)
        self.button.clicked.connect(self._search)
        self.results.itemClicked.connect(self._choose)

    # -- public ---------------------------------------------------------
    @property
    def current_id(self) -> int | None:
        return self._current

    def focus_input(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    def set_consumer(self, con_id: int) -> None:
        consumer = services.get_consumer(self.db, con_id)
        if not consumer:
            return
        self._current = int(con_id)
        self.edit.setText(f"{consumer['con_id']} — {consumer.get('con_name') or ''}")
        self.results.setVisible(False)
        self.hint.setText(
            f"Selected: {consumer.get('con_name') or ''} · meter {consumer.get('meter_no') or '-'} · "
            f"{consumer.get('type_name') or 'no type'} · rate {money(consumer.get('rate'))}"
        )
        self.consumer_selected.emit(int(con_id))

    def clear(self) -> None:
        self._current = None
        self.edit.clear()
        self.results.clear()
        self.results.setVisible(False)
        self.hint.setText("Type an account number or meter number. Results appear below.")

    # -- internals ------------------------------------------------------
    def _search(self) -> None:
        text = self.edit.text().strip()
        if not text:
            self.results.clear()
            self.results.setVisible(False)
            return
        try:
            rows = services.search_consumers(self.db, text, limit=20)
        except Exception as exc:
            self.hint.setText(str(exc))
            return
        self.results.clear()
        for c in rows:
            item = QListWidgetItem(
                f"{c['con_id']} — {c.get('con_name') or ''} — meter {c.get('meter_no') or '-'} "
                f"— {c.get('type_name') or 'no type'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, int(c["con_id"]))
            self.results.addItem(item)
        if rows:
            self.results.setVisible(True)
            self.hint.setText(f"{len(rows)} match(es). Click a row to select.")
        else:
            self.results.setVisible(False)
            self.hint.setText("No consumer found for that search.")

    def _accept_typed(self) -> None:
        text = self.edit.text().strip()
        try:
            consumer = services.get_consumer_by_key(self.db, text)
        except Exception as exc:
            self.hint.setText(str(exc))
            return
        if consumer:
            self.set_consumer(int(consumer["con_id"]))
        else:
            self._search()

    def _choose(self, item: QListWidgetItem) -> None:
        con_id = item.data(Qt.ItemDataRole.UserRole)
        if con_id:
            self.set_consumer(int(con_id))


def busy():
    class _Busy:
        def __enter__(self):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def __exit__(self, *exc):
            QApplication.restoreOverrideCursor()

    return _Busy()


def combo(items: list[dict], id_key: str, label_key: str, blank: str = "") -> QComboBox:
    box = QComboBox()
    if blank:
        box.addItem(blank, None)
    for item in items:
        box.addItem(str(item.get(label_key) or ""), item.get(id_key))
    return box


def set_combo_id(box: QComboBox, value) -> None:
    index = box.findData(value)
    box.setCurrentIndex(index if index >= 0 else 0)
