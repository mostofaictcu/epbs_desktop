"""Ink-saving HTML documents + direct printing / PDF output via Qt.

Document markup lives in ``epbs/templates`` (Jinja2) so bills, statements and
reports can be redesigned without touching Python.  The public builders keep
their original signatures and return the same final HTML string.
"""
from __future__ import annotations

import hashlib
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPen, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QApplication

from .config import resolve_logo

MONEY = "{:,.2f}"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def money(value) -> str:
    try:
        return MONEY.format(Decimal(str(value or 0)))
    except Exception:
        return "0.00"


def fmt_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d-%b-%Y")
    return str(value)


def _slab_range(slab: dict) -> str:
    end = slab.get("to_unit")
    return f"{slab.get('from_unit')}-{end if end else 'No limit'}"


def _logo_url(path: str | None) -> str:
    """Document logo: the configured file, else ``static/images/company_logo.jpg``.

    The printed copy is converted to a light grey so dark logos use much less
    ink; the result is cached in the temporary folder until the source changes.
    """
    p = resolve_logo(path, print_ready=True)
    if not p:
        return ""
    src = p.resolve()
    try:
        stat = src.stat()
        key = hashlib.sha1(
            f"{src}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
    except OSError:
        key = hashlib.sha1(str(src).encode()).hexdigest()[:16]
    out = Path(tempfile.gettempdir()) / f"epbs_print_logo_{key}.png"
    if not out.is_file():
        img = QImage(str(src))
        if img.isNull():
            return QUrl.fromLocalFile(str(src)).toString()
        if img.height() > 160:
            img = img.scaledToHeight(160, Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_Grayscale8)
        # Black -> ~50% grey; grey/white detail stays readable.
        lut = bytes(int(255 - (255 - v) * 0.5) for v in range(256))
        width, height, stride = img.width(), img.height(), img.bytesPerLine()
        raw = bytes(img.bits())
        light = bytearray(raw)
        for y in range(height):
            base = y * stride
            for x in range(width):
                light[base + x] = lut[raw[base + x]]
        light_img = QImage(bytes(light), width, height, stride,
                           QImage.Format.Format_Grayscale8).copy()
        try:
            if not light_img.save(str(out), "PNG"):
                return QUrl.fromLocalFile(str(src)).toString()
        except Exception:
            return QUrl.fromLocalFile(str(src)).toString()
    return QUrl.fromLocalFile(str(out)).toString()


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    finalize=lambda value: "" if value is None else value,
    keep_trailing_newline=True,
)
_env.filters["money"] = money
_env.filters["date"] = fmt_date
_env.filters["slab_range"] = _slab_range


def _company_context(company: dict | None) -> dict:
    """Normalise the company dict consumed by ``_header.html``."""
    company = company or {}
    address = " · ".join(
        str(part) for part in (
            company.get("company_address"),
            company.get("contact_no"),
            company.get("email"),
            company.get("website"),
        ) if part
    )
    return {
        "name": company.get("company_name") or "EPBS",
        "address": address,
        "logo_url": _logo_url(company.get("logo_url")),
    }


def _style(font_pt: float) -> str:
    """Render the shared print stylesheet with the document font sizes."""
    font_pt = float(font_pt)
    return _env.get_template("style.css").render(
        body=f"{font_pt:.1f}",
        small=f"{max(5.5, font_pt - 1):.1f}",
        h1=f"{font_pt + 3:.1f}",
        h2=f"{font_pt + 0.5:.1f}",
    )


def _render(template: str, font_pt: float, **context) -> str:
    """Render one document template with the shared stylesheet injected."""
    context.setdefault("style", _style(font_pt))
    return _env.get_template(template).render(**context)


def _now() -> str:
    return datetime.now().strftime("%d-%b-%Y %H:%M")


def _bill_font(font_pt: float) -> float:
    """Bills are half-page documents: half a point smaller saves height and ink."""
    return max(6.0, float(font_pt) - 0.5)


def bill_html(data: dict, company: dict, font_pt: float = 8.0, copy_label: str = "") -> str:
    font_pt = _bill_font(font_pt)
    bill = data["bill"]
    consumer = data.get("consumer") or {}
    details = data.get("details") or []
    slabs = data.get("slabs") or []
    reading = (data.get("readings") or [{}])[0] or {}
    previous_unit = reading.get("previous_unit")
    present_unit = reading.get("present_unit")
    if previous_unit is not None and present_unit is not None:
        units = int(present_unit) - int(previous_unit)
    else:
        units = 0
    rate = data.get("rate", 0)
    if reading.get("rate_applied") is not None:
        rate = reading["rate_applied"]

    label = copy_label or ("Office copy" if not bill.get("print_count") else "Consumer copy")
    minimum_applied = bool(bill.get("minimum_charge"))
    detail_line = "; ".join(
        f"{d.get('bill_month') or ''} ({d.get('bill_details') or ''})"
        for d in details if d.get("bill_month")
    )
    return _render(
        "bill.html", font_pt,
        company=_company_context(company),
        title="ELECTRICITY BILL",
        subtitle=(f"Bill No: {bill.get('bill_no')} · {label} · "
                  f"Issued {fmt_date(bill.get('issue_date'))}"),
        bill=bill,
        consumer=consumer,
        reading=reading,
        slabs=slabs,
        units=units,
        rate=rate,
        detail_line=detail_line,
        minimum_applied=minimum_applied,
        previous_unit="" if previous_unit is None else previous_unit,
        present_unit="" if present_unit is None else present_unit,
        signature_dashes="-" * (len("Authorised signature") + 3),
        signature_label="Authorised signature",
        printed_at=_now(),
    )


