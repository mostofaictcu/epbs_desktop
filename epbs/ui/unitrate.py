from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import services
from .common import (
    ConsumerPicker, Table, confirm_save, date_edit, error, info, money, to_date, warn,
)


class UnitRateTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.consumer: dict | None = None
        self._readings: list[dict] = []
        self._build()
        self.refresh_audit()
        self.ctx.data_changed.connect(self._refresh_consumer)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Unit change / rate change")
        title.setObjectName("h1")
        root.addWidget(title)
        hint = QLabel("Search a consumer by account or meter number, correct the last reading, change the rate, "
                      "and optionally recalculate the linked unpaid bill. Every change is audited.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.picker = ConsumerPicker(self.ctx.db)
        self.picker.consumer_selected.connect(self._load_consumer)
        root.addWidget(self.picker)
        self.consumer_info = QLabel("No consumer selected.")
        self.consumer_info.setWordWrap(True)
        root.addWidget(self.consumer_info)

        columns = QHBoxLayout()
        columns.setSpacing(12)

        # readings ------------------------------------------------------
        reading_group = QGroupBox("Meter reading")
        rg = QVBoxLayout(reading_group)
        self.reading_table = Table()
        self.reading_table.setMinimumHeight(150)
        self.reading_table.itemSelectionChanged.connect(self._reading_selected)
        rg.addWidget(self.reading_table)

        form = QFormLayout()
        self.prev_unit = QSpinBox()
        self.prev_unit.setRange(0, 100_000_000)
        self.prev_unit.setGroupSeparatorShown(True)
        self.pres_unit = QSpinBox()
        self.pres_unit.setRange(0, 100_000_000)
        self.pres_unit.setGroupSeparatorShown(True)
        self.prev_date = date_edit()
        self.pres_date = date_edit()
        self.recalc = QCheckBox("Recalculate the linked bill (only while it is unpaid)")
        self.recalc.setChecked(True)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason for the correction (stored in the audit log)")
        form.addRow("Previous unit", self.prev_unit)
        form.addRow("Present unit", self.pres_unit)
        form.addRow("Previous date", self.prev_date)
        form.addRow("Present date", self.pres_date)
        form.addRow("", self.recalc)
        form.addRow("Reason", self.reason)
        rg.addLayout(form)

        save_reading = QPushButton("Save reading correction")
        save_reading.setObjectName("primary")
        save_reading.clicked.connect(self._save_reading)
        rg.addWidget(save_reading, alignment=Qt.AlignmentFlag.AlignLeft)
        columns.addWidget(reading_group, 3)

        # rate ----------------------------------------------------------
        rate_group = QGroupBox("Rate")
        rl = QVBoxLayout(rate_group)
        self.rate_current = QLabel("-")
        self.rate_current.setObjectName("h2")
        rl.addWidget(QLabel("Current rate"))
        rl.addWidget(self.rate_current)
        self.rate_note = QLabel("")
        self.rate_note.setObjectName("muted")
        self.rate_note.setWordWrap(True)
        rl.addWidget(self.rate_note)
        self.new_rate = QDoubleSpinBox()
        self.new_rate.setRange(0, 100000)
        self.new_rate.setDecimals(2)
        self.new_rate.setSingleStep(0.5)
        rl.addWidget(QLabel("New rate"))
        rl.addWidget(self.new_rate)
        self.scope_consumer = QRadioButton("This consumer only (rate override)")
        self.scope_consumer.setChecked(True)
        self.scope_type = QRadioButton("All consumers of this type")
        rl.addWidget(self.scope_consumer)
        rl.addWidget(self.scope_type)
        self.rate_reason = QLineEdit()
        self.rate_reason.setPlaceholderText("Reason / reference")
        rl.addWidget(self.rate_reason)
        row = QHBoxLayout()
        apply_rate = QPushButton("Apply rate")
        apply_rate.setObjectName("primary")
        apply_rate.clicked.connect(self._apply_rate)
        clear_rate = QPushButton("Clear override")
        clear_rate.clicked.connect(self._clear_rate)
        row.addWidget(apply_rate)
        row.addWidget(clear_rate)
        row.addStretch(1)
        rl.addLayout(row)
        self.rate_summary = QLabel("")
        self.rate_summary.setWordWrap(True)
        self.rate_summary.setObjectName("muted")
        rl.addWidget(self.rate_summary)
        rl.addStretch(1)
        columns.addWidget(rate_group, 2)

        root.addLayout(columns, 1)

        audit_group = QGroupBox("Recent unit / rate audit log")
        ag = QVBoxLayout(audit_group)
        self.audit = Table()
        self.audit.setMinimumHeight(120)
        ag.addWidget(self.audit)
        root.addWidget(audit_group, 1)

    # ------------------------------------------------------------------
    def _refresh_consumer(self) -> None:
        if self.consumer:
            self._load_consumer(int(self.consumer["con_id"]))
        self.refresh_audit()

    def _load_consumer(self, con_id: int) -> None:
        try:
            consumer = services.get_consumer(self.ctx.db, con_id)
            readings = services.readings(self.ctx.db, con_id, 15)
            audit = services.audit_log(self.ctx.db, 40)
        except Exception as exc:
            error(self, str(exc))
            return
        if not consumer:
            return
        self.consumer = consumer
        self._readings = readings
        self.consumer_info.setText(
            f"<b>{consumer.get('con_name')}</b> · account {consumer.get('con_id')} · "
            f"meter {consumer.get('meter_no') or '-'} · type {consumer.get('type_name') or '-'} · "
            f"status {consumer.get('con_status')} · outstanding {money(consumer.get('due'))}"
        )
        self.rate_current.setText(money(consumer.get("rate")))
        override = consumer.get("rate_override")
        self.rate_note.setText(
            "Custom rate is active for this consumer."
            if override is not None else
            f"Using the type rate of {consumer.get('type_name') or 'no type'}."
        )
        self.new_rate.setValue(float(override if override is not None else consumer.get("rate") or 0))
        self.scope_type.setText(f"All consumers of type {consumer.get('type_name') or '-'}")
        if consumer.get("slab_count"):
            self.rate_summary.setText(
                f"'{consumer.get('type_name') or '-'}' uses a slab tariff. Changing the flat "
                "type rate only affects bills that bypass slabs (or consumers with a custom "
                "rate). Edit the slabs in Master data → Types → Slabs. A per-consumer rate "
                "bypasses the slab tariff for that account."
            )
        else:
            self.rate_summary.setText(
                f"Changing the type rate affects every '{consumer.get('type_name') or '-'}' consumer. "
                "Use the per-consumer override to change only this account."
            )
        self.reading_table.load(
            ["Bill", "Prev date", "Prev unit", "Present date", "Present unit", "Units", "Rate"],
            [[r.get("bill_no"), r.get("previous_date"), r.get("previous_unit"),
              r.get("present_date"), r.get("present_unit"), r.get("units"),
              r.get("rate_applied")] for r in readings],
            money_cols={6}, right_cols={2, 4, 5},
        )
        self._readings = readings
        if readings:
            self.reading_table.selectRow(0)
            self._apply_reading(readings[0])
        self.refresh_audit()

    def refresh_audit(self) -> None:
        try:
            rows = services.audit_log(self.ctx.db, 60)
        except Exception:
            rows = []
        self.audit.load(
            ["When", "Table", "Ref", "Field", "Old", "New", "User", "Note"],
            [[str(r.get("changed_at"))[:19], r.get("table_name"), r.get("ref_id"),
              r.get("field_name"), r.get("old_value"), r.get("new_value"),
              r.get("user_id"), r.get("note")] for r in rows],
        )

    def _reading_selected(self) -> None:
        row = self.reading_table.currentRow()
        if 0 <= row < len(self._readings):
            self._apply_reading(self._readings[row])

    def _apply_reading(self, reading: dict) -> None:
        self.prev_unit.setValue(int(reading.get("previous_unit") or 0))
        self.pres_unit.setValue(int(reading.get("present_unit") or 0))
        self.prev_date.setDate(_qdate(reading.get("previous_date")))
        self.pres_date.setDate(_qdate(reading.get("present_date")))

    def _save_reading(self) -> None:
        row = self.reading_table.currentRow()
        if not (0 <= row < len(self._readings)):
            warn(self, "Select a reading first.")
            return
        reading = self._readings[row]
        if self.pres_unit.value() < self.prev_unit.value():
            warn(self, "Present unit cannot be less than previous unit.")
            return
        detail = (f"Save this corrected reading for consumer "
                  f"{(self.consumer or {}).get('con_id', '-')}?\n\n"
                  f"Previous: {self.prev_unit.value():,} on {to_date(self.prev_date)}\n"
                  f"Present: {self.pres_unit.value():,} on {to_date(self.pres_date)}")
        if self.recalc.isChecked():
            detail += "\n\nThe linked bill will be recalculated."
        if not confirm_save(self, detail):
            return
        try:
            result = services.update_reading(
                self.ctx.db, int(reading["un_id"]), self.prev_unit.value(), self.pres_unit.value(),
                to_date(self.prev_date), to_date(self.pres_date), self.ctx.user_id,
                self.reason.text().strip(), self.recalc.isChecked(),
            )
        except Exception as exc:
            error(self, str(exc))
            return
        message = "Reading corrected."
        if result:
            if result.get("slabs"):
                message += (f"\nLinked bill recalculated slab by slab: "
                            f"{result['units']} units = {money(result['bill_amount'])} "
                            f"(average {money(result['rate'])}/unit); "
                            f"total now {money(result['total'])}.")
            else:
                message += (f"\nLinked bill recalculated: {result['units']} units x "
                            f"{money(result['rate'])} = {money(result['bill_amount'])}; "
                            f"total now {money(result['total'])}.")
        info(self, message)
        self.reason.clear()
        self.ctx.notify_change()
        if self.consumer:
            self._load_consumer(int(self.consumer["con_id"]))

    def _apply_rate(self) -> None:
        if not self.consumer:
            warn(self, "Select a consumer first.")
            return
        scope = "consumer" if self.scope_consumer.isChecked() else "type"
        where = ("this consumer" if scope == "consumer"
                 else f"every consumer of type {self.consumer.get('type_name') or '-'}")
        if not confirm_save(self, f"Change the rate to {money(self.new_rate.value())} "
                                  f"for {where}?\n\nNew bills will use the new rate."):
            return
        try:
            services.set_rate(self.ctx.db, int(self.consumer["con_id"]), self.new_rate.value(),
                              scope, self.ctx.user_id, self.rate_reason.text().strip())
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, "Rate updated. New bills will use the new rate.")
        self.rate_reason.clear()
        self.ctx.notify_change()
        self._load_consumer(int(self.consumer["con_id"]))

    def _clear_rate(self) -> None:
        if not self.consumer:
            warn(self, "Select a consumer first.")
            return
        if not confirm_save(self, f"Clear the rate override for consumer "
                                  f"{self.consumer.get('con_id')}?\n\n"
                                  "The consumer type rate will apply again."):
            return
        try:
            services.clear_rate_override(self.ctx.db, int(self.consumer["con_id"]), self.ctx.user_id)
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, "Per-consumer rate override cleared; the type rate applies again.")
        self.ctx.notify_change()
        self._load_consumer(int(self.consumer["con_id"]))


def _qdate(value):
    from .common import qdate
    return qdate(value)
