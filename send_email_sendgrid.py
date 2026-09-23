#!/usr/bin/env python3
"""
send_email_sendgrid.py

Downloads the latest Debt Review report + Failed + Intracking files
from Google Drive, then sends three emails via SendGrid SMTP:

  1. Full report          → EMAIL_TO
  2. Failed Clients       → TO_EMAIL_SMS
  3. Intracking Clients   → TO_EMAIL_SMS
"""

import os
import sys
import io
import ssl
import smtplib
import tempfile
from email.message import EmailMessage
from datetime import datetime

import pandas as pd
import xlsxwriter

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


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

EMAIL_TO_REPORT = env("EMAIL_TO",     "taahir@nationaldebt.org.za")
EMAIL_TO_SMS    = env("TO_EMAIL_SMS", "reece@nationaldebt.org.za")

FOLDER_ID = env("FOLDER_ID")

print("=" * 64)
print("Configuration")
print("=" * 64)
print(f"  SMTP_SERVER    : {SMTP_SERVER!r}")
print(f"  SMTP_PORT      : {SMTP_PORT_RAW!r}")
print(f"  SMTP_USER      : {SMTP_USER!r}")
print(f"  SMTP_PASSWORD  : {'*' * len(SMTP_PASSWORD) if SMTP_PASSWORD else '(empty)'}")
print(f"  EMAIL_FROM     : {EMAIL_FROM!r}")
print(f"  EMAIL_TO       : {EMAIL_TO_REPORT!r}")
print(f"  TO_EMAIL_SMS   : {EMAIL_TO_SMS!r}")
print(f"  FOLDER_ID      : {FOLDER_ID!r}")
print("=" * 64)

