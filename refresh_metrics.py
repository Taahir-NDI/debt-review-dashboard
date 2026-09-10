# ================================================================
# 🔄 REFRESH METRICS — Headless computation & Drive persistence
# ================================================================

import os
import io
import json
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ---- Google Drive helpers ----
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

def download_file(service, folder_id, file_name):
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if not files:
        raise Exception(f"File '{file_name}' not found in folder.")
    file_id = files[0]["id"]
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh

def upload_or_update(service, folder_id, file_name, content_bytes, mime_type="text/csv"):
    """Upload a new file or update if it exists."""
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get("files", [])

    media = MediaIoBaseUpload(content_bytes, mimetype=mime_type)
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        service.files().create(
            body={"name": file_name, "parents": [folder_id]},
            media_body=media
        ).execute()

# ---- Column detection (same logic as dashboard) ----
def find_columns(df):
    status_col = None
    for col in df.columns:
        if str(col).strip().upper() == "COLLECTION STATUS":
            status_col = col
            break
    if status_col is None:
        for col in df.columns:
            if "status" in str(col).lower():
                status_col = col
                break
    if status_col is None:
        status_col = df.columns[-1]

    id_col = None
    for col in df.columns:
        if str(col).strip().upper() == "APPLICANT NUMBER":
            id_col = col
            break
    if id_col is None:
        for col in df.columns:
            if "number" in str(col).lower() or "id" in str(col).lower():
                id_col = col
                break
    if id_col is None:
        id_col = df.columns[0]

    amount_col = None
    for col in df.columns:
        if "INSTALMENT AMOUNT" in str(col).upper():
            amount_col = col
            break
    if amount_col is None:
        amount_col = df.columns[-2]

    stage_col = None
    for col in df.columns:
        if "INSTALLMENT NO" in str(col).upper():
            stage_col = col
            break
    if stage_col is None:
        stage_col = df.columns[3]

    date_col = None
    for col in df.columns:
        if "COLLECTION DATE" in str(col).upper():
            date_col = col
            break

    name_col = None
    cell_col = None
    for col in df.columns:
        if "APPLICANT NAME" in str(col).upper() or "NAME" in str(col).upper():
            name_col = col
        if "CELL" in str(col).upper():
            cell_col = col

    return status_col, id_col, amount_col, stage_col, date_col, name_col, cell_col

