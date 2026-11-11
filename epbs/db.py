"""Thin PostgreSQL access layer (psycopg 3)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

from .config import DbConfig
from .schema import schema_sql, sync_identity_sequences


class DbError(RuntimeError):
    pass


class Database:
    def __init__(self, cfg: DbConfig):
        self.cfg = cfg
        self.conn: psycopg.Connection | None = None
        self.sequences_repaired = 0

    # -- connection -----------------------------------------------------
    def connect(self) -> None:
        self.close()
        try:
            self.conn = psycopg.connect(**self.cfg.connect_kwargs(), row_factory=dict_row, autocommit=True)
        except Exception as exc:  # psycopg.OperationalError and friends
            self.conn = None
            raise DbError(str(exc).strip()) from exc

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def ensure(self) -> psycopg.Connection:
        if self.conn is None or self.conn.closed:
            self.connect()
        return self.conn  # type: ignore[return-value]

    def ping(self) -> tuple[bool, str]:
        try:
            conn = self.ensure()
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
            return True, str(row["version"] if row else "")
        except Exception as exc:
            return False, str(exc).strip()

    # -- helpers --------------------------------------------------------
    def _run(self, sql: str, params: Sequence[Any] | None = None, fetch: bool = False):
        conn = self.ensure()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                if fetch:
                    return cur.fetchall()
                return cur.rowcount
        except psycopg.Error as exc:
            # leave a clean session for the next statement
            try:
                if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                    conn.rollback()
            except Exception:
                pass
            raise DbError(_pretty_error(exc)) from exc

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        return self._run(sql, params, fetch=True) or []

    def one(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None, default: Any = None) -> Any:
        row = self.one(sql, params)
        if not row:
            return default
        return next(iter(row.values()))

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        return int(self._run(sql, params) or 0)

    def execute_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        conn = self.ensure()
        count = 0
        try:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(sql, row)
                    count += cur.rowcount
            return count
        except psycopg.Error as exc:
            raise DbError(_pretty_error(exc)) from exc

    @contextmanager
    def tx(self):
        conn = self.ensure()
        with conn.transaction():
            yield self

    # -- schema ---------------------------------------------------------
    def initialize_schema(self) -> None:
        conn = self.ensure()
        try:
            conn.execute(schema_sql())
            # Advance identity sequences that a legacy import left behind.
            self.sequences_repaired = sync_identity_sequences(self)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise DbError(_pretty_error(exc)) from exc

    def table_exists(self, name: str) -> bool:
        return bool(self.scalar(
            """SELECT to_regclass(%s) IS NOT NULL""",
            (self._qualified(name),),
            default=False,
        ))

    def _qualified(self, name: str) -> str:
        schema = self.cfg.schema or "public"
        return f"{schema}.{name}"


def _pretty_error(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    if diag is not None:
        parts = [p for p in (getattr(diag, "message_primary", None),
                             getattr(diag, "message_detail", None),
                             getattr(diag, "message_hint", None)) if p]
        if parts:
            return " - ".join(parts)
    return str(exc).strip()
