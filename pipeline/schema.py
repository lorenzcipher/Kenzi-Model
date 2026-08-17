"""
SQLite schema for the budget advisor.

Run this file directly to create/reset the local database:
    python pipeline/schema.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "budget.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_date         TEXT NOT NULL,          -- ISO format YYYY-MM-DD
    description     TEXT NOT NULL,          -- raw description from bank export
    amount          REAL NOT NULL,          -- negative = expense, positive = income
    currency        TEXT NOT NULL DEFAULT 'DZD',
    category        TEXT NOT NULL DEFAULT 'uncategorized',
    category_source TEXT NOT NULL DEFAULT 'none',   -- 'rule', 'llm', or 'manual'
    account         TEXT,                   -- which account/card this came from
    source_file     TEXT,                   -- which import file this row came from
    raw_row_hash    TEXT UNIQUE,            -- prevents duplicate imports
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(tx_date);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);

CREATE TABLE IF NOT EXISTS category_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT NOT NULL UNIQUE,   -- lowercase substring to match in description
    category    TEXT NOT NULL
);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print(f"Database ready at {db_path}")
    finally:
        conn.close()


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


if __name__ == "__main__":
    init_db()
