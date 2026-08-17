"""
Manual tagging tool for transactions the rule-based categorizer can't resolve
(mainly Al Salam Bank's "Transaction Monetique" entries, which carry only a
card/reference number and no merchant name).

Run this after ingest.py. It walks through untagged 'card_purchase' rows one
at a time — you type a category, it saves and moves on. Ctrl+C anytime to stop
and keep what you've done so far.

Usage:
    python pipeline/manual_tag.py
    python pipeline/manual_tag.py --category card_purchase   # review a different bucket
"""
import argparse

from schema import get_connection

COMMON_CATEGORIES = [
    "groceries", "dining", "transport", "shopping", "health",
    "subscriptions", "utilities", "telecom", "cash_withdrawal",
    "internal_transfer", "transfer_out", "other",
]


def review(target_category: str = "card_purchase") -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, tx_date, description, amount FROM transactions "
        "WHERE category = ? AND category_source != 'manual' ORDER BY tx_date",
        (target_category,),
    )
    rows = cur.fetchall()

    if not rows:
        print(f"Nothing to review in '{target_category}'.")
        conn.close()
        return

    print(f"{len(rows)} transaction(s) to tag. Suggested categories:")
    print(", ".join(COMMON_CATEGORIES))
    print("Type a category, 's' to skip, or 'q' to quit.\n")

    tagged = 0
    try:
        for tx_id, tx_date, description, amount in rows:
            print(f"[{tx_date}] {description}  ->  {amount:,.2f} DZD")
            answer = input("  category: ").strip().lower()

            if answer == "q":
                break
            if answer == "s" or not answer:
                continue

            cur.execute(
                "UPDATE transactions SET category = ?, category_source = 'manual' "
                "WHERE id = ?",
                (answer, tx_id),
            )
            conn.commit()
            tagged += 1
    except KeyboardInterrupt:
        print("\nStopped early.")

    print(f"\nTagged {tagged} transaction(s). Run again anytime to keep going.")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="card_purchase",
                     help="Which existing category bucket to review")
    args = ap.parse_args()
    review(args.category)
