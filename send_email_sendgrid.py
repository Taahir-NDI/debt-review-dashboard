# ================================================================
# SEND EMAIL VIA SENDGRID — main report + SMS-only email
# ================================================================

import os
import io
import base64
import requests
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL       = os.getenv("FROM_EMAIL")
TO_EMAIL         = os.getenv("TO_EMAIL")
TO_EMAIL_SMS     = os.getenv("TO_EMAIL_SMS")
DASHBOARD_URL    = os.getenv("DASHBOARD_URL", "https://your-dashboard.streamlit.app")
FOLDER_ID        = os.getenv("FOLDER_ID")

DEFAULT_METRICS = {
    "settled_today_v": 0, "settled_today_c": 0,
    "settled_cycle_v": 0, "settled_cycle_c": 0,
    "success_rate": 0,
    "tracking_v": 0, "tracking_c": 0,
    "failed_cycle_v": 0, "failed_cycle_c": 0,
    "failed_mtd_v": 0, "failed_mtd_c": 0,
}


def get_drive_service():
    creds_info = {
        "type": "service_account",
        "project_id": os.getenv("PROJECT_ID"),
        "private_key_id": os.getenv("PRIVATE_KEY_ID"),
        "private_key": os.getenv("PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("CLIENT_EMAIL"),
        "client_id": os.getenv("CLIENT_ID"),
        "auth_uri": os.getenv("AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
        "token_uri": os.getenv("TOKEN_URI", "https://oauth2.googleapis.com/token"),
        "auth_provider_x509_cert_url": os.getenv(
            "AUTH_PROVIDER_X509_CERT_URL",
            "https://www.googleapis.com/oauth2/v1/certs",
        ),
        "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL"),
    }
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)


def download_from_drive(file_name):
    service = get_drive_service()
    query = f"'{FOLDER_ID}' in parents and name = '{file_name}' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if not files:
        raise Exception(f"{file_name} not found on Google Drive.")
    request = service.files().get_media(fileId=files[0]["id"])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh


def get_metrics():
    try:
        fh = download_from_drive("metrics_history.csv")
        df = pd.read_csv(fh)
        if len(df) > 0:
            latest = df.sort_values("report_date").iloc[-1]
            return {
                "settled_today_v": float(latest.get("settled_today_v", 0) or 0),
                "settled_today_c": int(float(latest.get("settled_today_c", 0) or 0)),
                "settled_cycle_v": float(latest.get("settled_cycle_v", 0) or 0),
                "settled_cycle_c": int(float(latest.get("settled_cycle_c", 0) or 0)),
                "success_rate":    float(latest.get("success_rate", 0) or 0),
                "tracking_v":      float(latest.get("tracking_v", 0) or 0),
                "tracking_c":      int(float(latest.get("tracking_c", 0) or 0)),
                "failed_cycle_v":  float(latest.get("failed_cycle_v", 0) or 0),
                "failed_cycle_c":  int(float(latest.get("failed_cycle_c", 0) or 0)),
                "failed_mtd_v":    float(latest.get("failed_mtd_v", 0) or 0),
                "failed_mtd_c":    int(float(latest.get("failed_mtd_c", 0) or 0)),
            }
    except Exception as e:
        print(f"Could not read metrics from Drive: {e}")
    return DEFAULT_METRICS


