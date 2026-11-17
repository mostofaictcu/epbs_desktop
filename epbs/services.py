"""Business rules for EPBS Desktop (reverse-engineered from EBPS.exe)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .db import Database, DbError
from .schema import sync_identity_sequences
from .security import decrypt, encrypt

PUNISHMENT_EXCLUDED_TYPES = {"BDF", "RES-QUATER"}
# primary keys that can collide when an imported id sequence lags behind
def _is_id_collision(exc: Exception) -> bool:
    """True when the failure is an id sequence/default problem.

    Covers duplicate primary keys and a missing sequence (NULL id) on the
    three tables written by bill generation.
    """
    message = str(exc).lower()
    if "duplicate key" in message and (
        "_pkey" in message or "un_id" in message or "bill_no" in message
        or "bill_det_id" in message
    ):
        return True
    if "not-null" in message or "null value in column" in message:
        return any(f'"{col}"' in message for col in ("un_id", "bill_no", "bill_det_id"))
    return False
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def q2(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def num(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


# --------------------------------------------------------------------------
# months
# --------------------------------------------------------------------------
def running_month(today: date | None = None) -> str:
    today = today or date.today()
    return f"{MONTH_NAMES[today.month - 1]}-{today.year}"


def month_choices(years: int = 6, include_blank: bool = False) -> list[tuple[str, str]]:
    today = date.today()
    year, month = today.year, today.month
    out: list[tuple[str, str]] = [("", "All months")] if include_blank else []
    for _ in range(years * 12 + 1):
        out.append((f"{MONTH_NAMES[month - 1]}-{year}", f"{MONTH_NAMES[month - 1]} {year}"))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return out


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------
def authenticate(db: Database, username: str, password: str) -> dict | None:
    if not username or not password:
        return None
    row = db.one(
        """SELECT * FROM tbl_users
            WHERE lower(username) = lower(%s) AND system_login = 'Active'""",
        (username.strip(),),
    )
    if not row:
        return None
    stored = (row.get("userpass") or "").strip()
    if stored in (encrypt(password), password):
        return row
    try:
        if decrypt(stored) == password:
            return row
    except Exception:
        pass
    return None


def change_password(db: Database, user_id: str, new_password: str) -> None:
    if not (5 <= len(new_password) <= 25):
        raise ValueError("Password must be 5 - 25 characters.")
    db.execute("UPDATE tbl_users SET userpass=%s WHERE user_id=%s", (encrypt(new_password), user_id))


def list_users(db: Database) -> list[dict]:
    return db.query("SELECT * FROM tbl_users ORDER BY username")


# --------------------------------------------------------------------------
# masters
# --------------------------------------------------------------------------
def masters(db: Database) -> dict[str, list[dict]]:
    return {
        "types": db.query("SELECT * FROM tbl_type ORDER BY type_name"),
        "areas": db.query("SELECT * FROM tbl_area ORDER BY area_details"),
        "departments": db.query("SELECT * FROM tbl_department ORDER BY dep_details"),
        "designations": db.query("SELECT * FROM tbl_designation ORDER BY des_details"),
        "groups": db.query(
            """SELECT group_id, group_name AS group_details FROM tbl_consumer_group
                ORDER BY group_name"""
        ),
    }


# --------------------------------------------------------------------------
# slab tariffs (optional, per consumer type)
# --------------------------------------------------------------------------
def normalize_slabs(slabs: list[dict]) -> list[dict]:
    """Validate slab rows and return them ordered with 1-based slab numbers.

    ``to_unit`` is the upper consumption threshold.  ``0`` means "no upper
    limit" and is only allowed on the last slab.  Thresholds must increase so
    a unit cannot be billed twice.
    """
    rows: list[dict] = []
    for index, raw in enumerate(slabs or [], start=1):
        try:
            start = int(raw.get("from_unit") or 0)
            end = int(raw.get("to_unit") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Slab {index}: units must be whole numbers.")
        rate = q2(raw.get("rate"))
        if start < 0 or end < 0:
            raise ValueError(f"Slab {index}: units cannot be negative.")
        if rate < 0:
            raise ValueError(f"Slab {index}: rate cannot be negative.")
        if end and end < start:
            raise ValueError(f"Slab {index}: end unit must be greater than the start unit.")
        rows.append({"from_unit": start, "to_unit": end, "rate": rate})

    finite = sorted((r for r in rows if r["to_unit"] > 0), key=lambda r: r["to_unit"])
    unlimited = [r for r in rows if r["to_unit"] == 0]
    if len(unlimited) > 1:
        raise ValueError("Only the last slab can have no upper limit.")

    last = 0
    for row in finite:
        if row["to_unit"] <= last:
            raise ValueError(f"Slab ending at {row['to_unit']:,} overlaps the previous slab.")
        last = row["to_unit"]

    ordered = finite + unlimited
    for number, row in enumerate(ordered, start=1):
        row["slab_no"] = number
    return ordered


def type_slabs(db: Database, type_id: int | None) -> list[dict]:
    """Slab tariff of a consumer type (empty = flat rate billing)."""
    if not type_id:
        return []
    return db.query(
        """SELECT slab_id, type_id, slab_no, from_unit, to_unit, rate
             FROM tbl_type_slab
            WHERE type_id=%s
            ORDER BY CASE WHEN to_unit = 0 THEN 1 ELSE 0 END, to_unit, slab_no""",
        (int(type_id),),
    )


def save_type_slabs(db: Database, type_id: int, slabs: list[dict], user_id: str = "",
                    note: str = "") -> None:
    """Replace the whole slab tariff of a type."""
    ordered = normalize_slabs(slabs)
    with db.tx():
        old = type_slabs(db, type_id)
        db.execute("DELETE FROM tbl_type_slab WHERE type_id=%s", (int(type_id),))
        for row in ordered:
            db.execute(
                """INSERT INTO tbl_type_slab (type_id, slab_no, from_unit, to_unit, rate)
                   VALUES (%s,%s,%s,%s,%s)""",
                (int(type_id), int(row["slab_no"]), int(row["from_unit"]),
                 int(row["to_unit"]), q2(row["rate"])),
            )
        _audit(db, "tbl_type", str(type_id), "slabs",
               _slab_text(old), _slab_text(ordered), user_id,
               note or "Slab tariff updated")


def _slab_text(rows: list[dict]) -> str:
    return "; ".join(
        f"{int(r.get('from_unit') or 0)}-"
        f"{int(r.get('to_unit') or 0) if int(r.get('to_unit') or 0) else 'limit'}"
        f" @ {q2(r.get('rate'))}"
        for r in rows
    )


def slab_breakdown(units: int, slabs: list[dict]) -> list[dict]:
    """Split ``units`` across progressive slabs.

    A slab is applied to the part of consumption above the previous slab's
    upper threshold, so 500 units with 0-400 @ 7.48 and 0-600 @ 10.20 gives
    400 units at 7.48 and 100 units at 10.20.  Consumption above the last
    finite threshold continues at the last slab's rate.
    """
    units = max(0, int(units or 0))
    if units <= 0 or not slabs:
        return []
    ordered = sorted(
        slabs,
        key=lambda s: (int(s.get("to_unit") or 0) == 0, int(s.get("to_unit") or 0),
                       int(s.get("slab_no") or 0)),
    )
    rows: list[dict] = []
    billed = 0
    for slab in ordered:
        end = int(slab.get("to_unit") or 0)
        rate = q2(slab.get("rate"))
        if end == 0:
            portion = units - billed
            if portion > 0:
                rows.append(_slab_line(billed, 0, portion, rate, len(rows) + 1))
                billed = units
            break
        if end <= billed:
            continue
        portion = min(units, end) - billed
        if portion > 0:
            rows.append(_slab_line(billed, end, portion, rate, len(rows) + 1))
            billed = min(units, end)
        if billed >= units:
            break
    if billed < units and ordered:
        rate = q2(ordered[-1].get("rate"))
        rows.append(_slab_line(billed, 0, units - billed, rate, len(rows) + 1))
    return rows


def _slab_line(billed: int, end: int, portion: int, rate: Decimal, slab_no: int) -> dict:
    return {
        "slab_no": slab_no,
        "from_unit": billed + 1 if billed else 0,
        "to_unit": end,
        "units": int(portion),
        "rate": rate,
        "amount": q2(Decimal(portion) * rate),
    }


def slab_snapshot(definitions: list[dict], lines: list[dict]) -> list[dict]:
    """Keep every tariff slab in a bill snapshot, including unused upper slabs.

    Zero-unit rows are not printed but let a later recalculation apply the
    correct rate when a corrected reading moves into a higher slab.
    """
    by_no = {int(r.get("slab_no") or 0): r for r in lines}
    out: list[dict] = []
    seen: set[int] = set()
    for index, slab in enumerate(definitions, start=1):
        number = int(slab.get("slab_no") or index)
        line = by_no.get(number)
        out.append({
            "slab_no": number,
            "from_unit": int(line.get("from_unit") or 0) if line
            else int(slab.get("from_unit") or 0),
            "to_unit": int(line.get("to_unit") or 0) if line
            else int(slab.get("to_unit") or 0),
            "units": int(line.get("units") or 0) if line else 0,
            "rate": q2(line.get("rate") if line else slab.get("rate")),
            "amount": q2(line.get("amount")) if line else q2(0),
        })
        seen.add(number)
    for line in lines:
        if int(line.get("slab_no") or 0) not in seen:
            out.append(line)
    return out


def slab_amount(rows: list[dict]) -> Decimal:
    return q2(sum((q2(r.get("amount")) for r in rows), Decimal("0")))


def sync_consumer_groups(db: Database) -> int:
    """Copy group names used on consumers into tbl_consumer_group."""
    return db.execute(
        """INSERT INTO tbl_consumer_group (group_name)
           SELECT min(btrim(con_group)) FROM tbl_consumer
            WHERE con_group IS NOT NULL AND btrim(con_group) <> ''
            GROUP BY lower(btrim(con_group))
           ON CONFLICT (group_name) DO NOTHING"""
    )


def company(db: Database, company_id: str = "1001") -> dict:
    row = db.one("SELECT * FROM tbl_company_info WHERE company_id=%s", (company_id,))
    return row or {"company_id": company_id, "company_name": "EPBS",
                   "company_address": "", "contact_no": "", "email": "", "website": ""}


def save_company(db: Database, data: dict) -> None:
    db.execute(
        """INSERT INTO tbl_company_info
               (company_id, company_name, company_address, reg_no, contact_no, email, website, logo_url)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (company_id) DO UPDATE SET
               company_name=EXCLUDED.company_name, company_address=EXCLUDED.company_address,
               reg_no=EXCLUDED.reg_no, contact_no=EXCLUDED.contact_no, email=EXCLUDED.email,
               website=EXCLUDED.website, logo_url=EXCLUDED.logo_url""",
        (data.get("company_id") or "1001", data.get("company_name"), data.get("company_address"),
         data.get("reg_no"), data.get("contact_no"), data.get("email"), data.get("website"),
         data.get("logo_url")),
    )


# --------------------------------------------------------------------------
# consumers
# --------------------------------------------------------------------------
_CONSUMER_SELECT = """
SELECT c.con_id, c.con_name, c.con_address, c.meter_no, c.con_contact, c.con_status,
       c.con_group, c.user_id, c.rate_override,
       c.area_id, a.area_details,
       c.type_id, t.type_name, COALESCE(c.rate_override, t.rate, 0)::numeric(12,2) AS rate,
       t.rate AS type_rate, t.meter_rent AS type_meter_rent,
       t.minimum_amount AS type_minimum_amount, t.fixed_charge AS type_fixed_charge,
       (SELECT count(*) FROM tbl_type_slab ts WHERE ts.type_id = c.type_id) AS slab_count,
       c.dep_id, d.dep_details,
       c.des_id, ds.des_details,
       COALESCE((SELECT SUM(b.total_amount) FROM tbl_bills b
                  WHERE b.con_id = c.con_id AND b.bill_status = 'Unpaid'), 0)::numeric(12,2) AS due
  FROM tbl_consumer c
  LEFT JOIN tbl_area a        ON a.area_id = c.area_id
  LEFT JOIN tbl_type t        ON t.type_id = c.type_id
  LEFT JOIN tbl_department d  ON d.dep_id  = c.dep_id
  LEFT JOIN tbl_designation ds ON ds.des_id = c.des_id