# ---- Core metric computation ----
def compute_metrics(fee_content, payment_content):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    first_of_month = today.replace(day=1)

    # ---- Detect current sheet from Fee Audit ----
    xls = pd.ExcelFile(fee_content)
    all_sheets = xls.sheet_names
    month_name_full = today.strftime("%B %Y").upper()
    month_name = today.strftime("%B").upper()
    month_short = today.strftime("%b").upper()

    current_sheet = None
    for s in all_sheets:
        if month_name_full in s.upper() or month_name in s.upper() or month_short in s.upper():
            current_sheet = s
            break
    if current_sheet is None:
        current_sheet = all_sheets[0]

    # ---- Read Fee Audit ----
    fee_df = pd.read_excel(fee_content, sheet_name=current_sheet)
    s_col, id_col, amt_col, stage_col, date_col, name_col, cell_col = find_columns(fee_df)

    fee_base = fee_df[[id_col, stage_col, amt_col, s_col] + ([date_col] if date_col else [])].copy()
    fee_base.rename(columns={id_col: "id_number", stage_col: "payment_stage",
                             amt_col: "amount", s_col: "status"}, inplace=True)
    if date_col:
        fee_base.rename(columns={date_col: "collection_date"}, inplace=True)
    fee_base["payment_stage"] = pd.to_numeric(fee_base["payment_stage"], errors="coerce")
    fee_base["amount"] = pd.to_numeric(fee_base["amount"], errors="coerce")
    fee_base["id_number"] = fee_base["id_number"].astype(str).str.strip()
    if "collection_date" in fee_base.columns:
        fee_base["collection_date"] = pd.to_datetime(fee_base["collection_date"], errors="coerce")
    fee_base = fee_base.dropna(subset=["id_number", "payment_stage"])
    fee_base = fee_base[~fee_base["status"].astype(str).str.upper().str.contains("CANCELLED", na=False)]

    # ---- Read Payment Status Report ----
    try:
        pay_df = pd.read_excel(payment_content, sheet_name="Details", header=3)
    except Exception:
        pay_df = pd.read_excel(payment_content, header=3)

    p_s_col, p_id_col, p_amt_col, p_stage_col, p_date_col, p_name_col, p_cell_col = find_columns(pay_df)
    pay_df = pay_df.rename(columns={
        p_id_col: "id_number", p_stage_col: "payment_stage", p_amt_col: "amount",
        p_s_col: "status", p_date_col: "collection_date"
    })
    pay_df["id_number"] = pay_df["id_number"].astype(str).str.strip()
    pay_df["payment_stage"] = pd.to_numeric(pay_df["payment_stage"], errors="coerce")
    pay_df["amount"] = pd.to_numeric(pay_df["amount"], errors="coerce")
    pay_df["collection_date"] = pd.to_datetime(pay_df["collection_date"], errors="coerce")

    # ---- Merge (fee audit is authoritative for the client list) ----
    merged = fee_base.merge(
        pay_df[["id_number", "payment_stage", "status", "amount", "collection_date"]],
        on=["id_number", "payment_stage"],
        how="left",
        suffixes=("", "_pmt")
    )
    # Prefer payment-report status/amount/date where available
    mask = merged["status_pmt"].notna() if "status_pmt" in merged.columns else None
    # Simpler: use the payment report values if present
    if "status_pmt" in merged.columns:
        merged["status"] = merged["status_pmt"].fillna(merged["status"])
    if "amount_pmt" in merged.columns:
        merged["amount"] = merged["amount_pmt"].fillna(merged["amount"])
    if "collection_date_pmt" in merged.columns:
        merged["collection_date"] = merged["collection_date_pmt"].fillna(merged["collection_date"])

    merged["status_upper"] = merged["status"].astype(str).str.upper()
    merged["payment_stage"] = pd.to_numeric(merged["payment_stage"], errors="coerce")
    stage12 = merged[merged["payment_stage"].isin([1, 2])].copy()

    # ---- Filter to "today" ----
    stage12 = stage12[stage12["collection_date"] <= today]

    # ---- Settled MTD ----
    settled_mtd = stage12[
        (stage12["status_upper"] == "SETTLED") &
        (stage12["collection_date"] >= first_of_month)
    ]
    settled_mtd_v = settled_mtd["amount"].sum()

    # ---- Failed MTD ----
    failed_mtd = stage12[
        (stage12["status_upper"] == "FAILED") &
        (stage12["collection_date"] >= first_of_month)
    ]
    failed_mtd_v = failed_mtd["amount"].sum()

    # ---- Disputed MTD ----
    disputed_mtd = stage12[
        (stage12["status_upper"] == "DISPUTED") &
        (stage12["collection_date"] >= first_of_month)
    ]
    disputed_mtd_v = disputed_mtd["amount"].sum()

    # ---- Success Rate ----
    denom = settled_mtd_v + failed_mtd_v + disputed_mtd_v
    success_rate = (settled_mtd_v / denom * 100) if denom > 0 else 0

    # ---- Tracking clients ----
    tracking = stage12[stage12["status_upper"].isin(["TRACKING", "INTRACKING"])]
    tracking_c = tracking["id_number"].nunique()

    # ---- Failed this cycle (since last Friday) ----
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    failed_cycle = stage12[
        (stage12["status_upper"] == "FAILED") &
        (stage12["collection_date"] >= last_friday)
    ]
    failed_cycle_c = len(failed_cycle)

    # ---- Future debits (Fee Audit "Future" status, stages 1 & 2) ----
    future_mask = fee_base["status"].astype(str).str.upper().str.contains("FUTURE", na=False)
    future_df = fee_base[future_mask].copy()
    future_df = future_df[future_df["payment_stage"].isin([1, 2])]
    future_df = future_df.dropna(subset=["collection_date"])

    tomorrow = today + timedelta(days=1)
    last_day_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    first_of_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_of_next = (first_of_next + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    current_future = future_df[
        (future_df["collection_date"] >= tomorrow) &
        (future_df["collection_date"] <= last_day_month)
    ]
    next_future = future_df[
        (future_df["collection_date"] >= first_of_next) &
        (future_df["collection_date"] <= last_of_next)
    ]

    current_debits_v = current_future["amount"].sum()
    next_debits_v = next_future["amount"].sum()

    # ---- Revenue (same calculation as dashboard) ----
    settled_all = stage12[stage12["status_upper"] == "SETTLED"].copy()
    settled_all = settled_all.sort_values(["id_number", "collection_date"])
    settled_all["rank"] = settled_all.groupby("id_number").cumcount() + 1

    def calc_rev(row):
        amt, rank = row["amount"], row["rank"]
        if pd.isna(rank):
            return 0
        if rank == 1:
            return amt if amt < 3000 else min(amt, 8000)
        elif rank == 2:
            return min(amt * 1.5, 3000) if amt < 3000 else min(amt, 8000)
        else:
            return min(amt * 0.05, 450)

    settled_all["revenue"] = settled_all.apply(calc_rev, axis=1)
    current_month_settled = settled_all[settled_all["collection_date"] >= first_of_month]
    revenue_total = current_month_settled["revenue"].sum()

    return {
        "report_date": today.strftime("%Y-%m-%d"),
        "month": today.strftime("%B %Y"),
        "settled_mtd_v": float(settled_mtd_v),
        "failed_mtd_v": float(failed_mtd_v),
        "success_rate": float(success_rate),
        "revenue_total": float(revenue_total),
        "current_debits_v": float(current_debits_v),
        "next_debits_v": float(next_debits_v),
        "settled_today_c": int(len(settled_mtd[settled_mtd["collection_date"] == today])),
        "tracking_c": int(tracking_c),
        "failed_cycle_c": int(failed_cycle_c),
    }

# ---- Main ----
def main():
    folder_id = os.getenv("FOLDER_ID")
    service = get_drive_service()

    print("📥 Downloading source files from Google Drive...")
    fee_content = download_file(service, folder_id, "Monthly Fees Audit.xlsx")
    payment_content = download_file(service, folder_id, "Payment Status Report.xlsx")

    print("🧮 Computing metrics...")
    new_row = compute_metrics(fee_content, payment_content)
    print("Computed:", json.dumps(new_row, indent=2))

    # ---- Load existing history (from Drive) or start fresh ----
    try:
        history_bytes = download_file(service, folder_id, "metrics_history.csv")
        history_df = pd.read_csv(history_bytes)
    except Exception:
        history_df = pd.DataFrame()

    # Update or append the row for this month
    if not history_df.empty and "month" in history_df.columns:
        mask = history_df["month"] == new_row["month"]
        if mask.any():
            for k, v in new_row.items():
                history_df.loc[mask, k] = v
        else:
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)
    else:
        history_df = pd.DataFrame([new_row])

    # ---- Write back to Drive ----
    csv_bytes = io.BytesIO(history_df.to_csv(index=False).encode("utf-8"))
    upload_or_update(service, folder_id, "metrics_history.csv", csv_bytes, "text/csv")
    print("✅ Updated metrics_history.csv on Google Drive.")

if __name__ == "__main__":
    main()
