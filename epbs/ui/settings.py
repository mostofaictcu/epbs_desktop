from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from ..config import PAPERS, AppConfig, DbConfig, load_config, resolve_logo
from ..db import Database
from .. import services
from .common import confirm_save, error, info, warn
from .logo import logo_pixmap


class DatabaseSettingsDialog(QDialog):
    """Used both at startup and from the Settings tab."""

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Database settings (PostgreSQL)")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)

        note = QLabel("PostgreSQL 18 connection. 'Create / upgrade schema' prepares an empty database.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        form = QFormLayout()
        db = cfg.db
        self.host = QLineEdit(db.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(db.port))
        self.dbname = QLineEdit(db.dbname)
        self.user = QLineEdit(db.user)
        self.password = QLineEdit(db.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.sslmode = QComboBox()
        self.sslmode.addItems(["disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
        self.sslmode.setCurrentText(db.sslmode if db.sslmode in
                                   ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] else "prefer")
        self.schema = QLineEdit(db.schema)
        self.schema.setToolTip("Usually 'public'. Leave empty for public.")
        form.addRow("Host", self.host)
        form.addRow("Port", self.port)
        form.addRow("Database", self.dbname)
        form.addRow("User", self.user)
        form.addRow("Password", self.password)
        form.addRow("SSL mode", self.sslmode)
        form.addRow("Schema", self.schema)
        root.addLayout(form)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        schema_btn = QPushButton("Create / upgrade schema")
        schema_btn.clicked.connect(self._init_schema)
        buttons.addWidget(test)
        buttons.addWidget(schema_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _temp_db(self) -> Database:
        return Database(DbConfig(
            host=self.host.text().strip() or "localhost",
            port=self.port.value(),
            dbname=self.dbname.text().strip() or "ebps_db",
            user=self.user.text().strip() or "postgres",
            password=self.password.text(),
            sslmode=self.sslmode.currentText(),
            schema=self.schema.text().strip() or "public",
        ))

    def _test(self) -> None:
        temp = self._temp_db()
        try:
            temp.connect()
            ok, version = temp.ping()
            if ok:
                self.status.setText(f"Connected. {version[:90]}")
            else:
                self.status.setText(version)
        except Exception as exc:
            self.status.setText(f"Connection failed: {exc}")
        finally:
            temp.close()

    def _init_schema(self) -> None:
        temp = self._temp_db()
        try:
            temp.connect()
            temp.initialize_schema()
            self.status.setText("Schema is ready (tables, indexes and seed data).")
        except Exception as exc:
            self.status.setText(f"Schema creation failed: {exc}")
        finally:
            temp.close()

    def _save(self) -> None:
        cfg_db = DbConfig(
            host=self.host.text().strip() or "localhost",
            port=self.port.value(),
            dbname=self.dbname.text().strip() or "ebps_db",
            user=self.user.text().strip() or "postgres",
            password=self.password.text(),
            sslmode=self.sslmode.currentText(),
            schema=self.schema.text().strip() or "public",
            connect_timeout=self.cfg.db.connect_timeout,
        )
        if not confirm_save(self, "Save this PostgreSQL connection and reconnect?\n\n"
                                  f"{cfg_db.label()}"):
            return
        self.cfg.db = cfg_db
        try:
            self.cfg.save()
        except Exception as exc:
            error(self, f"Could not write config.ini: {exc}")
            return
        self.accept()


class SettingsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        scroll.setWidget(host)
        root = QVBoxLayout(host)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        outer.addWidget(scroll)

        # master data ---------------------------------------------------
        master_group = QGroupBox("Master data")
        ml = QVBoxLayout(master_group)
        master_hint = QLabel("Consumer types and rates, areas, departments, designations "
                             "and consumer groups used by the consumer form.")
        master_hint.setObjectName("muted")
        master_hint.setWordWrap(True)
        open_master = QPushButton("Edit master data...")
        open_master.clicked.connect(lambda: ctx.navigate.emit("masters"))
        self.open_master = open_master
        master_row = QHBoxLayout()
        master_row.addWidget(open_master)
        master_row.addStretch(1)
        ml.addWidget(master_hint)
        ml.addLayout(master_row)
        root.addWidget(master_group)

        # database ------------------------------------------------------
        db_group = QGroupBox("Database")
        db_lay = QFormLayout(db_group)
        self.db_info = QLabel(ctx.cfg.db.label())
        self.db_info.setObjectName("muted")
        db_lay.addRow("Connected as", self.db_info)
        change = QPushButton("Change connection...")
        change.clicked.connect(self._change_db)
        init = QPushButton("Create / upgrade schema")
        init.clicked.connect(self._init_schema)
        repair = QPushButton("Repair ID sequences")
        repair.setToolTip("Fixes 'duplicate key value violates unique constraint ..._pkey' "
                          "after importing legacy data.")
        repair.clicked.connect(self._repair_sequences)
        row = QHBoxLayout()
        row.addWidget(change)
        row.addWidget(init)
        row.addWidget(repair)
        row.addStretch(1)
        db_lay.addRow(row)
        root.addWidget(db_group)

        # printing ------------------------------------------------------
        print_group = QGroupBox("Printing (ink saver)")
        pf = QFormLayout(print_group)
        self.printer = QComboBox()
        self.printer.addItem("System default printer", "")
        for p in QPrinterInfo.availablePrinters():
            self.printer.addItem(p.printerName(), p.printerName())
        idx = self.printer.findData(ctx.cfg.printer)
        self.printer.setCurrentIndex(idx if idx >= 0 else 0)
        self.paper = QComboBox()
        self.paper.addItems(list(PAPERS))
        self.paper.setCurrentText(ctx.cfg.paper)
        self.font_pt = QDoubleSpinBox()
        self.font_pt.setRange(6, 12)
        self.font_pt.setSingleStep(0.5)
        self.font_pt.setDecimals(1)
        self.font_pt.setValue(ctx.cfg.font_pt)
        self.font_pt.setSuffix(" pt")
        self.copy_label = QLineEdit(ctx.cfg.bill_copy_label)
        self.copy_label.setPlaceholderText("Optional label printed under the bill number")
        self.show_dialog = QCheckBox("Show the Windows print dialog before printing")
        self.show_dialog.setChecked(ctx.cfg.show_print_dialog)
        pf.addRow("Printer", self.printer)
        pf.addRow("Paper", self.paper)
        pf.addRow("Font size", self.font_pt)
        pf.addRow("Bill copy label", self.copy_label)
        pf.addRow("", self.show_dialog)
        hint = QLabel("Bills are printed in black on white: thin borders, small font, no background fills.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        pf.addRow(hint)
        root.addWidget(print_group)

        # app -----------------------------------------------------------
        app_group = QGroupBox("Billing defaults")
        af = QFormLayout(app_group)
        self.company_id = QLineEdit(ctx.cfg.company_id)
        self.auto_schema = QCheckBox("Create missing tables automatically on connect")
        self.auto_schema.setChecked(ctx.cfg.auto_schema)
        af.addRow("Company id", self.company_id)
        af.addRow("", self.auto_schema)
        rent_hint = QLabel("Meter rent is set on each consumer type (default 0) and is added "
                           "once to every bill. It can still be changed on the Generate bill "
                           "page for an individual bill.")
        rent_hint.setObjectName("muted")
        rent_hint.setWordWrap(True)
        af.addRow(rent_hint)
        root.addWidget(app_group)

        # company -------------------------------------------------------
        self.company_group = QGroupBox("Company information (printed on bills)")
        self.cf = QFormLayout(self.company_group)
        self.c_name = QLineEdit()
        self.c_address = QLineEdit()
        self.c_reg = QLineEdit()
        self.c_contact = QLineEdit()
        self.c_email = QLineEdit()
        self.c_website = QLineEdit()
        self.c_logo = QLineEdit()
        self.c_logo.setReadOnly(True)
        self.c_logo.setPlaceholderText("Default: static/images/logo.svg")
        pick = QPushButton("Choose logo...")
        pick.clicked.connect(self._choose_logo)
        use_default = QPushButton("Use default")
        use_default.setToolTip("Remove the custom logo and use static/images/logo.svg")
        use_default.clicked.connect(self._use_default_logo)
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(48, 64)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet(
            "background:#ffffff;border:1px solid #ccd6e0;border-radius:4px;")
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_preview)
        logo_row.addWidget(self.c_logo, 1)
        logo_row.addWidget(pick)
        logo_row.addWidget(use_default)
        self.cf.addRow("Name", self.c_name)
        self.cf.addRow("Address", self.c_address)
        self.cf.addRow("Registration", self.c_reg)
        self.cf.addRow("Contact", self.c_contact)
        self.cf.addRow("Email", self.c_email)
        self.cf.addRow("Website", self.c_website)
        self.cf.addRow("Logo", logo_row)
        root.addWidget(self.company_group)

        buttons = QHBoxLayout()
        save_print = QPushButton("Save settings")
        save_print.setObjectName("primary")
        save_print.clicked.connect(self._save_all)
        save_company = QPushButton("Save company")
        save_company.clicked.connect(self._save_company)
        buttons.addWidget(save_print)
        buttons.addWidget(save_company)
        buttons.addStretch(1)
        root.addLayout(buttons)
        root.addStretch(1)

        self.load_company()

    # ------------------------------------------------------------------
    def load_company(self) -> None:
        company = self.ctx.company()
        self.c_name.setText(company.get("company_name") or "")
        self.c_address.setText(company.get("company_address") or "")
        self.c_reg.setText(company.get("reg_no") or "")
        self.c_contact.setText(company.get("contact_no") or "")
        self.c_email.setText(company.get("email") or "")
        self.c_website.setText(company.get("website") or "")
        self.c_logo.setText(company.get("logo_url") or "")
        self._update_logo_preview()

    def _update_logo_preview(self) -> None:
        chosen = self.c_logo.text().strip()
        path = resolve_logo(chosen)
        pixmap = logo_pixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.logo_preview.clear()
            self.c_logo.setToolTip("No logo file found; the bundled crest is used.")
            return
        self.logo_preview.setPixmap(pixmap.scaled(
            44, 60, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        if chosen:
            self.c_logo.setToolTip(chosen)
        else:
            self.c_logo.setToolTip(f"Default logo: {path}")

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Company logo", "", "Images (*.png *.jpg *.jpeg *.bmp *.svg)")
        if path:
            self.c_logo.setText(path)
            self._update_logo_preview()

    def _use_default_logo(self) -> None:
        self.c_logo.clear()
        self._update_logo_preview()

    def _change_db(self) -> None:
        dialog = DatabaseSettingsDialog(self.ctx.cfg, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ok, message = self.ctx.reconnect()
        if not ok:
            error(self, message)
            return
        self.db_info.setText(self.ctx.cfg.db.label())
        self.ctx.notify_change()
        info(self, "Connected to the new database.")

    def _init_schema(self) -> None:
        if not confirm_save(self, "Create or upgrade the database schema?\n\n"
                                  "Missing tables and indexes are added; existing data is kept."):
            return
        try:
            self.ctx.db.initialize_schema()
            self.ctx.notify_change()
            info(self, "Schema created / upgraded successfully.")
        except Exception as exc:
            error(self, str(exc))

    def _repair_sequences(self) -> None:
        if not confirm_save(
            self,
            "Move the id sequences of bills, readings, payments and master data "
            "past their highest stored id?\n\n"
            "This fixes 'duplicate key value violates unique constraint ..._pkey' "
            "errors. No business data is changed.",
        ):
            return
        try:
            from ..schema import sync_identity_sequences
            count = sync_identity_sequences(self.ctx.db)
        except Exception as exc:
            error(self, str(exc))
            return
        if count:
            info(self, f"{count} id sequence(s) moved past the highest stored id.")
        else:
            info(self, "All id sequences are already ahead of the stored ids.")

    def _save_all(self) -> None:
        cfg = self.ctx.cfg
        cfg.printer = self.printer.currentData() or ""
        cfg.paper = self.paper.currentText()
        cfg.font_pt = self.font_pt.value()
        cfg.bill_copy_label = self.copy_label.text().strip()
        cfg.show_print_dialog = self.show_dialog.isChecked()
        cfg.company_id = self.company_id.text().strip() or "1001"
        cfg.auto_schema = self.auto_schema.isChecked()
        if not confirm_save(self, "Save these application settings to config.ini?\n\n"
                                  f"Printer: {cfg.printer or 'system default'}\n"
                                  f"Paper: {cfg.paper} · font {cfg.font_pt} pt"):
            return
        try:
            cfg.save()
        except Exception as exc:
            error(self, f"Could not save config.ini: {exc}")
            return
        self.ctx.config_changed.emit()
        info(self, "Settings saved to config.ini.")

    def _save_company(self) -> None:
        data = {
            "company_id": self.company_id.text().strip() or "1001",
            "company_name": self.c_name.text().strip(),
            "company_address": self.c_address.text().strip(),
            "reg_no": self.c_reg.text().strip(),
            "contact_no": self.c_contact.text().strip(),
            "email": self.c_email.text().strip(),
            "website": self.c_website.text().strip(),
            "logo_url": self.c_logo.text().strip(),
        }
        if not confirm_save(self, f"Save the company information for "
                                  f"{data['company_name'] or data['company_id']}?\n\n"
                                  "It is printed on bills and statements."):
            return
        try:
            services.save_company(self.ctx.db, data)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify_change()
        info(self, "Company information saved.")

    def refresh(self) -> None:
        self.db_info.setText(self.ctx.cfg.db.label())