"""


def get_consumer(db: Database, con_id: int) -> dict | None:
    return db.one(_CONSUMER_SELECT + " WHERE c.con_id = %s", (con_id,))


def get_consumer_by_key(db: Database, key: str) -> dict | None:
    key = (key or "").strip()
    if not key:
        return None
    row = None
    if key.isdigit():
        row = db.one(_CONSUMER_SELECT + " WHERE c.con_id = %s", (int(key),))
    if row is None:
        row = db.one(_CONSUMER_SELECT + " WHERE lower(c.meter_no) = lower(%s) ORDER BY c.con_id LIMIT 1", (key,))
    if row is None:
        row = db.one(_CONSUMER_SELECT + " WHERE lower(c.con_name) = lower(%s) ORDER BY c.con_id LIMIT 1", (key,))
    return row


def search_consumers(db: Database, text: str, limit: int = 30) -> list[dict]:
    text = (text or "").strip()
    like = f"%{text}%"
    return db.query(
        _CONSUMER_SELECT
        + """ WHERE (%s = '' OR c.con_id::text = %s OR c.meter_no ILIKE %s
                     OR c.con_name ILIKE %s OR c.con_contact ILIKE %s)
             ORDER BY CASE WHEN c.con_id::text = %s OR lower(c.meter_no) = lower(%s) THEN 0 ELSE 1 END,
                      c.con_id
             LIMIT %s""",
        (text, text, like, like, like, text, text, int(limit)),
    )


def _consumer_where(text: str = "", status: str = "") -> tuple[str, list]:
    conds = ["TRUE"]
    params: list = []
    text = (text or "").strip()
    if text:
        like = f"%{text}%"
        conds.append("(c.con_id::text = %s OR c.meter_no ILIKE %s "
                     "OR c.con_name ILIKE %s OR c.con_contact ILIKE %s)")
        params += [text, like, like, like]
    status = (status or "").strip()
    if status:
        conds.append("c.con_status = %s")
        params.append(status)
    return " AND ".join(conds), params


def list_consumers(db: Database, text: str = "", status: str = "", limit: int = 400) -> list[dict]:
    where, params = _consumer_where(text, status)
    return db.query(_CONSUMER_SELECT + f" WHERE {where} ORDER BY c.con_id LIMIT %s",
                    (*params, int(limit)))


def list_consumers_page(db: Database, text: str = "", status: str = "",
                        after_id: int | None = None, limit: int = 100
                        ) -> tuple[list[dict], bool, int | None]:
    """One keyset page ordered by con_id (ascending)."""
    where, params = _consumer_where(text, status)
    rows = db.query(
        _CONSUMER_SELECT
        + f""" WHERE {where}
                  AND (%s::int IS NULL OR c.con_id > %s::int)
              ORDER BY c.con_id LIMIT %s""",
        (*params, after_id, after_id, int(limit) + 1),
    )
    has_next = len(rows) > limit
    rows = rows[:limit]
    cursor = int(rows[-1]["con_id"]) if has_next and rows else None
    return rows, has_next, cursor


def count_consumers(db: Database, text: str = "", status: str = "") -> int:
    where, params = _consumer_where(text, status)
    return int(db.scalar(f"SELECT count(*) FROM tbl_consumer c WHERE {where}",
                         params, default=0) or 0)


def next_consumer_id(db: Database) -> int:
    value = db.scalar("SELECT MAX(con_id) FROM tbl_consumer", default=10000)
    return int(value or 10000) + 1


def save_consumer(db: Database, data: dict) -> int:
    con_id = int(data["con_id"])
    group = (data.get("con_group") or "").strip()[:45] or None
    if group:
        # A newly typed group is added to the master so it is offered next time.
        # Matching is case-insensitive and the stored master spelling wins.
        row = db.one("SELECT group_name FROM tbl_consumer_group WHERE lower(group_name)=lower(%s)",
                     (group,))
        if row:
            group = row["group_name"]
        else:
            db.execute(
                "INSERT INTO tbl_consumer_group (group_name) VALUES (%s) "
                "ON CONFLICT (group_name) DO NOTHING",
                (group,),
            )
    db.execute(
        """INSERT INTO tbl_consumer
               (con_id, con_name, con_address, area_id, meter_no, con_contact, con_status,
                des_id, type_id, dep_id, con_group, user_id, rate_override)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (con_id) DO UPDATE SET
               con_name=EXCLUDED.con_name, con_address=EXCLUDED.con_address,
               area_id=EXCLUDED.area_id, meter_no=EXCLUDED.meter_no,
               con_contact=EXCLUDED.con_contact, con_status=EXCLUDED.con_status,
               des_id=EXCLUDED.des_id, type_id=EXCLUDED.type_id, dep_id=EXCLUDED.dep_id,
               con_group=EXCLUDED.con_group, user_id=EXCLUDED.user_id,
               rate_override=EXCLUDED.rate_override""",
        (con_id, data.get("con_name"), data.get("con_address"), data.get("area_id"),
         data.get("meter_no"), data.get("con_contact"), data.get("con_status") or "Active",
         data.get("des_id"), data.get("type_id"), data.get("dep_id"), group,
         data.get("user_id"), data.get("rate_override")),
    )
    return con_id


def delete_consumer(db: Database, con_id: int) -> None:
    """Delete a consumer; refuse when bills/payments still reference it."""
    with db.tx():
        used = db.scalar(
            """SELECT (SELECT COUNT(*) FROM tbl_bills WHERE con_id=%s)
                    + (SELECT COUNT(*) FROM tbl_payment WHERE con_id=%s)
                    + (SELECT COUNT(*) FROM tbl_customize_bill WHERE con_id=%s)""",
            (con_id, con_id, con_id), default=0,
        )
        if used:
            raise ValueError("This consumer has bills, payments or customised bills "
                             "and cannot be deleted.")
        db.execute("DELETE FROM tbl_unit WHERE con_id=%s", (con_id,))
        db.execute("DELETE FROM tbl_consumer WHERE con_id=%s", (con_id,))


# --------------------------------------------------------------------------
# readings / preview
# --------------------------------------------------------------------------
def last_reading(db: Database, con_id: int) -> dict | None:
    return db.one(
        """SELECT * FROM tbl_unit WHERE con_id=%s
            ORDER BY present_date DESC NULLS LAST, un_id DESC LIMIT 1""",
        (con_id,),
    )


def readings(db: Database, con_id: int, limit: int = 12) -> list[dict]:
    return db.query(
        """SELECT * FROM tbl_unit WHERE con_id=%s
            ORDER BY present_date DESC NULLS LAST, un_id DESC LIMIT %s""",
        (con_id, int(limit)),
    )


def unpaid_due(db: Database, con_id: int, exclude_bill_no: int | None = None) -> Decimal:
    row = db.one(
        """SELECT COALESCE(SUM(total_amount),0) AS s FROM tbl_bills
            WHERE con_id=%s AND bill_status='Unpaid'
              AND (%s::int IS NULL OR bill_no <> %s::int)""",
        (con_id, exclude_bill_no, exclude_bill_no),
    )
    return q2((row or {}).get("s"))


def _billing_amount(db: Database, *, type_id, rate_override, fallback_rate,
                    units: int, rate=None, minimum=None, fixed_charge: bool = False) -> dict:
    """Price ``units`` with an explicit flat rate, slabs, or the flat type rate.

    An explicit ``rate`` (entered for one bill or a consumer override) always
    wins and bypasses the type's slab tariff.  A ``fixed_charge`` type bills
    its rate once per bill instead of multiplying it by the units (for example
    a BDF type).  ``minimum`` is the type's minimum charge: when the calculated
    charge is lower, the minimum is billed instead and ``minimum_charge``
    records that it was applied.
    """
    if fixed_charge:
        applied = q2(rate if rate is not None
                     else (rate_override if rate_override is not None else fallback_rate))
        result = {"amount": applied, "rate": applied, "slabs": [], "tariff_slabs": [],
                  "is_slab": False, "is_fixed": True}
    elif rate is not None:
        applied = q2(rate)
        result = {"amount": q2(Decimal(units) * applied), "rate": applied,
                  "slabs": [], "tariff_slabs": [], "is_slab": False, "is_fixed": False}
    elif rate_override is None:
        slabs = type_slabs(db, type_id)
        if slabs:
            rows = slab_breakdown(units, slabs)
            amount = slab_amount(rows)
            average = q2(Decimal(amount) / Decimal(units)) if units else Decimal("0.00")
            result = {"amount": amount, "rate": average, "slabs": rows,
                      "tariff_slabs": slabs, "is_slab": True, "is_fixed": False}
        else:
            applied = q2(fallback_rate)
            result = {"amount": q2(Decimal(units) * applied), "rate": applied,
                      "slabs": [], "tariff_slabs": [], "is_slab": False, "is_fixed": False}
    else:
        applied = q2(rate_override if rate_override is not None else fallback_rate)
        result = {"amount": q2(Decimal(units) * applied), "rate": applied,
                  "slabs": [], "tariff_slabs": [], "is_slab": False, "is_fixed": False}

    floor = q2(minimum)
    calculated = q2(result["amount"])
    result["calculated_amount"] = calculated
    result["minimum"] = floor
    result["amount"], result["minimum_charge"] = _apply_minimum(calculated, floor)
    return result


def _apply_minimum(amount, minimum) -> tuple[Decimal, Decimal]:
    """Return ``(bill_amount, minimum_charge)`` for a calculated charge."""
    amount = q2(amount)
    floor = q2(minimum)
    if floor > 0 and amount < floor:
        return floor, floor
    return amount, Decimal("0.00")


def preview_bill(db: Database, con_id: int, present_unit: int, meter_rent=None,
                 rate=None) -> dict:
    consumer = get_consumer(db, con_id)
    if not consumer:
        raise ValueError("Consumer not found.")
    prev = last_reading(db, con_id)
    previous_unit = int((prev or {}).get("present_unit") or 0)
    if present_unit < previous_unit:
        raise ValueError(f"Present unit ({present_unit}) cannot be less than previous unit ({previous_unit}).")
    units = int(present_unit) - previous_unit
    tariff = _billing_amount(
        db, type_id=consumer.get("type_id"), rate_override=consumer.get("rate_override"),
        fallback_rate=consumer.get("type_rate") if consumer.get("type_rate") is not None
        else consumer.get("rate"),
        units=units, rate=rate, minimum=consumer.get("type_minimum_amount"),
        fixed_charge=bool(consumer.get("type_fixed_charge")),
    )
    amount = tariff["amount"]
    rent = q2(meter_rent if meter_rent is not None
              else consumer.get("type_meter_rent"))
    due = unpaid_due(db, con_id)
    total = q2(amount + due + rent)
    return {
        "consumer": consumer, "previous_unit": previous_unit, "present_unit": int(present_unit),
        "units": units, "rate": tariff["rate"], "bill_amount": amount, "due": due,
        "meter_rent": rent, "total": total, "previous_date": (prev or {}).get("present_date"),
        "previous_reading": prev, "slabs": tariff["slabs"], "is_slab": tariff["is_slab"],
        "is_fixed": tariff["is_fixed"],
        "minimum": tariff["minimum"], "minimum_charge": tariff["minimum_charge"],
        "calculated_amount": tariff["calculated_amount"],
    }


# --------------------------------------------------------------------------
# bills
# --------------------------------------------------------------------------
def generate_bill(db: Database, *, con_id: int, present_unit: int, present_date: date,
                  bill_month: str, issue_date: date, last_date: date, meter_rent=None,
                  rate=None, save_rate: bool = True, user_id: str = "",
                  kind: str = "Generate") -> int:
    """Create a bill, repairing stale id sequences if needed.

    ``rate`` overrides the consumer/type rate for this bill; when
    ``save_rate`` is true it is also stored as the consumer's rate.

    Three attempts, so a bad sequence can never stop a bill:
      1. normal insert (identity columns allocate the ids);
      2. repair every id sequence, then normal insert;
      3. insert with ids computed as ``MAX(id) + 1`` (table locked for the
         transaction).  This works even when the table has no usable
         sequence/default at all.
    """
    args = dict(
        con_id=con_id, present_unit=present_unit, present_date=present_date,
        bill_month=bill_month, issue_date=issue_date, last_date=last_date,
        meter_rent=meter_rent, rate=rate, save_rate=save_rate,
        user_id=user_id, kind=kind,
    )
    try:
        return _generate_bill_once(db, **args)
    except DbError as exc:
        if not _is_id_collision(exc):
            raise
    # A legacy import left an id sequence on a value that is already used
    # (tbl_unit_pkey / tbl_bills_pkey).  Move the sequences past MAX(id)
    # and retry the same bill.
    try:
        sync_identity_sequences(db)
        return _generate_bill_once(db, **args)
    except DbError as exc:
        if not _is_id_collision(exc):
            raise
    # Still colliding (no sequence at all, sequence in another schema, ids
    # hidden by an open transaction...): allocate the ids explicitly.
    bill_no = _generate_bill_once(db, explicit_ids=True, **args)
    try:
        sync_identity_sequences(db)
    except Exception:
        pass
    return bill_no


def _generate_bill_once(db: Database, *, con_id: int, present_unit: int, present_date: date,
                        bill_month: str, issue_date: date, last_date: date, meter_rent=None,
                        rate=None, save_rate: bool = True, user_id: str = "",
                        kind: str = "Generate", explicit_ids: bool = False) -> int:
    with db.tx():
        if explicit_ids:
            # Serialise with any other writer before reading MAX(id).
            db.execute("LOCK TABLE tbl_bills, tbl_bills_details, tbl_unit "
                       "IN EXCLUSIVE MODE")
        consumer = db.one("SELECT * FROM tbl_consumer WHERE con_id=%s FOR UPDATE", (con_id,))
        if not consumer:
            raise ValueError("Consumer not found.")
        ctype = db.one("SELECT * FROM tbl_type WHERE type_id=%s", (consumer.get("type_id"),)) or {}
        if kind == "Punishment":
            if (consumer.get("con_status") or "") != "Active":
                raise ValueError("Punishment bill is not allowed for inactive consumers.")
            if (ctype.get("type_name") or "") in PUNISHMENT_EXCLUDED_TYPES:
                raise ValueError("Punishment Bill is not allowed for this consumer type.")
        prev = last_reading(db, con_id)
        previous_unit = int((prev or {}).get("present_unit") or 0)
        previous_date = (prev or {}).get("present_date") or present_date
        if present_unit < previous_unit:
            raise ValueError(f"Present unit ({present_unit}) cannot be less than previous unit ({previous_unit}).")
        units = int(present_unit) - previous_unit
        current_rate = q2(consumer.get("rate_override") if consumer.get("rate_override") is not None
                          else ctype.get("rate"))
        tariff = _billing_amount(
            db, type_id=consumer.get("type_id"),
            rate_override=consumer.get("rate_override"),
            fallback_rate=ctype.get("rate"), units=units, rate=rate,
            minimum=ctype.get("minimum_amount"),
            fixed_charge=bool(ctype.get("fixed_charge")),
        )
        applied_rate = tariff["rate"]
        amount = tariff["amount"]
        minimum_charge = tariff["minimum_charge"]
        fixed_charge = bool(tariff.get("is_fixed"))
        if applied_rate < 0:
            raise ValueError("Rate cannot be negative.")
        rent = q2(meter_rent if meter_rent is not None else ctype.get("meter_rent"))
        due = unpaid_due(db, con_id)
        total = q2(amount + due + rent)
        if explicit_ids:
            bill_no = int(db.scalar("SELECT COALESCE(MAX(bill_no), 0) + 1 FROM tbl_bills"))
            db.execute(
                """INSERT INTO tbl_bills
                       (bill_no, issue_date, last_date, bill_amount, due, meter_rent,
                        minimum_charge, fixed_charge, total_amount, bill_status, bill_print,
                        meter_no, con_id, user_id, remarks)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'Unpaid','No',%s,%s,%s,%s)""",
                (bill_no, issue_date, last_date, amount, due, rent, minimum_charge,
                 fixed_charge, total, consumer.get("meter_no"), con_id, user_id,
                 kind if kind != "Generate" else None),
            )
        else:
            row = db.one(
                """INSERT INTO tbl_bills
                       (issue_date, last_date, bill_amount, due, meter_rent, minimum_charge,
                        fixed_charge, total_amount, bill_status, bill_print, meter_no, con_id,
                        user_id, remarks)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Unpaid','No',%s,%s,%s,%s)
                   RETURNING bill_no""",
                (issue_date, last_date, amount, due, rent, minimum_charge, fixed_charge, total,
                 consumer.get("meter_no"), con_id, user_id, kind if kind != "Generate" else None),
            )
            bill_no = int(row["bill_no"])
        if explicit_ids:
            bill_det_id = int(db.scalar(
                "SELECT COALESCE(MAX(bill_det_id), 0) + 1 FROM tbl_bills_details"))
            db.execute(
                """INSERT INTO tbl_bills_details
                       (bill_det_id, bill_details, bill_month, bill_status, bill_amount, bill_no)
                   VALUES (%s,%s,%s,'Unpaid',%s,%s)""",
                (bill_det_id, kind, bill_month, amount, bill_no),
            )
        else:
            db.execute(
                """INSERT INTO tbl_bills_details
                       (bill_details, bill_month, bill_status, bill_amount, bill_no)
                   VALUES (%s,%s,'Unpaid',%s,%s)""",
                (kind, bill_month, amount, bill_no),
            )
        if explicit_ids:
            un_id = int(db.scalar("SELECT COALESCE(MAX(un_id), 0) + 1 FROM tbl_unit"))
            db.execute(
                """INSERT INTO tbl_unit
                       (un_id, previous_date, previous_unit, present_date, present_unit,
                        con_id, bill_no, rate_applied)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (un_id, previous_date, previous_unit, present_date, int(present_unit),
                 con_id, bill_no, applied_rate),
            )
        else:
            db.execute(
                """INSERT INTO tbl_unit
                       (previous_date, previous_unit, present_date, present_unit, con_id, bill_no, rate_applied)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (previous_date, previous_unit, present_date, int(present_unit), con_id, bill_no,
                 applied_rate),
            )
        for line in slab_snapshot(tariff.get("tariff_slabs") or [], tariff["slabs"]):
            db.execute(
                """INSERT INTO tbl_bill_slab
                       (bill_no, slab_no, from_unit, to_unit, units, rate, amount)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (bill_no, int(line["slab_no"]), int(line["from_unit"]),
                 int(line["to_unit"]), int(line["units"]), q2(line["rate"]),
                 q2(line["amount"])),
            )
        if save_rate and rate is not None and applied_rate != current_rate:
            db.execute("UPDATE tbl_consumer SET rate_override=%s WHERE con_id=%s",
                       (applied_rate, con_id))
            _audit(db, "tbl_consumer", str(con_id), "rate_override",
                   str(current_rate), str(applied_rate), user_id,
                   f"Rate entered while generating bill {bill_no}")
        return bill_no