required = {
    "SMTP_SERVER":   SMTP_SERVER,
    "SMTP_PORT":     SMTP_PORT_RAW,
    "SMTP_USER":     SMTP_USER,
    "SMTP_PASSWORD": SMTP_PASSWORD,
    "EMAIL_FROM":    EMAIL_FROM,
    "FOLDER_ID":     FOLDER_ID,
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
# 2. Google Drive connection
# ------------------------------------------------------------------
def get_drive_service():
    creds_info = {
        "type": "service_account",
        "project_id": env("PROJECT_ID"),
        "private_key_id": env("PRIVATE_KEY_ID"),
        "private_key": env("PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": env("CLIENT_EMAIL"),
        "client_id": env("CLIENT_ID"),
        "auth_uri": env("AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
        "token_uri": env("TOKEN_URI", "https://oauth2.googleapis.com/token"),
        "auth_provider_x509_cert_url": env("AUTH_PROVIDER_X509_CERT_URL",
                                            "https://www.googleapis.com/oauth2/v1/certs"),
        "client_x509_cert_url": env("CLIENT_X509_CERT_URL"),
        "universe_domain": env("UNIVERSE_DOMAIN", "googleapis.com"),
    }
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)


def list_folder_files(service, folder_id):
    """Return list of dicts: [{'id':..., 'name':..., 'mimeType':..., 'modifiedTime':...}]"""
    query = f"'{folder_id}' in parents and trashed = false"
    results = (service.files()
               .list(q=query,
                     fields="files(id, name, mimeType, modifiedTime)",
                     orderBy="modifiedTime desc",
                     pageSize=1000)
               .execute())
    return results.get("files", [])


def download_drive_file(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return dest_path


banner = lambda t: (print("=" * 64), print(t), print("=" * 64))
print()
print("Connecting to Google Drive…")
service = get_drive_service()
files = list_folder_files(service, FOLDER_ID)
print(f"Found {len(files)} file(s) in the Drive folder:")
for f in files:
    print(f"   • {f['name']}  ({f['modifiedTime']})")


# ------------------------------------------------------------------
# 3. Match the three files we need
# ------------------------------------------------------------------
def pick(pattern_keywords, files, exclude=None):
    """
    Return the newest file whose name contains ALL keywords (case-insensitive).
    exclude = list of already-picked file ids to avoid duplicates.
    """
    exclude = exclude or set()
    candidates = []
    for f in files:
        if f["id"] in exclude:
            continue
        name = f["name"].lower()
        if all(kw.lower() in name for kw in pattern_keywords):
            candidates.append(f)
    # Already sorted by modifiedTime desc from the API
    return candidates[0] if candidates else None


# The Debt Review report — whatever your refresh script names it.
# Add more keyword variants if your filename is different.
report_file = (
    pick(["debt", "dashboard"], files)
    or pick(["debt_review"], files)
    or pick(["report"], files)
    or pick(["fee", "audit"], files)
    or pick(["dashboard"], files)
)

failed_file = pick(["failed"], files, exclude={report_file["id"]} if report_file else None)
tracking_file = (
    pick(["intracking"], files, exclude={report_file["id"] if report_file else "",
                                          failed_file["id"] if failed_file else ""})
    or pick(["tracking"], files, exclude={report_file["id"] if report_file else "",
                                            failed_file["id"] if failed_file else ""})
)

print()
print("Selected files:")
print(f"   Report     : {report_file['name'] if report_file else '❌ none'}")
print(f"   Failed     : {failed_file['name'] if failed_file else '❌ none'}")
print(f"   Intracking : {tracking_file['name'] if tracking_file else '❌ none'}")


# ------------------------------------------------------------------
# 4. Download to a temp directory
# ------------------------------------------------------------------
tmpdir = tempfile.mkdtemp(prefix="report_")
local_paths = {}

def fetch(f, label):
    if not f:
        return None
    dest = os.path.join(tmpdir, f["name"])
    download_drive_file(service, f["id"], dest)
    size = os.path.getsize(dest)
    print(f"   ✅ downloaded {label}: {f['name']} ({size:,} bytes)")
    return dest

print()
print("Downloading…")
report_path   = fetch(report_file,   "report")
failed_path   = fetch(failed_file,   "failed")
tracking_path = fetch(tracking_file, "intracking")


# ------------------------------------------------------------------
# 5. Helpers
# ------------------------------------------------------------------
def read_any(path):
    if not path:
        return None
    if path.lower().endswith(".csv"):
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return pd.read_csv(path, encoding="latin-1")
    return pd.read_excel(path)


def excel_bytes(df, sheet_name="Sheet1"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def dashboard_metrics(path):
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
<div style="max-width:640px;margin:0 auto;padding:20px 12px;font-family:Arial,sans-serif;color:#1e1e2d;">
  <h2 style="margin:0 0 4px 0;font-size:22px;">📊 Debt Review Dashboard</h2>
  <p style="margin:0 0 20px 0;color:#6c757d;font-size:14px;">Report generated {today_str}</p>
  <h3 style="font-size:15px;margin:0 0 8px 0;">Key Metrics</h3>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    {rows if rows else "<tr><td>No metrics found.</td></tr>"}
  </table>
  <p style="margin:20px 0 0 0;font-size:13px;color:#555;">
    📎 Attached: <strong>{attached_name}</strong>
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
    lines += ["", f"Attached: {attached_name}",
              "Sent automatically by the Debt Review Dashboard workflow."]
    return "\n".join(lines)


def simple_html(title, intro, attached_name):
    return f"""\
<div style="max-width:640px;margin:0 auto;padding:20px 12px;font-family:Arial,sans-serif;color:#1e1e2d;">
  <h2 style="margin:0 0 4px 0;font-size:20px;">{title}</h2>
  <p style="margin:0 0 16px 0;color:#6c757d;font-size:14px;">{intro}</p>
  <p style="margin:0;font-size:13px;color:#555;">📎 Attached: <strong>{attached_name}</strong></p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0 10px 0;">
  <p style="margin:0;font-size:11px;color:#999;">Sent automatically by the Debt Review Dashboard workflow.</p>
</div>
"""


# ------------------------------------------------------------------
# 6. Build three messages
# ------------------------------------------------------------------
today_str = datetime.now().strftime("%d %B %Y")

# --- Email 1: full report ---
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
                           "⚠️ No report file was found in Google Drive.")
    print("⚠️ No report file found.")

# --- Email 2: failed clients ---
msg_failed = None
if failed_path:
    failed_df = read_any(failed_path)
    if failed_df is not None and not failed_df.empty:
        base = os.path.splitext(os.path.basename(failed_path))[0]
        attach_name = f"{base}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        data = excel_bytes(failed_df, "Failed Clients")
        msg_failed = EmailMessage()
        msg_failed["Subject"] = f"Failed Clients — {today_str} ({len(failed_df)} rows)"
        msg_failed["From"]    = EMAIL_FROM
        msg_failed["To"]      = EMAIL_TO_SMS
        msg_failed.set_content(f"Failed Clients — {today_str}\nRecords: {len(failed_df)}")
        msg_failed.add_alternative(simple_html(
            "❌ Failed Clients", f"{len(failed_df)} records · {today_str}", attach_name),
            subtype="html")
        msg_failed.add_attachment(
            data, maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attach_name)
        print(f"📧 Failed email prepared — {len(failed_df)} rows → {EMAIL_TO_SMS}")
    else:
        print("⚠️ Failed file empty — skipping.")
else:
    print("⚠️ No failed file in Drive — skipping.")

# --- Email 3: intracking clients ---
msg_tracking = None
if tracking_path:
    tracking_df = read_any(tracking_path)
    if tracking_df is not None and not tracking_df.empty:
        base = os.path.splitext(os.path.basename(tracking_path))[0]
        attach_name = f"{base}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        data = excel_bytes(tracking_df, "Intracking Clients")
        msg_tracking = EmailMessage()
        msg_tracking["Subject"] = f"Intracking Clients — {today_str} ({len(tracking_df)} rows)"
        msg_tracking["From"]    = EMAIL_FROM
        msg_tracking["To"]      = EMAIL_TO_SMS
        msg_tracking.set_content(f"Intracking Clients — {today_str}\nRecords: {len(tracking_df)}")
        msg_tracking.add_alternative(simple_html(
            "🔄 Intracking Clients", f"{len(tracking_df)} records · {today_str}", attach_name),
            subtype="html")
        msg_tracking.add_attachment(
            data, maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attach_name)
        print(f"📧 Intracking email prepared — {len(tracking_df)} rows → {EMAIL_TO_SMS}")
    else:
        print("⚠️ Intracking file empty — skipping.")
else:
    print("⚠️ No intracking file in Drive — skipping.")


# ------------------------------------------------------------------
# 7. Send all
# ------------------------------------------------------------------
messages = [("Report", msg_report)]
if msg_failed:   messages.append(("Failed", msg_failed))
if msg_tracking: messages.append(("Intracking", msg_tracking))


def send_all():
    print(f"📧 Connecting to {SMTP_SERVER}:{SMTP_PORT} …")
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT,
                              context=ssl.create_default_context(),
                              timeout=30) as s:
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
