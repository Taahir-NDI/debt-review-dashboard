import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

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
        "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
        "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL"),
    }
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)

def download_metrics_from_drive():
    service = get_drive_service()
    folder_id = os.getenv("FOLDER_ID")
    query = f"'{folder_id}' in parents and name = 'metrics_history.csv' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if not files:
        raise Exception("metrics_history.csv not found on Google Drive.")
    request = service.files().get_media(fileId=files[0]["id"])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return pd.read_csv(fh)

DEFAULT_METRICS = {
    "settled_mtd_v": 0, "failed_mtd_v": 0, "success_rate": 0,
    "revenue_total": 0, "current_debits_v": 0, "next_debits_v": 0,
    "tracking_c": 0, "failed_cycle_c": 0,
}

def generate_summary():
    try:
        df = download_metrics_from_drive()
        if len(df) > 0:
            latest = df.sort_values("report_date").iloc[-1]
            return {
                "settled_mtd_v": float(latest.get("settled_mtd_v", 0)),
                "failed_mtd_v": float(latest.get("failed_mtd_v", 0)),
                "success_rate": float(latest.get("success_rate", 0)),
                "revenue_total": float(latest.get("revenue_total", 0)),
                "current_debits_v": float(latest.get("current_debits_v", 0)),
                "next_debits_v": float(latest.get("next_debits_v", 0)),
                "tracking_c": float(latest.get("tracking_c", 0)),
                "failed_cycle_c": float(latest.get("failed_cycle_c", 0)),
            }
    except Exception as e:
        print(f"⚠️ Could not read from Drive: {e}")
    return DEFAULT_METRICS