def collect_payment(db: Database, bill_no: int, paid_date: date, user_id: str = "") -> int:
    with db.tx():
        bill = db.one("SELECT * FROM tbl_bills WHERE bill_no=%s FOR UPDATE", (bill_no,))
        if not bill:
            raise ValueError("Bill not found.")
        if bill.get("bill_status") == "Paid":
            raise ValueError("Bill already paid. Please search another bill.")
        row = db.one(
            """INSERT INTO tbl_payment (bill_no, bill_amount, paid_date, con_id, user_id)
               VALUES (%s,%s,%s,%s,%s) RETURNING payment_id""",
            (bill_no, q2(bill.get("total_amount")), paid_date, bill.get("con_id"), user_id),
        )
        db.execute("UPDATE tbl_bills SET bill_status='Paid' WHERE bill_no=%s", (bill_no,))
        db.execute("UPDATE tbl_bills_details SET bill_status='Paid' WHERE bill_no=%s", (bill_no,))
        return int(row["payment_id"])


def delete_payment(db: Database, payment_id: int) -> None:
    with db.tx():
        pay = db.one("SELECT * FROM tbl_payment WHERE payment_id=%s", (payment_id,))
        if not pay:
            return
        db.execute("DELETE FROM tbl_payment WHERE payment_id=%s", (payment_id,))
        remaining = db.scalar("SELECT COUNT(*) FROM tbl_payment WHERE bill_no=%s",
                              (pay.get("bill_no"),), default=0)
        if not remaining:
            db.execute("UPDATE tbl_bills SET bill_status='Unpaid' WHERE bill_no=%s", (pay.get("bill_no"),))
            db.execute("UPDATE tbl_bills_details SET bill_status='Unpaid' WHERE bill_no=%s", (pay.get("bill_no"),))


