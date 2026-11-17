from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
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
        self.has_slabs = False
        self.has_override = False
        self._build()
        self.ctx.data_changed.connect(self.reload_consumer)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        scroll.setWidget(host)
        outer.addWidget(scroll)
        root = QVBoxLayout(host)
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
        self.meter_rent.setValue(0)
        self.meter_rent.setToolTip("Meter rent is added once to this bill. It defaults to the "
                                   "consumer type's meter rent, or 0 when the type has none.")
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
        self.flat_rate = QCheckBox("Bill at a flat rate (ignore the slab tariff)")
        self.flat_rate.setToolTip("Tick to bill this bill at one rate per unit instead of "
                                  "the consumer type's slab tariff.")
        self.flat_rate.toggled.connect(self._rate_mode_changed)
        self.tariff_note = QLabel("")
        self.tariff_note.setObjectName("muted")
        self.tariff_note.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem("Generate (normal bill)", "Generate")
        self.kind.addItem("Punishment bill", "Punishment")

        form.addRow("Present unit", self.present_unit)
        form.addRow("Present date", self.present_date)
        form.addRow("Bill month", self.month)
        form.addRow("Issue date", self.issue_date)
        form.addRow("Last date", self.last_date)
        self.rate_caption = QLabel("Rate")
        form.addRow(self.rate_caption, self.rate)
        form.addRow("", self.flat_rate)
        form.addRow("", self.save_rate)
        form.addRow("", self.tariff_note)
        form.addRow("Meter rent", self.meter_rent)
        form.addRow("Bill type", self.kind)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for field in (self.present_unit, self.present_date, self.month, self.issue_date,
                      self.last_date, self.rate, self.meter_rent, self.kind):
            field.setMinimumWidth(220)
            field.setMinimumHeight(28)
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
        self.slab_caption = QLabel("Slab breakdown")
        self.slab_caption.setObjectName("muted")
        self.slab_table = Table()
        self.slab_table.setMinimumHeight(110)
        self.slab_table.setVisible(False)
        self.slab_caption.setVisible(False)
        sl.addWidget(self.slab_caption)
        sl.addWidget(self.slab_table)
        grid = QFormLayout()
        self.prev_label = QLabel("-")
        self.rate_label = QLabel("0.00")
        self.amount_label = QLabel("0.00")
        self.minimum_label = QLabel("—")
        self.due_label = QLabel("0.00")
        self.rent_label = QLabel("0.00")
        self.total_label = QLabel("0.00")
        self.total_label.setObjectName("total")
        self.summary_rate_caption = QLabel("Rate")
        grid.addRow("Previous unit", self.prev_label)
        grid.addRow(self.summary_rate_caption, self.rate_label)
        grid.addRow("This bill", self.amount_label)
        grid.addRow("Minimum amount", self.minimum_label)
        grid.addRow("Previous due", self.due_label)
        grid.addRow("Meter rent", self.rent_label)
        grid.addRow("Total payable", self.total_label)
        sl.addLayout(grid)
        self.minimum_note = QLabel("")
        self.minimum_note.setObjectName("muted")
        self.minimum_note.setWordWrap(True)
        self.minimum_note.setVisible(False)
        sl.addWidget(self.minimum_note)
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
        rent_default = consumer.get("type_meter_rent")
        self.meter_rent.blockSignals(True)
        self.meter_rent.setValue(float(rent_default or 0))
        self.meter_rent.blockSignals(False)

        self.has_slabs = bool(consumer.get("slab_count"))
        self.has_override = consumer.get("rate_override") is not None
        self.flat_rate.blockSignals(True)
        self.flat_rate.setChecked(not self.has_slabs or self.has_override)
        self.flat_rate.blockSignals(False)
        self.flat_rate.setVisible(self.has_slabs)
        self.flat_rate.setEnabled(self.has_slabs and not self.has_override)
        self.tariff_note.setText(
            f"Custom flat rate {money(consumer.get('rate'))}: the type slab tariff is bypassed."
            if self.has_override else
            (f"{consumer.get('slab_count')} slab(s) configured for "
             f"{consumer.get('type_name') or 'this type'}. The rate shown is the average "
             "for the units used; the bill is calculated slab by slab."
             if self.has_slabs else
             "Flat-rate billing: units × rate.")
        )
        minimum = float(consumer.get("type_minimum_amount") or 0)
        if minimum:
            self.tariff_note.setText(
                self.tariff_note.text()
                + f" Minimum amount {money(minimum)}: a lower calculated charge is billed at "
                  "this minimum.")
        self._rate_mode_changed()
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

    def _slab_mode(self) -> bool:
        return bool(self.consumer and self.has_slabs and not self.has_override
                    and not self.flat_rate.isChecked())

    def _rate_mode_changed(self) -> None:
        slab_mode = self._slab_mode()
        if not slab_mode and self.consumer:
            # Back to flat billing: start from the consumer's own flat rate
            # rather than the average that was displayed for the slab tariff.
            self.rate.blockSignals(True)
            self.rate.setValue(float(self.consumer.get("rate") or 0))
            self.rate.blockSignals(False)
        self.rate.setEnabled(not slab_mode)
        self.save_rate.setEnabled(not slab_mode)
        caption = "Average rate" if slab_mode else "Rate"
        self.rate_caption.setText(caption)
        self.summary_rate_caption.setText(caption)
        self._update_summary()

    def _update_summary(self) -> None:
        self.slab_table.setVisible(False)
        self.slab_caption.setVisible(False)
        if not self.consumer:
            self.units_label.setText("0")
            for label in (self.prev_label, self.rate_label, self.amount_label, self.due_label,
                          self.rent_label, self.total_label):
                label.setText("0.00")
            self.minimum_label.setText("—")
            self.minimum_note.setVisible(False)
            self.warning.setText("")
            self._set_enabled(False)
            return
        present = self.present_unit.value()
        units = present - self.previous_unit
        if units < 0:
            self.units_label.setText(f"{units:,}")
            self.prev_label.setText(f"{self.previous_unit:,}")
            self.minimum_label.setText("—")
            self.minimum_note.setVisible(False)
            self.warning.setText(f"Present unit is below the previous reading ({self.previous_unit:,}). "
                                 "Correct the reading in Unit / Rate change first.")
            self._set_enabled(False)
            return
        slab_mode = self._slab_mode()
        try:
            preview = services.preview_bill(
                self.ctx.db, int(self.consumer["con_id"]), present,
                self.meter_rent.value(),
                None if slab_mode else float(self.rate.value()),
            )
        except Exception as exc:
            self.minimum_label.setText("—")
            self.minimum_note.setVisible(False)
            self.warning.setText(str(exc))
            self._set_enabled(False)
            return
        if slab_mode:
            self.rate.blockSignals(True)
            self.rate.setValue(float(preview.get("rate") or 0))
            self.rate.blockSignals(False)
        self.units_label.setText(f"{int(preview.get('units') or 0):,}")
        self.prev_label.setText(f"{self.previous_unit:,}")
        self.rate_label.setText(money(preview.get("rate")))
        self.amount_label.setText(money(preview.get("bill_amount")))
        minimum = preview.get("minimum") or 0
        self.minimum_label.setText(money(minimum) if minimum else "—")
        if preview.get("minimum_charge"):
            self.minimum_note.setText(
                f"Calculated charge {money(preview.get('calculated_amount'))} is below the type "
                f"minimum, so {money(preview.get('bill_amount'))} will be billed.")
            self.minimum_note.setVisible(True)
        else:
            self.minimum_note.setVisible(False)
        self.due_label.setText(money(preview.get("due")))
        self.rent_label.setText(money(preview.get("meter_rent")))
        self.total_label.setText(money(preview.get("total")))
        slabs = preview.get("slabs") or []
        if slabs:
            self.slab_table.load(
                ["Slab", "Range", "Units", "Rate", "Amount"],
                [[s.get("slab_no"),
                  f"{s.get('from_unit')}-{s.get('to_unit') or 'No limit'}",
                  s.get("units"), s.get("rate"), s.get("amount")] for s in slabs],
                money_cols={3, 4}, right_cols={2},
            )
        self.slab_table.setVisible(bool(slabs))
        self.slab_caption.setVisible(bool(slabs))
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
        slab_mode = self._slab_mode()
        rate = None if slab_mode else float(self.rate.value())
        save_rate = self.save_rate.isChecked() and not slab_mode
        try:
            preview = services.preview_bill(self.ctx.db, int(self.consumer["con_id"]), present,
                                            self.meter_rent.value(), rate)
            rate_note = ""
            if save_rate and preview.get("rate") != preview.get("consumer", {}).get("rate"):
                rate_note = "\nNew customer rate will be saved."
            slabs = preview.get("slabs") or []
            if preview.get("minimum_charge"):
                charge_line = (f"Units: {preview.get('units'):,} · calculated "
                               f"{money(preview.get('calculated_amount'))} · minimum charge "
                               f"{money(preview.get('bill_amount'))} applied")
            elif slabs:
                charge_line = (f"Units: {preview.get('units'):,} · slab amount: "
                               f"{money(preview.get('bill_amount'))} "
                               f"(average {money(preview.get('rate'))}/unit)\n")
                charge_line += "\n".join(
                    f"  {s.get('units'):,} units @ {money(s.get('rate'))} = "
                    f"{money(s.get('amount'))}" for s in slabs)
            else:
                charge_line = (f"Units: {preview.get('units'):,} × "
                               f"{money(preview.get('rate'))} = "
                               f"{money(preview.get('bill_amount'))}")
            if not confirm_save(
                self,
                f"Generate bill for {self.consumer.get('con_id')} - "
                f"{self.consumer.get('con_name') or ''}?\n\n"
                f"Month: {self.month.currentText()}\n"
                f"Previous unit: {self.previous_unit:,} · Present unit: {present:,}\n"
                f"{charge_line}\n"
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
