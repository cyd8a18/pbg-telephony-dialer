import sqlite3
from pathlib import Path
from typing import Union


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_lines (
    id TEXT PRIMARY KEY,
    call_control_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS client_legs (
    call_control_id TEXT PRIMARY KEY,
    agent_line_id TEXT,
    client_id TEXT,
    phone TEXT,
    direction TEXT NOT NULL,
    status TEXT NOT NULL,
    status_rank INTEGER NOT NULL,
    identity_status TEXT NOT NULL DEFAULT 'unknown',
    ambiguous_client_ids TEXT,
    last_event_timestamp TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_line_id) REFERENCES agent_lines(id)
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_key TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    call_control_id TEXT,
    event_timestamp TEXT,
    payload TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: Union[str, Path]) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
