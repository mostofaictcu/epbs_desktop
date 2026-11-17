"""Ink-saving HTML documents + direct printing / PDF output via Qt."""
from __future__ import annotations

import hashlib
import html as _html
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPen, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QApplication

from .config import resolve_logo

MONEY = "{:,.2f}"


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


def esc(value) -> str:
    return _html.escape(str(value if value is not None else ""))


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


def _signature(label: str = "Authorised signature") -> str:
    """Dashed signature line: label length + 3 dashes, as requested."""
    return (f'<div class="sig"><div>{"-" * (len(label) + 3)}</div>'
            f'<div class="small">{esc(label)}</div></div>')


_CSS = """
body { font-family: 'Segoe UI','DejaVu Sans',Arial,sans-serif; color:#000; background:#fff;
       margin:0; padding:0; }
p, div, td, th, span { color:#000; }
.title { font-size:%(h1).1fpt; font-weight:bold; text-align:center; margin:0; }
.sub { font-size:%(small).1fpt; text-align:center; margin:0; }
h4 { font-size:%(h2).1fpt; margin:2pt 0 0.5pt 0; font-weight:bold; }
table { border-collapse:collapse; width:100%%; }
table.grid td, table.grid th { border:1px dashed #000; padding:0.7pt 2.5pt;
     font-size:%(body).1fpt; vertical-align:top; }
table.grid th { font-weight:bold; text-align:left; background:none; }
table.plain td { padding:0.6pt 2pt; font-size:%(body).1fpt; vertical-align:top; }
table.plain td.k { font-weight:bold; white-space:nowrap; }
table.tot td { padding:0.8pt 3pt; font-size:%(body).1fpt; }
table.tot td.k { font-weight:bold; text-align:right; }
.right { text-align:right; }
.center { text-align:center; }
.mono { font-family:'Consolas','DejaVu Sans Mono',monospace; }
.small { font-size:%(small).1fpt; }
.sig { text-align:right; margin:0; line-height:1.1; }
.footer { font-size:%(small).1fpt; margin-top:2pt; }
"""


def _css(font_pt: float) -> str:
    return _CSS % {"body": font_pt, "small": max(5.5, font_pt - 1),
                   "h1": font_pt + 3, "h2": font_pt + 0.5}


def _company_header(company: dict, title: str, subtitle: str, font_pt: float, logo: bool = True) -> str:
    url = _logo_url(company.get("logo_url")) if logo else ""
    img = (f'<div class="center"><img src="{esc(url)}" height="60" border="0" '
           f'style="margin:2pt 0"></div>' if url else "")
    addr = " · ".join(x for x in [
        company.get("company_address"), company.get("contact_no"),
        company.get("email"), company.get("website")] if x)
    return f"""
    <div class="title">{esc(company.get('company_name') or 'EPBS')}</div>
    <div class="sub">{esc(addr)}</div>
    {img}
    <div class="sub"><b>{esc(title)}</b></div>
    {f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ''}"""


def _bill_font(font_pt: float) -> float:
    """Bills are half-page documents: half a point smaller saves height and ink."""
    return max(6.0, float(font_pt) - 0.5)