def delete_bill(db: Database, bill_no: int) -> None:
    with db.tx():
        if db.scalar("SELECT COUNT(*) FROM tbl_payment WHERE bill_no=%s", (bill_no,), default=0):
            raise ValueError("Bill has a payment record. Delete the payment first.")
        db.execute("DELETE FROM tbl_bills_details WHERE bill_no=%s", (bill_no,))
        db.execute("DELETE FROM tbl_unit WHERE bill_no=%s", (bill_no,))
        db.execute("DELETE FROM tbl_bill_slab WHERE bill_no=%s", (bill_no,))
        db.execute("DELETE FROM tbl_bills WHERE bill_no=%s", (bill_no,))


def mark_printed(db: Database, bill_no: int) -> None:
    db.execute(
        """UPDATE tbl_bills SET bill_print='Yes', print_count=print_count+1,
                  last_printed_at=now() WHERE bill_no=%s""",
        (bill_no,),
    )


_BILL_SELECT = """
SELECT b.bill_no, b.issue_date, b.last_date, b.bill_amount, b.due, b.meter_rent,
       b.minimum_charge, b.fixed_charge, b.total_amount, b.bill_status, b.bill_print, b.meter_no,
       b.con_id, b.user_id, b.print_count, b.last_printed_at, b.remarks,
       c.con_name, c.con_address, t.type_name, COALESCE(c.rate_override, t.rate, 0)::numeric(12,2) AS rate,
       COALESCE((SELECT u.present_unit - u.previous_unit FROM tbl_unit u
                  WHERE u.bill_no=b.bill_no ORDER BY u.un_id DESC LIMIT 1), 0) AS units
  FROM tbl_bills b
  LEFT JOIN tbl_consumer c ON c.con_id=b.con_id
  LEFT JOIN tbl_type t ON t.type_id=c.type_id
"""


def get_bill(db: Database, bill_no: int) -> dict | None:
    return db.one(_BILL_SELECT + " WHERE b.bill_no=%s", (bill_no,))


def consumer_bills(db: Database, con_id: int, limit: int = 200) -> list[dict]:
    return db.query(_BILL_SELECT + " WHERE b.con_id=%s ORDER BY b.bill_no DESC LIMIT %s",
                    (con_id, int(limit)))


def consumer_bills_page(db: Database, con_id: int, before_no: int | None = None,
                        limit: int = 50) -> tuple[list[dict], bool, int | None]:
    rows = db.query(
        _BILL_SELECT
        + """ WHERE b.con_id=%s AND (%s::int IS NULL OR b.bill_no < %s::int)
              ORDER BY b.bill_no DESC LIMIT %s""",
        (con_id, before_no, before_no, int(limit) + 1),
    )
    has_next = len(rows) > limit
    rows = rows[:limit]
    cursor = int(rows[-1]["bill_no"]) if has_next and rows else None
    return rows, has_next, cursor


def consumer_payments(db: Database, con_id: int, limit: int = 100) -> list[dict]:
    return db.query(
        """SELECT p.*, b.total_amount, b.bill_status FROM tbl_payment p
             LEFT JOIN tbl_bills b ON b.bill_no=p.bill_no
            WHERE p.con_id=%s ORDER BY p.payment_id DESC LIMIT %s""",
        (con_id, int(limit)),
    )


