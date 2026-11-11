"""Long-running export work executed by the :class:`~epbs.jobs.JobQueue`.

Every function here runs in the queue's worker thread: it must not touch
widgets.  It opens its own database connection so report queries never block
the screen, and reports progress through the ``log`` callable.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from .. import excelio, printing, services
from ..config import AppConfig
from ..db import Database


def _connect(cfg: AppConfig) -> Database:
    db = Database(cfg.db)
    db.connect()
    return db


def _size(path: str) -> str:
    try:
        size = Path(path).stat().st_size
    except OSError:
        return ""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):,.1f} MB"
    return f"{max(1, size // 1024):,} KB"


def _summary(action: str, path: str, rows: int | None, seconds: float) -> str:
    bits = [f"{action}: {Path(path).name}"]
    if rows is not None:
        bits.append(f"{rows:,} rows")
    size = _size(path)
    if size:
        bits.append(size)
    bits.append(f"{seconds:.1f} s")
    return " · ".join(bits)


# -- Excel -----------------------------------------------------------------
def report_excel(cfg: AppConfig, filters: dict, path: str, log) -> tuple[str, str]:
    started = time.perf_counter()
    db = _connect(cfg)
    try:
        log("Reading the report from the database…")
        result = services.run_report(db, **filters)
        rows = result.get("rows") or []
        log(f"{len(rows):,} rows read. Building the workbook…")
        excelio.export_report(path, result.get("title") or "Report",
                              result.get("headers") or [], rows,
                              result.get("footer"), result.get("money_cols"))
        return _summary("Excel saved", path, len(rows),
                        time.perf_counter() - started), str(path)
    finally:
        db.close()


def database_excel(cfg: AppConfig, db_label: str, path: str, log) -> tuple[str, str]:
    started = time.perf_counter()
    db = _connect(cfg)
    try:
        log("Reading every table…")
        datasets = services.export_datasets(db)
        total = sum(len(rows) for _headers, rows in datasets.values())
        log(f"{len(datasets)} sheets, {total:,} rows. Building the workbook…")
        excelio.export_workbook(path, datasets, {
            "Generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Database": db_label,
            "Sheets": ", ".join(datasets.keys()),
            "Note": "Passwords are not exported (shown as 'encrypted').",
        })
        return _summary("Database backup saved", path, total,
                        time.perf_counter() - started), str(path)
    finally:
        db.close()


# -- PDF -------------------------------------------------------------------
def _render_report_pdf(cfg: AppConfig, title: str, headers: list[str], rows: list[list],
                       footer: dict | None, subtitle: str, company: dict, font_pt: float,
                       money_cols, path: str, log, started: float) -> tuple[str, str]:
    log(f"{len(rows):,} rows ready. Building the PDF…")
    html = printing.report_html(title, headers, rows, footer, company, subtitle,
                                font_pt, money_cols)
    log("Rendering pages…")
    ok, message = printing.pdf_from_html(html, path, paper=cfg.paper,
                                         document_name=title or "Report")
    if not ok:
        raise RuntimeError(message)
    return _summary("PDF saved", path, len(rows),
                    time.perf_counter() - started), str(path)


def report_pdf(cfg: AppConfig, filters: dict, subtitle: str, company: dict,
               font_pt: float, path: str, log) -> tuple[str, str]:
    started = time.perf_counter()
    db = _connect(cfg)
    try:
        log("Reading the report from the database…")
        result = services.run_report(db, **filters)
        rows = result.get("rows") or []
        log(f"{len(rows):,} rows read.")
        return _render_report_pdf(
            cfg, result.get("title") or "Report", result.get("headers") or [],
            result.get("rows") or [], result.get("footer"), subtitle, company,
            font_pt, result.get("money_cols"), path, log, started)
    finally:
        db.close()


def report_pdf_rows(cfg: AppConfig, title: str, headers: list[str], rows: list[list],
                    footer: dict | None, subtitle: str, company: dict, font_pt: float,
                    money_cols, path: str, log) -> tuple[str, str]:
    return _render_report_pdf(cfg, title, headers, rows, footer, subtitle, company,
                              font_pt, money_cols, path, log, time.perf_counter())


def bill_pdf(cfg: AppConfig, bill_no: int, company: dict, font_pt: float,
             copy_label: str, path: str, log) -> tuple[str, str]:
    started = time.perf_counter()
    db = _connect(cfg)
    try:
        log(f"Reading bill {bill_no}…")
        data = services.bill_detail(db, bill_no)
        consumer = data.get("consumer") or {}
        payload = dict(data)
        payload["rate"] = consumer.get("rate")
        html = printing.bill_html(payload, company, font_pt, copy_label)
        log("Rendering the PDF…")
        ok, message = printing.pdf_from_html(html, path, paper=cfg.paper,
                                             document_name=f"Bill {bill_no}")
        if not ok:
            raise RuntimeError(message)
        return _summary("Bill PDF saved", path, None,
                        time.perf_counter() - started), str(path)
    finally:
        db.close()


def statement_pdf(cfg: AppConfig, con_id: int, company: dict, font_pt: float,
                  path: str, log) -> tuple[str, str]:
    started = time.perf_counter()
    db = _connect(cfg)
    try:
        log(f"Reading the account {con_id} statement…")
        consumer = services.get_consumer(db, con_id)
        if not consumer:
            raise ValueError("Consumer not found.")
        bills = services.consumer_bills(db, con_id)
        payments = services.consumer_payments(db, con_id)
        readings = services.readings(db, con_id, 30)
        log(f"{len(bills)} bills, {len(payments)} payments, {len(readings)} readings. "
            "Building the PDF…")
        html = printing.statement_html(consumer, bills, payments, readings, company, font_pt)
        ok, message = printing.pdf_from_html(html, path, paper="A4",
                                             document_name=f"Statement {con_id}")
        if not ok:
            raise RuntimeError(message)
        return _summary("Statement PDF saved", path, len(bills),
                        time.perf_counter() - started), str(path)
    finally:
        db.close()
