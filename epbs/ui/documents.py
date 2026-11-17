"""High-level document actions shared by the screens."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from .. import printing, services
from .common import error, info
from .export_jobs import bill_pdf, report_pdf_rows, statement_pdf

DOWNLOADS = Path.home() / "Documents"


def _default_dir(name: str) -> str:
    folder = DOWNLOADS if DOWNLOADS.exists() else Path.home()
    return str(folder / name)


def _pdf_path(parent, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, "Save PDF", _default_dir(suggested), "PDF files (*.pdf)")
    if not path:
        return None
    return path if path.lower().endswith(".pdf") else path + ".pdf"


def pdf_done(parent, title: str):
    """Return a job callback that confirms where the PDF was written."""

    def callback(ok: bool, summary: str, path: str) -> None:
        if ok:
            info(parent, f"{title} saved to:\n\n{path or summary}", "PDF saved")
        else:
            error(parent, f"{title} was not saved.\n\n{summary}", "PDF save failed")
    return callback


def print_bill(ctx, bill_no: int, parent=None, as_pdf: bool = False, mark: bool = True) -> bool:
    if as_pdf:
        pdf = _pdf_path(parent, f"bill_{bill_no}.pdf")
        if not pdf:
            return False
        ctx.jobs.submit(
            f"Bill {bill_no} PDF",
            lambda log: bill_pdf(ctx.cfg, bill_no, ctx.company(), ctx.cfg.font_pt,
                                 ctx.cfg.bill_copy_label, pdf, log),
            on_done=pdf_done(parent, f"Bill {bill_no} PDF"))
        return True
    try:
        data = services.bill_detail(ctx.db, bill_no)
    except Exception as exc:
        error(parent, str(exc))
        return False
    consumer = data.get("consumer") or {}
    payload = dict(data)
    payload["rate"] = consumer.get("rate")
    html = printing.bill_html(payload, ctx.company(), ctx.cfg.font_pt,
                              ctx.cfg.bill_copy_label)
    if ctx.cfg.paper == "Receipt 80mm":
        ok, message = printing.print_document(
            html, paper="Receipt 80mm", printer_name=ctx.cfg.printer,
            pdf_path=None, show_dialog=ctx.cfg.show_print_dialog,
            document_name=f"Bill {bill_no}",
        )
    else:
        ok, message = printing.print_documents_2up(
            [html], printer_name=ctx.cfg.printer, pdf_path=None,
            show_dialog=ctx.cfg.show_print_dialog,
            document_name=f"Bill {bill_no}",
        )
    if ok:
        if mark:
            try:
                services.mark_printed(ctx.db, bill_no)
            except Exception:
                pass
    else:
        info(parent, message)
    return ok


def print_bills(ctx, bill_nos: list[int], parent=None) -> int:
    """Print selected bills two per A4 portrait sheet (half-A4 layout)."""
    if not bill_nos:
        return 0
    payloads = []
    for bill_no in bill_nos:
        try:
            data = services.bill_detail(ctx.db, bill_no)
        except Exception as exc:
            error(parent, str(exc))
            return 0
        consumer = data.get("consumer") or {}
        payload = dict(data)
        payload["rate"] = consumer.get("rate")
        payloads.append(payload)

    if ctx.cfg.paper == "Receipt 80mm":
        count = 0
        for payload, bill_no in zip(payloads, bill_nos):
            html = printing.bill_html(payload, ctx.company(), ctx.cfg.font_pt,
                                      ctx.cfg.bill_copy_label)
            ok, message = printing.print_document(
                html, paper="Receipt 80mm", printer_name=ctx.cfg.printer,
                pdf_path=None, show_dialog=False,
                document_name=f"Bill {bill_no}",
            )
            if ok:
                count += 1
                try:
                    services.mark_printed(ctx.db, bill_no)
                except Exception:
                    pass
            else:
                info(parent, message)
        info(parent, f"{count} bill(s) sent to the printer.")
        return count

    htmls = [printing.bill_html(payload, ctx.company(), ctx.cfg.font_pt,
                                ctx.cfg.bill_copy_label) for payload in payloads]
    ok, message = printing.print_documents_2up(
        htmls, printer_name=ctx.cfg.printer, pdf_path=None,
        show_dialog=ctx.cfg.show_print_dialog,
        document_name=f"Bills ({len(htmls)})",
    )
    if not ok:
        info(parent, message)
        return 0
    for bill_no in bill_nos:
        try:
            services.mark_printed(ctx.db, bill_no)
        except Exception:
            pass
    info(parent, f"{len(htmls)} bill(s) sent to the printer "
                 f"({(len(htmls) + 1) // 2} A4 sheet(s), 2 per sheet).")
    return len(htmls)


def print_statement(ctx, con_id: int, parent=None, as_pdf: bool = False) -> bool:
    if as_pdf:
        pdf = _pdf_path(parent, f"statement_{con_id}.pdf")
        if not pdf:
            return False
        ctx.jobs.submit(
            f"Statement {con_id} PDF",
            lambda log: statement_pdf(ctx.cfg, con_id, ctx.company(), ctx.cfg.font_pt,
                                      pdf, log),
            on_done=pdf_done(parent, f"Statement {con_id} PDF"))
        return True
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
    ok, message = printing.print_document(
        html, paper="A4", printer_name=ctx.cfg.printer, pdf_path=None,
        show_dialog=ctx.cfg.show_print_dialog,
        document_name=f"Statement {con_id}",
    )
    if not ok:
        info(parent, message)
    return ok


def print_report(ctx, title: str, headers: list[str], rows: list[list], footer: dict | None,
                 subtitle: str = "", money_cols: list[int] | None = None,
                 parent=None, as_pdf: bool = False) -> bool:
    if as_pdf:
        pdf = _pdf_path(parent, f"{_slug(title)}_{datetime.now():%Y%m%d_%H%M}.pdf")
        if not pdf:
            return False
        ctx.jobs.submit(
            f"Report PDF — {title}",
            lambda log: report_pdf_rows(ctx.cfg, title, headers, rows, footer, subtitle,
                                        ctx.company(), ctx.cfg.font_pt, money_cols,
                                        pdf, log),
            on_done=pdf_done(parent, f"Report PDF — {title}"))
        return True
    html = printing.report_html(title, headers, rows, footer, ctx.company(), subtitle,
                                ctx.cfg.font_pt, money_cols)
    ok, message = printing.print_document(
        html, paper="A4", printer_name=ctx.cfg.printer, pdf_path=None,
        show_dialog=ctx.cfg.show_print_dialog,
        document_name=title,
    )
    if not ok:
        info(parent, message)
    return ok


def _slug(text: str) -> str:
    keep = [ch if ch.isalnum() else "_" for ch in (text or "report").lower()]
    slug = "".join(keep).strip("_")
    return slug[:50] or "report"