def statement_html(consumer: dict, bills: list[dict], payments: list[dict],
                   readings: list[dict], company: dict, font_pt: float = 8.0) -> str:
    total_due = sum(float(b.get("total_amount") or 0) for b in bills
                    if b.get("bill_status") == "Unpaid")
    return _render(
        "statement.html", font_pt,
        company=_company_context(company),
        title="CONSUMER STATEMENT",
        subtitle="",
        consumer=consumer or {},
        bills=bills or [],
        payments=payments or [],
        readings=readings or [],
        total_due=total_due,
        printed_at=_now(),
    )


def report_html(title: str, headers: list[str], rows: list[list], footer: dict | None,
                company: dict, subtitle: str = "", font_pt: float = 8.0,
                money_cols: list[int] | None = None) -> str:
    footer_rows: list[tuple[str, str]] = []
    for key, value in (footer or {}).items():
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            if any(word in key.lower() for word in
                   ("total", "amount", "collected", "billed", "due")):
                text = money(value)
            else:
                text = f"{int(value):,}"
        else:
            text = str(value)
        footer_rows.append((key, text))
    return _render(
        "report.html", font_pt,
        company=_company_context(company),
        title=title,
        subtitle=subtitle,
        headers=headers or [],
        rows=rows or [],
        money_cols=set(money_cols or []),
        footer_rows=footer_rows,
        printed_at=_now(),
    )


def _page_size(paper: str) -> QPageSize:
    if paper == "A5":
        return QPageSize(QPageSize.PageSizeId.A5)
    if paper == "Letter":
        return QPageSize(QPageSize.PageSizeId.Letter)
    if paper == "Receipt 80mm":
        return QPageSize(QSizeF(80, 297), QPageSize.Unit.Millimeter, "80mm receipt")
    return QPageSize(QPageSize.PageSizeId.A4)


def pdf_from_html(html_text: str, path: str | Path, *, paper: str = "A4",
                   document_name: str = "EPBS document") -> tuple[bool, str]:
    """Render ``html_text`` to a PDF file.

    Unlike :func:`print_document` this uses no dialog and no cursor, so it can
    run in a worker thread and keep the window responsive.
    """
    if not QApplication.instance():
        return False, "Qt application is not running."

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(document_name)
    printer.setFullPage(False)
    printer.setPageSize(_page_size(paper))
    printer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(QFont("Segoe UI", max(6, int(round(8)))))
    doc.setHtml(html_text)
    doc.setPageSize(QSizeF(printer.pageRect(QPrinter.Unit.Point).size()))
    doc.print_(printer)

    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False, f"PDF was not created: {p}"
    return True, str(p)


def print_document(html_text: str, *, paper: str = "A4", printer_name: str = "",
                   pdf_path: str | Path | None = None, show_dialog: bool = False,
                   document_name: str = "EPBS document") -> tuple[bool, str]:
    """Render ``html_text`` and print it or write a PDF.

    Returns ``(ok, message)``.  When printing directly, the configured
    printer is used (or the system default when none is configured).
    """
    if not QApplication.instance():
        return False, "Qt application is not running."

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(document_name)
    printer.setFullPage(False)
    printer.setPageSize(_page_size(paper))
    printer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)

    if pdf_path:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
    else:
        available = {p.printerName() for p in QPrinterInfo.availablePrinters()}
        if printer_name and printer_name in available:
            printer.setPrinterName(printer_name)
        elif QPrinterInfo.defaultPrinter().isNull():
            return False, "No printer is installed on this computer."
        if show_dialog:
            dialog = QPrintDialog(printer)
            dialog.setWindowTitle("Print")
            if not dialog.exec():
                return False, "Printing cancelled."

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(QFont("Segoe UI", max(6, int(round(8)))))
    doc.setHtml(html_text)
    doc.setPageSize(QSizeF(printer.pageRect(QPrinter.Unit.Point).size()))
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        doc.print_(printer)
    except Exception as exc:
        return False, str(exc)
    finally:
        QApplication.restoreOverrideCursor()

    if pdf_path:
        p = Path(pdf_path)
        if not p.exists() or p.stat().st_size == 0:
            return False, f"PDF was not created: {p}"
        return True, str(p)
    return True, "Sent to printer"


