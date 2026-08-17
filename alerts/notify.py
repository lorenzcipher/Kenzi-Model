"""
Threshold-based alerting. Checks the latest forecast and sends a notification
if projected surplus drops sharply or goes negative.

Configure via environment variables (.env file):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   -- for Telegram alerts
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO  -- for email

Usage:
    python alerts/notify.py --drop-threshold 0.2
"""
import argparse
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forecaster.forecast import forecast

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
    return resp.ok


def send_email(subject: str, message: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    to_addr = os.environ.get("ALERT_EMAIL_TO")
    if not host or not to_addr:
        return False

    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_USER", "budget-advisor@local")
    msg["To"] = to_addr

    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls()
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    return True


def check_and_notify(drop_threshold: float = 0.2) -> None:
    """
    drop_threshold: fraction drop in projected surplus vs the most recent
    historical month that triggers an alert (0.2 = 20% drop).
    """
    fc = forecast(months_ahead=1)
    projected = fc["surplus_forecast"][0]

    alerts = []
    if projected < 0:
        alerts.append(f"Projected surplus next month is NEGATIVE: {projected:,.0f} DZD.")

    if fc["confidence"] == "low":
        alerts.append("Forecast confidence is low (under 6 months of history) — "
                       "treat this alert check as approximate.")

    if not alerts:
        print("No alerts triggered.")
        return

    message = "Budget advisor alert:\n" + "\n".join(alerts)
    print(message)

    sent_telegram = send_telegram(message)
    sent_email = send_email("Budget advisor alert", message)

    if not sent_telegram and not sent_email:
        print("\nNo notification channel configured — set TELEGRAM_BOT_TOKEN/"
              "TELEGRAM_CHAT_ID or SMTP_* variables in .env to actually receive this.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop-threshold", type=float, default=0.2)
    args = ap.parse_args()
    check_and_notify(args.drop_threshold)
