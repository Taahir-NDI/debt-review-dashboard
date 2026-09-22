#!/usr/bin/env python3
"""
send_email_report.py — Sends the latest Debt Review report via SMTP.
Works with Gmail on port 465 (SSL) or 587 (STARTTLS).
"""

import os
import sys
import glob
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime


# ------------------------------------------------------------------
# 1. Read env vars — treat empty strings as unset
# ------------------------------------------------------------------
def env(name, default=""):
    val = os.getenv(name)
    return val if val not in (None, "") else default


SMTP_SERVER   = env("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT_RAW = env("SMTP_PORT", "465")          # default to 465 now
SMTP_USER     = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
EMAIL_FROM    = env("EMAIL_FROM", SMTP_USER)
EMAIL_TO      = env("EMAIL_TO")

print("=" * 60)
print("SMTP configuration")
print("=" * 60)
print(f"  SMTP_SERVER   : {SMTP_SERVER!r}")
print(f"  SMTP_PORT     : {SMTP_PORT_RAW!r}")
print(f"  SMTP_USER     : {SMTP_USER!r}")
print(f"  SMTP_PASSWORD : {'*' * len(SMTP_PASSWORD) if SMTP_PASSWORD else '(empty)'}")
print(f"  EMAIL_FROM    : {EMAIL_FROM!r}")
print(f"  EMAIL_TO      : {EMAIL_TO!r}")
print("=" * 60)

missing = [n for n, v in [
    ("SMTP_SERVER", SMTP_SERVER),
    ("SMTP_PORT", SMTP_PORT_RAW),
    ("SMTP_USER", SMTP_USER),
    ("SMTP_PASSWORD", SMTP_PASSWORD),
    ("EMAIL_FROM", EMAIL_FROM),
    ("EMAIL_TO", EMAIL_TO),
] if not v]

if missing:
    print(f"❌ Missing required configuration: {', '.join(missing)}")
    sys.exit(1)

try:
    SMTP_PORT = int(SMTP_PORT_RAW)
except ValueError:
    print(f"❌ SMTP_PORT must be an integer, got {SMTP_PORT_RAW!r}")
    sys.exit(1)

recipients = [a.strip() for a in EMAIL_TO.split(",") if a.strip()]
if not recipients:
    print("❌ EMAIL_TO contained no valid addresses.")
    sys.exit(1)


# ------------------------------------------------------------------
# 2. Find the report to attach
# ------------------------------------------------------------------
def find_reports():
    for pat in ["Debt_Review_Dashboard_*.xlsx", "*.xlsx",
                "reports/*.xlsx", "history/*.xlsx"]:
        found = glob.glob(pat)
        if found:
            found.sort(key=os.path.getmtime, reverse=True)
            return [found[0]]
    return []


attachments = find_reports()
print(f"📎 Attachments found: {attachments if attachments else '(none)'}")


# ------------------------------------------------------------------
# 3. Build the email
# ------------------------------------------------------------------
today_str = datetime.now().strftime("%d %B %Y")
msg = EmailMessage()
msg["Subject"] = f"Debt Review Report — {today_str}"
msg["From"]    = EMAIL_FROM
msg["To"]      = ", ".join(recipients)

msg.set_content(f"""Hi,

Please find attached the Debt Review report for {today_str}.

This email was generated automatically by the Debt Review Dashboard workflow.

Regards,
Debt Review Dashboard
""")

for path in attachments:
    try:
        with open(path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=os.path.basename(path),
        )
        print(f"   attached: {os.path.basename(path)} ({len(data):,} bytes)")
    except Exception as e:
        print(f"⚠️  Could not attach {path}: {e}")


# ------------------------------------------------------------------
# 4. Send
# ------------------------------------------------------------------
def send_via_ssl():
    """Port 465 — implicit TLS. Most reliable in GitHub Actions."""
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx, timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def send_via_starttls():
    """Port 587 — plaintext connect, upgrade with STARTTLS.
    Correct order: ehlo() -> starttls() -> ehlo() -> login()."""
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.ehlo()                                    # 1st EHLO (plaintext)
        server.starttls(context=ssl.create_default_context())  # upgrade
        server.ehlo()                                    # 2nd EHLO (inside TLS) — REQUIRED
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


try:
    print(f"📧 Connecting to {SMTP_SERVER}:{SMTP_PORT} …")
    if SMTP_PORT == 465:
        send_via_ssl()
    else:
        send_via_starttls()

    print(f"✅ Email sent successfully to: {', '.join(recipients)}")

except smtplib.SMTPAuthenticationError as e:
    print("❌ SMTP authentication failed.")
    print("   For Gmail: use a 16-character App Password, not your login password.")
    print(f"   Server said: {e}")
    sys.exit(1)

except smtplib.SMTPServerDisconnected as e:
    print(f"❌ Server disconnected: {e}")
    print("   This usually means the network blocked the SMTP port.")
    print("   Try SMTP_PORT=465 with the SSL branch (this script handles both).")
    sys.exit(1)

except smtplib.SMTPException as e:
    print(f"❌ SMTP error: {e}")
    sys.exit(1)

except Exception as e:
    print(f"❌ Unexpected error: {e!r}")
    sys.exit(1)
