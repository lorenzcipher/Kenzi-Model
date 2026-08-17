"""
Rule-based categorizer.

Matches transaction descriptions against keyword rules stored in the
category_rules table. Falls back to 'uncategorized' if nothing matches.

Start simple with keyword rules. Once you have a few hundred uncategorized
transactions, that's the point to add an LLM fallback (see categorize_llm
below, disabled by default).
"""
import sqlite3
from pathlib import Path

from schema import DB_PATH, get_connection

# Seed rules — edit freely, these are just a starting point.
# Add your own recurring merchants/keywords as you see them in your data.
#
# Al Salam Bank specific: most "Transaction Monetique" / "Op retrait" / "Op
# paiement" entries carry only a card/reference number, no merchant name.
# There's nothing to pattern-match there — mapped to honest catch-all buckets
# below ('card_purchase', 'cash_withdrawal') rather than 'uncategorized'.
# See pipeline/manual_tag.py to enrich these into real categories over time.
DEFAULT_RULES = {
    # keyword (lowercase substring) -> category
    # --- bank fees, always essential/untouchable ---
    "tva sur com": "bank_fees",
    "commission payee": "bank_fees",
    "commission carte": "bank_fees",
    # --- cash withdrawals (generic, no merchant) ---
    "retrait espece": "cash_withdrawal",
    "op retrait": "cash_withdrawal",
    # --- card/generic payments (no merchant) ---
    "op paiement": "card_purchase",
    "transaction monetique": "card_purchase",
    # --- transfers ---
    "virement recu": "transfer_in",
    "virement de salaire": "income",
    "virement ordonne": "transfer_out",
    "virement vers": "transfer_out",
    "cheque collection": "transfer_in",
    "operation diverse": "other_income",
    "djezzy": "telecom",
    "mobilis": "telecom",
    "ooredoo": "telecom",
    "sonelgaz": "utilities",
    "seaal": "utilities",
    "algerie telecom": "utilities",
    "carrefour": "groceries",
    "uno": "groceries",
    "ardis": "groceries",
    "cevital": "groceries",
    "naftal": "transport",
    "essence": "transport",
    "taxi": "transport",
    "yassir": "transport",
    "glovo": "food_delivery",
    "restaurant": "dining",
    "cafe": "dining",
    "pharmacie": "health",
    "clinique": "health",
    "loyer": "rent",
    "virement": "transfer",
    "salaire": "income",
    "retrait": "cash_withdrawal",
    "gab": "cash_withdrawal",
    "amazon": "shopping",
    "aliexpress": "shopping",
    "netflix": "subscriptions",
    "spotify": "subscriptions",
}


def seed_rules(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for keyword, category in DEFAULT_RULES.items():
        cur.execute(
            "INSERT OR IGNORE INTO category_rules (keyword, category) VALUES (?, ?)",
            (keyword, category),
        )
    conn.commit()


def load_rules(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT keyword, category FROM category_rules")
    return dict(cur.fetchall())


def categorize(description: str, rules: dict) -> tuple[str, str]:
    """
    Returns (category, source). source is 'rule' if matched, else 'none'.

    Checks longest keywords first, so a specific rule like 'virement de
    salaire' wins over a generic one like 'virement' that happens to also
    be a substring — otherwise whichever rule was inserted into the DB
    first would win regardless of specificity, which silently swallows
    more precise rules added later.
    """
    desc_lower = description.lower()
    for keyword in sorted(rules.keys(), key=len, reverse=True):
        if keyword in desc_lower:
            return rules[keyword], "rule"
    return "uncategorized", "none"


def categorize_llm(description: str) -> str:
    """
    Optional fallback for transactions no rule matches.
    Only call this in small batches — it costs an API call per transaction.
    Requires GEMINI_API_KEY in your environment (see advisor/client.py).
    """
    from advisor.client import ask

    prompt = (
        "Classify this bank transaction description into exactly one category "
        "from this list: groceries, dining, transport, utilities, telecom, rent, "
        "health, shopping, subscriptions, transfer, income, cash_withdrawal, other.\n"
        f'Description: "{description}"\n'
        "Reply with only the category word, nothing else."
    )
    return ask(prompt, max_tokens=10).strip().lower()


def recategorize_existing(conn: sqlite3.Connection) -> int:
    """
    Reapplies current rules to every transaction NOT manually tagged.
    Safe to run anytime rules change — never overwrites category_source='manual'.
    Returns the number of rows changed.
    """
    rules = load_rules(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, description FROM transactions WHERE category_source != 'manual'"
    )
    rows = cur.fetchall()

    changed = 0
    for tx_id, description in rows:
        category, source = categorize(description, rules)
        cur.execute(
            "UPDATE transactions SET category = ?, category_source = ? WHERE id = ?",
            (category, source, tx_id),
        )
        changed += 1
    conn.commit()
    return changed


if __name__ == "__main__":
    conn = get_connection()
    seed_rules(conn)
    print(f"Seeded {len(DEFAULT_RULES)} category rules into {DB_PATH}")
    n = recategorize_existing(conn)
    print(f"Recategorized {n} existing transaction(s) with current rules.")
    conn.close()
