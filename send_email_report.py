#!/usr/bin/env python3
"""
send_email_report.py

Sends three emails via SMTP (SendGrid compatible):

  1. Full Debt Review report (HTML summary + Excel attachment)
        → EMAIL_TO        (default: taahir@nationaldebt.org.za)
  2. Failed Clients list (Excel attachment)
        → TO_EMAIL_SMS    (default: reece@nationaldebt.org.za)
  3. Intracking Clients list (Excel attachment)
        → TO_EMAIL_SMS    (default: reece@nationaldebt.org.za)

Sale Not Submitted stays inside the main Excel report as a tab.
"""

import os
import sys
import glob
import io
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

import pandas as pd


# ------------------------------------------------------------------
# 1. Env helpers
# ------------------------------------------------------------------
def env(name, default=""):
    val = os.getenv(name)
    return val if val not in (None, "") else default


SMTP_SERVER   = env("SMTP_SERVER", "smtp.sendgrid.net")
SMTP_PORT_RAW = env("SMTP_PORT", "587")
SMTP_USER     = env("SMTP_USER", "apikey")
SMTP_PASSWORD = env("SMTP_PASSWORD")
EMAIL_FROM    = env("EMAIL_FROM", SMTP_USER)

# Recipients (fallbacks baked in so this works even if secrets are missing)
EMAIL_TO_REPORT = env("EMAIL_TO",          "taahir@nationaldebt.org.za")
EMAIL_TO_SMS    = env("TO_EMAIL_SMS",      "reece@nationaldebt.org.za")


# ------------------------------------------------------------------
# 2. Startup diagnostics
# ------------------------------------------------------------------
def banner(title):
    print("=" * 64)
    print(title)
    print("=" * 64)


banner("SMTP configuration")
print(f"  SMTP_SERVER     : {SMTP_SERVER!r}")
print(f"  SMTP_PORT       : {SMTP_PORT_RAW!r}")
print(f"  SMTP_USER       : {SMTP_USER!r}")
print(f"  SMTP_PASSWORD   : {'*' * len(SMTP_PASSWORD) if SMTP_PASSWORD else '(empty)'}")
print(f"  EMAIL_FROM      : {EMAIL_FROM!r}")
print(f"  EMAIL_TO        : {EMAIL_TO_REPORT!r}   (full report)")
print(f"  TO_EMAIL_SMS    : {EMAIL_TO_SMS!r}   (failed + intracking)")
print("=" * 64)

required = {
    "SMTP_SERVER":   SMTP_SERVER,
    "SMTP_PORT":     SMTP_PORT_RAW,
    "SMTP_USER":     SMTP_USER,
    "SMTP_PASSWORD": SMTP_PASSWORD,
    "EMAIL_FROM":    EMAIL_FROM,
}
missing = [k for k, v in required.items() if not v]
if missing:
    print(f"❌ Missing required configuration: {', '.join(missing)}")
    sys.exit(1)

try:
    SMTP_PORT = int(SMTP_PORT_RAW)
except ValueError:
    print(f"❌ SMTP_PORT must be an integer, got {SMTP_PORT_RAW!r}")
    sys.exit(1)


# ------------------------------------------------------------------
# 3. File discovery
# ------------------------------------------------------------------
def find_latest(patterns):
    """Return the newest file matching any pattern, or None."""
    for pat in patterns:
        matches = glob.glob(pat)
        if matches:
            matches.sort(key=os.path.getmtime, reverse=True)
            return matches[0]
    return None


banner("Locating files")

report_path = find_latest([
    "Debt_Review_Dashboard_*.xlsx",
    "reports/Debt_Review_Dashboard_*.xlsx",
    "*.xlsx",
])
print(f"  Report          : {report_path}")

failed_path = find_latest([
    "failed_sms.xlsx", "failed_sms.csv",
    "failed_clients.xlsx", "failed_clients.csv",
    "Failed_Clients.xlsx", "Failed_Clients.csv",
    "*Failed*.xlsx", "*Failed*.csv",
    "*failed*.xlsx", "*failed*.csv",
])
print(f"  Failed list     : {failed_path}")

