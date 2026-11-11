from __future__ import annotations

import sys
import traceback
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFormLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from . import excelio, services
from .config import APP_NAME, APP_VERSION, DEFAULT_LOGO_JPG, DEFAULT_LOGO_SVG, load_config
from .context import AppContext
from .db import Database, DbError
from .theme import apply_theme
from .ui.bills import BillsTab
from .ui.common import confirm_save, error, info, warn
from .ui.consumers import ConsumersTab
from .ui.dashboard import DashboardTab
from .ui.documents import print_report
from .ui.generate import BillGenerateTab
from .ui.home import HomeTab
from .ui.icons import make_icon
from .ui.login import LoginDialog
from .ui.logo import logo_pixmap
from .ui.masters import MasterDataTab
from .ui.palette import accent as section_accent
from .ui.reports import ReportsTab
from .ui.settings import DatabaseSettingsDialog, SettingsTab
from .ui.unitrate import UnitRateTab


class ChangePasswordDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Change password")
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.EchoMode.Password)
        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Current password", self.current)
        form.addRow("New password", self.new)
        form.addRow("Repeat new password", self.confirm)
        root.addLayout(form)
        note = QLabel("5 - 25 characters. Passwords are stored with the legacy reversible cipher.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        row = QVBoxLayout()
        save = QPushButton("Change password")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        root.addLayout(row)

    def _save(self) -> None:
        if services.authenticate(self.ctx.db, self.ctx.user_name, self.current.text()) is None:
            warn(self, "Current password is not correct.")
            return
        if self.new.text() != self.confirm.text():
            warn(self, "The new passwords do not match.")
            return
        if not confirm_save(self, f"Change the password for {self.ctx.user_name}?"):
            return
        try:
            services.change_password(self.ctx.db, self.ctx.user_id, self.new.text())
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, "Password changed.")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, cfg, db: Database, user: dict):
        super().__init__()
        self.cfg = cfg
        self.db = db
        self.ctx = AppContext(cfg, db, user, self)
        self.ctx.config_changed.connect(self._refresh_status)
        self.ctx.navigate.connect(self._go_section)
        self.setWindowTitle(f"{APP_NAME} — CU Electric Billing")
        if DEFAULT_LOGO_SVG.is_file():
            self.setWindowIcon(QIcon(logo_pixmap(DEFAULT_LOGO_SVG, 256)))
        self.resize(1280, 820)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.home = HomeTab(self.ctx)
        self.dashboard = DashboardTab(self.ctx)
        self.consumers = ConsumersTab(self.ctx)
        self.generate = BillGenerateTab(self.ctx)
        self.bills = BillsTab(self.ctx)
        self.unitrate = UnitRateTab(self.ctx)
        self.reports = ReportsTab(self.ctx)
        self.masters = MasterDataTab(self.ctx)
        self.settings = SettingsTab(self.ctx)
        for widget, label, icon_name in [
            (self.home, "Home", "home"),
            (self.dashboard, "Dashboard", "dashboard"),
            (self.consumers, "Consumers", "consumers"),
            (self.generate, "Generate bill", "bill"),
            (self.bills, "Bills && payments", "payments"),
            (self.unitrate, "Unit / rate change", "unitrate"),
            (self.reports, "Reports && Excel", "reports"),
            (self.masters, "Master data", "masters"),
            (self.settings, "Settings", "settings"),
        ]:
            self.tabs.addTab(widget, make_icon(icon_name, 18, section_accent(icon_name)),
                             label)
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.home.navigate.connect(self._go_section)
        self.home.action.connect(self._home_action)

        self._build_menu()
        self._refresh_status()
        repaired = int(getattr(self.ctx.db, "sequences_repaired", 0) or 0)
        if repaired:
            self.statusBar().showMessage(
                f"Ready · repaired {repaired} id sequence(s) to prevent duplicate-key errors",
                15000,
            )
        else:
            self.statusBar().showMessage("Ready")

        self.consumers.refresh()
        self.bills.refresh()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        backup = file_menu.addAction("Backup database to Excel...")
        backup.triggered.connect(self.backup_excel)
        file_menu.addSeparator()
        pw = file_menu.addAction("Change password...")
        pw.triggered.connect(self.change_password)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Exit")
        quit_action.triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        self.full_screen_action = view_menu.addAction("Full screen")
        self.full_screen_action.setCheckable(True)
        self.full_screen_action.setShortcut("F11")
        self.full_screen_action.triggered.connect(self._toggle_full_screen)

        help_menu = self.menuBar().addMenu("&Help")
        about = help_menu.addAction("About")
        about.triggered.connect(self._about)

    def _toggle_full_screen(self, checked: bool = False) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showMaximized()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.full_screen_action.setChecked(False)
            self.showMaximized()
            return
        super().keyPressEvent(event)

    def _refresh_status(self) -> None:
        paper = self.cfg.paper
        self.statusBar().showMessage(
            f"User: {self.ctx.user_name} ({self.ctx.user.get('access_type') or '-'})   |   "
            f"Database: {self.cfg.db.label()}   |   Printer: {self.cfg.printer or 'system default'}   |   "
            f"Paper: {paper}   |   Ink saver: on"
        )

    def _tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _go_section(self, key: str) -> None:
        target = {
            "dashboard": self.dashboard,
            "consumers": self.consumers,
            "generate": self.generate,
            "bills": self.bills,
            "unitrate": self.unitrate,
            "reports": self.reports,
            "masters": self.masters,
            "settings": self.settings,
        }.get(key)
        if target is not None:
            self.tabs.setCurrentWidget(target)

    def _home_action(self, key: str) -> None:
        if key == "excel":
            self.backup_excel()
        elif key == "password":
            self.change_password()
        elif key == "about":
            self._about()

    def change_password(self) -> None:
        ChangePasswordDialog(self.ctx, self).exec()

    def backup_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup database to Excel",
            f"epbs_backup_{date.today():%Y%m%d}.xlsx", "Excel files (*.xlsx)")
        if not path:
            return
        try:
            excelio.backup_database(self.db, path, self.cfg.db.label())
        except Exception as exc:
            error(self, str(exc))
            return
        info(self, f"Backup written to:\n{path}")

    def _about(self) -> None:
        logo = ""
        if DEFAULT_LOGO_JPG.is_file():
            logo = (f'<p align="center"><img src="{DEFAULT_LOGO_JPG.as_uri()}" '
                    f'height="72"></p>')
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"{logo}<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Python desktop re-implementation of the EPBS (Cable Operator System - "
            "CU Electric Billing) application.</p>"
            "<p>PostgreSQL 18 backend · PySide6 interface · direct printing · PDF · Excel.</p>"
            "<p><b>Printing:</b> black on white, thin borders, small font, no background fills."
            " Bills can be sent directly to the printer.</p>",
        )

    def closeEvent(self, event) -> None:
        try:
            self.db.close()
        finally:
            event.accept()