def consumer_payments_page(db: Database, con_id: int, before_id: int | None = None,
                           limit: int = 50) -> tuple[list[dict], bool, int | None]:
    rows = db.query(
        """SELECT p.*, b.total_amount, b.bill_status FROM tbl_payment p
             LEFT JOIN tbl_bills b ON b.bill_no=p.bill_no
            WHERE p.con_id=%s AND (%s::int IS NULL OR p.payment_id < %s::int)
            ORDER BY p.payment_id DESC LIMIT %s""",
        (con_id, before_id, before_id, int(limit) + 1),
    )
    has_next = len(rows) > limit
    rows = rows[:limit]
    cursor = int(rows[-1]["payment_id"]) if has_next and rows else None
    return rows, has_next, cursor


def readings_page(db: Database, con_id: int, before_id: int | None = None,
                  limit: int = 50) -> tuple[list[dict], bool, int | None]:
    rows = db.query(
        """SELECT * FROM tbl_unit
            WHERE con_id=%s AND (%s::int IS NULL OR un_id < %s::int)
            ORDER BY un_id DESC LIMIT %s""",
        (con_id, before_id, before_id, int(limit) + 1),
    )
    has_next = len(rows) > limit
    rows = rows[:limit]
    cursor = int(rows[-1]["un_id"]) if has_next and rows else None
    return rows, has_next, cursor


def consumer_stats(db: Database, con_id: int) -> dict:
    return db.one(
        """SELECT (SELECT count(*) FROM tbl_bills WHERE con_id=%s) AS bills,
                  (SELECT count(*) FROM tbl_payment WHERE con_id=%s) AS payments,
                  (SELECT count(*) FROM tbl_unit WHERE con_id=%s) AS readings""",
        (con_id, con_id, con_id),
    ) or {"bills": 0, "payments": 0, "readings": 0}


def _bill_where(text: str = "", status: str = "", month: str = "",
                date_from: date | None = None, date_to: date | None = None
                ) -> tuple[str, list]:
    conds = ["TRUE"]
    params: list = []
    text = (text or "").strip()
    if text:
        like = f"%{text}%"
        conds.append("(b.bill_no::text = %s OR b.meter_no ILIKE %s "
                     "OR c.con_id::text = %s OR c.con_name ILIKE %s)")
        params += [text, like, text, like]
    status = (status or "").strip()
    if status:
        conds.append("b.bill_status = %s")
        params.append(status)
    month = (month or "").strip()
    if month:
        conds.append("EXISTS (SELECT 1 FROM tbl_bills_details d "
                     "WHERE d.bill_no=b.bill_no AND d.bill_month = %s)")
        params.append(month)
    if date_from is not None:
        conds.append("b.issue_date >= %s::date")
        params.append(date_from)
    if date_to is not None:
        conds.append("b.issue_date <= %s::date")
        params.append(date_to)
    return " AND ".join(conds), params


def search_bills(db: Database, text: str = "", status: str = "", month: str = "",
                 date_from: date | None = None, date_to: date | None = None,
                 limit: int = 500) -> list[dict]:
    where, params = _bill_where(text, status, month, date_from, date_to)
    return db.query(_BILL_SELECT + f" WHERE {where} ORDER BY b.bill_no DESC LIMIT %s",
                    (*params, int(limit)))


def search_bills_page(db: Database, text: str = "", status: str = "", month: str = "",
                      date_from: date | None = None, date_to: date | None = None,
                      before_no: int | None = None, limit: int = 100
                      ) -> tuple[list[dict], bool, int | None]:
    """One keyset page ordered by bill_no (descending)."""
    where, params = _bill_where(text, status, month, date_from, date_to)
    rows = db.query(
        _BILL_SELECT
        + f""" WHERE {where} AND (%s::int IS NULL OR b.bill_no < %s::int)
              ORDER BY b.bill_no DESC LIMIT %s""",
        (*params, before_no, before_no, int(limit) + 1),
    )
    has_next = len(rows) > limit
    rows = rows[:limit]
    cursor = int(rows[-1]["bill_no"]) if has_next and rows else None
    return rows, has_next, cursor


def count_bills(db: Database, text: str = "", status: str = "", month: str = "",
                date_from: date | None = None, date_to: date | None = None) -> int:
    where, params = _bill_where(text, status, month, date_from, date_to)
    return int(db.scalar(
        "SELECT count(*) FROM tbl_bills b "
        "LEFT JOIN tbl_consumer c ON c.con_id=b.con_id "
        f"WHERE {where}", params, default=0) or 0)


def bill_slabs(db: Database, bill_no: int, include_empty: bool = False) -> list[dict]:
    return db.query(
        """SELECT bill_slab_id, bill_no, slab_no, from_unit, to_unit, units, rate, amount
             FROM tbl_bill_slab
            WHERE bill_no=%s AND (%s OR units > 0)
            ORDER BY slab_no, bill_slab_id""",
        (bill_no, bool(include_empty)),
    )


def bill_detail(db: Database, bill_no: int) -> dict:
    bill = get_bill(db, bill_no)
    if not bill:
        raise ValueError("Bill not found.")
    consumer = get_consumer(db, bill.get("con_id")) if bill.get("con_id") else None
    return {
        "bill": bill,
        "consumer": consumer,
        "details": db.query("SELECT * FROM tbl_bills_details WHERE bill_no=%s ORDER BY bill_det_id", (bill_no,)),
        "readings": db.query("SELECT * FROM tbl_unit WHERE bill_no=%s ORDER BY un_id", (bill_no,)),
        "payments": db.query("SELECT * FROM tbl_payment WHERE bill_no=%s ORDER BY payment_id", (bill_no,)),
        "slabs": bill_slabs(db, bill_no),
    }


def recalc_bill(db: Database, bill_no: int, user_id: str = "", note: str = "") -> dict:
    """Recompute amount/due/total from the linked reading and current rate."""
    with db.tx():
        bill = db.one("SELECT * FROM tbl_bills WHERE bill_no=%s FOR UPDATE", (bill_no,))
        if not bill:
            raise ValueError("Bill not found.")
        reading = db.one(
            """SELECT * FROM tbl_unit WHERE bill_no=%s ORDER BY un_id DESC LIMIT 1""", (bill_no,)
        )
        if not reading:
            raise ValueError("This bill has no meter reading to recalculate.")
        consumer = get_consumer(db, bill.get("con_id")) if bill.get("con_id") else None
        units = int(reading.get("present_unit") or 0) - int(reading.get("previous_unit") or 0)
        snapshot = bill_slabs(db, bill_no, include_empty=True)
        fixed = bool((consumer or {}).get("type_fixed_charge"))
        lines: list[dict] = []
        if fixed:
            rate = q2(reading.get("rate_applied") if reading.get("rate_applied") is not None
                      else (consumer or {}).get("rate"))
            amount = rate
            # a fixed-charge type ignores slab rates; drop any old snapshot lines
            db.execute("DELETE FROM tbl_bill_slab WHERE bill_no=%s", (bill_no,))
        elif snapshot:
            lines = slab_breakdown(units, snapshot)
            amount = slab_amount(lines)
            rate = q2(Decimal(amount) / Decimal(units)) if units else Decimal("0.00")
            db.execute("DELETE FROM tbl_bill_slab WHERE bill_no=%s", (bill_no,))
            for line in slab_snapshot(snapshot, lines):
                db.execute(
                    """INSERT INTO tbl_bill_slab
                           (bill_no, slab_no, from_unit, to_unit, units, rate, amount)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (bill_no, int(line["slab_no"]), int(line["from_unit"]),
                     int(line["to_unit"]), int(line["units"]), q2(line["rate"]),
                     q2(line["amount"])),
                )
            db.execute("UPDATE tbl_unit SET rate_applied=%s WHERE un_id=%s",
                       (rate, reading.get("un_id")))
        else:
            rate = q2(reading.get("rate_applied") if reading.get("rate_applied") is not None
                      else (consumer or {}).get("rate"))
            amount = q2(Decimal(units) * rate)
        minimum = q2((consumer or {}).get("type_minimum_amount"))
        amount, minimum_charge = _apply_minimum(amount, minimum)
        rent = q2(bill.get("meter_rent"))
        due = unpaid_due(db, bill.get("con_id"), exclude_bill_no=bill_no)
        total = q2(amount + due + rent)
        db.execute(
            """UPDATE tbl_bills SET bill_amount=%s, due=%s, total_amount=%s,
                      minimum_charge=%s, fixed_charge=%s WHERE bill_no=%s""",
            (amount, due, total, minimum_charge, fixed, bill_no),
        )
        db.execute(
            """UPDATE tbl_bills_details SET bill_amount=%s
                WHERE bill_no=%s AND bill_details IN ('Generate','Punishment')""",
            (amount, bill_no),
        )
        _audit(db, "tbl_bills", str(bill_no), "total_amount",
               str(bill.get("total_amount")), str(total), user_id,
               note or (f"Recalculated: minimum charge {amount}" if minimum_charge
                        else (f"Recalculated: fixed charge {amount}" if fixed
                              else f"Recalculated: {units} units x {rate}")))
        return {"units": units, "rate": rate, "bill_amount": amount, "due": due,
                "meter_rent": rent, "total": total, "slabs": lines,
                "minimum_charge": minimum_charge, "is_fixed": fixed}


# --------------------------------------------------------------------------
# unit / rate change
# --------------------------------------------------------------------------
def update_reading(db: Database, un_id: int, previous_unit: int, present_unit: int,
                   previous_date: date | None, present_date: date | None,
                   user_id: str = "", note: str = "", recalc: bool = True) -> dict | None:
    with db.tx():
        reading = db.one("SELECT * FROM tbl_unit WHERE un_id=%s FOR UPDATE", (un_id,))
        if not reading:
            raise ValueError("Reading not found.")
        if present_unit < previous_unit:
            raise ValueError("Present unit cannot be less than previous unit.")
        db.execute(
            """UPDATE tbl_unit SET previous_unit=%s, present_unit=%s,
                      previous_date=%s, present_date=%s WHERE un_id=%s""",
            (int(previous_unit), int(present_unit), previous_date, present_date, un_id),
        )
        _audit(db, "tbl_unit", str(un_id), "units",
               f"{reading.get('previous_unit')}->{reading.get('present_unit')}",
               f"{previous_unit}->{present_unit}", user_id, note)
        result = None
        if recalc and reading.get("bill_no"):
            bill = db.one("SELECT bill_status FROM tbl_bills WHERE bill_no=%s", (reading["bill_no"],))
            if bill and bill.get("bill_status") == "Unpaid":
                result = recalc_bill(db, int(reading["bill_no"]), user_id,
                                     note or "Automatic recalculation after reading change")
        return result


def set_rate(db: Database, con_id: int, new_rate: float, scope: str,
             user_id: str = "", note: str = "") -> None:
    new_rate = q2(new_rate)
    if new_rate < 0:
        raise ValueError("Rate cannot be negative.")
    with db.tx():
        consumer = get_consumer(db, con_id)
        if not consumer:
            raise ValueError("Consumer not found.")
        if scope == "consumer":
            db.execute("UPDATE tbl_consumer SET rate_override=%s WHERE con_id=%s", (new_rate, con_id))
            _audit(db, "tbl_consumer", str(con_id), "rate_override",
                   str(consumer.get("rate")), str(new_rate), user_id,
                   note or "Per-consumer rate override")
        elif scope == "type":
            if not consumer.get("type_id"):
                raise ValueError("Consumer has no type assigned.")
            db.execute("UPDATE tbl_type SET rate=%s WHERE type_id=%s", (new_rate, consumer["type_id"]))
            db.execute("UPDATE tbl_consumer SET rate_override=NULL WHERE con_id=%s", (con_id,))
            _audit(db, "tbl_type", str(consumer["type_id"]), "rate",
                   str(consumer.get("rate")), str(new_rate), user_id,
                   note or f"Rate for type {consumer.get('type_name')}")
        else:
            raise ValueError("Unknown rate change scope.")


def clear_rate_override(db: Database, con_id: int, user_id: str = "") -> None:
    with db.tx():
        consumer = get_consumer(db, con_id)
        if not consumer:
            raise ValueError("Consumer not found.")
        db.execute("UPDATE tbl_consumer SET rate_override=NULL WHERE con_id=%s", (con_id,))
        _audit(db, "tbl_consumer", str(con_id), "rate_override",
               str(consumer.get("rate")), "type rate", user_id, "Override cleared")


def _audit(db: Database, table_name: str, ref_id: str, field: str, old, new,
           user_id: str, note: str) -> None:
    db.execute(
        """INSERT INTO tbl_audit (table_name, ref_id, field_name, old_value, new_value, user_id, note)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (table_name, ref_id, field, str(old) if old is not None else None,
         str(new) if new is not None else None, user_id, (note or "")[:250]),
    )


