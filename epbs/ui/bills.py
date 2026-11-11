from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import services
from .common import (
    Pager, Table, confirm_delete, confirm_save, date_edit, error, info, money, to_date, warn,
)
from .documents import print_bill, print_bills


class PaymentDialog(QDialog):
    def __init__(self, ctx, bill: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bill = bill
        self.setWindowTitle(f"Collect payment - bill {bill['bill_no']}")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        info_label = QLabel(
            f"Bill <b>{bill['bill_no']}</b> · {bill.get('con_name') or ''}<br>"
            f"Total payable: <b>{money(bill.get('total_amount'))}</b>"
        )
        root.addWidget(info_label)
        form = QFormLayout()
        self.paid_date = date_edit(date.today())
        form.addRow("Paid date", self.paid_date)
        root.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Record payment")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _save(self) -> None:
        paid_date = to_date(self.paid_date)
        if not confirm_save(
            self,
            f"Record a payment for bill {self.bill['bill_no']} - "
            f"{self.bill.get('con_name') or ''}?\n\n"
            f"Amount: {money(self.bill.get('total_amount'))}\n"
            f"Paid date: {paid_date}"
        ):
            return
        try:
            services.collect_payment(self.ctx.db, int(self.bill["bill_no"]),
                                     paid_date, self.ctx.user_id)
        except Exception as exc:
            error(self, str(exc))
            return
        self.accept()


class BillDetailDialog(QDialog):
    def __init__(self, ctx, bill_no: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bill_no = bill_no
        self.setWindowTitle(f"Bill {bill_no}")
        self.resize(760, 560)
        root = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setObjectName("h1")
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        root.addWidget(self.head)
        root.addWidget(self.sub)

        self.tabs = QTabWidget()
        self.details = Table()
        self.readings = Table()
        self.payments = Table()
        self.tabs.addTab(self.details, "Bill lines")
        self.tabs.addTab(self.readings, "Meter reading")
        self.tabs.addTab(self.payments, "Payments")
        root.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        print_btn = QPushButton("Print (ink saver)")
        print_btn.setObjectName("primary")
        print_btn.clicked.connect(self._print)
        pdf_btn = QPushButton("Save PDF")
        pdf_btn.clicked.connect(self._pdf)
        pay_btn = QPushButton("Collect payment")
        pay_btn.clicked.connect(self._pay)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(print_btn)
        row.addWidget(pdf_btn)
        row.addWidget(pay_btn)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
        self.reload()

    def reload(self) -> None:
        try:
            data = services.bill_detail(self.ctx.db, self.bill_no)
        except Exception as exc:
            error(self, str(exc))
            return
        bill = data["bill"]
        c = data.get("consumer") or {}
        self.head.setText(f"Bill {bill['bill_no']} — {c.get('con_name') or ''}")
        self.sub.setText(
            f"Account {bill.get('con_id')} · meter {bill.get('meter_no') or '-'} · "
            f"issue {bill.get('issue_date')} · last date {bill.get('last_date')} · "
            f"units {bill.get('units')} · status {bill.get('bill_status')} · "
            f"total {money(bill.get('total_amount'))}"
        )
        self.details.load(
            ["Month", "Details", "Status", "Amount"],
            [[d.get("bill_month"), d.get("bill_details"), d.get("bill_status"), d.get("bill_amount")]
             for d in data["details"]],
            money_cols={3},
        )
        self.readings.load(
            ["Prev date", "Prev unit", "Present date", "Present unit", "Units", "Rate"],
            [[r.get("previous_date"), r.get("previous_unit"), r.get("present_date"),
              r.get("present_unit"), r.get("units"), r.get("rate_applied")] for r in data["readings"]],
            money_cols={5}, right_cols={1, 3, 4},
        )
        self.payments.load(
            ["Payment", "Paid date", "Amount", "User"],
            [[p.get("payment_id"), p.get("paid_date"), p.get("bill_amount"), p.get("user_id")]
             for p in data["payments"]],
            money_cols={2},
        )

    def _print(self) -> None:
        print_bill(self.ctx, self.bill_no, self)
        self.reload()

    def _pdf(self) -> None:
        print_bill(self.ctx, self.bill_no, self, as_pdf=True)

    def _pay(self) -> None:
        bill = services.get_bill(self.ctx.db, self.bill_no)
        dialog = PaymentDialog(self.ctx, bill, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ctx.notify_change()
            self.reload()
            info(self, "Payment recorded.")


class BillsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._rows: list[dict] = []
        self._build()
        self.ctx.data_changed.connect(self.refresh)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Bills and payments")
        title.setObjectName("h1")
        header.addWidget(title)
        header.addStretch(1)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        header.addWidget(self.summary)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Bill no, account no, meter no or consumer name...")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search)
        self.status = QComboBox()
        self.status.addItem("All status", "")
        self.status.addItem("Unpaid", "Unpaid")
        self.status.addItem("Paid", "Paid")
        self.month = QComboBox()
        for value, label in services.month_choices(6, include_blank=True):
            self.month.addItem(label, value)
        self.use_dates = QCheckBox("Date range")
        self.date_from = date_edit(date(date.today().year, 1, 1))
        self.date_to = date_edit(date.today())
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.use_dates.toggled.connect(self.date_from.setEnabled)
        self.use_dates.toggled.connect(self.date_to.setEnabled)
        self.use_dates.toggled.connect(self._search)
        find = QPushButton("Search")
        find.clicked.connect(self._search)
        self.status.currentIndexChanged.connect(self._search)
        self.month.currentIndexChanged.connect(self._search)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status)
        filters.addWidget(self.month)
        filters.addWidget(self.use_dates)
        filters.addWidget(self.date_from)
        filters.addWidget(self.date_to)
        filters.addWidget(find)
        root.addLayout(filters)

        self.table = Table()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _i: self._open())
        root.addWidget(self.table, 1)

        self.pager = Pager()
        self.pager.page_changed.connect(self.refresh)
        root.addWidget(self.pager)

        actions = QHBoxLayout()
        open_btn = QPushButton("Open / print")
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self._open)
        pdf_btn = QPushButton("Save PDF")
        pdf_btn.clicked.connect(self._pdf)
        pay_btn = QPushButton("Collect payment")
        pay_btn.clicked.connect(self._pay)
        batch_btn = QPushButton("Print selected bills")
        batch_btn.clicked.connect(self._print_selected)
        delete_btn = QPushButton("Delete bill")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete)
        actions.addWidget(open_btn)
        actions.addWidget(pdf_btn)
        actions.addWidget(pay_btn)
        actions.addWidget(batch_btn)
        actions.addStretch(1)
        actions.addWidget(delete_btn)
        root.addLayout(actions)

    # ------------------------------------------------------------------
    def _search(self) -> None:
        self.pager.reset()
        self.refresh()

    def _filters(self) -> dict:
        use_dates = self.use_dates.isChecked()
        return {
            "text": self.search.text(),
            "status": self.status.currentData() or "",
            "month": self.month.currentData() or "",
            "date_from": to_date(self.date_from) if use_dates else None,
            "date_to": to_date(self.date_to) if use_dates else None,
        }

    def refresh(self) -> None:
        filters = self._filters()
        try:
            rows, has_next, cursor = services.search_bills_page(
                self.ctx.db, before_no=self.pager.current(), limit=100, **filters)
            total = services.count_bills(self.ctx.db, **filters)
        except Exception as exc:
            error(self, str(exc))
            return
        self._rows = rows
        self.table.load(
            ["Bill No", "Issue date", "Account", "Consumer", "Meter", "Units", "Bill", "Due",
             "Rent", "Total", "Status", "Printed"],
            [[b["bill_no"], b.get("issue_date"), b.get("con_id"), b.get("con_name"),
              b.get("meter_no"), b.get("units"), b.get("bill_amount"), b.get("due"),
              b.get("meter_rent"), b.get("total_amount"), b.get("bill_status"),
              b.get("bill_print")] for b in self._rows],
            money_cols={6, 7, 8, 9}, right_cols={5},
        )
        self.pager.set_result(has_next, cursor)
        total_amount = sum(float(b.get("total_amount") or 0) for b in self._rows)
        unpaid = sum(float(b.get("total_amount") or 0) for b in self._rows
                     if b.get("bill_status") == "Unpaid")
        self.summary.setText(
            f"{self.pager.label.text()} · {total} bill(s) matching · this page: "
            f"total {money(total_amount)} · unpaid {money(unpaid)}")

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _selected_rows(self) -> list[dict]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

    def _open(self) -> None:
        bill = self._selected()
        if not bill:
            warn(self, "Select a bill first.")
            return
        BillDetailDialog(self.ctx, int(bill["bill_no"]), self).exec()

    def _pdf(self) -> None:
        bill = self._selected()
        if not bill:
            warn(self, "Select a bill first.")
            return
        print_bill(self.ctx, int(bill["bill_no"]), self, as_pdf=True)

    def _print_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            warn(self, "Select one or more bills first.")
            return
        print_bills(self.ctx, [int(b["bill_no"]) for b in rows], self)
        self.refresh()

    def _pay(self) -> None:
        bill = self._selected()
        if not bill:
            warn(self, "Select a bill first.")
            return
        if bill.get("bill_status") == "Paid":
            info(self, "This bill is already paid.")
            return
        dialog = PaymentDialog(self.ctx, bill, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ctx.notify_change()
            info(self, "Payment recorded.")
            self.refresh()

    def _delete(self) -> None:
        bill = self._selected()
        if not bill:
            warn(self, "Select a bill first.")
            return
        if not confirm_delete(self, f"Delete bill {bill['bill_no']} - "
                                    f"{bill.get('con_name') or ''} and its reading?\n\n"
                                    "Bills with a payment cannot be deleted. "
                                    "This cannot be undone."):
            return
        try:
            services.delete_bill(self.ctx.db, int(bill["bill_no"]))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()
