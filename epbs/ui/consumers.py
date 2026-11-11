from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import services
from ..excelio import import_consumers
from .common import (
    PagedTable, Pager, Table, combo, confirm_delete, confirm_save, error, info, money,
    set_combo_id, warn,
)
from .documents import print_statement


class ConsumerDialog(QDialog):
    def __init__(self, ctx, con_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.con_id = con_id
        self.setWindowTitle("Consumer" if con_id else "New consumer")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(6)

        self.account = QSpinBox()
        self.account.setRange(1, 2_000_000_000)
        self.name = QLineEdit()
        self.address = QLineEdit()
        self.meter = QLineEdit()
        self.contact = QLineEdit()
        self.status = QComboBox()
        self.status.addItems(["Active", "Inactive"])
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.group.setToolTip("Pick an existing group or type a new one; it is added to the list.")

        self.masters = services.masters(ctx.db)
        self.type_box = combo(self.masters["types"], "type_id", "type_name", "(none)")
        self.area_box = combo(self.masters["areas"], "area_id", "area_details", "(none)")
        self.dept_box = combo(self.masters["departments"], "dep_id", "dep_details", "(none)")
        self.des_box = combo(self.masters["designations"], "des_id", "des_details", "(none)")
        self.group.addItems([g["group_details"] for g in self.masters["groups"]])
        completer = self.group.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)

        self.custom_rate = QCheckBox("Use a custom rate for this consumer")
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 100000)
        self.rate.setDecimals(2)
        self.rate.setEnabled(False)
        self.rate.setValue(0)
        self.custom_rate.toggled.connect(self.rate.setEnabled)

        form.addRow("Account no", self.account)
        form.addRow("Name", self.name)
        form.addRow("Address", self.address)
        form.addRow("Meter no", self.meter)
        form.addRow("Contact", self.contact)
        form.addRow("Status", self.status)
        form.addRow("Type", self.type_box)
        form.addRow("Area", self.area_box)
        form.addRow("Department", self.dept_box)
        form.addRow("Designation", self.des_box)
        group_row = QHBoxLayout()
        group_row.addWidget(self.group, 1)
        add_group = QPushButton("+")
        add_group.setFixedWidth(30)
        add_group.setToolTip("Add a new consumer group")
        add_group.clicked.connect(self._add_group)
        group_row.addWidget(add_group)
        form.addRow("Group", group_row)
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.custom_rate)
        rate_row.addWidget(self.rate, 1)
        form.addRow("Rate override", rate_row)
        root.addLayout(form)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        if con_id:
            self._load(con_id)
        else:
            self.account.setValue(services.next_consumer_id(ctx.db))

    def _load(self, con_id: int) -> None:
        c = services.get_consumer(self.ctx.db, con_id)
        if not c:
            error(self, "Consumer not found.")
            self.reject()
            return
        self.account.setValue(int(c["con_id"]))
        self.account.setEnabled(False)
        self.name.setText(c.get("con_name") or "")
        self.address.setText(c.get("con_address") or "")
        self.meter.setText(c.get("meter_no") or "")
        self.contact.setText(c.get("con_contact") or "")
        self.status.setCurrentText(c.get("con_status") or "Active")
        self.group.setCurrentText(c.get("con_group") or "")
        set_combo_id(self.type_box, c.get("type_id"))
        set_combo_id(self.area_box, c.get("area_id"))
        set_combo_id(self.dept_box, c.get("dep_id"))
        set_combo_id(self.des_box, c.get("des_id"))
        if c.get("rate_override") is not None:
            self.custom_rate.setChecked(True)
            self.rate.setValue(float(c["rate_override"]))
        else:
            self.rate.setValue(float(c.get("rate") or 0))

    def _add_group(self) -> None:
        name, ok = QInputDialog.getText(self, "New consumer group", "Group name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        if not confirm_save(self, f"Add the group '{name}' to the consumer group list?"):
            return
        try:
            services.add_master_row(self.ctx.db, "group", name)
        except ValueError as exc:
            # already present: still select the existing spelling
            if "already exists" not in str(exc).lower():
                error(self, str(exc))
                return
        groups = [g["group_details"]
                  for g in services.masters(self.ctx.db)["groups"]]
        actual = next((g for g in groups if g.casefold() == name.casefold()), name)
        self.group.clear()
        self.group.addItems(groups)
        index = self.group.findText(actual, Qt.MatchFlag.MatchFixedString)
        if index < 0:
            self.group.addItem(actual)
            index = self.group.count() - 1
        self.group.setCurrentIndex(index)

    def _save(self) -> None:
        if not self.name.text().strip():
            warn(self, "Consumer name is required.")
            return
        data = {
            "con_id": self.account.value(),
            "con_name": self.name.text().strip(),
            "con_address": self.address.text().strip(),
            "meter_no": self.meter.text().strip(),
            "con_contact": self.contact.text().strip(),
            "con_status": self.status.currentText(),
            "con_group": self.group.currentText().strip(),
            "type_id": self.type_box.currentData(),
            "area_id": self.area_box.currentData(),
            "dep_id": self.dept_box.currentData(),
            "des_id": self.des_box.currentData(),
            "rate_override": self.rate.value() if self.custom_rate.isChecked() else None,
            "user_id": self.ctx.user_id,
        }
        action = "Update" if self.con_id else "Create"
        detail = (f"{action} consumer {data['con_id']} - {data['con_name']}?"
                  f"\n\nMeter: {data['meter_no'] or '-'}"
                  f"\nGroup: {data['con_group'] or '-'}"
                  f"\nStatus: {data['con_status']}")
        if not confirm_save(self, detail):
            return
        try:
            services.save_consumer(self.ctx.db, data)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.accept()


class ConsumerDetailDialog(QDialog):
    def __init__(self, ctx, con_id: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.con_id = con_id
        self.setWindowTitle(f"Consumer {con_id}")
        self.resize(920, 640)
        root = QVBoxLayout(self)

        self.header = QLabel()
        self.header.setObjectName("h1")
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        root.addWidget(self.header)
        root.addWidget(self.sub)

        stats = QHBoxLayout()
        self.due = QLabel()
        self.due.setObjectName("total")
        self.last_reading = QLabel()
        self.bills_count = QLabel()
        stats.addWidget(QLabel("Outstanding:"))
        stats.addWidget(self.due)
        stats.addSpacing(20)
        stats.addWidget(self.last_reading)
        stats.addSpacing(20)
        stats.addWidget(self.bills_count)
        stats.addStretch(1)
        root.addLayout(stats)

        self.tabs = QTabWidget()
        self.bills = PagedTable()
        self.readings = PagedTable()
        self.payments = PagedTable()
        self.tabs.addTab(self.bills, "Bills")
        self.tabs.addTab(self.readings, "Meter readings")
        self.tabs.addTab(self.payments, "Payments")
        self.bills.page_changed.connect(self._load_bills)
        self.readings.page_changed.connect(self._load_readings)
        self.payments.page_changed.connect(self._load_payments)
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        edit = QPushButton("Edit consumer")
        edit.clicked.connect(self._edit)
        print_btn = QPushButton("Print statement")
        print_btn.setObjectName("primary")
        print_btn.clicked.connect(lambda: print_statement(self.ctx, self.con_id, self))
        pdf_btn = QPushButton("Statement PDF")
        pdf_btn.clicked.connect(lambda: print_statement(self.ctx, self.con_id, self, as_pdf=True))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(edit)
        buttons.addWidget(print_btn)
        buttons.addWidget(pdf_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.reload()

    def reload(self) -> None:
        c = services.get_consumer(self.ctx.db, self.con_id)
        if not c:
            error(self, "Consumer not found.")
            return
        self.header.setText(f"{c.get('con_id')} — {c.get('con_name') or ''}")
        self.sub.setText(
            f"Meter {c.get('meter_no') or '-'} · {c.get('type_name') or 'no type'} · "
            f"rate {money(c.get('rate'))} · {c.get('area_details') or 'no area'} · "
            f"{c.get('con_status')} · {c.get('con_contact') or ''}"
        )
        due = services.unpaid_due(self.ctx.db, self.con_id)
        self.due.setText(money(due))
        last = services.last_reading(self.ctx.db, self.con_id)
        self.last_reading.setText(
            f"Last reading: {last.get('present_unit') if last else '-'} "
            f"({last.get('present_date') if last else 'none'})"
        )
        stats = services.consumer_stats(self.ctx.db, self.con_id)
        self.bills_count.setText(
            f"Bills: {stats['bills']} · Payments: {stats['payments']} · "
            f"Readings: {stats['readings']}"
        )
        self.bills.reset()
        self.readings.reset()
        self.payments.reset()
        self._load_bills()
        self._load_readings()
        self._load_payments()

    def _load_bills(self) -> None:
        rows, has_next, cursor = services.consumer_bills_page(
            self.ctx.db, self.con_id, self.bills.pager.current(), 50)
        self.bills.load(
            ["Bill No", "Date", "Meter", "Units", "Bill", "Due", "Rent", "Total", "Status"],
            [[b["bill_no"], b.get("issue_date"), b.get("meter_no"), b.get("units"),
              b.get("bill_amount"), b.get("due"), b.get("meter_rent"), b.get("total_amount"),
              b.get("bill_status")] for b in rows],
            money_cols={4, 5, 6, 7}, has_next=has_next, next_cursor=cursor,
        )

    def _load_readings(self) -> None:
        rows, has_next, cursor = services.readings_page(
            self.ctx.db, self.con_id, self.readings.pager.current(), 50)
        self.readings.load(
            ["Prev date", "Prev unit", "Present date", "Present unit", "Units", "Rate", "Bill No"],
            [[r.get("previous_date"), r.get("previous_unit"), r.get("present_date"),
              r.get("present_unit"), r.get("units"), r.get("rate_applied"), r.get("bill_no")]
             for r in rows],
            money_cols={5}, has_next=has_next, next_cursor=cursor,
        )

    def _load_payments(self) -> None:
        rows, has_next, cursor = services.consumer_payments_page(
            self.ctx.db, self.con_id, self.payments.pager.current(), 50)
        self.payments.load(
            ["Payment", "Paid date", "Bill No", "Amount", "User"],
            [[p.get("payment_id"), p.get("paid_date"), p.get("bill_no"), p.get("bill_amount"),
              p.get("user_id")] for p in rows],
            money_cols={3}, has_next=has_next, next_cursor=cursor,
        )

    def _edit(self) -> None:
        dialog = ConsumerDialog(self.ctx, self.con_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()


class ConsumersTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Consumers")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        import_btn = QPushButton("Import from Excel...")
        import_btn.clicked.connect(self._import)
        new_btn = QPushButton("New consumer")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._new)
        top.addWidget(import_btn)
        top.addWidget(new_btn)
        root.addLayout(top)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, meter no, account no or contact...")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search)
        self.status = QComboBox()
        self.status.addItem("All status", "")
        self.status.addItem("Active", "Active")
        self.status.addItem("Inactive", "Inactive")
        self.status.currentIndexChanged.connect(self._search)
        find = QPushButton("Search")
        find.clicked.connect(self._search)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.status)
        search_row.addWidget(find)
        root.addLayout(search_row)

        self.table = Table()
        root.addWidget(self.table, 1)

        self.pager = Pager()
        self.pager.page_changed.connect(self.refresh)
        root.addWidget(self.pager)

        self.count = QLabel("")
        self.count.setObjectName("muted")
        root.addWidget(self.count)

        actions = QHBoxLayout()
        details = QPushButton("Details / statement")
        details.setObjectName("primary")
        details.clicked.connect(self._details)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit)
        toggle = QPushButton("Toggle active")
        toggle.clicked.connect(self._toggle)
        delete = QPushButton("Delete")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        actions.addWidget(details)
        actions.addWidget(edit)
        actions.addWidget(toggle)
        actions.addStretch(1)
        actions.addWidget(delete)
        root.addLayout(actions)

        self.table.doubleClicked.connect(lambda _i: self._details())
        self.table.itemSelectionChanged.connect(self._selection)

    # ------------------------------------------------------------------
    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _selection(self) -> None:
        pass

    def _search(self) -> None:
        self.pager.reset()
        self.refresh()

    def refresh(self) -> None:
        text = self.search.text()
        status = self.status.currentData() or ""
        try:
            rows, has_next, cursor = services.list_consumers_page(
                self.ctx.db, text, status, after_id=self.pager.current(), limit=100)
            total = services.count_consumers(self.ctx.db, text, status)
        except Exception as exc:
            error(self, str(exc))
            return
        self._rows = rows
        self.table.load(
            ["Account", "Name", "Meter", "Type", "Rate", "Area", "Department", "Group", "Status", "Due"],
            [[c["con_id"], c.get("con_name"), c.get("meter_no"), c.get("type_name"), c.get("rate"),
              c.get("area_details"), c.get("dep_details"), c.get("con_group"), c.get("con_status"),
              c.get("due")] for c in self._rows],
            money_cols={4, 9},
        )
        self.pager.set_result(has_next, cursor)
        self.count.setText(
            f"{self.pager.label.text()} · {total} consumer(s) matching · "
            f"showing {len(self._rows)}")

    def _details(self) -> None:
        c = self._selected()
        if not c:
            warn(self, "Select a consumer first.")
            return
        ConsumerDetailDialog(self.ctx, int(c["con_id"]), self).exec()

    def _new(self) -> None:
        dialog = ConsumerDialog(self.ctx, None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._search()

    def _edit(self) -> None:
        c = self._selected()
        if not c:
            warn(self, "Select a consumer first.")
            return
        dialog = ConsumerDialog(self.ctx, int(c["con_id"]), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _toggle(self) -> None:
        c = self._selected()
        if not c:
            warn(self, "Select a consumer first.")
            return
        new_status = "Inactive" if c.get("con_status") == "Active" else "Active"
        if not confirm_save(self, f"Change consumer {c['con_id']} - {c.get('con_name')} "
                                  f"to {new_status}?"):
            return
        try:
            self.ctx.db.execute("UPDATE tbl_consumer SET con_status=%s WHERE con_id=%s",
                                (new_status, c["con_id"]))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()

    def _delete(self) -> None:
        c = self._selected()
        if not c:
            warn(self, "Select a consumer first.")
            return
        if not confirm_delete(self, f"Delete consumer {c['con_id']} - {c.get('con_name')}?\n\n"
                                    "Consumers with bills cannot be deleted. "
                                    "This cannot be undone."):
            return
        try:
            services.delete_consumer(self.ctx.db, int(c["con_id"]))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import consumers", "", "Excel files (*.xlsx *.xlsm)")
        if not path:
            return
        if not confirm_save(self, "Import consumers from this workbook?\n\n"
                                  f"{path}\n\nExisting accounts will be updated."):
            return
        try:
            result = import_consumers(self.ctx.db, path)
        except Exception as exc:
            error(self, str(exc))
            return
        message = f"Created: {result['created']}, updated: {result['updated']}."
        if result["errors"]:
            message += "\n\n" + "\n".join(result["errors"][:15])
        info(self, message)
        self.ctx.notify_change()
        self._search()