def bill_html(data: dict, company: dict, font_pt: float = 8.0, copy_label: str = "") -> str:
    font_pt = _bill_font(font_pt)
    bill = data["bill"]
    c = data.get("consumer") or {}
    readings = data.get("readings") or []
    details = data.get("details") or []
    slabs = data.get("slabs") or []
    readings = readings[:1] or [{}]
    r = readings[0]
    prev_unit = r.get("previous_unit")
    pres_unit = r.get("present_unit")
    units = (int(pres_unit) - int(prev_unit)) if prev_unit is not None and pres_unit is not None else 0
    rate = data.get("rate", 0)
    if r.get("rate_applied") is not None:
        rate = r["rate_applied"]

    label = copy_label or ("Office copy" if not bill.get("print_count") else "Consumer copy")
    detail_line = "; ".join(
        f"{d.get('bill_month') or ''} ({d.get('bill_details') or ''})" for d in details if d.get("bill_month")
    )
    slab_rows = "".join(
        f"<tr><td>{esc(s.get('slab_no'))}</td>"
        f"<td class='right'>{esc(_slab_range(s))}</td>"
        f"<td class='right'>{esc(s.get('units'))}</td>"
        f"<td class='right'>{esc(money(s.get('rate')))}</td>"
        f"<td class='right'>{esc(money(s.get('amount')))}</td></tr>"
        for s in slabs
    )
    slab_table = ""
    if slabs:
        slab_table = f"""
    <h4>Slab calculation</h4>
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2">
      <tr><th>Slab</th><th>Range (units)</th><th>Units</th><th>Rate</th><th>Amount</th></tr>
      {slab_rows}
    </table>"""

    return f"""<html><head><meta charset="utf-8"><style>{_css(font_pt)}</style></head><body>
    {_company_header(company, 'ELECTRICITY BILL',
                     f'Bill No: {bill.get("bill_no")} · {label} · '
                     f'Issued {fmt_date(bill.get("issue_date"))}', font_pt)}
    <table class="plain" width="100%" cellspacing="0" cellpadding="2">
      <tr><td class="k" width="13%">Account</td><td width="37%">{esc(c.get('con_id') or bill.get('con_id'))}</td>
          <td class="k" width="13%">Bill date</td><td width="37%">{esc(fmt_date(bill.get('issue_date')))}</td></tr>
      <tr><td class="k">Name</td><td>{esc(c.get('con_name'))}</td>
          <td class="k">Last date</td><td>{esc(fmt_date(bill.get('last_date')))}</td></tr>
      <tr><td class="k">Meter no</td><td>{esc(bill.get('meter_no') or c.get('meter_no'))}</td>
          <td class="k">Status</td><td>{esc(bill.get('bill_status'))}</td></tr>
      <tr><td class="k">Type</td><td>{esc(c.get('type_name'))}</td>
          <td class="k">Area</td><td>{esc(c.get('area_details'))}</td></tr>
      <tr><td class="k">Address</td><td colspan="3">{esc(c.get('con_address'))}</td></tr>
    </table>
    <h4>Meter reading</h4>
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2">
      <tr><th>Previous date</th><th>Previous unit</th><th>Present date</th><th>Present unit</th>
          <th>Units used</th><th>{'Average rate' if slabs else 'Rate'}</th></tr>
      <tr><td>{esc(fmt_date(r.get('previous_date')))}</td><td class="right">{esc(prev_unit if prev_unit is not None else '')}</td>
          <td>{esc(fmt_date(r.get('present_date')))}</td><td class="right">{esc(pres_unit if pres_unit is not None else '')}</td>
          <td class="right"><b>{units}</b></td><td class="right">{esc(money(rate))}</td></tr>
    </table>
    {slab_table}
    <h4>Charges</h4>
    <table class="tot" width="100%" cellspacing="0" cellpadding="1">
      <tr><td width="55%"></td><td class="k" width="25%">Meter rent</td><td class="right" width="20%">{esc(money(bill.get('meter_rent')))}</td></tr>
      <tr><td></td><td class="k">{'Slab amount (' + str(units) + ' units)' if slabs else 'Units used × rate (' + str(units) + ' × ' + esc(money(rate)) + ')'}</td><td class="right">{esc(money(bill.get('bill_amount')))}</td></tr>
      <tr><td></td><td class="k">Previous due</td><td class="right">{esc(money(bill.get('due')))}</td></tr>
      <tr><td></td><td class="k"><b>TOTAL PAYABLE</b></td>
          <td class="right"><b>{esc(money(bill.get('total_amount')))}</b></td></tr>
    </table>
    <div class="footer">
      {f'<div>Bill lines: {esc(detail_line)}</div>' if detail_line else ''}
      <table width="100%" cellspacing="0" cellpadding="0"><tr>
        <td width="62%" valign="bottom">Please pay on or before
            <b>{esc(fmt_date(bill.get('last_date')))}</b>.
            Printed: {esc(datetime.now().strftime('%d-%b-%Y %H:%M'))}</td>
        <td width="38%" valign="bottom">{_signature()}</td>
      </tr></table>
    </div>
    </body></html>"""


