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


def save_order(order_id: str, repo: str, email: str, txn: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO orders (id, created_at, repo, email, txn) VALUES (?,?,?,?,?)",
            (order_id, int(time.time()), repo, email, txn),
        )
        conn.commit()


def stats() -> dict[str, int]:
    with _connect() as conn:
        reports = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"]
        orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    return {"reports": int(reports), "orders": int(orders)}