def main_html(metrics):
    today = datetime.now().strftime("%d %B %Y")

    def row(label, value, count_label=None):
        count_html = (
            f"<div style='font-size:13px;color:#6c757d;margin-top:2px;'>{count_label}</div>"
            if count_label else ""
        )
        return f"""
        <tr>
            <td style="padding:14px 16px;border-bottom:1px solid #eef0f3;vertical-align:middle;">
                <div style="font-size:14px;color:#1e1e2d;font-weight:600;">{label}</div>
            </td>
            <td style="padding:14px 16px;border-bottom:1px solid #eef0f3;text-align:right;vertical-align:middle;">
                <div style="font-size:20px;color:#1e1e2d;font-weight:700;">{value}</div>
                {count_html}
            </td>
        </tr>
        """

    rows = (
        row("Settled Today", f"R {metrics['settled_today_v']:,.2f}",
            f"{metrics['settled_today_c']} clients") +
        row("Settled Period", f"R {metrics['settled_cycle_v']:,.2f}",
            f"{metrics['settled_cycle_c']} clients") +
        row("Success Rate", f"{metrics['success_rate']:.1f}%") +
        row("Intracking", f"R {metrics['tracking_v']:,.2f}",
            f"{metrics['tracking_c']} clients") +
        row("Failed Period", f"R {metrics['failed_cycle_v']:,.2f}",
            f"{metrics['failed_cycle_c']} clients") +
        row("Failed MTD", f"R {metrics['failed_mtd_v']:,.2f}",
            f"{metrics['failed_mtd_c']} clients")
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="margin:0;padding:0;background:#f5f6f8;font-family:Arial,Helvetica,sans-serif;color:#1e1e2d;">
        <div style="max-width:560px;margin:0 auto;padding:24px 12px;">

            <div style="background:#ffffff;border-radius:12px;padding:26px 26px 20px 26px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">

                <h2 style="margin:0 0 4px 0;font-size:22px;color:#1e1e2d;">
                    Debt Review Dashboard
                </h2>
                <p style="margin:0 0 20px 0;color:#6c757d;font-size:14px;">
                    Report generated {today}
                </p>

                <table style="width:100%;border-collapse:collapse;">
                    {rows}
                </table>

                <div style="text-align:center;margin-top:24px;">
                    <a href="{DASHBOARD_URL}"
                       style="display:inline-block;background:#4e8cff;color:#ffffff;
                              padding:10px 22px;border-radius:6px;text-decoration:none;
                              font-size:14px;font-weight:600;">
                        View Full Dashboard &rarr;
                    </a>
                </div>

                <hr style="border:none;border-top:1px solid #eef0f3;margin:24px 0 12px 0;">
                <p style="margin:0;font-size:12px;color:#9aa0a6;text-align:center;">
                    Sent automatically by the Debt Review Dashboard workflow.<br>
                    Full Excel report attached.
                </p>
            </div>

        </div>
    </body>
    </html>
    """


def sms_html():
    today = datetime.now().strftime("%d %B %Y")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="margin:0;padding:0;background:#f5f6f8;font-family:Arial,Helvetica,sans-serif;">
        <div style="max-width:560px;margin:0 auto;padding:24px 12px;">
            <div style="background:#ffffff;border-radius:12px;padding:26px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">

                <h2 style="margin:0 0 4px 0;font-size:20px;color:#1e1e2d;">
                    SMS Lists — Failed &amp; Intracking
                </h2>
                <p style="margin:0 0 18px 0;color:#6c757d;font-size:14px;">
                    Generated {today}
                </p>

                <div style="background:#fff8e1;border-left:4px solid #ffc107;
                            padding:12px 16px;border-radius:6px;font-size:14px;color:#664d03;">
                    Attached for the SMS team:
                    <ul style="margin:8px 0 0 0;padding-left:20px;">
                        <li><strong>Failed_SMS.xlsx</strong> — Failed, Disputed, and Cancelled Mandate clients within the current Settled Period</li>
                        <li><strong>Intracking_SMS.xlsx</strong> — clients currently being tracked</li>
                    </ul>
                </div>

                <hr style="border:none;border-top:1px solid #eef0f3;margin:22px 0 12px 0;">
                <p style="margin:0;font-size:12px;color:#9aa0a6;text-align:center;">
                    Sent automatically by the Debt Review Dashboard workflow.
                </p>
            </div>
        </div>
    </body>
    </html>
    """


def _post_sendgrid(payload, label):
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
    if r.status_code == 202:
        print(f"{label}: sent")
        return True
    print(f"{label}: SendGrid error {r.status_code} - {r.text}")
    return False


def send_main_email():
    if not SENDGRID_API_KEY or not TO_EMAIL:
        print("Main email: missing SENDGRID_API_KEY or TO_EMAIL")
        return
    metrics = get_metrics()
    today = datetime.now().strftime("%d %b %Y")

    attachments = []
    try:
        xlsx = download_from_drive("Debt_Review_Report.xlsx").read()
        attachments.append({
            "content": base64.b64encode(xlsx).decode("utf-8"),
            "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "filename": f"Debt_Review_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            "disposition": "attachment",
        })
        print(f"Attached full report ({len(xlsx)/1024:.1f} KB)")
    except Exception as e:
        print(f"Could not attach full report: {e}")

    payload = {
        "personalizations": [{"to": [{"email": TO_EMAIL}]}],
        "from": {"email": FROM_EMAIL},
        "subject": f"Debt Review Report - {today}",
        "content": [{"type": "text/html", "value": main_html(metrics)}],
    }
    if attachments:
        payload["attachments"] = attachments

    _post_sendgrid(payload, "Main email")


def send_sms_email():
    if not SENDGRID_API_KEY or not TO_EMAIL_SMS:
        print("SMS email: missing SENDGRID_API_KEY or TO_EMAIL_SMS - skipping")
        return
    today = datetime.now().strftime("%d %b %Y")

    attachments = []
    for drive_name in ["Failed_SMS.xlsx", "Intracking_SMS.xlsx"]:
        try:
            b = download_from_drive(drive_name).read()
            attachments.append({
                "content": base64.b64encode(b).decode("utf-8"),
                "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "filename": f"{drive_name.replace('.xlsx', '')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                "disposition": "attachment",
            })
            print(f"Attached {drive_name} ({len(b)/1024:.1f} KB)")
        except Exception as e:
            print(f"Could not attach {drive_name}: {e}")

    if not attachments:
        print("SMS email: no attachments - skipping")
        return

    payload = {
        "personalizations": [{"to": [{"email": TO_EMAIL_SMS}]}],
        "from": {"email": FROM_EMAIL},
        "subject": f"SMS Lists (Failed & Intracking) - {today}",
        "content": [{"type": "text/html", "value": sms_html()}],
        "attachments": attachments,
    }
    _post_sendgrid(payload, "SMS email")


if __name__ == "__main__":
    send_main_email()
    send_sms_email()
