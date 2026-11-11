from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import services
from .bills import BillDetailDialog
from .common import ConsumerPicker, Table, error, money
from .consumers import ConsumerDetailDialog


class DashboardTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._recent_bills: list[dict] = []
        self._build()
        self.ctx.data_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        title = QLabel("Dashboard")
        title.setObjectName("h1")
        root.addWidget(title)

        cards = QGridLayout()
        cards.setSpacing(8)
        self.kpi = {}
        specs = [
            ("consumers", "Consumers", "blue"),
            ("active_consumers", "Active consumers", "green"),
            ("unpaid", "Unpaid bills", "amber"),
            ("unpaid_total", "Outstanding amount", "rose"),
            ("collected", "Total collected", "teal"),
            ("billed_this_month", "Billed this month", "indigo"),
        ]
        for index, (key, label, tone) in enumerate(specs):
            card = _Kpi(label, tone)
            cards.addWidget(card, index // 3, index % 3)
            self.kpi[key] = card
        root.addLayout(cards)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Quick search:"))
        self.picker = ConsumerPicker(self.ctx.db)
        self.picker.consumer_selected.connect(self._open_consumer)
        quick.addWidget(self.picker, 1)
        root.addLayout(quick)

        columns = QHBoxLayout()
        recent_group = QVBoxLayout()
        label = QLabel("Recent bills")
        label.setObjectName("h2")
        recent_group.addWidget(label)
        self.bills = Table()
        self.bills.doubleClicked.connect(lambda _i: self._open_bill())
        recent_group.addWidget(self.bills)
        columns.addLayout(recent_group, 3)

        payments_group = QVBoxLayout()
        label2 = QLabel("Recent payments")
        label2.setObjectName("h2")
        payments_group.addWidget(label2)
        self.payments = Table()
        payments_group.addWidget(self.payments)
        columns.addLayout(payments_group, 2)
        root.addLayout(columns, 1)

        dues_group = QVBoxLayout()
        label3 = QLabel("Outstanding by consumer type")
        label3.setObjectName("h2")
        dues_group.addWidget(label3)
        self.dues = Table()
        self.dues.setMaximumHeight(150)
        dues_group.addWidget(self.dues)
        root.addLayout(dues_group)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Open selected bill")
        open_btn.clicked.connect(self._open_bill)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(open_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

    def refresh(self) -> None:
        try:
            stats = services.dashboard(self.ctx.db)
        except Exception as exc:
            error(self, str(exc))
            return
        for key in ("consumers", "active_consumers", "unpaid"):
            self.kpi[key].set(f"{int(stats.get(key) or 0):,}")
        for key in ("unpaid_total", "collected", "billed_this_month"):
            self.kpi[key].set(money(stats.get(key)))
        self._recent_bills = stats.get("recent_bills") or []
        self.bills.load(
            ["Bill", "Date", "Account", "Consumer", "Units", "Total", "Status"],
            [[b["bill_no"], b.get("issue_date"), b.get("con_id"), b.get("con_name"),
              b.get("units"), b.get("total_amount"), b.get("bill_status")] for b in self._recent_bills],
            money_cols={5}, right_cols={4},
        )
        self.payments.load(
            ["Payment", "Date", "Bill", "Consumer", "Amount"],
            [[p.get("payment_id"), p.get("paid_date"), p.get("bill_no"), p.get("con_name"),
              p.get("bill_amount")] for p in (stats.get("recent_payments") or [])],
            money_cols={4},
        )
        self.dues.load(
            ["Type", "Consumers", "Outstanding"],
            [[d.get("type_name") or "(no type)", d.get("consumers"), d.get("total")]
             for d in (stats.get("dues_by_type") or [])],
            money_cols={2},
        )

    def _open_consumer(self, con_id: int) -> None:
        ConsumerDetailDialog(self.ctx, con_id, self).exec()

    def _open_bill(self) -> None:
        row = self.bills.currentRow()
        if 0 <= row < len(self._recent_bills):
            BillDetailDialog(self.ctx, int(self._recent_bills[row]["bill_no"]), self).exec()


class _Kpi(QFrame):
    def __init__(self, label: str, tone: str = "blue", parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        self.setProperty("tone", tone)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