def audit_log(db: Database, limit: int = 100) -> list[dict]:
    return db.query(
        """SELECT audit_id, changed_at, table_name, ref_id, field_name, old_value,
                  new_value, user_id, note
             FROM tbl_audit ORDER BY audit_id DESC LIMIT %s""",
        (int(limit),),
    )


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------
def dashboard(db: Database) -> dict:
    stats = db.one(
        """SELECT (SELECT COUNT(*) FROM tbl_consumer) AS consumers,
                  (SELECT COUNT(*) FROM tbl_consumer WHERE con_status='Active') AS active_consumers,
                  (SELECT COUNT(*) FROM tbl_bills) AS bills,
                  (SELECT COUNT(*) FROM tbl_bills WHERE bill_status='Unpaid') AS unpaid,
                  (SELECT COALESCE(SUM(total_amount),0) FROM tbl_bills WHERE bill_status='Unpaid') AS unpaid_total,
                  (SELECT COUNT(*) FROM tbl_payment) AS payments,
                  (SELECT COALESCE(SUM(bill_amount),0) FROM tbl_payment) AS collected,
                  (SELECT COALESCE(SUM(bill_amount),0) FROM tbl_bills WHERE issue_date >= date_trunc('month', now())::date) AS billed_this_month"""
    ) or {}
    stats["recent_bills"] = db.query(_BILL_SELECT + " ORDER BY b.bill_no DESC LIMIT 8")
    stats["recent_payments"] = db.query(
        """SELECT p.payment_id, p.bill_no, p.bill_amount, p.paid_date, c.con_name, c.con_id
             FROM tbl_payment p LEFT JOIN tbl_consumer c ON c.con_id=p.con_id
            ORDER BY p.payment_id DESC LIMIT 8"""
    )
    stats["dues_by_type"] = db.query(
        """SELECT t.type_name, COUNT(DISTINCT c.con_id) AS consumers,
                  COALESCE(SUM(b.total_amount),0) AS total
             FROM tbl_bills b JOIN tbl_consumer c ON c.con_id=b.con_id
             LEFT JOIN tbl_type t ON t.type_id=c.type_id
            WHERE b.bill_status='Unpaid'
            GROUP BY t.type_name ORDER BY total DESC LIMIT 8"""
    )
    return stats


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def run_report(db: Database, kind: str, *, date_from: date | None = None,
               date_to: date | None = None, status: str = "", month: str = "",
               cursor=None, limit: int | None = None) -> dict:
    """Return a report page for the reports screen.

    ``limit`` enables keyset pagination for the detail reports (bills,
    collections, outstanding dues by consumer, consumer list); the result then
    contains ``has_next`` and ``next_cursor``.  Without ``limit`` every row is
    returned, which is what Excel export and printing use.
    """
    paged = bool(limit)
    page_limit = int(limit or 0)

    if kind == "bills":
        where, params = _bill_where(status=status, month=month,
                                    date_from=date_from, date_to=date_to)
        if paged:
            rows = db.query(
                _BILL_SELECT
                + f""" WHERE {where} AND (%s::int IS NULL OR b.bill_no < %s::int)
                      ORDER BY b.bill_no DESC LIMIT %s""",
                (*params, cursor, cursor, page_limit + 1),
            )
            has_next = len(rows) > page_limit
            rows = rows[:page_limit]
            next_cursor = int(rows[-1]["bill_no"]) if has_next and rows else None
        else:
            rows = db.query(_BILL_SELECT + f" WHERE {where} ORDER BY b.bill_no DESC", params)
            has_next, next_cursor = False, None
        totals = db.one(
            "SELECT count(*) AS bills, COALESCE(sum(b.total_amount),0) AS total "
            f"FROM tbl_bills b WHERE {where}", params) or {}
        headers = ["Bill No", "Issue date", "Account", "Consumer", "Meter", "Units",
                   "Bill amount", "Due", "Meter rent", "Total", "Status"]
        data = [[r["bill_no"], _d(r["issue_date"]), r["con_id"], r["con_name"], r["meter_no"],
                 r["units"], num(r["bill_amount"]), num(r["due"]), num(r["meter_rent"]),
                 num(r["total_amount"]), r["bill_status"]] for r in rows]
        return {"title": "Bills register", "headers": headers, "rows": data,
                "footer": {"Bills": int(totals.get("bills") or 0),
                           "Total": num(totals.get("total"))},
                "money_cols": [6, 7, 8, 9], "has_next": has_next,
                "next_cursor": next_cursor, "row_count": len(data)}

    if kind == "collections":
        conds = ["TRUE"]
        params: list = []
        if date_from is not None:
            conds.append("p.paid_date >= %s::date")
            params.append(date_from)
        if date_to is not None:
            conds.append("p.paid_date <= %s::date")
            params.append(date_to)
        where = " AND ".join(conds)
        base = """SELECT p.payment_id, p.paid_date, p.bill_no, p.con_id, c.con_name,
                         c.meter_no, p.bill_amount, p.user_id
                    FROM tbl_payment p LEFT JOIN tbl_consumer c ON c.con_id=p.con_id"""
        if paged:
            rows = db.query(
                base
                + f""" WHERE {where} AND (%s::int IS NULL OR p.payment_id < %s::int)
                      ORDER BY p.payment_id DESC LIMIT %s""",
                (*params, cursor, cursor, page_limit + 1),
            )
            has_next = len(rows) > page_limit
            rows = rows[:page_limit]
            next_cursor = int(rows[-1]["payment_id"]) if has_next and rows else None
        else:
            rows = db.query(base + f" WHERE {where} ORDER BY p.payment_id DESC", params)
            has_next, next_cursor = False, None
        totals = db.one(
            "SELECT count(*) AS payments, COALESCE(sum(p.bill_amount),0) AS collected "
            f"FROM tbl_payment p WHERE {where}", params) or {}
        headers = ["Payment", "Paid date", "Bill No", "Account", "Consumer", "Meter", "Amount", "User"]
        data = [[r["payment_id"], _d(r["paid_date"]), r["bill_no"], r["con_id"], r["con_name"],
                 r["meter_no"], num(r["bill_amount"]), r["user_id"]] for r in rows]
        return {"title": "Collections", "headers": headers, "rows": data,
                "footer": {"Payments": int(totals.get("payments") or 0),
                           "Collected": num(totals.get("collected"))},
                "money_cols": [6], "has_next": has_next,
                "next_cursor": next_cursor, "row_count": len(data)}

    if kind == "dues_consumer":
        due_sql = """SELECT c.con_id, c.con_name, c.meter_no, t.type_name, a.area_details,
                            COUNT(b.bill_no) AS bills, SUM(b.total_amount) AS total
                       FROM tbl_bills b JOIN tbl_consumer c ON c.con_id=b.con_id
                       LEFT JOIN tbl_type t ON t.type_id=c.type_id
                       LEFT JOIN tbl_area a ON a.area_id=c.area_id
                      WHERE b.bill_status='Unpaid'
                      GROUP BY c.con_id, c.con_name, c.meter_no, t.type_name, a.area_details"""
        if paged:
            cur_total = cursor.get("total") if isinstance(cursor, dict) else None
            cur_con = cursor.get("con_id") if isinstance(cursor, dict) else None
            rows = db.query(
                f"""WITH due AS ({due_sql})
                    SELECT * FROM due
                     WHERE (%s::numeric IS NULL OR total < %s::numeric
                            OR (total = %s::numeric AND con_id > %s::int))
                     ORDER BY total DESC, con_id LIMIT %s""",
                (cur_total, cur_total, cur_total, cur_con, page_limit + 1),
            )
            has_next = len(rows) > page_limit
            rows = rows[:page_limit]
            next_cursor = ({"total": rows[-1]["total"], "con_id": int(rows[-1]["con_id"])}
                           if has_next and rows else None)
        else:
            rows = db.query(due_sql + " ORDER BY total DESC, con_id")
            has_next, next_cursor = False, None
        totals = db.one(
            f"WITH due AS ({due_sql}) "
            "SELECT count(*) AS consumers, COALESCE(sum(total),0) AS total FROM due") or {}
        headers = ["Account", "Consumer", "Meter", "Type", "Area", "Unpaid bills", "Total due"]
        data = [[r["con_id"], r["con_name"], r["meter_no"], r["type_name"], r["area_details"],
                 r["bills"], num(r["total"])] for r in rows]
        return {"title": "Outstanding dues by consumer", "headers": headers, "rows": data,
                "footer": {"Consumers": int(totals.get("consumers") or 0),
                           "Total due": num(totals.get("total"))},
                "money_cols": [6], "has_next": has_next,
                "next_cursor": next_cursor, "row_count": len(data)}

    if kind == "dues_area":
        rows = db.query(
            """SELECT COALESCE(a.area_details,'(no area)') AS area, COUNT(DISTINCT c.con_id) AS consumers,
                      COUNT(b.bill_no) AS bills, SUM(b.total_amount) AS total
                 FROM tbl_bills b JOIN tbl_consumer c ON c.con_id=b.con_id
                 LEFT JOIN tbl_area a ON a.area_id=c.area_id
                WHERE b.bill_status='Unpaid'
                GROUP BY 1 ORDER BY total DESC"""
        )
        return {"title": "Outstanding dues by area",
                "headers": ["Area", "Consumers", "Bills", "Total due"],
                "rows": [[r["area"], r["consumers"], r["bills"], num(r["total"])] for r in rows],
                "footer": {"Areas": len(rows), "Total due": sum(num(r["total"]) for r in rows)},
                "money_cols": [3], "has_next": False, "next_cursor": None,
                "row_count": len(rows)}

    if kind == "dues_type":
        rows = db.query(
            """SELECT COALESCE(t.type_name,'(no type)') AS type_name, COUNT(DISTINCT c.con_id) AS consumers,
                      COUNT(b.bill_no) AS bills, SUM(b.total_amount) AS total
                 FROM tbl_bills b JOIN tbl_consumer c ON c.con_id=b.con_id
                 LEFT JOIN tbl_type t ON t.type_id=c.type_id
                WHERE b.bill_status='Unpaid'
                GROUP BY 1 ORDER BY total DESC"""
        )
        return {"title": "Outstanding dues by consumer type",
                "headers": ["Type", "Consumers", "Bills", "Total due"],
                "rows": [[r["type_name"], r["consumers"], r["bills"], num(r["total"])] for r in rows],
                "footer": {"Types": len(rows), "Total due": sum(num(r["total"]) for r in rows)},
                "money_cols": [3], "has_next": False, "next_cursor": None,
                "row_count": len(rows)}

    if kind == "consumers":
        where, params = _consumer_where(status=status)
        if paged:
            rows, has_next, next_cursor = list_consumers_page(
                db, status=status, after_id=cursor, limit=page_limit)
        else:
            rows = list_consumers(db, status=status, limit=100000)
            has_next, next_cursor = False, None
        total_consumers = count_consumers(db, status=status)
        total_due = db.scalar(
            """SELECT COALESCE(SUM(b.total_amount),0)
                 FROM tbl_bills b JOIN tbl_consumer c ON c.con_id=b.con_id
                WHERE b.bill_status='Unpaid'""" + f" AND {where}",
            params, default=0)
        headers = ["Account", "Consumer", "Meter", "Type", "Rate", "Area", "Department",
                   "Designation", "Group", "Status", "Contact", "Address", "Due"]
        data = [[r["con_id"], r["con_name"], r["meter_no"], r["type_name"], num(r["rate"]),
                 r["area_details"], r["dep_details"], r["des_details"], r["con_group"],
                 r["con_status"], r["con_contact"], r["con_address"], num(r["due"])] for r in rows]
        return {"title": "Consumer list", "headers": headers, "rows": data,
                "footer": {"Consumers": total_consumers, "Total due": num(total_due)},
                "money_cols": [4, 12], "has_next": has_next,
                "next_cursor": next_cursor, "row_count": len(data)}

    if kind == "monthly":
        rows = db.query(
            """SELECT d.bill_month,
                      COUNT(DISTINCT b.bill_no) AS bills,
                      COALESCE(SUM(u.units),0) AS units,
                      COALESCE(SUM(b.bill_amount),0) AS billed,
                      COALESCE(SUM(b.total_amount),0) AS total,
                      COALESCE(SUM(p.paid),0) AS collected
                 FROM tbl_bills_details d
                 JOIN tbl_bills b ON b.bill_no=d.bill_no
                 LEFT JOIN (SELECT bill_no, SUM(present_unit-previous_unit) AS units
                              FROM tbl_unit GROUP BY bill_no) u ON u.bill_no=b.bill_no
                 LEFT JOIN (SELECT bill_no, SUM(bill_amount) AS paid
                              FROM tbl_payment GROUP BY bill_no) p ON p.bill_no=b.bill_no
                WHERE d.bill_month IS NOT NULL AND d.bill_month <> ''
                  AND (%s = '' OR d.bill_month = %s)
                GROUP BY d.bill_month
                ORDER BY MIN(b.issue_date) DESC NULLS LAST""",
            (month, month),
        )
        return {"title": "Monthly billing summary",
                "headers": ["Bill month", "Bills", "Units", "Billed", "Total", "Collected"],
                "rows": [[r["bill_month"], r["bills"], int(r["units"]), num(r["billed"]),
                          num(r["total"]), num(r["collected"])] for r in rows],
                "footer": {"Months": len(rows),
                           "Billed": sum(num(r["billed"]) for r in rows),
                           "Collected": sum(num(r["collected"]) for r in rows)},
                "money_cols": [3, 4, 5], "has_next": False, "next_cursor": None,
                "row_count": len(rows)}

    raise ValueError(f"Unknown report: {kind}")


