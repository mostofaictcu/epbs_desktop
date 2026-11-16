"""Application configuration (config.ini).

The file lives next to ``main.py`` (override with the EPBS_CONFIG
environment variable).  Database credentials are kept in plain text inside
the local file - keep the file private / set NTFS permissions.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "EPBS Desktop"
APP_VERSION = "1.0.0"
APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("EPBS_CONFIG") or (APP_DIR / "config.ini"))

STATIC_DIR = APP_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
DEFAULT_LOGO_SVG = IMAGES_DIR / "logo.svg"          # screen / window icon
DEFAULT_LOGO_JPG = IMAGES_DIR / "company_logo.jpg"  # printed documents and PDF

PAPERS = ("A4", "A5", "Letter", "Receipt 80mm")


def resolve_logo(path: str | Path | None = None, *, print_ready: bool = False) -> Path | None:
    """Return a usable logo file.

    A logo chosen in Settings wins; when it is empty or missing the bundled
    crest is used, ``logo.svg`` on screen and ``company_logo.jpg`` for print /
    PDF (raster images render more reliably in Qt documents).
    """
    if path:
        candidate = Path(str(path)).expanduser()
        if candidate.is_file():
            if print_ready and candidate.suffix.lower() == ".svg":
                if DEFAULT_LOGO_JPG.is_file():
                    return DEFAULT_LOGO_JPG
            else:
                return candidate
    fallback = DEFAULT_LOGO_JPG if print_ready else DEFAULT_LOGO_SVG
    return fallback if fallback.is_file() else None


def _get(cp, section, key, default=""):
    try:
        return cp.get(section, key)
    except Exception:
        return default


def _bool(value, default=False):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class DbConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "ebps_db"
    user: str = "postgres"
    password: str = ""
    sslmode: str = "prefer"
    schema: str = "public"
    connect_timeout: int = 5

    def connect_kwargs(self) -> dict:
        kw = dict(
            host=self.host,
            port=int(self.port),
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            sslmode=self.sslmode or "prefer",
            connect_timeout=int(self.connect_timeout or 5),
        )
        if self.schema and self.schema != "public":
            safe = "".join(ch for ch in self.schema if ch.isalnum() or ch == "_")
            if safe:
                kw["options"] = f"-c search_path={safe},public"
        return kw

    def label(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"


@dataclass
class AppConfig:
    db: DbConfig = field(default_factory=DbConfig)
    company_id: str = "1001"
    paper: str = "A4"
    font_pt: float = 8.0
    printer: str = ""              # empty = system default printer
    show_print_dialog: bool = False
    auto_schema: bool = True       # create/upgrade schema when DB is empty
    bill_copy_label: str = ""
    path: Path = CONFIG_PATH

    def save(self, path: Path | None = None) -> Path:
        target = Path(path or self.path)
        cp = configparser.ConfigParser(interpolation=None)
        cp["database"] = {
            "host": self.db.host,
            "port": str(self.db.port),
            "dbname": self.db.dbname,
            "user": self.db.user,
            "password": self.db.password,
            "sslmode": self.db.sslmode,
            "schema": self.db.schema,
            "connect_timeout": str(self.db.connect_timeout),
        }
        cp["app"] = {
            "company_id": self.company_id,
            "paper": self.paper,
            "font_pt": f"{self.font_pt:.1f}",
            "printer": self.printer,
            "show_print_dialog": "1" if self.show_print_dialog else "0",
            "auto_schema": "1" if self.auto_schema else "0",
            "bill_copy_label": self.bill_copy_label,
        }
        target.write_text(
            "; EPBS Desktop configuration\n"
            "; Created by the application. Keep this file private (it holds the DB password).\n"
            + _CP_HEADER
            + "\n",
            encoding="utf-8",
        )
        with target.open("a", encoding="utf-8") as fh:
            cp.write(fh)
        self.path = target
        return target


_CP_HEADER = "; Sections: [database] connection, [app] preferences\n;"


def load_config(path: Path | None = None) -> AppConfig:
    target = Path(path or CONFIG_PATH)
    cfg = AppConfig(path=target)
    if not target.exists():
        cfg.save(target)
        return cfg
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(target, encoding="utf-8")
    db = cfg.db
    db.host = _get(cp, "database", "host", db.host) or "localhost"
    db.port = int(_get(cp, "database", "port", db.port) or 5432)
    db.dbname = _get(cp, "database", "dbname", db.dbname) or "ebps_db"
    db.user = _get(cp, "database", "user", db.user) or "postgres"
    db.password = _get(cp, "database", "password", "")
    db.sslmode = _get(cp, "database", "sslmode", "prefer") or "prefer"
    db.schema = _get(cp, "database", "schema", "public") or "public"
    db.connect_timeout = int(_get(cp, "database", "connect_timeout", 5) or 5)

    cfg.company_id = _get(cp, "app", "company_id", "1001") or "1001"
    paper = _get(cp, "app", "paper", "A4")
    cfg.paper = paper if paper in PAPERS else "A4"
    try:
        cfg.font_pt = float(_get(cp, "app", "font_pt", 8) or 8)
    except ValueError:
        cfg.font_pt = 8.0
    cfg.font_pt = min(12.0, max(6.0, cfg.font_pt))
    cfg.printer = _get(cp, "app", "printer", "")
    cfg.show_print_dialog = _bool(_get(cp, "app", "show_print_dialog", "0"))
    cfg.auto_schema = _bool(_get(cp, "app", "auto_schema", "1"), True)
    cfg.bill_copy_label = _get(cp, "app", "bill_copy_label", "")
    return cfg
