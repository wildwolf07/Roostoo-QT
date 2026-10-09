"""SQLite audit trail: every API call, order, signal decision and equity snapshot.

This is the evidence for "Trade Log Integrity": each order row carries the
reason that produced it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_calls (
    ts TEXT, method TEXT, path TEXT, params TEXT, http_status INTEGER,
    success INTEGER, err_msg TEXT, latency_ms REAL, attempt INTEGER
);
CREATE TABLE IF NOT EXISTS orders (
    ts TEXT, mode TEXT, pair TEXT, side TEXT, type TEXT, quantity REAL, price REAL,
    order_id TEXT, status TEXT, filled_qty REAL, avg_price REAL, commission REAL,
    reason TEXT, response TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT, equity REAL, usd REAL, gross_exposure REAL, drawdown REAL, holdings TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    ts TEXT, kind TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def _exec(self, sql: str, args: tuple) -> None:
        with self.lock:
            self.conn.execute(sql, args)
            self.conn.commit()

    def log_api_call(self, rec: dict) -> None:
        self._exec(
            "INSERT INTO api_calls VALUES (?,?,?,?,?,?,?,?,?)",
            (_now(), rec["method"], rec["path"], json.dumps(rec["params"]), rec["http_status"],
             int(rec["success"]), rec["err_msg"], rec["latency_ms"], rec["attempt"]),
        )

    def log_order(self, mode: str, pair: str, side: str, otype: str, qty: float,
                  price: Optional[float], reason: str, resp: Optional[dict]) -> None:
        d = (resp or {}).get("OrderDetail", {}) if resp else {}
        self._exec(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), mode, pair, side, otype, qty, price, str(d.get("OrderID", "")),
             d.get("Status") or ("REJECTED" if resp else "NO_RESPONSE"),
             d.get("FilledQuantity"), d.get("FilledAverPrice"), d.get("CommissionChargeValue"),
             reason, json.dumps(resp)[:2000] if resp else None),
        )

    def log_equity(self, equity: float, usd: float, gross: float, dd: float, holdings: dict) -> None:
        self._exec("INSERT INTO equity VALUES (?,?,?,?,?,?)",
                   (_now(), equity, usd, gross, dd, json.dumps(holdings)))

    def log_decision(self, kind: str, payload: Any) -> None:
        self._exec("INSERT INTO decisions VALUES (?,?,?)", (_now(), kind, json.dumps(payload, default=str)))

    def get_kv(self, key: str) -> Optional[Any]:
        with self.lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_kv(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, default=str)))
