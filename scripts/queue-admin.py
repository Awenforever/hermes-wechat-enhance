#!/usr/bin/env python3
"""Inspect and safely maintain the durable Weixin outbound queue."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path


def default_db() -> Path:
    configured = os.getenv("HERMES_WEIXIN_QUEUE_DB", "").strip()
    if configured:
        return Path(configured)
    return Path(os.getenv("HERMES_HOME", "/opt/data")) / "weixin" / "send-queue.sqlite3"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def status(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count, MIN(enqueued_at) AS oldest, "
        "MAX(enqueued_at) AS newest FROM outbound_queue GROUP BY status"
    ).fetchall()
    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))


def list_items(conn: sqlite3.Connection, limit: int) -> None:
    rows = conn.execute(
        "SELECT seq,account_id,user_id,delivery_id,chunk_index,enqueued_at,"
        "expires_at,status,LENGTH(content) AS content_chars "
        "FROM outbound_queue ORDER BY seq LIMIT ?",
        (limit,),
    ).fetchall()
    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))


def export_items(conn: sqlite3.Connection, output: Path) -> None:
    rows = conn.execute("SELECT * FROM outbound_queue ORDER BY seq").fetchall()
    payload = [dict(row) for row in rows]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, output)
    print(f"exported={len(payload)} path={output}")


def expire_due(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        "UPDATE outbound_queue SET status='expired' "
        "WHERE status='queued' AND expires_at <= ?",
        (time.time(),),
    )
    conn.commit()
    print(f"expired={cursor.rowcount}")


def clear_pending(conn: sqlite3.Connection, confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("clear-pending requires --yes")
    cursor = conn.execute(
        "UPDATE outbound_queue SET status='discarded' "
        "WHERE status='queued'"
    )
    conn.commit()
    print(f"discarded={cursor.rowcount}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "list", "export", "expire", "clear-pending"])
    parser.add_argument("--db", type=Path, default=default_db())
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.db.exists():
        print(f"queue database does not exist: {args.db}")
        return 0
    with connect(args.db) as conn:
        if args.command == "status":
            status(conn)
        elif args.command == "list":
            list_items(conn, max(1, min(args.limit, 1000)))
        elif args.command == "export":
            if args.output is None:
                raise SystemExit("export requires --output")
            export_items(conn, args.output)
        elif args.command == "expire":
            expire_due(conn)
        else:
            clear_pending(conn, args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
