from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import excelio, services
from .common import Pager, Table, date_edit, error, info, money, to_date, warn
from .documents import print_report

REPORTS = [
    ("bills", "Bills register"),
    ("collections", "Collections (payments)"),
    ("dues_consumer", "Outstanding dues by consumer"),
    ("dues_area", "Outstanding dues by area"),
    ("dues_type", "Outstanding dues by consumer type"),
    ("consumers", "Consumer list"),
    ("monthly", "Monthly billing summary"),
]


class ReportsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._result: dict | None = None
        self._build()
        self._kind_changed()
        self.ctx.data_changed.connect(self._stale)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Reports and Excel")
        title.setObjectName("h1")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.kind = QComboBox()
        for key, label in REPORTS:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.date_from = date_edit(date(date.today().year, 1, 1))
        self.date_to = date_edit(date.today())
        self.month = QComboBox()
        for value, label in services.month_choices(6, include_blank=True):
            self.month.addItem(label, value)
        self.status = QComboBox()
        self.status.addItem("All status", "")
        self.status.addItem("Unpaid", "Unpaid")
        self.status.addItem("Paid", "Paid")
        self.status.setVisible(False)
        run = QPushButton("Run report")
        run.setObjectName("primary")
        run.clicked.connect(self.run)
        filters.addWidget(QLabel("Report"))
        filters.addWidget(self.kind, 1)
        filters.addWidget(QLabel("From"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("To"))
        filters.addWidget(self.date_to)
        filters.addWidget(self.month)
        filters.addWidget(self.status)
        filters.addWidget(run)
        root.addLayout(filters)

        self.table = Table()
        root.addWidget(self.table, 1)

        self.pager = Pager()
        self.pager.page_changed.connect(self._fetch)
        root.addWidget(self.pager)

        self.footer = QLabel("Choose a report and press 'Run report'.")
        self.footer.setObjectName("muted")
        root.addWidget(self.footer)

        actions = QHBoxLayout()
        export = QPushButton("Export report to Excel")
        export.clicked.connect(self.export_current)
        print_btn = QPushButton("Print report")
        print_btn.clicked.connect(lambda: self._print(as_pdf=False))
        pdf_btn = QPushButton("Report PDF")
        pdf_btn.clicked.connect(lambda: self._print(as_pdf=True))
        backup = QPushButton("Full database to Excel")
        backup.setObjectName("primary")
        backup.clicked.connect(self.export_all)
        actions.addWidget(export)
        actions.addWidget(print_btn)
        actions.addWidget(pdf_btn)
        actions.addStretch(1)
        actions.addWidget(backup)
        root.addLayout(actions)

    # ------------------------------------------------------------------
    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        self.date_from.setEnabled(kind in ("bills", "collections"))
        self.date_to.setEnabled(kind in ("bills", "collections"))
        self.month.setEnabled(kind in ("bills", "monthly"))
        self.status.setVisible(kind in ("bills", "consumers"))

    def _stale(self) -> None:
        if self._result:
            self.footer.setText(self.footer.text() + "  (data changed - run again)")

    def _subtitle(self) -> str:
        kind = self.kind.currentData()
        bits = []
        if kind in ("bills", "collections"):
            bits.append(f"Dates {to_date(self.date_from)} to {to_date(self.date_to)}")
        if kind in ("bills", "monthly") and self.month.currentData():
            bits.append(f"Month {self.month.currentData()}")
        if kind in ("bills", "consumers") and self.status.currentData():
            bits.append(f"Status {self.status.currentData()}")
        return " · ".join(bits)

    def _filters(self) -> dict:
        kind = self.kind.currentData()
        return {
            "kind": kind,
            "date_from": to_date(self.date_from) if kind in ("bills", "collections") else None,
            "date_to": to_date(self.date_to) if kind in ("bills", "collections") else None,
            "status": self.status.currentData() if kind in ("bills", "consumers") else "",
            "month": self.month.currentData() if kind in ("bills", "monthly") else "",
        }

    def run(self) -> None:
        self.pager.reset()
        self._fetch()

    def _fetch(self) -> None:
        try:
            result = services.run_report(
                self.ctx.db, cursor=self.pager.current(), limit=200, **self._filters())
        except Exception as exc:
            error(self, str(exc))
            return
        self._result = result
        self.table.load(result["headers"], result["rows"],
                        money_cols=set(result.get("money_cols") or []))
        self.pager.set_result(result.get("has_next"), result.get("next_cursor"))
        foot = result.get("footer") or {}
        self.footer.setText(
            " · ".join(f"{k}: {money(v) if k.lower().find('total') >= 0 or k.lower().find('amount') >= 0 or k.lower().find('collected') >= 0 or k.lower().find('billed') >= 0 or k.lower().find('due') >= 0 else v}"
                       for k, v in foot.items())
            + f" · {self.pager.label.text()} · showing {result.get('row_count', len(result['rows']))}"
            + (" · " + self._subtitle() if self._subtitle() else "")
        )

    def _all_result(self) -> dict:
        """Every row for export/print (pagination is only for the screen)."""
        return services.run_report(self.ctx.db, **self._filters())

    def export_current(self) -> None:
        if not self._result:
            warn(self, "Run a report first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", f"{self.kind.currentData()}_{date.today():%Y%m%d}.xlsx",
            "Excel files (*.xlsx)")
        if not path:
            return
        try:
            result = self._all_result()
            excelio.export_report(path, result["title"], result["headers"],
                                  result["rows"], result.get("footer"),
                                  result.get("money_cols"))
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, f"Exported:\n{path}")

    def export_all(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Full database export", f"epbs_database_{date.today():%Y%m%d}.xlsx",
            "Excel files (*.xlsx)")
        if not path:
            return
        try:
            excelio.backup_database(self.ctx.db, path, self.ctx.cfg.db.label())
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, f"Full database exported to:\n{path}\n\n"
                   "Sheets: consumers, bills, details, readings, payments, masters, company, audit.")

    def _print(self, as_pdf: bool) -> None:
        if not self._result:
            warn(self, "Run a report first.")
            return
        try:
            result = self._all_result()
        except Exception as exc:
            error(self, str(exc))
            return
        print_report(self.ctx, result["title"], result["headers"],
                     result["rows"], result.get("footer"), self._subtitle(),
                     result.get("money_cols"), self, as_pdf)
