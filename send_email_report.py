# ================================================================
# 📧 SEND EMAIL REPORT — Daily/Weekly Summary
# ================================================================

import os
import smtplib
import io
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import json

# ---- Configuration (from environment variables) ----
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_EMAIL = SMTP_USER

# ---- Generate Summary Metrics ----
def generate_summary():
    """Generate key metrics for the email report."""
    # For this example, we'll read from the history file if it exists
    # In practice, you would query your database or read the latest dashboard state
    try:
        history_file = "history/metrics_history.csv"
        if os.path.exists(history_file):
            df = pd.read_csv(history_file)
            latest = df.iloc[-1]
            metrics = {
                'settled_mtd_v': latest.get('settled_mtd_v', 0),
                'failed_mtd_v': latest.get('failed_mtd_v', 0),
                'success_rate': latest.get('success_rate', 0),
                'revenue_total': latest.get('revenue_total', 0),
                'current_debits_v': latest.get('current_debits_v', 0),
                'next_debits_v': latest.get('next_debits_v', 0),
                'tracking_c': latest.get('tracking_c', 0),
                'failed_cycle_c': latest.get('failed_cycle_c', 0),
            }
        else:
            # Fallback metrics
            metrics = {
                'settled_mtd_v': 0,
                'failed_mtd_v': 0,
                'success_rate': 0,
                'revenue_total': 0,
                'current_debits_v': 0,
                'next_debits_v': 0,
                'tracking_c': 0,
                'failed_cycle_c': 0,
            }
    except:
        metrics = {
            'settled_mtd_v': 0,
            'failed_mtd_v': 0,
            'success_rate': 0,
            'revenue_total': 0,
            'current_debits_v': 0,
            'next_debits_v': 0,
            'tracking_c': 0,
            'failed_cycle_c': 0,
        }
    return metrics

# ---- Create HTML Email Body ----
def create_html_body(metrics):
    """Create a styled HTML email body with metrics."""
    today = datetime.now().strftime('%d %B %Y')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f8f9fa; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header {{ border-bottom: 2px solid #4e8cff; padding-bottom: 15px; margin-bottom: 20px; }}
            h1 {{ color: #1e1e2d; font-size: 24px; margin: 0; }}
            .subtitle {{ color: #6c757d; font-size: 14px; }}
            .metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .metric-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px; border-left: 4px solid #4e8cff; }}
            .metric-label {{ font-size: 12px; color: #8a8a8a; text-transform: uppercase; letter-spacing: 0.3px; }}
            .metric-value {{ font-size: 22px; font-weight: 700; color: #1e1e2d; }}
            .metric-delta {{ font-size: 13px; color: #6c757d; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; text-align: center; }}
            .green {{ color: #28a745; }}
            .red {{ color: #dc3545; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Debt Review Dashboard Report</h1>
                <div class="subtitle">Report generated on {today}</div>
            </div>
            
            <div class="metric-grid">
                <div class="metric-card" style="border-left-color: #28a745;">
                    <div class="metric-label">💰 Revenue (Period)</div>
                    <div class="metric-value">R {metrics['revenue_total']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #6f42c1;">
                    <div class="metric-label">🎯 Success Rate</div>
                    <div class="metric-value">{metrics['success_rate']:.1f}%</div>
                </div>
                <div class="metric-card" style="border-left-color: #17a2b8;">
                    <div class="metric-label">✅ Settled Amount</div>
                    <div class="metric-value">R {metrics['settled_mtd_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #dc3545;">
                    <div class="metric-label">❌ Failed Amount</div>
                    <div class="metric-value">R {metrics['failed_mtd_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #ff9f43;">
                    <div class="metric-label">📅 Current Month Debits</div>
                    <div class="metric-value">R {metrics['current_debits_v']:,.2f}</div>
                    <div class="metric-delta">Next Month: R {metrics['next_debits_v']:,.2f}</div>
                </div>
                <div class="metric-card" style="border-left-color: #20c997;">
                    <div class="metric-label">👥 Intracking Clients</div>
                    <div class="metric-value">{metrics['tracking_c']:.0f} clients</div>
                    <div class="metric-delta">Failed: {metrics['failed_cycle_c']:.0f}</div>
                </div>
            </div>
            
            <p style="color: #6c757d; font-size: 13px; margin-top: 10px;">
                <a href="{os.getenv('DASHBOARD_URL', 'https://your-dashboard.streamlit.app')}">View full dashboard →</a>
            </p>
            
            <div class="footer">
                Automated report from Debt Review Dashboard · Data refreshed from Google Drive
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ---- Send Email ----
def send_email():
    """Send the email report."""
    metrics = generate_summary()
    html_body = create_html_body(metrics)
    
    msg = MIMEMultipart('alternative')
    msg['From'] = FROM_EMAIL
    msg['To'] = TO_EMAIL
    msg['Subject'] = f"📊 Debt Review Report - {datetime.now().strftime('%d %b %Y')}"
    
    # Attach HTML body
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {TO_EMAIL}")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

# ---- Run ----
if __name__ == "__main__":
    send_email()
