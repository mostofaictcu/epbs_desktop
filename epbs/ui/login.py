from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from .. import services
from ..config import APP_NAME, APP_VERSION, AppConfig, DEFAULT_LOGO_SVG, resolve_logo
from ..db import Database, DbError
from .logo import AnimatedLogo, logo_pixmap


class LoginDialog(QDialog):
    def __init__(self, db: Database, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.cfg = cfg
        self.user: dict | None = None
        self.setWindowTitle(f"{APP_NAME} - Login")
        self.setMinimumWidth(420)
        if DEFAULT_LOGO_SVG.is_file():
            self.setWindowIcon(QIcon(logo_pixmap(DEFAULT_LOGO_SVG, 256)))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        self.logo = AnimatedLogo(height=86)
        self.logo.setToolTip("Company logo (Settings → Company information)")
        try:
            logo_path = resolve_logo((services.company(self.db, cfg.company_id) or {}).get("logo_url"))
        except Exception:
            logo_path = resolve_logo(None)
        if logo_path and self.logo.set_source(logo_path):
            root.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
            root.addSpacing(6)
        title = QLabel("EPBS")
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Cable Operator System · CU Electric Billing")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(14)

        form = QFormLayout()
        form.setSpacing(8)
        self.username = QLineEdit()
        self.username.setPlaceholderText("User name")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        self.show_pw = QCheckBox("Show password")
        self.show_pw.toggled.connect(
            lambda on: self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        form.addRow("User name", self.username)
        form.addRow("Password", self.password)
        form.addRow("", self.show_pw)
        root.addLayout(form)

        self.message = QLabel("")
        self.message.setObjectName("warning")
        self.message.setWordWrap(True)
        root.addWidget(self.message)

        buttons = QHBoxLayout()
        self.db_label = QLabel(cfg.db.label())
        self.db_label.setObjectName("muted")
        settings_btn = QPushButton("Database settings")
        settings_btn.clicked.connect(self._db_settings)
        self.login_btn = QPushButton("Login")
        self.login_btn.setObjectName("primary")
        self.login_btn.setDefault(True)
        self.login_btn.clicked.connect(self._login)
        buttons.addWidget(self.db_label, 1)
        buttons.addWidget(settings_btn)
        buttons.addWidget(self.login_btn)
        root.addLayout(buttons)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(version)

        self.username.setFocus()

    def _login(self) -> None:
        try:
            user = services.authenticate(self.db, self.username.text(), self.password.text())
        except DbError as exc:
            self.message.setText(str(exc))
            return
        if not user:
            self.message.setText("Access denied. Please enter the correct user name and password.")
            self.password.selectAll()
            self.password.setFocus()
            return
        self.user = user
        self.accept()

    def _db_settings(self) -> None:
        from .settings import DatabaseSettingsDialog

        dialog = DatabaseSettingsDialog(self.cfg, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cfg = dialog.cfg
            self.db.cfg = self.cfg.db
            try:
                self.db.connect()
                ok, _ = self.db.ping()
            except Exception as exc:
                self.message.setText(str(exc))
                return
            if not ok:
                self.message.setText("Database connection failed.")
                return
            if not self.db.table_exists("tbl_users"):
                if self.cfg.auto_schema:
                    try:
                        self.db.initialize_schema()
                    except DbError as exc:
                        self.message.setText(f"Could not create schema: {exc}")
                        return
            self.db_label.setText(self.cfg.db.label())
            self.message.setText("Connected to the new database. Please log in.")