tracking_path = find_latest([
    "intracking_sms.xlsx", "intracking_sms.csv",
    "intracking_clients.xlsx", "intracking_clients.csv",
    "Intracking_Clients.xlsx", "Intracking_Clients.csv",
    "*Intracking*.xlsx", "*Intracking*.csv",
    "*intracking*.xlsx", "*intracking*.csv",
])
print(f"  Intracking list : {tracking_path}")


# ------------------------------------------------------------------
# 4. Excel helpers
# ------------------------------------------------------------------
def read_any(path):
    """Read CSV or Excel into a DataFrame."""
    if not path:
        return None
    if path.lower().endswith(".csv"):
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return pd.read_csv(path, encoding="latin-1")
    return pd.read_excel(path)


def excel_bytes(df, sheet_name="Sheet1"):
    """Return the DataFrame as an in-memory .xlsx file (bytes)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


# ------------------------------------------------------------------
# 5. Email bodies
# ------------------------------------------------------------------
def dashboard_metrics(path):
    """Return [(metric, value), ...] from the Dashboard sheet."""
    if not path:
        return []
    try:
        df = pd.read_excel(path, sheet_name="Dashboard")
    except Exception as e:
        print(f"⚠️  No Dashboard sheet in {path}: {e}")
        return []
    out = []
    for _, row in df.iterrows():
        name  = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        value = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
        if name and name.lower() != "nan":
            out.append((name, value))
    return out


def html_report_body(metrics, attached_name):
    today_str = datetime.now().strftime("%d %B %Y")
    rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#555;'>{n}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right;'>{v}</td>"
        f"</tr>"
        for n, v in metrics
    )
    return f"""\
<div style="max-width:640px;margin:0 auto;padding:20px 12px;font-family:Arial,Helvetica,sans-serif;color:#1e1e2d;">
  <h2 style="margin:0 0 4px 0;font-size:22px;">📊 Debt Review Dashboard</h2>
  <p style="margin:0 0 20px 0;color:#6c757d;font-size:14px;">Report generated {today_str}</p>

  <h3 style="font-size:15px;margin:0 0 8px 0;">Key Metrics</h3>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    {rows if rows else "<tr><td>No metrics found.</td></tr>"}
  </table>

  <p style="margin:20px 0 0 0;font-size:13px;color:#555;">
    📎 Full Excel report attached: <strong>{attached_name}</strong>
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0 10px 0;">
  <p style="margin:0;font-size:11px;color:#999;">Sent automatically by the Debt Review Dashboard workflow.</p>
</div>
"""


def text_report_body(metrics, attached_name):
    today_str = datetime.now().strftime("%d %B %Y")
    lines = [f"Debt Review Dashboard — {today_str}", "", "Key Metrics:"]
    for n, v in metrics:
        lines.append(f"  {n}: {v}")
    lines.append("")
    lines.append(f"Full Excel report attached: {attached_name}")
    lines.append("Sent automatically by the Debt Review Dashboard workflow.")
    return "\n".join(lines)


def simple_html(title, intro, attached_name):
    return f"""\
<div style="max-width:640px;margin:0 auto;padding:20px 12px;font-family:Arial,Helvetica,sans-serif;color:#1e1e2d;">
  <h2 style="margin:0 0 4px 0;font-size:20px;">{title}</h2>
  <p style="margin:0 0 16px 0;color:#6c757d;font-size:14px;">{intro}</p>
  <p style="margin:0;font-size:13px;color:#555;">
    📎 Excel attachment: <strong>{attached_name}</strong>
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0 10px 0;">
  <p style="margin:0;font-size:11px;color:#999;">Sent automatically by the Debt Review Dashboard workflow.</p>
