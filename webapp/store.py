"""SQLite persistence. One table for shared reports, one for paid orders."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "launchguard.db"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reports (
                   id TEXT PRIMARY KEY,
                   created_at INTEGER NOT NULL,
                   source TEXT NOT NULL,
                   payload TEXT NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                   id TEXT PRIMARY KEY,
                   created_at INTEGER NOT NULL,
                   repo TEXT NOT NULL,
                   email TEXT NOT NULL,
                   txn TEXT NOT NULL,
                   status TEXT NOT NULL DEFAULT 'new'
               )"""
        )
        conn.commit()


def save_report(report_id: str, source: str, payload: dict[str, Any]) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reports (id, created_at, source, payload) VALUES (?,?,?,?)",
            (report_id, int(time.time()), source, json.dumps(payload)),
        )
        conn.commit()


def get_report(report_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM reports WHERE id = ?", (report_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def get_report_age(report_id: str) -> int:
    with _connect() as conn:
        row = conn.execute("SELECT created_at FROM reports WHERE id = ?", (report_id,)).fetchone()
    return int(time.time()) - int(row["created_at"]) if row else 0


def save_order(order_id: str, repo: str, email: str, txn: str, *, status: str = "new") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO orders (id, created_at, repo, email, txn, status) VALUES (?,?,?,?,?,?)",
            (order_id, int(time.time()), repo, email, txn, status),
        )
        conn.commit()


def order_exists_txn(txn: str) -> bool:
    """IPN retries; a duplicate must not create a second row."""
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM orders WHERE txn = ? LIMIT 1", (txn,)).fetchone()
    return row is not None


def list_orders(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, repo, email, txn, status FROM orders "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_order_status(order_id: str, status: str) -> bool:
    with _lock, _connect() as conn:
        cursor = conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
    return cursor.rowcount > 0


def claim_repo(email: str, repo: str) -> str | None:
    """The buyer tells us which repository after paying; attach it to their
    newest order. PayPal could never know this on its own."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM orders WHERE lower(email) = lower(?) ORDER BY created_at DESC LIMIT 1",
            (email.strip(),),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE orders SET repo = ? WHERE id = ?", (repo.strip()[:200], row["id"]))
        conn.commit()
    return str(row["id"])


def stats() -> dict[str, int]:
    with _connect() as conn:
        reports = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"]
        orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    return {"reports": int(reports), "orders": int(orders)}