def statement_html(consumer: dict, bills: list[dict], payments: list[dict],
                   readings: list[dict], company: dict, font_pt: float = 8.0) -> str:
    rows = "".join(
        f"<tr><td>{esc(b.get('bill_no'))}</td><td>{esc(fmt_date(b.get('issue_date')))}</td>"
        f"<td>{esc(b.get('meter_no'))}</td><td class='right'>{esc(b.get('units') or 0)}</td>"
        f"<td class='right'>{esc(money(b.get('bill_amount')))}</td>"
        f"<td class='right'>{esc(money(b.get('due')))}</td>"
        f"<td class='right'>{esc(money(b.get('total_amount')))}</td>"
        f"<td>{esc(b.get('bill_status'))}</td></tr>" for b in bills)
    read_rows = "".join(
        f"<tr><td>{esc(fmt_date(r.get('previous_date')))}</td><td class='right'>{esc(r.get('previous_unit'))}</td>"
        f"<td>{esc(fmt_date(r.get('present_date')))}</td><td class='right'>{esc(r.get('present_unit'))}</td>"
        f"<td class='right'>{esc(r.get('units'))}</td></tr>" for r in readings)
    total_due = sum(float(b.get("total_amount") or 0) for b in bills if b.get("bill_status") == "Unpaid")
    return f"""<html><head><meta charset="utf-8"><style>{_css(font_pt)}</style></head><body>
    {_company_header(company, 'CONSUMER STATEMENT', '', font_pt)}
    <table class="plain" width="100%" cellspacing="0" cellpadding="2">
      <tr><td class="k" width="14%">Account</td><td width="36%">{esc(consumer.get('con_id'))}</td>
          <td class="k" width="14%">Name</td><td width="36%">{esc(consumer.get('con_name'))}</td></tr>
      <tr><td class="k">Meter no</td><td>{esc(consumer.get('meter_no'))}</td>
          <td class="k">Type / rate</td><td>{esc(consumer.get('type_name'))} / {esc(money(consumer.get('rate')))}</td></tr>
      <tr><td class="k">Address</td><td colspan="3">{esc(consumer.get('con_address'))}</td></tr>
    </table>
    <h4>Bills</h4>
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2"><tr><th>Bill No</th><th>Date</th><th>Meter</th><th>Units</th>
      <th>Bill</th><th>Due</th><th>Total</th><th>Status</th></tr>{rows or '<tr><td colspan="8">No bills.</td></tr>'}</table>
    <table class="tot" width="100%" cellspacing="0" cellpadding="0"><tr><td class="k">Outstanding total</td>
      <td class="right"><b>{esc(money(total_due))}</b></td></tr></table>
    <h4>Recent meter readings</h4>
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2"><tr><th>Previous date</th><th>Prev unit</th><th>Present date</th>
      <th>Present unit</th><th>Units</th></tr>{read_rows or '<tr><td colspan="5">No readings.</td></tr>'}</table>
    <h4>Recent payments</h4>
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2"><tr><th>Payment</th><th>Date</th><th>Bill No</th><th>Amount</th></tr>
    {''.join(f"<tr><td>{esc(p.get('payment_id'))}</td><td>{esc(fmt_date(p.get('paid_date')))}</td>"
             f"<td>{esc(p.get('bill_no'))}</td><td class='right'>{esc(money(p.get('bill_amount')))}</td></tr>" for p in payments)
     or '<tr><td colspan="4">No payments.</td></tr>'}</table>
    <div class="footer">Printed: {esc(datetime.now().strftime('%d-%b-%Y %H:%M'))}</div>
    </body></html>"""


def report_html(title: str, headers: list[str], rows: list[list], footer: dict | None,
                company: dict, subtitle: str = "", font_pt: float = 8.0,
                money_cols: list[int] | None = None) -> str:
    money_cols = money_cols or []
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for i, value in enumerate(row):
            if i in money_cols:
                cells.append(f"<td class='right'>{esc(money(value))}</td>")
            elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                cells.append(f"<td class='right'>{esc(value)}</td>")
            else:
                cells.append(f"<td>{esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    foot = ""
    if footer:
        parts = []
        for k, v in footer.items():
            if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                text = money(v) if any(w in k.lower() for w in
                                       ("total", "amount", "collected", "billed", "due")) else f"{int(v):,}"
            else:
                text = str(v)
            parts.append(f"<tr><td class='k'>{esc(k)}</td><td class='right'>{esc(text)}</td></tr>")
        foot = "".join(parts)
    return f"""<html><head><meta charset="utf-8"><style>{_css(font_pt)}</style></head><body>
    {_company_header(company, title, subtitle, font_pt)}
    <table class="grid" width="100%" border="1" cellspacing="0" cellpadding="2"><tr>{head}</tr>{''.join(body) or '<tr><td colspan="%d">No data.</td></tr>' % len(headers)}</table>
    {f'<table class="tot" width="45%" align="right" cellspacing="0" cellpadding="0">{foot}</table>' if foot else ''}
    <div class="footer">Rows: {len(rows)} · Printed: {esc(datetime.now().strftime('%d-%b-%Y %H:%M'))}</div>
    </body></html>"""


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
