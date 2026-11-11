"""Shared application context passed to every screen."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from . import services
from .config import AppConfig
from .db import Database, DbError
from .jobs import JobQueue


class AppContext(QObject):
    data_changed = Signal()
    config_changed = Signal()
    navigate = Signal(str)

    def __init__(self, cfg: AppConfig, db: Database, user: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.db = db
        self.user = user or {}
        self.jobs = JobQueue(self)

    @property
    def user_id(self) -> str:
        return str(self.user.get("user_id") or "")

    @property
    def user_name(self) -> str:
        return str(self.user.get("username") or self.user.get("full_name") or "")

    @property
    def is_admin(self) -> bool:
        return str(self.user.get("access_type") or "").lower().startswith("admin")

    def company(self) -> dict:
        try:
            return services.company(self.db, self.cfg.company_id)
        except Exception:
            return {"company_id": self.cfg.company_id, "company_name": "EPBS"}

    def notify_change(self) -> None:
        self.data_changed.emit()

    def reconnect(self) -> tuple[bool, str]:
        old = self.db.cfg
        new_db = Database(self.cfg.db)
        try:
            new_db.connect()
        except DbError as exc:
            return False, str(exc)
        self.db.close()
        self.db = new_db
        try:
            if not self.db.table_exists("tbl_users") and self.cfg.auto_schema:
                self.db.initialize_schema()
        except Exception as exc:
            self.db.cfg = old
            return False, f"Connected, but the schema check failed: {exc}"
        self.config_changed.emit()
        return True, "Connected"
