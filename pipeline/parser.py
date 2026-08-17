"""
CSV parser for bank statement exports.

Bank export formats vary a lot (column names, date formats, whether debit/credit
are separate columns or one signed amount column). Rather than guess, this
parser takes an explicit column mapping so it works with whatever your bank
actually gives you. Adjust COLUMN_MAP below once you've looked at a real export.

Currently configured for Al Salam Bank Algeria's "Releve de Compte" format:
Date | Libelle | Sens (D/C) | Montant | Solde, with DD-MM-YYYY dates and
comma-thousands/dot-decimal numbers (e.g. "30,000.00").

If your bank exports PDF instead of CSV, export/copy the table into a CSV first
(most Algerian bank portals let you export "releve de compte" as CSV or Excel).
"""
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

# --- EDIT THIS to match your bank's actual export column names ---
COLUMN_MAP = {
    "tx_date": "Date",
    "description": "Libelle",
    "sens": "Sens",        # 'D' = debit (money out), 'C' = credit (money in)
    "montant": "Montant",  # single unsigned amount column
}

# If your bank instead gives ONE already-signed amount column (no separate
# debit/credit indicator), set SINGLE_AMOUNT_COLUMN to that column name and
# set SENS_MODE to False.
SINGLE_AMOUNT_COLUMN = None  # e.g. "Montant" when there's no Sens column
SENS_MODE = True  # True = use the D/C 'Sens' column, False = signed amount column

DATE_FORMAT = "%d-%m-%Y"  # Al Salam Bank format. Use "%d/%m/%Y" for slash-separated dates.

# Al Salam Bank numbers use comma as thousands separator and dot as decimal
# (e.g. "30,000.00" = thirty thousand). Some other banks do the opposite
# (comma as decimal, e.g. European CSVs) — if so, swap the .replace() calls below.
NUMBER_USES_COMMA_THOUSANDS = True


def _row_hash(tx_date: str, description: str, amount: float) -> str:
    raw = f"{tx_date}|{description}|{amount:.2f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_csv(filepath: str, account_label: str = "default") -> pd.DataFrame:
    """
    Reads a raw bank CSV export and returns a normalized DataFrame with columns:
    tx_date, description, amount, account, source_file, raw_row_hash

    amount is signed: negative = money out, positive = money in.
    """
    path = Path(filepath)
    # Try a couple of common encodings — many Algerian bank exports use latin-1/cp1252.
    for encoding in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=encoding, sep=None, engine="python")
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    else:
        raise ValueError(f"Could not read {filepath} with any known encoding")

    out = pd.DataFrame()
    out["tx_date"] = df[COLUMN_MAP["tx_date"]].apply(
        lambda x: datetime.strptime(str(x).strip(), DATE_FORMAT).date().isoformat()
    )
    out["description"] = df[COLUMN_MAP["description"]].astype(str).str.strip()

    def _to_float(series: pd.Series) -> pd.Series:
        s = series.astype(str).str.replace(" ", "", regex=False)
        if NUMBER_USES_COMMA_THOUSANDS:
            # "30,000.00" -> "30000.00"
            s = s.str.replace(",", "", regex=False)
        else:
            # European style "30.000,00" -> "30000.00"
            s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        return s.replace("", "0").astype(float)

    if SENS_MODE:
        magnitude = _to_float(df[COLUMN_MAP["montant"]])
        sign = df[COLUMN_MAP["sens"]].astype(str).str.strip().str.upper().map(
            {"D": -1, "C": 1}
        )
        if sign.isna().any():
            bad = df.loc[sign.isna(), COLUMN_MAP["sens"]].unique()
            raise ValueError(f"Unrecognized 'Sens' values (expected D/C): {bad}")
        out["amount"] = magnitude * sign
    elif SINGLE_AMOUNT_COLUMN:
        out["amount"] = _to_float(df[SINGLE_AMOUNT_COLUMN])
    else:
        debit = _to_float(df[COLUMN_MAP["debit"]])
        credit = _to_float(df[COLUMN_MAP["credit"]])
        out["amount"] = credit - debit

    out["account"] = account_label
    out["source_file"] = path.name
    out["raw_row_hash"] = out.apply(
        lambda r: _row_hash(r["tx_date"], r["description"], r["amount"]), axis=1
    )

    return out
