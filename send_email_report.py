#!/usr/bin/env python3
"""
send_email_report.py

Sends the latest Debt Review report via SMTP (SendGrid compatible),
with a rich HTML body pulled from the 'Dashboard' sheet of the attached Excel.

Environment variables:
    SMTP_SERVER    e.g. smtp.sendgrid.net
    SMTP_PORT      e.g. 587
    SMTP_USER      e.g. apikey
    SMTP_PASSWORD  SendGrid API key (starts with SG.)
    EMAIL_FROM     Verified sender in SendGrid
    EMAIL_TO       Comma-separated recipients
"""

import os
import sys
import glob
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

import pandas as pd


# ------------------------------------------------------------------
# 1. Read env vars
# ------------------------------------------------------------------
def env(name, default=""):
    val = os.getenv(name)
    return val if val not in (None, "") else default


SMTP_SERVER   = env("SMTP_SERVER", "smtp.sendgrid.net")
SMTP_PORT_RAW = env("SMTP_PORT", "587")
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
# 2. Find latest report
# ------------------------------------------------------------------
def find_report():
    for pat in ["Debt_Review_Dashboard_*.xlsx", "*.xlsx",
                "reports/*.xlsx", "history/*.xlsx"]:
        found = glob.glob(pat)
        if found:
            found.sort(key=os.path.getmtime, reverse=True)
            return found[0]
    return None


report_path = find_report()
print(f"📎 Report: {report_path or '(none)'}")


# ------------------------------------------------------------------
# 3. Extract metrics from the Dashboard sheet
# ------------------------------------------------------------------
def load_metrics(path):
    """Return list of (metric_name, value_string) tuples from the Dashboard sheet."""
    if not path:
        return []
    try:
        df = pd.read_excel(path, sheet_name="Dashboard")
    except Exception as e:
        print(f"⚠️  Could not read Dashboard sheet: {e}")
        return []

    # The Dashboard sheet has two columns: 'Metric' and 'Value'
    if df.shape[1] < 2:
        return []

    metrics = []
    for _, row in df.iterrows():
        name  = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        value = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
        if name and name.lower() != "nan":
            metrics.append((name, value))
    return metrics


def metrics_to_dict(metrics):
    return {name: value for name, value in metrics}


metrics     = load_metrics(report_path)
metrics_map = metrics_to_dict(metrics)


# ------------------------------------------------------------------
# 4. Build highlights
# ------------------------------------------------------------------
def parse_amount(value):
    """Extract a numeric R amount from a string like '12 | R14,500.00' → 14500.0."""
    if not value:
        return 0.0
    try:
        chunk = value.split("|")[-1].replace("R", "").replace(",", "").strip()
        return float(chunk) if chunk else 0.0
    except Exception:
        return 0.0


def parse_count(value):
    """Extract the leading count from '12 | R14,500.00' → 12."""
    if not value:
        return 0
    try:
        return int(value.split("|")[0].strip())
    except Exception:
        return 0


highlights = []

# Total due this period
due_count = parse_count(metrics_map.get("Curr Month Debits (Stage 1/2)", ""))
due_value = parse_amount(metrics_map.get("Curr Month Debits (Stage 1/2)", ""))
if due_count:
    highlights.append(("📅", "Clients Due This Period",
                       f"{due_count} clients · R {due_value:,.2f}"))

# Settled
settled_count = parse_count(metrics_map.get("Settled Period (Stage 1/2)", ""))
settled_value = parse_amount(metrics_map.get("Settled Period (Stage 1/2)", ""))
if settled_count:
    highlights.append(("✅", "Settled",
                       f"{settled_count} clients · R {settled_value:,.2f}"))

# Failed
failed_count = parse_count(metrics_map.get("Failed Period (Stage 1/2)", ""))
failed_value = parse_amount(metrics_map.get("Failed Period (Stage 1/2)", ""))
if failed_count:
    highlights.append(("❌", "Failed",
                       f"{failed_count} clients · R {failed_value:,.2f}"))

# Disputed
disp_count = parse_count(metrics_map.get("Disputed (Stage 1/2)", ""))
disp_value = parse_amount(metrics_map.get("Disputed (Stage 1/2)", ""))
if disp_count:
    highlights.append(("⚠️", "Disputed",
                       f"{disp_count} clients · R {disp_value:,.2f}"))

# Cancelled mandate
cm_count = parse_count(metrics_map.get("Client Cancelled Mandate (Stage 1/2)", ""))
cm_value = parse_amount(metrics_map.get("Client Cancelled Mandate (Stage 1/2)", ""))
if cm_count:
    highlights.append(("🚫", "Client Cancelled Mandate",
                       f"{cm_count} clients · R {cm_value:,.2f}"))

# Sale Not Submitted
sns_count = parse_count(metrics_map.get("Sale Not Submitted (Stage 1/2)", ""))
sns_value = parse_amount(metrics_map.get("Sale Not Submitted (Stage 1/2)", ""))
if sns_count:
    highlights.append(("📭", "Sale Not Submitted",
                       f"{sns_count} clients · R {sns_value:,.2f}"))