def _ensure_database(cfg):
    """Connect, creating/upgrading the schema when needed."""
    while True:
        db = Database(cfg.db)
        try:
            db.connect()
        except DbError as exc:
            dialog = DatabaseSettingsDialog(cfg)
            dialog.setWindowTitle("Database connection failed - EPBS")
            dialog.status.setText(f"{exc}\n\nCorrect the connection and press Save.")
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            cfg = load_config()
            continue

        if not db.table_exists("tbl_users"):
            try:
                db.initialize_schema()
            except DbError as exc:
                error(None, f"The database is reachable but the schema could not be created:\n\n{exc}")
                dialog = DatabaseSettingsDialog(cfg)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    db.close()
                    return None
                cfg = load_config()
                continue
        elif cfg.auto_schema:
            # Idempotent upgrade for databases created by an older version
            # (for example: drop the legacy foreign-key constraints).
            try:
                db.initialize_schema()
            except DbError as exc:
                error(None, f"The database schema could not be upgraded:\n\n{exc}")
                db.close()
                return None
        return db


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    if DEFAULT_LOGO_SVG.is_file():
        app.setWindowIcon(QIcon(logo_pixmap(DEFAULT_LOGO_SVG, 256)))
    apply_theme(app)

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        QMessageBox.critical(None, "Unexpected error", text[-2500:])
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook

    cfg = load_config()
    db = _ensure_database(cfg)
    if db is None:
        return 0

    login = LoginDialog(db, cfg)
    if login.exec() != QDialog.DialogCode.Accepted or not login.user:
        db.close()
        return 0

    window = MainWindow(login.cfg, db, login.user)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
