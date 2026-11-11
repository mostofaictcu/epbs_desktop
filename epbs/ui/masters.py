"""Master data: consumer types, areas, departments, designations and groups."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import services
from .common import Table, confirm_delete, confirm_save, error, money, warn


class MasterDialog(QDialog):
    def __init__(self, title: str, name: str = "", rate: float | None = None,
                 with_rate: bool = False, parent=None):
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
        if with_rate:
            form.addRow("Rate", self.rate)
        root.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _accept(self) -> None:
        if not self.name.text().strip():
            warn(self, "Name is required.")
            return
        self.accept()

    def values(self) -> tuple[str, float | None]:
        return self.name.text().strip(), (self.rate.value() if self.with_rate else None)


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
        buttons.addStretch(1)
        buttons.addWidget(delete)
        root.addLayout(buttons)

        hint = QLabel("Changes are saved immediately. An item used by a consumer "
                      "cannot be deleted.")
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
            headers.append("Rate")
        headers.append("Used by")
        data = []
        for row in self._rows:
            values = [row["id"], row["name"]]
            if self.with_rate:
                values.append(row.get("rate"))
            values.append(row.get("used"))
            data.append(values)
        money_cols = {2} if self.with_rate else set()
        self.table.load(headers, data, money_cols=money_cols, right_cols={len(headers) - 1})
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
        name, rate = dialog.values()
        detail = f"Add {self._name_header.lower()} '{name}'"
        if self.with_rate:
            detail += f" with rate {rate:.2f}"
        if not confirm_save(self, detail + "?"):
            return
        try:
            services.add_master_row(self.ctx.db, self.kind, name, rate)
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
                              float(row.get("rate") or 0), self.with_rate, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, rate = dialog.values()
        detail = f"Change {self._name_header.lower()} '{row['name']}' to '{name}'"
        if self.with_rate and float(row.get("rate") or 0) != float(rate or 0):
            detail += f"\n\nRate: {money(row.get('rate'))} → {money(rate)}"
        if self.kind == "group":
            detail += "\n\nEvery consumer using this group will be updated."
        if not confirm_save(self, detail + "?"):
            return
        try:
            services.update_master_row(self.ctx.db, self.kind, int(row["id"]), name, rate)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
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
