"""Copy the legacy MySQL EBPS database into the PostgreSQL 18 database.

Usage (from the EPBS_Desktop folder):

    python tools/migrate_from_mysql.py --mysql-user root --mysql-password secret

The PostgreSQL connection is read from config.ini (or --pg-config PATH).
The target schema is created automatically when missing.

Options:
    --replace       delete existing business rows before copying (cascade!)
    --skip-existing keep rows that already exist (default)

Master lists (area / department / designation / consumer type) are matched
by name.  A legacy name that is missing from PostgreSQL is inserted first, so
the old foreign keys keep pointing at the correct master row.  The migration
does not rely on database foreign keys (the legacy MySQL schema had none).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymysql
from pymysql.cursors import DictCursor

from epbs.config import load_config
from epbs.db import Database
from epbs import services

# target table, source table, source id, source name, target id, target name,
# extra target columns that are copied from a source column with the same name
MASTERS = [
    ("tbl_type", "tbl_Type", "Type_ID", "Type_Name", "type_id", "type_name", ["rate"]),
    ("tbl_area", "tbl_area", "Area_ID", "Area_Details", "area_id", "area_details", []),
    ("tbl_department", "tbl_department", "Dep_ID", "Dep_Details", "dep_id", "dep_details", []),
    ("tbl_designation", "tbl_designation", "Des_ID", "Des_Details", "des_id", "des_details", []),
]

# (target table, source table, target columns)
TABLES = [
    ("tbl_users", "tbl_Users",
     ["user_id", "full_name", "user_address", "user_contact", "username", "userpass",
      "access_type", "user_permission", "system_login"]),
    ("tbl_company_info", "tbl_Company_Info",
     ["company_id", "company_name", "company_address", "reg_no", "contact_no", "email",
      "website", "logo_url"]),
    ("tbl_consumer", "tbl_consumer",
     ["con_id", "con_name", "con_address", "area_id", "meter_no", "con_contact", "con_status",
      "des_id", "type_id", "dep_id", "con_group", "user_id"]),
    ("tbl_bills", "tbl_Bills",
     ["bill_no", "issue_date", "last_date", "bill_amount", "due", "meter_rent", "total_amount",
      "bill_status", "bill_print", "meter_no", "con_id", "user_id"]),
    ("tbl_bills_details", "tbl_Bills_Details",
     ["bill_det_id", "bill_details", "bill_month", "bill_status", "bill_amount", "bill_no"]),
    ("tbl_unit", "tbl_unit",
     ["un_id", "previous_date", "previous_unit", "present_date", "present_unit", "con_id",
      "bill_no"]),
    ("tbl_payment", "tbl_payment",
     ["payment_id", "bill_no", "bill_amount", "paid_date", "con_id", "user_id"]),
    ("tbl_customize_bill", "tbl_customize_bill",
     ["cus_bill_no", "issue_date", "last_date", "total_amount", "meter_no", "con_id", "user_id"]),
    ("tbl_customize_bill_details", "tbl_customize_bill_details",
     ["cus_det_id", "bill_no", "bill_month", "bill_amount", "cus_bill_no"]),
]

# consumer foreign keys that must be remapped by master name
CONSUMER_FKS = {
    "area_id": "tbl_area",
    "type_id": "tbl_type",
    "dep_id": "tbl_department",
    "des_id": "tbl_designation",
}

# NOT NULL columns may be NULL in the old dump
DEFAULTS = {
    "tbl_consumer": {"con_status": "Active"},
    "tbl_bills": {"bill_status": "Unpaid", "bill_print": "No", "due": 0},
    "tbl_bills_details": {"bill_status": "Unpaid"},
}

# identity columns that must be advanced after explicit ids were inserted
SEQUENCES = [
    ("tbl_type", "type_id"), ("tbl_area", "area_id"), ("tbl_department", "dep_id"),
    ("tbl_designation", "des_id"), ("tbl_bills", "bill_no"),
    ("tbl_bills_details", "bill_det_id"), ("tbl_unit", "un_id"),
    ("tbl_payment", "payment_id"), ("tbl_customize_bill", "cus_bill_no"),
    ("tbl_customize_bill_details", "cus_det_id"),
]

# delete order (children first)
TRUNCATE_ORDER = [
    "tbl_customize_bill_details", "tbl_customize_bill", "tbl_payment", "tbl_bills_details",
    "tbl_unit", "tbl_bills", "tbl_consumer",
]


def _key(value) -> str:
    """Normalise a master name for matching (case/space insensitive)."""
    return " ".join(str(value or "").split()).casefold()


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        if not value or value.startswith("0000-00-00"):
            return None
    return value


def _sync_masters(cur, db: Database) -> dict[str, dict[int, int]]:
    """Insert missing master rows and return legacy-id -> target-id maps."""
    maps: dict[str, dict[int, int]] = {}
    for target, source, sid, sname, tid, tname, extra in MASTERS:
        cur.execute(f"SELECT * FROM `{source}`")
        source_rows = cur.fetchall()
        target_rows = db.query(f"SELECT {tid}, {tname} FROM {target}")
        by_name = {_key(row[tname]): int(row[tid]) for row in target_rows}
        mapping: dict[int, int] = {}
        added = 0
        for row in source_rows:
            low = {str(k).lower(): v for k, v in row.items()}
            old_id = low.get(sid.lower())
            name = " ".join(str(low.get(sname.lower()) or "").split())
            if old_id is None or not name:
                continue
            key = name.casefold()
            new_id = by_name.get(key)
            if new_id is None:
                columns = [tname] + extra
                values = [name] + [_clean(low.get(c)) for c in extra]
                placeholders = ",".join(["%s"] * len(columns))
                new_id = int(db.scalar(
                    f"INSERT INTO {target} ({','.join(columns)}) VALUES ({placeholders}) "
                    f"RETURNING {tid}", values))
                by_name[key] = new_id
                added += 1
            mapping[int(old_id)] = new_id
        maps[target] = mapping
        print(f"  {target}: {len(mapping)} legacy ids mapped ({added} new rows)")
    return maps


def _copy_table(cur, db: Database, target: str, source: str, columns: list[str],
                maps: dict[str, dict[int, int]]) -> int:
    try:
        cur.execute(f"SELECT * FROM `{source}`")
        rows = cur.fetchall()
    except Exception as exc:
        print(f"  ! {source}: {exc}")
        return 0
    if not rows:
        print(f"  {target}: 0 rows")
        return 0

    lower_rows = [{str(k).lower(): v for k, v in row.items()} for row in rows]
    defaults = DEFAULTS.get(target, {})
    if target == "tbl_consumer":
        for r in lower_rows:
            for field, master in CONSUMER_FKS.items():
                old = r.get(field)
                r[field] = maps[master].get(int(old)) if old not in (None, "") else None
    for r in lower_rows:
        for field, value in defaults.items():
            if r.get(field) is None:
                r[field] = value

    tuples = [tuple(_clean(r.get(col)) for col in columns) for r in lower_rows]
    placeholders = ",".join(["%s"] * len(columns))
    sql = (f"INSERT INTO {target} ({','.join(columns)}) VALUES ({placeholders}) "
           f"ON CONFLICT DO NOTHING")
    conn = db.ensure()
    with conn.cursor() as pcur:
        pcur.executemany(sql, tuples)
    print(f"  {target}: {len(tuples)} rows")
    return len(tuples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-host", default="localhost")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="root")
    parser.add_argument("--mysql-password", default="")
    parser.add_argument("--mysql-db", default="ebps_db")
    parser.add_argument("--pg-config", default=str(ROOT / "config.ini"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    cfg = load_config(Path(args.pg_config))
    db = Database(cfg.db)
    db.connect()
    db.initialize_schema()
    print(f"PostgreSQL: {cfg.db.label()}")

    source = pymysql.connect(host=args.mysql_host, port=args.mysql_port, user=args.mysql_user,
                             password=args.mysql_password, database=args.mysql_db,
                             charset="utf8mb4", cursorclass=DictCursor)
    print(f"MySQL: {args.mysql_user}@{args.mysql_host}:{args.mysql_port}/{args.mysql_db}")

    if args.replace:
        with db.tx():
            for table in TRUNCATE_ORDER:
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM tbl_company_info")
        print("Existing business rows deleted.")

    total = 0
    with source.cursor() as cur, db.tx():
        maps = _sync_masters(cur, db)
        for target, src, columns in TABLES:
            total += _copy_table(cur, db, target, src, columns, maps)

    with db.tx():
        for table, column in SEQUENCES:
            db.execute(
                "SELECT setval(pg_get_serial_sequence(%s, %s)::regclass, "
                "COALESCE((SELECT MAX(" + column + ") FROM " + table + "), 0) + 1, false)",
                (table, column),
            )
        groups = services.sync_consumer_groups(db)
    source.close()
    db.close()
    print(f"Done. {total} rows copied, {groups} consumer groups. "
          "Log in with the legacy users (same passwords).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
