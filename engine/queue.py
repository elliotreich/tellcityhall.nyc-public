"""
SQLite-backed persistence for the digest message queue.
Stores pending messages and digests for Council district delivery.

Tables:
  pending_messages — individual constituent messages awaiting inclusion in a digest
  digests          — records of sent digests for auditing
"""
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config as app_config


def _get_db_path() -> Path:
    """Resolve the digest database path at call time (supports test overrides)."""
    return app_config.DIGEST_DB_PATH


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the digest database with WAL mode enabled."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they do not exist. Safe to call repeatedly."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_messages (
                id TEXT PRIMARY KEY,
                district INTEGER NOT NULL,
                sender_name TEXT NOT NULL,
                sender_email TEXT NOT NULL,
                sender_address TEXT NOT NULL,
                topic TEXT NOT NULL DEFAULT 'Other',
                message TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                digest_id TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                verification_token TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS digests (
                id TEXT PRIMARY KEY,
                district INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'sent'
            );

            CREATE INDEX IF NOT EXISTS idx_pending_district_status
                ON pending_messages(district, status);

            CREATE INDEX IF NOT EXISTS idx_pending_verification_token
                ON pending_messages(verification_token);
        """)
        conn.commit()
    finally:
        conn.close()


def enqueue(
    district: int,
    sender_name: str,
    sender_email: str,
    sender_address: str,
    topic: str,
    message: str,
) -> tuple[str, str]:
    """
    Enqueue a constituent message for later digest delivery.

    Returns (message_id, verification_token).  The verification token must be
    sent to the constituent so they can confirm their email address before the
    message is eligible for a digest.
    """
    message_id = secrets.token_urlsafe(16)
    verification_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO pending_messages
               (id, district, sender_name, sender_email, sender_address,
                topic, message, submitted_at, verification_token)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                district,
                sender_name,
                sender_email,
                sender_address,
                topic,
                message,
                now,
                verification_token,
            ),
        )
        conn.commit()
        return message_id, verification_token
    finally:
        conn.close()


def pending_for_district(district: int, verified_only: bool = True) -> list[dict]:
    """Return pending (un-sent) messages for a district, ordered by submission time.

    When *verified_only* is True (default) only messages whose constituent has
    confirmed their email are returned.
    """
    conn = _get_conn()
    try:
        if verified_only:
            rows = conn.execute(
                """SELECT * FROM pending_messages
                   WHERE district = ? AND status = 'pending' AND verified = 1
                   ORDER BY submitted_at ASC""",
                (district,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM pending_messages
                   WHERE district = ? AND status = 'pending'
                   ORDER BY submitted_at ASC""",
                (district,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_count(district: int, verified_only: bool = True) -> int:
    """Count pending messages for a given district."""
    conn = _get_conn()
    try:
        if verified_only:
            row = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE district = ? AND status = 'pending' AND verified = 1",
                (district,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE district = ? AND status = 'pending'",
                (district,),
            ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_districts_with_pending(verified_only: bool = True) -> list[int]:
    """Return all district numbers that have pending (un-sent) messages."""
    conn = _get_conn()
    try:
        if verified_only:
            rows = conn.execute(
                "SELECT DISTINCT district FROM pending_messages WHERE status = 'pending' AND verified = 1"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT district FROM pending_messages WHERE status = 'pending'"
            ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def create_digest(district: int, message_ids: list[str]) -> str:
    """Create a digest record and mark messages as *queued* for this digest.

    Returns the new digest id.  Messages are updated from 'pending' to 'queued'
    so they are not picked up by a subsequent run.
    """
    digest_id = secrets.token_urlsafe(16)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO digests (id, district, sent_at, message_count, status) VALUES (?, ?, ?, ?, 'sending')",
            (digest_id, district, now, len(message_ids)),
        )
        placeholders = ",".join("?" for _ in message_ids)
        conn.execute(
            f"UPDATE pending_messages SET status = 'queued', digest_id = ? WHERE id IN ({placeholders})",
            [digest_id] + message_ids,
        )
        conn.commit()
        return digest_id
    finally:
        conn.close()


def mark_sent(message_ids: list[str], digest_id: str):
    """Mark queued messages as sent and finalise the digest."""
    conn = _get_conn()
    try:
        placeholders = ",".join("?" for _ in message_ids)
        conn.execute(
            f"UPDATE pending_messages SET status = 'sent' WHERE id IN ({placeholders})",
            message_ids,
        )
        conn.execute(
            "UPDATE digests SET status = 'sent' WHERE id = ?",
            (digest_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(message_ids: list[str], digest_id: str):
    """Mark queued messages as failed on send error."""
    conn = _get_conn()
    try:
        placeholders = ",".join("?" for _ in message_ids)
        conn.execute(
            f"UPDATE pending_messages SET status = 'failed' WHERE id IN ({placeholders})",
            message_ids,
        )
        conn.execute(
            "UPDATE digests SET status = 'failed' WHERE id = ?",
            (digest_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_message_by_token(token: str) -> Optional[dict]:
    """Look up a message by its verification token."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM pending_messages WHERE verification_token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def verify_message(token: str) -> bool:
    """Mark a message as verified.  Returns True if a row was updated."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "UPDATE pending_messages SET verified = 1 WHERE verification_token = ? AND verified = 0",
            (token,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
