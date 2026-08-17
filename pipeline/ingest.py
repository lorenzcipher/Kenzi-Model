"""
End-to-end ingestion: CSV -> parsed -> categorized -> stored in SQLite.

Usage:
    python pipeline/ingest.py data/sample_transactions.csv --account checking
"""
import argparse
import sqlite3

from categorizer import categorize, load_rules, seed_rules
from parser import parse_csv
from schema import get_connection, init_db


def ingest_file(filepath: str, account_label: str) -> None:
    conn = get_connection()
    init_db()  # safe to call repeatedly, creates tables if missing
    seed_rules(conn)  # safe to call repeatedly, uses INSERT OR IGNORE

    df = parse_csv(filepath, account_label=account_label)
    rules = load_rules(conn)

    inserted, skipped = 0, 0
    cur = conn.cursor()
    for _, row in df.iterrows():
        category, source = categorize(row["description"], rules)
        try:
            cur.execute(
                """
                INSERT INTO transactions
                    (tx_date, description, amount, category, category_source,
                     account, source_file, raw_row_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["tx_date"],
                    row["description"],
                    row["amount"],
                    category,
                    source,
                    row["account"],
                    row["source_file"],
                    row["raw_row_hash"],
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # raw_row_hash already exists -> this transaction was already imported
            skipped += 1

    conn.commit()
    conn.close()

    print(f"Imported {inserted} transactions ({skipped} duplicates skipped).")

    uncategorized = df.shape[0] - inserted + skipped  # rough signal, refined below
    _print_uncategorized_summary()


def _print_uncategorized_summary() -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM transactions WHERE category = 'uncategorized'"
    )
    count = cur.fetchone()[0]
    conn.close()
    if count:
        print(f"{count} transactions are still 'uncategorized'. "
              f"Add keywords to DEFAULT_RULES in categorizer.py, or run the "
              f"LLM fallback for these.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest a bank CSV export.")
    ap.add_argument("filepath", help="Path to the CSV file to import")
    ap.add_argument("--account", default="default", help="Label for this account")
    args = ap.parse_args()

    ingest_file(args.filepath, args.account)
