"""High-level document actions shared by the screens."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from .. import printing, services
from .common import error, info

DOWNLOADS = Path.home() / "Documents"


def _default_dir(name: str) -> str:
    folder = DOWNLOADS if DOWNLOADS.exists() else Path.home()
    return str(folder / name)


def _pdf_path(parent, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, "Save PDF", _default_dir(suggested), "PDF files (*.pdf)")
    if not path:
        return None
    return path if path.lower().endswith(".pdf") else path + ".pdf"


def print_bill(ctx, bill_no: int, parent=None, as_pdf: bool = False, mark: bool = True) -> bool:
    try:
        data = services.bill_detail(ctx.db, bill_no)
    except Exception as exc:
        error(parent, str(exc))
        return False
    consumer = data.get("consumer") or {}
    payload = dict(data)
    payload["rate"] = consumer.get("rate")
    html = printing.bill_html(payload, ctx.company(), ctx.cfg.font_pt, ctx.cfg.bill_copy_label)
    pdf = _pdf_path(parent, f"bill_{bill_no}.pdf") if as_pdf else None
    if as_pdf and not pdf:
        return False
    ok, message = printing.print_document(
        html, paper=ctx.cfg.paper, printer_name=ctx.cfg.printer, pdf_path=pdf,
        show_dialog=ctx.cfg.show_print_dialog if not as_pdf else False,
        document_name=f"Bill {bill_no}",
    )
    if ok:
        if mark and not as_pdf:
            try:
                services.mark_printed(ctx.db, bill_no)
            except Exception:
                pass
        if as_pdf:
            info(parent, f"PDF saved:\n{pdf}")
    else:
        info(parent, message)
    return ok


def print_bills(ctx, bill_nos: list[int], parent=None) -> int:
    count = 0
    show = ctx.cfg.show_print_dialog
    ctx.cfg.show_print_dialog = False
    try:
        for bill_no in bill_nos:
            if print_bill(ctx, bill_no, parent, as_pdf=False, mark=True):
                count += 1
    finally:
        ctx.cfg.show_print_dialog = show
    info(parent, f"{count} bill(s) sent to the printer.")
    return count


def print_statement(ctx, con_id: int, parent=None, as_pdf: bool = False) -> bool:
    try:
        consumer = services.get_consumer(ctx.db, con_id)
        if not consumer:
            raise ValueError("Consumer not found.")
        bills = services.consumer_bills(ctx.db, con_id)
        payments = services.consumer_payments(ctx.db, con_id)
        readings = services.readings(ctx.db, con_id, 30)
    except Exception as exc:
        error(parent, str(exc))
        return False
    html = printing.statement_html(consumer, bills, payments, readings, ctx.company(), ctx.cfg.font_pt)
    pdf = _pdf_path(parent, f"statement_{con_id}.pdf") if as_pdf else None
    if as_pdf and not pdf:
        return False
    ok, message = printing.print_document(
        html, paper="A4", printer_name=ctx.cfg.printer, pdf_path=pdf,
        show_dialog=ctx.cfg.show_print_dialog if not as_pdf else False,
        document_name=f"Statement {con_id}",
    )
    if ok and as_pdf:
        info(parent, f"PDF saved:\n{pdf}")
    elif not ok:
        info(parent, message)
    return ok


def print_report(ctx, title: str, headers: list[str], rows: list[list], footer: dict | None,
                 subtitle: str = "", money_cols: list[int] | None = None,
                 parent=None, as_pdf: bool = False) -> bool:
    html = printing.report_html(title, headers, rows, footer, ctx.company(), subtitle,
                                ctx.cfg.font_pt, money_cols)
    pdf = _pdf_path(parent, f"{_slug(title)}_{datetime.now():%Y%m%d_%H%M}.pdf") if as_pdf else None
    if as_pdf and not pdf:
        return False
    ok, message = printing.print_document(
        html, paper="A4", printer_name=ctx.cfg.printer, pdf_path=pdf,
        show_dialog=ctx.cfg.show_print_dialog if not as_pdf else False,
        document_name=title,
    )
    if ok and as_pdf:
        info(parent, f"PDF saved:\n{pdf}")
    elif not ok:
        info(parent, message)
    return ok


def _slug(text: str) -> str:
    keep = [ch if ch.isalnum() else "_" for ch in (text or "report").lower()]
    slug = "".join(keep).strip("_")
    return slug[:50] or "report"
