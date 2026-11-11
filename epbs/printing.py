"""Ink-saving HTML documents + direct printing / PDF output via Qt."""
from __future__ import annotations

import html as _html
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF, Qt, QUrl
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
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


def _logo_url(path: str | None) -> str:
    """Document logo: the configured file, else ``static/images/company_logo.jpg``."""
    p = resolve_logo(path, print_ready=True)
    if not p:
        return ""
    return QUrl.fromLocalFile(str(p.resolve())).toString()


_CSS = """
body { font-family: 'Segoe UI','DejaVu Sans',Arial,sans-serif; color:#000; background:#fff;
       margin:0; padding:0; }
p, div, td, th, span { color:#000; }
.title { font-size:%(h1).1fpt; font-weight:bold; text-align:center; margin:0 0 1pt 0; }
.sub { font-size:%(small).1fpt; text-align:center; margin:0 0 2pt 0; }
h4 { font-size:%(h2).1fpt; margin:4pt 0 2pt 0; font-weight:bold; border-bottom:0.6pt solid #000;
     padding-bottom:1pt; }
table { border-collapse:collapse; width:100%%; }
table.grid td, table.grid th { border:0.6pt solid #000; padding:1.2pt 3pt; font-size:%(body).1fpt;
     vertical-align:top; }
table.grid th { font-weight:bold; text-align:left; background:none; }
table.plain td { padding:0.8pt 2pt; font-size:%(body).1fpt; vertical-align:top; }
table.plain td.k { font-weight:bold; white-space:nowrap; }
table.tot td { padding:1pt 3pt; font-size:%(body).1fpt; }
table.tot td.k { font-weight:bold; text-align:right; }
.right { text-align:right; }
.center { text-align:center; }
.mono { font-family:'Consolas','DejaVu Sans Mono',monospace; }
.small { font-size:%(small).1fpt; }
.line { border-top:0.6pt solid #000; margin:4pt 0; }
.footer { font-size:%(small).1fpt; margin-top:3pt; }
"""


def _css(font_pt: float) -> str:
    return _CSS % {"body": font_pt, "small": max(5.5, font_pt - 1),
                   "h1": font_pt + 3, "h2": font_pt + 0.5}


def _company_header(company: dict, title: str, subtitle: str, font_pt: float, logo: bool = True) -> str:
    logo_html = ""
    url = _logo_url(company.get("logo_url"))
    if logo and url:
        logo_html = (f'<img src="{esc(url)}" height="42" border="0" '
                     f'style="float:left;margin-right:6pt">')
    addr = " · ".join(x for x in [
        company.get("company_address"), company.get("contact_no"),
        company.get("email"), company.get("website")] if x)
    return f"""
    <div>{logo_html}
      <div class="title">{esc(company.get('company_name') or 'EPBS')}</div>
      <div class="sub">{esc(addr)}</div>
      <div class="sub"><b>{esc(title)}</b></div>
      {f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ''}
    </div>"""


def bill_html(data: dict, company: dict, font_pt: float = 8.0, copy_label: str = "") -> str:
    bill = data["bill"]
    c = data.get("consumer") or {}
    readings = data.get("readings") or []
    details = data.get("details") or []
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

    return f"""<html><head><meta charset="utf-8"><style>{_css(font_pt)}</style></head><body>
    {_company_header(company, 'ELECTRICITY BILL', f'Bill No: {bill.get("bill_no")}', font_pt)}
    <div class="small center">{esc(label)} · Issued {esc(fmt_date(bill.get('issue_date')))}</div>
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
          <th>Units used</th><th>Rate</th></tr>
      <tr><td>{esc(fmt_date(r.get('previous_date')))}</td><td class="right">{esc(prev_unit if prev_unit is not None else '')}</td>
          <td>{esc(fmt_date(r.get('present_date')))}</td><td class="right">{esc(pres_unit if pres_unit is not None else '')}</td>
          <td class="right"><b>{units}</b></td><td class="right">{esc(money(rate))}</td></tr>
    </table>
    <h4>Charges</h4>
    <table class="tot" width="100%" cellspacing="0" cellpadding="1">
      <tr><td width="55%"></td><td class="k" width="25%">Meter rent</td><td class="right" width="20%">{esc(money(bill.get('meter_rent')))}</td></tr>
      <tr><td></td><td class="k">Units used × rate ({units} × {esc(money(rate))})</td><td class="right">{esc(money(bill.get('bill_amount')))}</td></tr>
      <tr><td></td><td class="k">Previous due</td><td class="right">{esc(money(bill.get('due')))}</td></tr>
      <tr><td></td><td class="k"><b>TOTAL PAYABLE</b></td>
          <td class="right"><b>{esc(money(bill.get('total_amount')))}</b></td></tr>
    </table>
    <div class="footer">
      {f'<div>Bill lines: {esc(detail_line)}</div>' if detail_line else ''}
      <div>Please pay on or before <b>{esc(fmt_date(bill.get('last_date')))}</b>.
           Printed: {esc(datetime.now().strftime('%d-%b-%Y %H:%M'))}</div>
      <div style="margin-top:10pt">Authorised signature ______________________</div>
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