def _paint_2up(printer: QPrinter, html_texts: list[str]) -> None:
    """Draw two half-page documents plus a labelled cut line on each sheet."""
    page = printer.pageRect(QPrinter.Unit.Point)
    full_w, full_h = page.width(), page.height()
    margin = 8 / 25.4 * 72.0            # 8 mm content margin
    content_w = full_w - 2 * margin
    content_h = full_h - 2 * margin
    gap = 16.0
    half = (content_h - gap) / 2.0
    # QPrinter in HighResolution mode paints in device pixels; documents are
    # laid out in points, so scale the painter to 72 dpi logical units.
    dpi_scale = printer.logicalDpiX() / 72.0

    painter = QPainter(printer)
    try:
        for start in range(0, len(html_texts), 2):
            if start:
                printer.newPage()
            painter.save()
            painter.scale(dpi_scale, dpi_scale)
            pair = html_texts[start:start + 2]
            docs = []
            for html in pair:
                doc = QTextDocument()
                doc.setDocumentMargin(0)
                doc.setDefaultFont(QFont("Segoe UI", max(6, int(round(8)))))
                doc.setHtml(html)
                doc.setPageSize(QSizeF(content_w, half))
                docs.append((doc, doc.size().height()))

            # One scale for the whole sheet so both bills look identical.
            tallest = max((doc_h for _doc, doc_h in docs), default=half)
            fit = min(1.0, half / tallest) if tallest > 0 else 1.0
            for slot, (doc, doc_h) in enumerate(docs):
                top = margin + slot * (half + gap)
                painter.save()
                painter.setClipRect(QRectF(margin, top, content_w, half))
                painter.translate(margin, top)
                if fit < 1.0:
                    painter.scale(fit, fit)
                    painter.translate((content_w / fit - content_w) / 2, 0)
                doc.drawContents(painter, QRectF(0, 0, content_w, doc_h))
                painter.restore()

            # Dashed cut line (paper edge to paper edge) with a clear label.
            y = margin + half + gap / 2.0
            painter.setPen(QPen(QColor("#000000"), 0.7, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(0, y), QPointF(full_w, y))
            cut_font = QFont("Segoe UI")
            cut_font.setPixelSize(8)
            painter.setFont(cut_font)
            metrics = painter.fontMetrics()
            text = "CUT HERE"
            box = QRectF((full_w - metrics.horizontalAdvance(text)) / 2.0 - 5,
                         y - metrics.height() / 2.0 - 1,
                         metrics.horizontalAdvance(text) + 10,
                         metrics.height() + 2)
            painter.fillRect(box, QColor("#ffffff"))
            painter.setPen(QPen(QColor("#000000"), 0.7))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
    finally:
        painter.end()


def pdf_documents_2up(html_texts: list[str], path: str | Path, *,
                      document_name: str = "EPBS bills") -> tuple[bool, str]:
    """Write half-page documents to an A4 portrait PDF, two per sheet.

    Safe to call from a worker thread: no dialog and no cursor override.
    """
    if not QApplication.instance():
        return False, "Qt application is not running."
    if not html_texts:
        return False, "No documents to print."

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(document_name)
    printer.setFullPage(True)
    printer.setPageSize(_page_size("A4"))
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))

    try:
        _paint_2up(printer, html_texts)
    except Exception as exc:
        return False, str(exc)

    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False, f"PDF was not created: {p}"
    return True, str(p)


def print_documents_2up(html_texts: list[str], *, printer_name: str = "",
                        pdf_path: str | Path | None = None, show_dialog: bool = False,
                        document_name: str = "EPBS bills") -> tuple[bool, str]:
    """Print half-page documents two per A4 portrait sheet.

    Each document is drawn into one half of the printable A4 area, with a
    labelled dashed cut line between the halves.  An odd number of documents
    leaves the bottom half empty; it can still be cut and reused.
    """
    if not QApplication.instance():
        return False, "Qt application is not running."
    if not html_texts:
        return False, "No documents to print."

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(document_name)
    printer.setFullPage(True)
    printer.setPageSize(_page_size("A4"))

    if pdf_path:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
    else:
        available = {p.printerName() for p in QPrinterInfo.availablePrinters()}
        if printer_name and printer_name in available:
            printer.setPrinterName(printer_name)
        elif QPrinterInfo.defaultPrinter().isNull():
            return False, "No printer is installed on this computer."
        if show_dialog:
            dialog = QPrintDialog(printer)
            dialog.setWindowTitle("Print bill(s)")
            if not dialog.exec():
                return False, "Printing cancelled."

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        _paint_2up(printer, html_texts)
    except Exception as exc:
        return False, str(exc)
    finally:
        QApplication.restoreOverrideCursor()

    if pdf_path:
        p = Path(pdf_path)
        if not p.exists() or p.stat().st_size == 0:
            return False, f"PDF was not created: {p}"
        return True, str(p)
    return True, "Sent to printer"
