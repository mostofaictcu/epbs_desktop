"""Excel export / import (openpyxl) - ink friendly, no coloured fills."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import services
from .db import Database

MONEY_FMT = "#,##0.00"
INT_FMT = "#,##0"
THIN = Side(style="thin", color="000000")
BORDER = Border(bottom=THIN)


def _write_sheet(ws, headers: list[str], rows: list[list], money_cols: set[int] | None = None,
                 max_width: int = 42) -> None:
    money_cols = money_cols or set()
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.border = BORDER
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append(row)
    widths = {}
    for idx, header in enumerate(headers, start=1):
        values = [header] + [str(r[idx - 1]) for r in rows[:300] if len(r) >= idx and r[idx - 1] is not None]
        widths[idx] = min(max_width, max(8, min(36, max(len(v) for v in values) + 2)))
        ws.column_dimensions[get_column_letter(idx)].width = widths[idx]
        if (idx - 1) in money_cols:
            for cell in ws[get_column_letter(idx)][1:]:
                cell.number_format = MONEY_FMT
    ws.freeze_panes = "A2"
    if headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, ws.max_row)}"


def export_workbook(path: str | Path, datasets: dict[str, tuple[list[str], list[list]]],
                    meta: dict | None = None) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    info = wb.create_sheet("Info")
    info["A1"] = "EPBS Desktop - Excel export"
    info["A1"].font = Font(bold=True, size=14)
    row = 3
    for key, value in (meta or {}).items():
        info.cell(row=row, column=1, value=key).font = Font(bold=True)
        info.cell(row=row, column=2, value=str(value))
        row += 1
    info.column_dimensions["A"].width = 22
    info.column_dimensions["B"].width = 60

    for title, (headers, rows) in datasets.items():
        name = title[:31] or "Sheet"
        ws = wb.create_sheet(name)
        _write_sheet(ws, headers or ["(empty)"], rows)
    target = Path(path)
    wb.save(target)
    return target


def export_report(path: str | Path, title: str, headers: list[str], rows: list[list],
                  footer: dict | None = None, money_cols: list[int] | None = None) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = (title or "Report")[:31]
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    start = 3
    data_rows = [[h for h in headers]] + rows
    for r in data_rows:
        ws.append(r)
    for cell in ws[start]:
        cell.font = Font(bold=True)
        cell.border = BORDER
    for idx, header in enumerate(headers, start=1):
        width = min(38, max(9, max([len(str(header))] + [len(str(r[idx - 1])) for r in rows[:300]
                                                          if len(r) >= idx]) + 2))
        ws.column_dimensions[get_column_letter(idx)].width = width
        if money_cols and (idx - 1) in money_cols:
            for cell in ws[get_column_letter(idx)][start:]:
                cell.number_format = MONEY_FMT
    ws.freeze_panes = f"A{start + 1}"
    if headers:
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(headers))}{ws.max_row}"
    if footer:
        ws.append([])
        for k, v in footer.items():
            ws.append([k, v])
            if isinstance(v, (int, float)):
                ws.cell(row=ws.max_row, column=2).number_format = MONEY_FMT
    target = Path(path)
    wb.save(target)
    return target


def backup_database(db: Database, path: str | Path, db_label: str = "") -> Path:
    datasets = services.export_datasets(db)
    meta = {
        "Generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Database": db_label,
        "Sheets": ", ".join(datasets.keys()),
        "Note": "Passwords are not exported (shown as 'encrypted').",
    }
    return export_workbook(path, datasets, meta)


def _norm(value) -> str:
    return str(value or "").strip()


def _account(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        return str(int(value))
    return _norm(value)


def import_consumers(db: Database, path: str | Path) -> dict:
    """Import/update consumers from an Excel file.

    Recognised columns (case-insensitive): Account, Name, Address, Meter,
    Contact, Type, Area, Department, Designation, Group, Status,
    Rate override.  Missing master values are created automatically.
    """
    wb = load_workbook(filename=str(path), data_only=True, read_only=True)
    ws = wb["Consumers"] if "Consumers" in wb.sheetnames else wb.active
    rows = ws.iter_rows(values_only=True)
    try:
        raw_headers = next(rows)
    except StopIteration:
        return {"created": 0, "updated": 0, "errors": ["The sheet is empty."]}
    mapping = {_norm(h).lower().replace("_", " "): i for i, h in enumerate(raw_headers) if h is not None}

    def col(*names):
        for name in names:
            idx = mapping.get(name)
            if idx is not None:
                return idx
        return None

    c_account = col("account", "account no", "con id", "id")
    c_name = col("name", "consumer", "consumer name", "con name")
    if c_account is None or c_name is None:
        return {"created": 0, "updated": 0,
                "errors": ["The sheet needs at least 'Account' and 'Name' columns."]}
    c_addr = col("address")
    c_meter = col("meter", "meter no", "meter number")
    c_contact = col("contact", "phone")
    c_type = col("type", "consumer type")
    c_area = col("area")
    c_dept = col("department")
    c_des = col("designation")
    c_group = col("group", "con group")
    c_status = col("status", "con status")
    c_rate = col("rate override", "rate")

    created = updated = 0
    errors: list[str] = []
    cache: dict[str, dict[str, int]] = {}

    for rowno, row in enumerate(rows, start=2):
        try:
            account = _account(row[c_account]) if c_account < len(row) else ""
            name = _norm(row[c_name]) if c_name < len(row) else ""
            if not account and not name:
                continue
            if not account.isdigit():
                errors.append(f"Row {rowno}: account must be numeric ({account!r}).")
                continue
            con_id = int(account)
            exists = db.one("SELECT con_id FROM tbl_consumer WHERE con_id=%s", (con_id,))
            data = {
                "con_id": con_id,
                "con_name": name,
                "con_address": _norm(row[c_addr]) if c_addr is not None and c_addr < len(row) else None,
                "meter_no": _norm(row[c_meter]) if c_meter is not None and c_meter < len(row) else None,
                "con_contact": _norm(row[c_contact]) if c_contact is not None and c_contact < len(row) else None,
                "con_group": _norm(row[c_group]) if c_group is not None and c_group < len(row) else None,
                "con_status": (_norm(row[c_status]) if c_status is not None and c_status < len(row) else "") or "Active",
                "user_id": "IMPORT",
            }
            for kind, idx in (("type", c_type), ("area", c_area), ("department", c_dept),
                              ("designation", c_des)):
                value = _norm(row[idx]) if idx is not None and idx < len(row) else ""
                if value:
                    if kind not in cache:
                        cache[kind] = services.master_maps(db).get(kind, {})
                    master_id = cache[kind].get(value) or services.ensure_master(db, kind, value)
                    if master_id:
                        cache[kind].setdefault(value, int(master_id))
                    data[{"type": "type_id", "area": "area_id", "department": "dep_id",
                          "designation": "des_id"}[kind]] = master_id
            if c_rate is not None and c_rate < len(row):
                raw = _norm(row[c_rate])
                if raw:
                    data["rate_override"] = float(raw)
            services.save_consumer(db, data)
            if exists:
                updated += 1
            else:
                created += 1
        except Exception as exc:
            errors.append(f"Row {rowno}: {exc}")
    wb.close()
    return {"created": created, "updated": updated, "errors": errors}