# Revenue
revenue_value = metrics_map.get("Revenue Total (Stage 1/2, Period)", "")
if revenue_value:
    highlights.append(("💰", "Revenue", revenue_value))

# Success rate
success_rate = metrics_map.get(
    "Success Rate (Period, by value, Disputed = Failure)", "")
if success_rate:
    highlights.append(("🎯", "Success Rate", success_rate))


# ------------------------------------------------------------------
# 5. Render HTML
# ------------------------------------------------------------------
def html_body(metrics, highlights):
    today_str = datetime.now().strftime("%d %B %Y")

    # Highlights table
    hl_rows = ""
    for icon, label, value in highlights:
        hl_rows += (
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;'>{icon}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;'>"
            f"<strong>{label}</strong></td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;"
            f"text-align:right;'>{value}</td>"
            f"</tr>"
        )

    # Full dashboard table
    full_rows = ""
    for name, value in metrics:
        full_rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f0f0f0;"
            f"color:#555;'>{name}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f0f0f0;"
            f"text-align:right;'>{value}</td>"
            f"</tr>"
        )

    return f"""\
<html>
<body style="margin:0;padding:0;background:#f5f6f8;font-family:Arial,sans-serif;
             color:#1e1e2d;">
  <div style="max-width:640px;margin:0 auto;padding:24px 12px;">

    <div style="background:#ffffff;border-radius:12px;padding:24px;
                box-shadow:0 2px 8px rgba(0,0,0,0.06);">

      <h2 style="margin:0 0 4px 0;font-size:22px;color:#1e1e2d;">
        📊 Debt Review Dashboard
      </h2>
      <p style="margin:0 0 20px 0;color:#6c757d;font-size:14px;">
        Report generated {today_str}
      </p>

      <h3 style="font-size:16px;color:#1e1e2d;margin:0 0 8px 0;">
        Key Highlights
      </h3>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        {hl_rows if hl_rows else "<tr><td>No highlights available.</td></tr>"}
      </table>

      <h3 style="font-size:16px;color:#1e1e2d;margin:24px 0 8px 0;">
        Full Metrics
      </h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        {full_rows if full_rows else "<tr><td>No metrics available.</td></tr>"}
      </table>

      <p style="margin:24px 0 0 0;font-size:14px;color:#555;">
        📎 The full Excel report is attached.
      </p>

      <hr style="border:none;border-top:1px solid #eee;margin:24px 0 12px 0;">
      <p style="margin:0;font-size:12px;color:#999;">
        Sent automatically by the Debt Review Dashboard workflow.
      </p>
    </div>

  </div>
</body>
</html>
"""


# ------------------------------------------------------------------
# 6. Render plain-text fallback
# ------------------------------------------------------------------
def text_body(metrics, highlights):
    today_str = datetime.now().strftime("%d %B %Y")
    lines = [f"Debt Review Dashboard — {today_str}", "", "Key Highlights:"]
    for icon, label, value in highlights:
        lines.append(f"  {icon} {label}: {value}")
    lines.append("")
    lines.append("Full Metrics:")
    for name, value in metrics:
        lines.append(f"  {name}: {value}")
    lines.append("")
    lines.append("The full Excel report is attached.")
    lines.append("")
    lines.append("Sent automatically by the Debt Review Dashboard workflow.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# 7. Compose email
# ------------------------------------------------------------------
today_str = datetime.now().strftime("%d %B %Y")

msg = EmailMessage()
msg["Subject"] = f"Debt Review Report — {today_str}"
msg["From"]    = EMAIL_FROM
msg["To"]      = ", ".join(recipients)

# Plain text first, then HTML (multipart/alternative)
msg.set_content(text_body(metrics, highlights))
msg.add_alternative(html_body(metrics, highlights), subtype="html")

# Attach the Excel file
if report_path:
    try:
        with open(report_path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=os.path.basename(report_path),
        )
        print(f"   attached: {os.path.basename(report_path)} ({len(data):,} bytes)")
    except Exception as e:
        print(f"⚠️  Could not attach {report_path}: {e}")


# ------------------------------------------------------------------
# 8. Send
# ------------------------------------------------------------------
def send_via_ssl():
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx, timeout=30) as s:
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


def send_via_starttls():
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


try:
    print(f"📧 Connecting to {SMTP_SERVER}:{SMTP_PORT} …")
    if SMTP_PORT == 465:
        send_via_ssl()
    else:
        send_via_starttls()
    print(f"✅ Email sent successfully to: {', '.join(recipients)}")
except smtplib.SMTPAuthenticationError as e:
    print(f"❌ SMTP authentication failed: {e}")
    sys.exit(1)
except smtplib.SMTPServerDisconnected as e:
    print(f"❌ Server disconnected: {e}")
    sys.exit(1)
except smtplib.SMTPException as e:
    print(f"❌ SMTP error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e!r}")
    sys.exit(1)
