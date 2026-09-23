# ================================================================
# SEND EMAIL VIA SENDGRID — main report + separate SMS email
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
    "settled_mtd_v": 0, "failed_mtd_v": 0, "success_rate": 0,
    "revenue_total": 0, "current_debits_v": 0, "next_debits_v": 0,
    "tracking_c": 0, "failed_cycle_c": 0,
}


# ----------------------------------------------------------------
# GOOGLE DRIVE
# ----------------------------------------------------------------
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
                "settled_mtd_v":    float(latest.get("settled_mtd_v", 0) or 0),
                "failed_mtd_v":     float(latest.get("failed_mtd_v", 0) or 0),
                "success_rate":     float(latest.get("success_rate", 0) or 0),
                "revenue_total":    float(latest.get("revenue_total", 0) or 0),
                "current_debits_v": float(latest.get("current_debits_v", 0) or 0),
                "next_debits_v":    float(latest.get("next_debits_v", 0) or 0),
                "tracking_c":       float(latest.get("tracking_c", 0) or 0),
                "failed_cycle_c":   float(latest.get("failed_cycle_c", 0) or 0),
            }
    except Exception as e:
        print(f"Could not read metrics from Drive: {e}")
    return DEFAULT_METRICS


# ----------------------------------------------------------------
# HTML BODIES
# ----------------------------------------------------------------
def main_html(metrics):
    today = datetime.now().strftime("%d %B %Y")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f8f9fa; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white;
                          border-radius: 12px; padding: 30px;
                          box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header {{ border-bottom: 2px solid #4e8cff; padding-bottom: 15px; margin-bottom: 20px; }}
            h1 {{ color: #1e1e2d; font-size: 24px; margin: 0; }}
            .subtitle {{ color: #6c757d; font-size: 14px; }}
            .metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .metric-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px;
                            border-left: 4px solid #4e8cff; }}
            .metric-label {{ font-size: 12px; color: #8a8a8a; text-transform: uppercase; letter-spacing: 0.3px; }}
            .metric-value {{ font-size: 22px; font-weight: 700; color: #1e1e2d; }}
            .metric-delta {{ font-size: 13px; color: #6c757d; }}
            .btn {{ display: inline-block; background: #4e8cff; color: white;
                    padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-top: 10px; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #dee2e6;
                       font-size: 12px; color: #6c757d; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Debt Review Dashboard Report</h1>
                <div class="subtitle">Generated on {today}</div>
            </div>
            <div class="metric-grid">
                <div class="metric-card" style="border-left-color: #28a745;">
                    <div class="metric-label">Revenue (Period)</div>
                    <div class="metric-value">R {metrics['revenue_total']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #6f42c1;">
                    <div class="metric-label">Success Rate</div>
                    <div class="metric-value">{metrics['success_rate']:.1f}%</div>
                </div>
                <div class="metric-card" style="border-left-color: #17a2b8;">
                    <div class="metric-label">Settled Amount</div>
                    <div class="metric-value">R {metrics['settled_mtd_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #dc3545;">
                    <div class="metric-label">Failed Amount</div>
                    <div class="metric-value">R {metrics['failed_mtd_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #ff9f43;">
                    <div class="metric-label">Current Month Debits</div>
                    <div class="metric-value">R {metrics['current_debits_v']:,.2f}</div>
                    <div class="metric-delta">Next Month: R {metrics['next_debits_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #20c997;">
                    <div class="metric-label">Intracking Clients</div>
                    <div class="metric-value">{metrics['tracking_c']:.0f} clients</div>
                    <div class="metric-delta">Failed: {metrics['failed_cycle_c']:.0f}</div>
                </div>
            </div>
            <div style="text-align: center; margin-top: 15px;">
                <a href="{DASHBOARD_URL}" class="btn">View Full Dashboard &rarr;</a>
            </div>
            <div class="footer">
                Automated report from Debt Review Dashboard<br>
                Full Excel report attached.
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
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f8f9fa; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white;
                          border-radius: 12px; padding: 30px;
                          box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header {{ border-bottom: 2px solid #dc3545; padding-bottom: 15px; margin-bottom: 20px; }}
            h1 {{ color: #1e1e2d; font-size: 22px; margin: 0; }}
            .subtitle {{ color: #6c757d; font-size: 14px; }}
            .note {{ background: #fff3cd; border-left: 4px solid #ffc107;
                     padding: 12px 16px; border-radius: 6px; margin: 20px 0;
                     font-size: 14px; color: #664d03; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #dee2e6;
                       font-size: 12px; color: #6c757d; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>SMS Lists — Failed &amp; Intracking</h1>
                <div class="subtitle">Generated on {today}</div>
            </div>
            <div class="note">
                Attached for the SMS team:
                <ul>
                    <li><strong>Failed_SMS.xlsx</strong> — Failed, Disputed, and Cancelled Mandate clients within the current Settled Period</li>
                    <li><strong>Intracking_SMS.xlsx</strong> — clients currently being tracked</li>
                </ul>
            </div>
            <div class="footer">Automated SMS lists from Debt Review Dashboard</div>
        </div>
    </body>
    </html>
    """


# ----------------------------------------------------------------
# SEND HELPERS
# ----------------------------------------------------------------
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