def _d(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else "")


# --------------------------------------------------------------------------
# Excel / data export helpers
# --------------------------------------------------------------------------
EXPORT_TABLES = [
    ("Consumers", "tbl_consumer", """SELECT c.con_id, c.con_name, c.con_address,
            a.area_details AS area, c.meter_no, c.con_contact, c.con_status,
            ds.des_details AS designation, t.type_name AS type, d.dep_details AS department,
            c.con_group, c.user_id, c.rate_override
            FROM tbl_consumer c
            LEFT JOIN tbl_area a ON a.area_id=c.area_id
            LEFT JOIN tbl_designation ds ON ds.des_id=c.des_id
            LEFT JOIN tbl_type t ON t.type_id=c.type_id
            LEFT JOIN tbl_department d ON d.dep_id=c.dep_id
            ORDER BY c.con_id"""),
    ("Bills", "tbl_bills", """SELECT bill_no, issue_date, last_date, bill_amount, due, meter_rent,
            minimum_charge, fixed_charge, total_amount, bill_status, bill_print, print_count,
            meter_no, con_id, user_id, remarks FROM tbl_bills ORDER BY bill_no"""),
    ("BillDetails", "tbl_bills_details", """SELECT bill_det_id, bill_details, bill_month, bill_status,
            bill_amount, bill_no FROM tbl_bills_details ORDER BY bill_det_id"""),
    ("UnitReadings", "tbl_unit", """SELECT un_id, previous_date, previous_unit, present_date,
            present_unit, con_id, bill_no, rate_applied, units FROM tbl_unit ORDER BY un_id"""),
    ("Payments", "tbl_payment", """SELECT payment_id, bill_no, bill_amount, paid_date, con_id, user_id
            FROM tbl_payment ORDER BY payment_id"""),
    ("Types", "tbl_type",
     "SELECT type_id, type_name, rate, fixed_charge, meter_rent, minimum_amount "
     "FROM tbl_type ORDER BY type_id"),
    ("TypeSlabs", "tbl_type_slab", """SELECT slab_id, type_id, slab_no, from_unit, to_unit,
            rate FROM tbl_type_slab ORDER BY type_id, slab_no"""),
    ("BillSlabs", "tbl_bill_slab", """SELECT bill_slab_id, bill_no, slab_no, from_unit,
            to_unit, units, rate, amount FROM tbl_bill_slab ORDER BY bill_no, slab_no"""),
    ("Areas", "tbl_area", "SELECT area_id, area_details FROM tbl_area ORDER BY area_id"),
    ("Departments", "tbl_department", "SELECT dep_id, dep_details FROM tbl_department ORDER BY dep_id"),
    ("Designations", "tbl_designation", "SELECT des_id, des_details FROM tbl_designation ORDER BY des_id"),
    ("ConsumerGroups", "tbl_consumer_group",
     "SELECT group_id, group_name FROM tbl_consumer_group ORDER BY group_id"),
    ("Company", "tbl_company_info", "SELECT * FROM tbl_company_info ORDER BY company_id"),
    ("Users", "tbl_users", """SELECT user_id, full_name, user_address, user_contact, username,
            '(encrypted)' AS userpass, access_type, user_permission, system_login
            FROM tbl_users ORDER BY user_id"""),
    ("Audit", "tbl_audit", """SELECT audit_id, changed_at, table_name, ref_id, field_name,
            old_value, new_value, user_id, note FROM tbl_audit ORDER BY audit_id"""),
]