</div>
"""


# ------------------------------------------------------------------
# 6. Build the three messages
# ------------------------------------------------------------------
today_str = datetime.now().strftime("%d %B %Y")

# -------- Email 1: Full report --------
metrics = dashboard_metrics(report_path)
msg_report = EmailMessage()
msg_report["Subject"] = f"Debt Review Report — {today_str}"
msg_report["From"]    = EMAIL_FROM
msg_report["To"]      = EMAIL_TO_REPORT

if report_path:
    report_name = os.path.basename(report_path)
    msg_report.set_content(text_report_body(metrics, report_name))
    msg_report.add_alternative(html_report_body(metrics, report_name), subtype="html")
    with open(report_path, "rb") as f:
        msg_report.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=report_name,
        )
    print(f"📧 Report email prepared — attach: {report_name}")
else:
    msg_report.set_content(f"Debt Review Report — {today_str}\n\n"
                           "⚠️ No Excel report file was found in the repo.")
    print("⚠️ No report file found — sending notification only.")

# -------- Email 2: Failed clients --------
msg_failed = None
if failed_path:
    failed_df = read_any(failed_path)
    if failed_df is not None and not failed_df.empty:
        base = os.path.splitext(os.path.basename(failed_path))[0]
        attach_name = f"{base}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        data = excel_bytes(failed_df, sheet_name="Failed Clients")

        msg_failed = EmailMessage()
        msg_failed["Subject"] = f"Failed Clients — {today_str} ({len(failed_df)} rows)"
        msg_failed["From"]    = EMAIL_FROM
        msg_failed["To"]      = EMAIL_TO_SMS
        msg_failed.set_content(
            f"Failed Clients list for {today_str}.\n\n"
            f"Total records: {len(failed_df)}\n"
            f"Excel attachment: {attach_name}\n\n"
            "Sent automatically by the Debt Review Dashboard workflow."
        )
        msg_failed.add_alternative(
            simple_html(
                "❌ Failed Clients",
                f"{len(failed_df)} records · {today_str}",
                attach_name,
            ),
            subtype="html",
        )
        msg_failed.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attach_name,
        )
        print(f"📧 Failed email prepared — {len(failed_df)} rows → {EMAIL_TO_SMS}")
    else:
        print("⚠️ Failed file found but empty — skipping email.")
else:
    print("⚠️ No failed clients file found — skipping email.")

# -------- Email 3: Intracking clients --------
msg_tracking = None
if tracking_path:
    tracking_df = read_any(tracking_path)
    if tracking_df is not None and not tracking_df.empty:
        base = os.path.splitext(os.path.basename(tracking_path))[0]
        attach_name = f"{base}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        data = excel_bytes(tracking_df, sheet_name="Intracking Clients")

        msg_tracking = EmailMessage()
        msg_tracking["Subject"] = f"Intracking Clients — {today_str} ({len(tracking_df)} rows)"
        msg_tracking["From"]    = EMAIL_FROM
        msg_tracking["To"]      = EMAIL_TO_SMS
        msg_tracking.set_content(
            f"Intracking Clients list for {today_str}.\n\n"
            f"Total records: {len(tracking_df)}\n"
            f"Excel attachment: {attach_name}\n\n"
            "Sent automatically by the Debt Review Dashboard workflow."
        )
        msg_tracking.add_alternative(
            simple_html(
                "🔄 Intracking Clients",
                f"{len(tracking_df)} records · {today_str}",
                attach_name,
            ),
            subtype="html",
        )
        msg_tracking.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attach_name,
        )
        print(f"📧 Intracking email prepared — {len(tracking_df)} rows → {EMAIL_TO_SMS}")
    else:
        print("⚠️ Intracking file found but empty — skipping email.")
else:
    print("⚠️ No intracking clients file found — skipping email.")


# ------------------------------------------------------------------
# 7. Send all messages over one SMTP connection
# ------------------------------------------------------------------
messages = [("Report", msg_report)]
if msg_failed:   messages.append(("Failed", msg_failed))
if msg_tracking: messages.append(("Intracking", msg_tracking))


def send_all():
    print(f"📧 Connecting to {SMTP_SERVER}:{SMTP_PORT} …")
    if SMTP_PORT == 465:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx, timeout=30) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            for label, m in messages:
                s.send_message(m)
                print(f"   ✅ {label} sent → {m['To']}")
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(SMTP_USER, SMTP_PASSWORD)
            for label, m in messages:
                s.send_message(m)
                print(f"   ✅ {label} sent → {m['To']}")


try:
    send_all()
    print(f"\n🎉 Done — {len(messages)} email(s) dispatched.")
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
