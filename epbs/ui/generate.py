from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import services
from .common import (
    Card, ConsumerPicker, Table, confirm_save, date_edit, error, money, to_date, warn,
)
from .documents import print_bill


class BillResultDialog(QDialog):
    def __init__(self, ctx, bill_no: int, total, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bill_no = bill_no
        self.setWindowTitle(f"Bill {bill_no} generated")
        root = QVBoxLayout(self)
        label = QLabel(f"Bill <b>{bill_no}</b> generated.<br>Total payable: <b>{money(total)}</b>")
        label.setObjectName("h2")
        root.addWidget(label)
        note = QLabel("Printed in ink-saver mode (black on white, small font, no background fills).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        row = QHBoxLayout()
        print_btn = QPushButton("Print now")
        print_btn.setObjectName("primary")
        print_btn.clicked.connect(self._print)
        pdf_btn = QPushButton("Save PDF")
        pdf_btn.clicked.connect(self._pdf)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(print_btn)
        row.addWidget(pdf_btn)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _print(self) -> None:
        print_bill(self.ctx, self.bill_no, self)

    def _pdf(self) -> None:
        print_bill(self.ctx, self.bill_no, self, as_pdf=True)


class BillGenerateTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.consumer: dict | None = None
        self.previous_unit = 0
        self._build()
        self.ctx.data_changed.connect(self.reload_consumer)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Generate bill")
        title.setObjectName("h1")
        root.addWidget(title)
        hint = QLabel("Search by account number or meter number. Units and total price are shown before saving.")
        hint.setObjectName("muted")
        root.addWidget(hint)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        left = QVBoxLayout()
        right = QVBoxLayout()

        consumer_group = QGroupBox("Consumer")
        cg = QVBoxLayout(consumer_group)
        self.picker = ConsumerPicker(self.ctx.db)
        self.picker.consumer_selected.connect(self._load_consumer)
        self.consumer_info = QLabel("No consumer selected.")
        self.consumer_info.setWordWrap(True)
        cg.addWidget(self.picker)
        cg.addWidget(self.consumer_info)
        left.addWidget(consumer_group)

        form_group = QGroupBox("Reading, month and dates")
        form = QFormLayout(form_group)
        self.present_unit = QSpinBox()
        self.present_unit.setRange(0, 100_000_000)
        self.present_unit.setGroupSeparatorShown(True)
        self.present_unit.valueChanged.connect(self._update_summary)
        self.present_date = date_edit()
        self.present_date.dateChanged.connect(self._update_summary)
        self.month = QComboBox()
        for value, label in services.month_choices(6):
            self.month.addItem(label, value)
        self.issue_date = date_edit()
        self.last_date = date_edit()
        self.meter_rent = QDoubleSpinBox()
        self.meter_rent.setRange(0, 100_000)
        self.meter_rent.setDecimals(2)
        self.meter_rent.setValue(self.ctx.cfg.meter_rent_default)
        self.meter_rent.valueChanged.connect(self._update_summary)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 100_000)
        self.rate.setDecimals(2)
        self.rate.setGroupSeparatorShown(True)
        self.rate.setSuffix(" / unit")
        self.rate.setToolTip("Rate applied to this bill. Change it here to bill this customer "
                             "at a different rate.")
        self.rate.valueChanged.connect(self._update_summary)
        self.save_rate = QCheckBox("Save this rate for this customer")
        self.save_rate.setChecked(True)
        self.save_rate.setToolTip("Store the rate above as this consumer's own rate. "
                                  "Clear it to use the rate only for this bill.")
        self.kind = QComboBox()
        self.kind.addItem("Generate (normal bill)", "Generate")
        self.kind.addItem("Punishment bill", "Punishment")

        form.addRow("Present unit", self.present_unit)
        form.addRow("Present date", self.present_date)
        form.addRow("Bill month", self.month)
        form.addRow("Issue date", self.issue_date)
        form.addRow("Last date", self.last_date)
        form.addRow("Rate", self.rate)
        form.addRow("", self.save_rate)
        form.addRow("Meter rent", self.meter_rent)
        form.addRow("Bill type", self.kind)
        left.addWidget(form_group)

        buttons = QHBoxLayout()
        self.generate_btn = QPushButton("Generate bill")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.clicked.connect(lambda: self._generate(False, False))
        self.print_btn = QPushButton("Generate + print")
        self.print_btn.clicked.connect(lambda: self._generate(True, False))
        self.pdf_btn = QPushButton("Generate + PDF")
        self.pdf_btn.clicked.connect(lambda: self._generate(False, True))
        buttons.addWidget(self.generate_btn)
        buttons.addWidget(self.print_btn)
        buttons.addWidget(self.pdf_btn)
        buttons.addStretch(1)
        left.addLayout(buttons)

        recent_group = QGroupBox("Recent bills of this consumer")
        rg = QVBoxLayout(recent_group)
        self.recent = Table()
        self.recent.setMinimumHeight(140)
        rg.addWidget(self.recent)
        left.addWidget(recent_group)
        left.addStretch(1)

        summary_group = QGroupBox("Summary")
        sl = QVBoxLayout(summary_group)
        self.units_label = QLabel("0")
        self.units_label.setObjectName("units")
        self.units_caption = QLabel("Units used")
        self.units_caption.setObjectName("muted")
        sl.addWidget(self.units_caption)
        sl.addWidget(self.units_label)
        grid = QFormLayout()
        self.prev_label = QLabel("-")
        self.rate_label = QLabel("0.00")
        self.amount_label = QLabel("0.00")
        self.due_label = QLabel("0.00")
        self.rent_label = QLabel("0.00")
        self.total_label = QLabel("0.00")
        self.total_label.setObjectName("total")
        grid.addRow("Previous unit", self.prev_label)
        grid.addRow("Rate", self.rate_label)
        grid.addRow("This bill", self.amount_label)
        grid.addRow("Previous due", self.due_label)
        grid.addRow("Meter rent", self.rent_label)
        grid.addRow("Total payable", self.total_label)
        sl.addLayout(grid)
        self.warning = QLabel("")
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        sl.addWidget(self.warning)
        sl.addStretch(1)
        right.addWidget(summary_group)
        right.addStretch(1)

        columns.addLayout(left, 3)
        columns.addLayout(right, 2)
        root.addLayout(columns, 1)

    # ------------------------------------------------------------------
    def reload_consumer(self) -> None:
        if self.consumer:
            self._load_consumer(int(self.consumer["con_id"]))

    def _load_consumer(self, con_id: int) -> None:
        try:
            consumer = services.get_consumer(self.ctx.db, con_id)
            if not consumer:
                raise ValueError("Consumer not found.")
            prev = services.last_reading(self.ctx.db, con_id)
        except Exception as exc:
            error(self, str(exc))
            return
        self.consumer = consumer
        self.previous_unit = int((prev or {}).get("present_unit") or 0)
        self.consumer_info.setText(
            f"<b>{consumer.get('con_name')}</b> · account {consumer.get('con_id')} · "
            f"meter {consumer.get('meter_no') or '-'} · {consumer.get('type_name') or 'no type'} · "
            f"{consumer.get('area_details') or 'no area'} · {consumer.get('con_status')} · "
            f"contact {consumer.get('con_contact') or '-'}"
        )
        self.present_unit.blockSignals(True)
        self.present_unit.setValue(self.previous_unit)
        self.present_unit.blockSignals(False)
        self.rate.blockSignals(True)
        self.rate.setValue(float(consumer.get("rate") or 0))
        self.rate.blockSignals(False)
        self._update_summary()
        self._load_recent(con_id)

    def _load_recent(self, con_id: int) -> None:
        try:
            bills = services.consumer_bills(self.ctx.db, con_id, 8)
        except Exception:
            bills = []
        self.recent.load(
            ["Bill", "Date", "Units", "Total", "Status"],
            [[b["bill_no"], b.get("issue_date"), b.get("units"), b.get("total_amount"),
              b.get("bill_status")] for b in bills],
            money_cols={3}, right_cols={2},
        )

    def _update_summary(self) -> None:
        if not self.consumer:
            self.units_label.setText("0")
            for label in (self.prev_label, self.rate_label, self.amount_label, self.due_label,
                          self.rent_label, self.total_label):
                label.setText("0.00")
            self.warning.setText("")
            self._set_enabled(False)
            return
        present = self.present_unit.value()
        units = present - self.previous_unit
        rate = float(self.rate.value())
        rent = float(self.meter_rent.value())
        due = float(self.consumer.get("due") or 0)
        amount = round(units * rate, 2)
        total = round(amount + due + rent, 2)
        self.units_label.setText(f"{units:,}")
        self.prev_label.setText(f"{self.previous_unit:,}")
        self.rate_label.setText(money(rate))
        self.amount_label.setText(money(amount))
        self.due_label.setText(money(due))
        self.rent_label.setText(money(rent))
        self.total_label.setText(money(total))
        if units < 0:
            self.warning.setText(f"Present unit is below the previous reading ({self.previous_unit:,}). "
                                 "Correct the reading in Unit / Rate change first.")
            self._set_enabled(False)
        else:
            self.warning.setText("")
            self._set_enabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        for button in (self.generate_btn, self.print_btn, self.pdf_btn):
            button.setEnabled(enabled)

    def _generate(self, do_print: bool, do_pdf: bool) -> None:
        if not self.consumer:
            warn(self, "Select a consumer first.")
            return
        present = self.present_unit.value()
        rate = float(self.rate.value())
        save_rate = self.save_rate.isChecked()
        try:
            preview = services.preview_bill(self.ctx.db, int(self.consumer["con_id"]), present,
                                            self.meter_rent.value(), rate)
            rate_note = ""
            if save_rate and preview.get("rate") != preview.get("consumer", {}).get("rate"):
                rate_note = "\nNew customer rate will be saved."
            if not confirm_save(
                self,
                f"Generate bill for {self.consumer.get('con_id')} - "
                f"{self.consumer.get('con_name') or ''}?\n\n"
                f"Month: {self.month.currentText()}\n"
                f"Previous unit: {self.previous_unit:,} · Present unit: {present:,}\n"
                f"Units: {preview.get('units'):,} × {money(preview.get('rate'))} = "
                f"{money(preview.get('bill_amount'))}\n"
                f"Due: {money(preview.get('due'))} · Meter rent: "
                f"{money(preview.get('meter_rent'))}\n"
                f"Total: {money(preview.get('total'))}{rate_note}\n\n"
                "The bill will be saved."
            ):
                return
            bill_no = services.generate_bill(
                self.ctx.db,
                con_id=int(self.consumer["con_id"]),
                present_unit=present,
                present_date=to_date(self.present_date),
                bill_month=self.month.currentData(),
                issue_date=to_date(self.issue_date),
                last_date=to_date(self.last_date),
                meter_rent=self.meter_rent.value(),
                rate=rate,
                save_rate=save_rate,
                user_id=self.ctx.user_id,
                kind=self.kind.currentData(),
            )
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self._load_consumer(int(self.consumer["con_id"]))
        if do_print:
            print_bill(self.ctx, bill_no, self)
        if do_pdf:
            print_bill(self.ctx, bill_no, self, as_pdf=True)
        if not do_print and not do_pdf:
            BillResultDialog(self.ctx, bill_no, preview.get("total"), self).exec()
        else:
            from .common import info
            info(self, f"Bill {bill_no} generated and saved.")