def export_datasets(db: Database) -> dict[str, tuple[list[str], list[list]]]:
    out: dict[str, tuple[list[str], list[list]]] = {}
    for title, _table, sql in EXPORT_TABLES:
        rows = db.query(sql)
        if rows:
            headers = list(rows[0].keys())
            out[title] = (headers, [[_cell(r.get(h)) for h in headers] for r in rows])
        else:
            # keep headers even when empty
            cur = db.query(sql + " LIMIT 0")
            out[title] = (list(cur[0].keys()) if cur else [], [])
    return out


def _cell(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def master_maps(db: Database) -> dict[str, dict[str, int]]:
    return {
        "type": {r["type_name"]: r["type_id"] for r in db.query("SELECT type_name, type_id FROM tbl_type")},
        "area": {r["area_details"]: r["area_id"] for r in db.query("SELECT area_details, area_id FROM tbl_area")},
        "department": {r["dep_details"]: r["dep_id"] for r in db.query("SELECT dep_details, dep_id FROM tbl_department")},
        "designation": {r["des_details"]: r["des_id"] for r in db.query("SELECT des_details, des_id FROM tbl_designation")},
    }


def ensure_master(db: Database, kind: str, name: str) -> int | None:
    name = (name or "").strip()[:45]
    if not name:
        return None
    table, col = {"type": ("tbl_type", "type_name"), "area": ("tbl_area", "area_details"),
                  "department": ("tbl_department", "dep_details"),
                  "designation": ("tbl_designation", "des_details"),
                  "group": ("tbl_consumer_group", "group_name")}[kind]
    existing = db.one(f"SELECT * FROM {table} WHERE lower({col}) = lower(%s)", (name,))
    if existing:
        return int(existing[next(k for k in existing if k.endswith("_id"))])
    row = db.one(f"INSERT INTO {table} ({col}) VALUES (%s) RETURNING *", (name,))
    return int(row[next(k for k in row if k.endswith("_id"))]) if row else None


# --------------------------------------------------------------------------
# master data management (Settings -> Master data)
# --------------------------------------------------------------------------
MASTER_SPECS = {
    "type": ("tbl_type", "type_id", "type_name", "Consumer type", True),
    "area": ("tbl_area", "area_id", "area_details", "Area", False),
    "department": ("tbl_department", "dep_id", "dep_details", "Department", False),
    "designation": ("tbl_designation", "des_id", "des_details", "Designation", False),
    "group": ("tbl_consumer_group", "group_id", "group_name", "Consumer group", False),
}

MASTER_FK = {"type": "type_id", "area": "area_id", "department": "dep_id",
             "designation": "des_id"}


def list_master_rows(db: Database, kind: str) -> list[dict]:
    """Rows for the master-data screen, including the usage count."""
    table, idc, namec, _label, has_rate = MASTER_SPECS[kind]
    rate = "m.rate" if has_rate else "NULL::numeric AS rate"
    if kind == "group":
        used = ("(SELECT count(*) FROM tbl_consumer c "
                "WHERE lower(c.con_group)=lower(m.group_name))")
    else:
        used = f"(SELECT count(*) FROM tbl_consumer c WHERE c.{MASTER_FK[kind]}=m.{idc})"
    extra = ""
    if kind == "type":
        extra = (""", m.meter_rent, m.minimum_amount, m.fixed_charge,
            (SELECT count(*) FROM tbl_type_slab s WHERE s.type_id=m.type_id) AS slabs""")
    return db.query(
        f"""SELECT m.{idc} AS id, m.{namec} AS name, {rate}{extra}, {used} AS used
              FROM {table} m ORDER BY lower(m.{namec})"""
    )


def add_master_row(db: Database, kind: str, name: str, rate=None,
                   meter_rent=None, minimum_amount=None, fixed_charge: bool = False) -> int:
    table, idc, namec, label, has_rate = MASTER_SPECS[kind]
    name = (name or "").strip()[:45]
    if not name:
        raise ValueError("Name is required.")
    if db.one(f"SELECT {idc} FROM {table} WHERE lower({namec})=lower(%s)", (name,)):
        raise ValueError(f"{label} '{name}' already exists.")
    if has_rate:
        row = db.one(f"INSERT INTO {table} ({namec}, rate, fixed_charge, meter_rent, "
                     f"minimum_amount) VALUES (%s,%s,%s,%s,%s) RETURNING {idc}",
                     (name, q2(rate), bool(fixed_charge), q2(meter_rent),
                      q2(minimum_amount)))
    else:
        row = db.one(f"INSERT INTO {table} ({namec}) VALUES (%s) RETURNING {idc}", (name,))
    return int(row[idc])


def update_master_row(db: Database, kind: str, row_id: int, name: str, rate=None,
                      meter_rent=None, minimum_amount=None,
                      fixed_charge: bool = False) -> None:
    table, idc, namec, label, has_rate = MASTER_SPECS[kind]
    name = (name or "").strip()[:45]
    if not name:
        raise ValueError("Name is required.")
    duplicate = db.one(
        f"SELECT {idc} FROM {table} WHERE lower({namec})=lower(%s) AND {idc}<>%s",
        (name, int(row_id)))
    if duplicate:
        raise ValueError(f"{label} '{name}' already exists.")
    with db.tx():
        if kind == "group":
            old = db.one("SELECT group_name FROM tbl_consumer_group WHERE group_id=%s",
                         (int(row_id),))
            db.execute("UPDATE tbl_consumer_group SET group_name=%s WHERE group_id=%s",
                       (name, int(row_id)))
            if old:
                db.execute("UPDATE tbl_consumer SET con_group=%s "
                           "WHERE lower(con_group)=lower(%s)",
                           (name, old["group_name"]))
        elif has_rate:
            db.execute(f"UPDATE {table} SET {namec}=%s, rate=%s, fixed_charge=%s, "
                       f"meter_rent=%s, minimum_amount=%s WHERE {idc}=%s",
                       (name, q2(rate), bool(fixed_charge), q2(meter_rent),
                        q2(minimum_amount), int(row_id)))
        else:
            db.execute(f"UPDATE {table} SET {namec}=%s WHERE {idc}=%s", (name, int(row_id)))


def delete_master_row(db: Database, kind: str, row_id: int) -> None:
    table, idc, namec, label, _has_rate = MASTER_SPECS[kind]
    if kind == "group":
        row = db.one("SELECT group_name FROM tbl_consumer_group WHERE group_id=%s",
                     (int(row_id),))
        used = db.scalar("SELECT count(*) FROM tbl_consumer WHERE lower(con_group)=lower(%s)",
                         (row["group_name"] if row else "",), default=0)
    else:
        used = db.scalar(f"SELECT count(*) FROM tbl_consumer WHERE {MASTER_FK[kind]}=%s",
                         (int(row_id),), default=0)
    if used:
        raise ValueError(f"{label} is used by {used} consumer(s). Change those consumers first.")
    with db.tx():
        if kind == "type":
            db.execute("DELETE FROM tbl_type_slab WHERE type_id=%s", (int(row_id),))
        db.execute(f"DELETE FROM {table} WHERE {idc}=%s", (int(row_id),))
