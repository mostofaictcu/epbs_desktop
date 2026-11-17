"""Master data: consumer types, areas, departments, designations and groups."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import services
from .common import Table, confirm_delete, confirm_save, error, money, warn


class MasterDialog(QDialog):
    def __init__(self, title: str, name: str = "", rate: float | None = None,
                 with_rate: bool = False, meter_rent: float | None = None,
                 minimum_amount: float | None = None, fixed_charge: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self.with_rate = with_rate
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(45)
        form.addRow("Name", self.name)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 100000)
        self.rate.setDecimals(2)
        self.rate.setValue(float(rate or 0))
        self.rate.setSuffix(" / unit")
        self.rate_caption = QLabel("Flat rate")
        self.fixed_charge = QCheckBox("Fixed charge (rate is billed once per bill)")
        self.fixed_charge.setToolTip(
            "Tick this for types such as BDF where the rate is a flat amount per bill, "
            "not a price per unit. The bill charges the rate once, even when the consumer "
            "uses 0 units. Slab tariffs are ignored.")
        self.fixed_charge.setChecked(bool(fixed_charge))
        self.fixed_charge.toggled.connect(self._fixed_charge_changed)
        self.meter_rent = QDoubleSpinBox()
        self.meter_rent.setRange(0, 100000)
        self.meter_rent.setDecimals(2)
        self.meter_rent.setValue(float(meter_rent or 0))
        self.meter_rent.setSuffix(" / bill")
        self.minimum_amount = QDoubleSpinBox()
        self.minimum_amount.setRange(0, 100000)
        self.minimum_amount.setDecimals(2)
        self.minimum_amount.setValue(float(minimum_amount or 0))
        self.minimum_amount.setSuffix(" / bill")
        self.minimum_amount.setToolTip("Minimum energy charge for one bill. When the calculated "
                                       "amount is lower, this amount is billed instead. 0 = no "
                                       "minimum. Meter rent and previous dues are added after it.")
        if with_rate:
            form.addRow(self.rate_caption, self.rate)
            form.addRow("", self.fixed_charge)
            form.addRow("Default meter rent", self.meter_rent)
            form.addRow("Minimum amount", self.minimum_amount)
        root.addLayout(form)
        if with_rate:
            note = QLabel("Slabs are optional; a type with no slabs bills at the flat rate. "
                          "Tick fixed charge when the rate is an amount per bill, not per unit "
                          "(for example BDF). Meter rent is added once per bill; the minimum "
                          "raises a lower charge. 0 disables either.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            root.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._fixed_charge_changed(self.fixed_charge.isChecked())

    def _fixed_charge_changed(self, checked: bool) -> None:
        self.rate_caption.setText("Fixed charge" if checked else "Flat rate")
        self.rate.setSuffix(" / bill" if checked else " / unit")

    def _accept(self) -> None:
        if not self.name.text().strip():
            warn(self, "Name is required.")
            return
        self.accept()

    def values(self) -> tuple[str, float | None, float | None, float | None, bool | None]:
        return (self.name.text().strip(),
                (self.rate.value() if self.with_rate else None),
                (self.meter_rent.value() if self.with_rate else None),
                (self.minimum_amount.value() if self.with_rate else None),
                (self.fixed_charge.isChecked() if self.with_rate else None))


class SlabDialog(QDialog):
    """Progressive slab tariff editor for one consumer type."""

    def __init__(self, ctx, type_row: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.type_id = int(type_row["id"])
        self.type_name = str(type_row.get("name") or "")
        self.setWindowTitle(f"Slabs - {self.type_name}")
        self.resize(620, 430)
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        minimum = float(type_row.get("minimum_amount") or 0)
        head = QLabel(
            f"<b>{self.type_name}</b> · slab tariff"
            + (f" · minimum amount {money(minimum)}" if minimum else "")
            + "<br>"
            "Each slab applies to the units above the previous slab's end. "
            "Example: 500 units with 0-400 @ 7.48 and 401-600 @ 10.20 = "
            "400 × 7.48 + 100 × 10.20."
        )
        head.setWordWrap(True)
        root.addWidget(head)

        self.table = Table()
        root.addWidget(self.table, 1)

        form = QFormLayout()
        row = QHBoxLayout()
        self.from_unit = QSpinBox()
        self.from_unit.setRange(0, 100_000_000)
        self.from_unit.setGroupSeparatorShown(True)
        self.to_unit = QSpinBox()
        self.to_unit.setRange(0, 100_000_000)
        self.to_unit.setGroupSeparatorShown(True)
        self.to_unit.setSpecialValueText("No upper limit")
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 100_000)
        self.rate.setDecimals(2)
        self.rate.setSingleStep(0.5)
        row.addWidget(QLabel("From"))
        row.addWidget(self.from_unit)
        row.addWidget(QLabel("To"))
        row.addWidget(self.to_unit)
        row.addWidget(QLabel("Rate"))
        row.addWidget(self.rate)
        form.addRow("Units", row)
        root.addLayout(form)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add slab")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._add)
        self.update_btn = QPushButton("Update selected")
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._update)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._remove)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.update_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        hint = QLabel("To = 0 means the last slab has no upper limit. "
                      "Consumption above the last ended slab continues at that slab's rate.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self.table.itemSelectionChanged.connect(self._selected)
        self._load()

    def _load(self) -> None:
        try:
            self._rows = [dict(r) for r in services.type_slabs(self.ctx.db, self.type_id)]
        except Exception as exc:
            error(self, str(exc))
            return
        self._refresh()

    def _refresh(self) -> None:
        self._rows = services.normalize_slabs(self._rows) if self._rows else []
        self.table.load(
            ["Slab", "From unit", "To unit", "Rate"],
            [[r.get("slab_no"), r.get("from_unit"),
              (r.get("to_unit") or "No limit"), r.get("rate")] for r in self._rows],
            money_cols={3}, right_cols={1, 2},
        )
        self.from_unit.setValue(int((self._rows[-1].get("to_unit") or 0) + 1) if self._rows
                               else 0)
        self.to_unit.setValue(int((self._rows[-1].get("to_unit") or 0) + 100) if self._rows
                              else 100)
        if self._rows:
            self.rate.setValue(float(self._rows[-1].get("rate") or 0))
        self.table.clearSelection()
        self.update_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)

    def _selected(self) -> None:
        row = self.table.currentRow()
        valid = 0 <= row < len(self._rows)
        self.update_btn.setEnabled(valid)
        self.remove_btn.setEnabled(valid)
        if valid:
            item = self._rows[row]
            self.from_unit.setValue(int(item.get("from_unit") or 0))
            self.to_unit.setValue(int(item.get("to_unit") or 0))
            self.rate.setValue(float(item.get("rate") or 0))

    def _candidate(self) -> dict:
        return {
            "from_unit": self.from_unit.value(),
            "to_unit": self.to_unit.value(),
            "rate": self.rate.value(),
        }

    def _apply_rows(self, rows: list[dict]) -> None:
        try:
            self._rows = services.normalize_slabs(rows)
        except Exception as exc:
            warn(self, str(exc))
            return
        self._refresh()

    def _add(self) -> None:
        self._apply_rows([*self._rows, self._candidate()])

    def _update(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._rows)):
            warn(self, "Select a slab first.")
            return
        rows = list(self._rows)
        rows[row] = self._candidate()
        self._apply_rows(rows)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._rows)):
            warn(self, "Select a slab first.")
            return
        rows = list(self._rows)
        del rows[row]
        self._apply_rows(rows)

    def _save(self) -> None:
        try:
            slabs = services.normalize_slabs(self._rows)
        except Exception as exc:
            warn(self, str(exc))
            return
        if not confirm_save(
            self,
            f"Save {len(slabs)} slab(s) for type {self.type_name}?\n\n"
            + ("\n".join(f"Slab {s['slab_no']}: {s['from_unit']}-"
                         f"{s['to_unit'] or 'no limit'} @ {money(s['rate'])}"
                         for s in slabs) if slabs else "No slabs: flat rate billing.")
        ):
            return
        try:
            services.save_type_slabs(self.ctx.db, self.type_id, slabs, self.ctx.user_id)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.accept()


class MasterPane(QWidget):
    """One editable master list."""

    def __init__(self, ctx, kind: str, name_header: str, with_rate: bool = False,
                 parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.with_rate = with_rate
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        self.table = Table()
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add = QPushButton("Add")
        add.setObjectName("primary")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit)
        delete = QPushButton("Delete")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        buttons.addWidget(add)
        buttons.addWidget(edit)
        self.slabs_btn = QPushButton("Slabs...")
        self.slabs_btn.setToolTip("Edit the progressive slab tariff of the selected consumer type")
        self.slabs_btn.clicked.connect(self._slabs)
        self.slabs_btn.setVisible(self.kind == "type")
        buttons.addWidget(self.slabs_btn)
        buttons.addStretch(1)
        buttons.addWidget(delete)
        root.addLayout(buttons)

        hint = QLabel("Changes are saved immediately. An item used by a consumer "
                      "cannot be deleted. Types can use a flat rate or a slab tariff, "
                      "a fixed charge per bill (BDF-style), and an optional minimum "
                      "amount per bill.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._name_header = name_header
        self.table.doubleClicked.connect(lambda _i: self._edit())
        self.refresh()

    def refresh(self) -> None:
        try:
            self._rows = services.list_master_rows(self.ctx.db, self.kind)
        except Exception as exc:
            error(self, str(exc))
            return
        headers = ["ID", self._name_header]
        if self.with_rate:
            headers += ["Rate", "Billing", "Meter rent", "Minimum", "Slabs"]
            money_cols = {2, 4, 5}
            right_cols = {6}
        else:
            headers.append("Used by")
            money_cols = set()
            right_cols = {len(headers) - 1}
        data = []
        for row in self._rows:
            values = [row["id"], row["name"]]
            if self.with_rate:
                values += [row.get("rate"),
                           "Fixed / bill" if row.get("fixed_charge") else "Per unit",
                           row.get("meter_rent") or 0, row.get("minimum_amount") or 0,
                           row.get("slabs") or 0]
            else:
                values.append(row.get("used"))
            data.append(values)
        self.table.load(headers, data, money_cols=money_cols, right_cols=right_cols)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _add(self) -> None:
        dialog = MasterDialog(f"Add {self._name_header.lower()}", with_rate=self.with_rate,
                              parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, rate, meter_rent, minimum_amount, fixed_charge = dialog.values()
        detail = f"Add {self._name_header.lower()} '{name}'"
        if self.with_rate:
            detail += (f" with rate {rate:.2f}, meter rent {meter_rent:.2f} "
                       f"and minimum amount {minimum_amount:.2f}")
            if fixed_charge:
                detail += "\n\nThe rate is billed once per bill as a fixed charge, not per unit."
        if not confirm_save(self, detail + "?"):
            return
        try:
            services.add_master_row(self.ctx.db, self.kind, name, rate, meter_rent,
                                    minimum_amount, bool(fixed_charge))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()

    def _edit(self) -> None:
        row = self._selected()
        if not row:
            warn(self, "Select a row first.")
            return
        dialog = MasterDialog(f"Edit {self._name_header.lower()}", str(row["name"]),
                              float(row.get("rate") or 0), self.with_rate,
                              float(row.get("meter_rent") or 0),
                              float(row.get("minimum_amount") or 0),
                              bool(row.get("fixed_charge")), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, rate, meter_rent, minimum_amount, fixed_charge = dialog.values()
        detail = f"Change {self._name_header.lower()} '{row['name']}' to '{name}'"
        if self.with_rate and float(row.get("rate") or 0) != float(rate or 0):
            detail += f"\n\nRate: {money(row.get('rate'))} → {money(rate)}"
        if self.with_rate and bool(row.get("fixed_charge")) != bool(fixed_charge):
            detail += ("\nBilling: " + ("fixed amount per bill" if fixed_charge
                                        else "per unit"))
        if self.with_rate and float(row.get("meter_rent") or 0) != float(meter_rent or 0):
            detail += f"\nMeter rent: {money(row.get('meter_rent'))} → {money(meter_rent)}"
        if (self.with_rate
                and float(row.get("minimum_amount") or 0) != float(minimum_amount or 0)):
            detail += (f"\nMinimum amount: {money(row.get('minimum_amount'))} → "
                       f"{money(minimum_amount)}")
        if self.kind == "group":
            detail += "\n\nEvery consumer using this group will be updated."
        if not confirm_save(self, detail + "?"):
            return
        try:
            services.update_master_row(self.ctx.db, self.kind, int(row["id"]), name, rate,
                                       meter_rent, minimum_amount, bool(fixed_charge))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()

    def _slabs(self) -> None:
        row = self._selected()
        if not row:
            warn(self, "Select a consumer type first.")
            return
        if row.get("fixed_charge"):
            warn(self, "This type is billed as a fixed amount per bill, so slab rates are not "
                       "used. Clear the fixed charge flag first.")
            return
        if SlabDialog(self.ctx, row, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _delete(self) -> None:
        row = self._selected()
        if not row:
            warn(self, "Select a row first.")
            return
        if not confirm_delete(self, f"Delete {self._name_header.lower()} '{row['name']}'?\n\n"
                                    f"Used by {row.get('used') or 0} consumer(s). "
                                    "This cannot be undone."):
            return
        try:
            services.delete_master_row(self.ctx.db, self.kind, int(row["id"]))
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        self.refresh()


class MasterDataTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Master data")
        title.setObjectName("h1")
        root.addWidget(title)
        hint = QLabel("Areas, consumer types, departments, designations and consumer groups "
                      "used by the consumer form. Add a group here or type a new one while "
                      "adding a consumer; matching names are reused.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.tabs = QTabWidget()
        self.panes = {
            "type": MasterPane(ctx, "type", "Consumer type", True),
            "area": MasterPane(ctx, "area", "Area"),
            "department": MasterPane(ctx, "department", "Department"),
            "designation": MasterPane(ctx, "designation", "Designation"),
            "group": MasterPane(ctx, "group", "Consumer group"),
        }
        for key, label in [("type", "Types"), ("area", "Areas"),
                           ("department", "Departments"), ("designation", "Designations"),
                           ("group", "Groups")]:
            self.tabs.addTab(self.panes[key], label)
        root.addWidget(self.tabs, 1)

        self.ctx.data_changed.connect(self.refresh)

    def refresh(self) -> None:
        for pane in self.panes.values():
            pane.refresh()
