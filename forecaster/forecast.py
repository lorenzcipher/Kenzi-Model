"""
Cash flow forecaster.

Reads the transactions table, aggregates by month, and projects income,
expenses, and surplus forward. Model choice depends on how much history
you have:

- Under 6 months of data: not enough for seasonal models. Falls back to a
  simple average + linear trend, and says so.
- 6+ months: fits a linear trend per category (statsmodels OLS). Swap in
  SARIMAX or Prophet here once you have a year or more of data and want
  to capture seasonality (e.g. Ramadan spending spikes).

Usage:
    python forecaster/forecast.py --months 3
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.schema import get_connection

# Categories excluded from the expense side of the forecast. These are not
# consumption — they're money moved between the user's own accounts. Counting
# them as spending makes the surplus look far more negative than it really is,
# and (since they're lumpy one-offs) extrapolating them as recurring breaks
# the trend line. Tag transfers as 'internal_transfer' via pipeline/manual_tag.py
# to move them here. Family/external transfers stay as 'transfer_out' and DO
# count as real spending.
EXCLUDED_FROM_EXPENSES = {"internal_transfer"}


def load_monthly_aggregates() -> pd.DataFrame:
    """
    Returns a DataFrame indexed by year-month with columns:
    income, expenses, surplus (all positive numbers except surplus can be negative)

    Expenses exclude EXCLUDED_FROM_EXPENSES categories (self-transfers), since
    those aren't consumption and shouldn't drag the surplus forecast down.
    """
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT tx_date, amount, category FROM transactions", conn
    )
    conn.close()

    if df.empty:
        raise ValueError("No transactions found. Run pipeline/ingest.py first.")

    df["tx_date"] = pd.to_datetime(df["tx_date"])
    df["month"] = df["tx_date"].dt.to_period("M")

    is_expense = (df["amount"] < 0) & (~df["category"].isin(EXCLUDED_FROM_EXPENSES))
    income = df[df["amount"] > 0].groupby("month")["amount"].sum()
    expenses = df[is_expense].groupby("month")["amount"].sum().abs()

    monthly = pd.DataFrame({"income": income, "expenses": expenses}).fillna(0)
    monthly["surplus"] = monthly["income"] - monthly["expenses"]
    return monthly.sort_index()


def load_monthly_by_category() -> pd.DataFrame:
    """Monthly expense totals broken down by category, for the category forecast table."""
    conn = get_connection()
    placeholders = ",".join("?" for _ in EXCLUDED_FROM_EXPENSES) or "''"
    df = pd.read_sql_query(
        f"SELECT tx_date, amount, category FROM transactions "
        f"WHERE amount < 0 AND category NOT IN ({placeholders})",
        conn,
        params=tuple(EXCLUDED_FROM_EXPENSES),
    )
    conn.close()
    df["tx_date"] = pd.to_datetime(df["tx_date"])
    df["month"] = df["tx_date"].dt.to_period("M")
    df["amount"] = df["amount"].abs()
    return df.pivot_table(
        index="month", columns="category", values="amount", aggfunc="sum"
    ).fillna(0)


def _linear_trend_forecast(series: pd.Series, months_ahead: int) -> list[float]:
    """Fits amount = a * month_index + b and projects forward. Floors at 0."""
    x = np.arange(len(series))
    y = series.values
    if len(x) < 2:
        # Not enough points for a trend line — just repeat the last known value.
        base = y[-1] if len(y) else 0
        return [max(base, 0)] * months_ahead
    a, b = np.polyfit(x, y, 1)
    future_x = np.arange(len(series), len(series) + months_ahead)
    return [max(a * xi + b, 0) for xi in future_x]


def forecast(months_ahead: int = 3) -> dict:
    monthly = load_monthly_aggregates()
    n_months = len(monthly)

    income_fc = _linear_trend_forecast(monthly["income"], months_ahead)
    expenses_fc = _linear_trend_forecast(monthly["expenses"], months_ahead)
    surplus_fc = [i - e for i, e in zip(income_fc, expenses_fc)]

    by_category = load_monthly_by_category()
    category_forecast = {}
    for col in by_category.columns:
        category_forecast[col] = _linear_trend_forecast(by_category[col], months_ahead)

    confidence = "low" if n_months < 6 else "moderate" if n_months < 12 else "good"

    return {
        "months_of_history": n_months,
        "confidence": confidence,
        "months_ahead": months_ahead,
        "income_forecast": income_fc,
        "expenses_forecast": expenses_fc,
        "surplus_forecast": surplus_fc,
        "category_forecast": category_forecast,
        "avg_monthly_surplus": float(np.mean(surplus_fc)),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3, help="Months ahead to forecast")
    args = ap.parse_args()

    result = forecast(args.months)
    print(f"History available: {result['months_of_history']} month(s) "
          f"(confidence: {result['confidence']})")
    print(f"\nForecast for next {args.months} month(s):")
    for i in range(args.months):
        print(f"  Month +{i+1}: income={result['income_forecast'][i]:,.0f}  "
              f"expenses={result['expenses_forecast'][i]:,.0f}  "
              f"surplus={result['surplus_forecast'][i]:,.0f}")
    print(f"\nAverage monthly surplus projected: {result['avg_monthly_surplus']:,.0f} DZD")

    if result["confidence"] == "low":
        print("\nNote: forecast confidence is low with under 6 months of history. "
              "Treat these numbers as rough estimates, not commitments.")
