# ================================================================
# 🔄 REFRESH METRICS + EXCEL REPORT — Headless computation & Drive
# ================================================================

import os
import io
import json
import base64
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ================================================================
# 🆔 ID NORMALIZER — Keeps IDs as clean integer strings
# ================================================================
def normalize_id(val):
    """
    Convert any ID value to a clean integer-style string.
    Handles:
      - Excel numbers like 7801066006087 → "7801066006087"
      - Excel floats like 7801066006087.0 → "7801066006087"
      - Strings with trailing '.0' → "7801066006087"
      - Empty/NaN → ""
    """
    if pd.isna(val):
        return ""
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        if float(val).is_integer():
            return str(int(val))
        return str(val)
    s = str(val).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s

# ================================================================
# 🔐 GOOGLE DRIVE HELPERS
# ================================================================
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

# ================================================================
# 🔍 COLUMN DETECTION
# ================================================================
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

# ================================================================
# 🧮 BUILD REPORT — Computes metrics and lists
# ================================================================
def build_report(fee_content, payment_content):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    first_of_month = today.replace(day=1)
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)

    xls = pd.ExcelFile(fee_content)
    all_sheets = xls.sheet_names
    month_full = today.strftime("%B %Y").upper()
    month_name = today.strftime("%B").upper()
    month_short = today.strftime("%b").upper()

    current_sheet = None
    for s in all_sheets:
        if month_full in s.upper() or month_name in s.upper() or month_short in s.upper():
            current_sheet = s
            break
    if current_sheet is None:
        current_sheet = all_sheets[0]

    # ---- Read Fee Audit ----
    fee_df = pd.read_excel(fee_content, sheet_name=current_sheet)
    s_col, id_col, amt_col, stage_col, date_col, name_col, cell_col = find_columns(fee_df)

    fee_base_cols = [id_col, stage_col, amt_col, s_col]
    if date_col: fee_base_cols.append(date_col)
    if name_col: fee_base_cols.append(name_col)
    if cell_col: fee_base_cols.append(cell_col)

    fee_base = fee_df[fee_base_cols].copy()
    fee_base.rename(columns={id_col: "id_number", stage_col: "payment_stage",
                             amt_col: "amount", s_col: "status"}, inplace=True)
    if date_col: fee_base.rename(columns={date_col: "collection_date"}, inplace=True)
    if name_col: fee_base.rename(columns={name_col: "client_name"}, inplace=True)
    if cell_col: fee_base.rename(columns={cell_col: "cell"}, inplace=True)

    for col in ["client_name", "cell", "collection_date"]:
        if col not in fee_base.columns:
            fee_base[col] = ""

    # ---- FIX 2: Use normalize_id for clean IDs ----
    fee_base["id_number"] = fee_base["id_number"].apply(normalize_id)

    fee_base["payment_stage"] = pd.to_numeric(fee_base["payment_stage"], errors="coerce")
    fee_base["amount"] = pd.to_numeric(fee_base["amount"], errors="coerce")
    fee_base["collection_date"] = pd.to_datetime(fee_base["collection_date"], errors="coerce")
    fee_base = fee_base.dropna(subset=["id_number", "payment_stage"])

    status_up = fee_base["status"].astype(str).str.upper()
    cancel = status_up.str.contains("CANCELLED", na=False)
    keep = status_up.str.contains("CLIENT CANCELLED MANDATE", na=False)
    fee_base = fee_base[~(cancel & ~keep)].copy()

    # ---- Read Payment Status Report ----
    try:
        pay_df = pd.read_excel(payment_content, sheet_name="Details", header=3)
    except Exception:
        pay_df = pd.read_excel(payment_content, header=3)

    p_s_col, p_id_col, p_amt_col, p_stage_col, p_date_col, p_name_col, p_cell_col = find_columns(pay_df)

    pmt = pay_df.rename(columns={
        p_id_col: "id_number", p_stage_col: "payment_stage", p_amt_col: "amount",
        p_s_col: "status", p_date_col: "collection_date"
    })
    # ---- FIX 2: Clean ID ----
    pmt["id_number"] = pmt["id_number"].apply(normalize_id)
    pmt["payment_stage"] = pd.to_numeric(pmt["payment_stage"], errors="coerce")
    pmt["amount"] = pd.to_numeric(pmt["amount"], errors="coerce")
    pmt["collection_date"] = pd.to_datetime(pmt["collection_date"], errors="coerce")

    # ---- SMS lists (from Payment Report) ----
    sms_cols = ["id_number", "client_name", "cell", "payment_stage", "amount", "status"]
    pmt_sms = pay_df.rename(columns={
        p_id_col: "id_number", p_name_col: "client_name", p_cell_col: "cell",
        p_stage_col: "payment_stage", p_amt_col: "amount",
        p_s_col: "status", p_date_col: "collection_date"
    })
    pmt_sms["payment_stage"] = pd.to_numeric(pmt_sms["payment_stage"], errors="coerce")
    pmt_sms["amount"] = pd.to_numeric(pmt_sms["amount"], errors="coerce")
    pmt_sms["collection_date"] = pd.to_datetime(pmt_sms["collection_date"], errors="coerce")
    # ---- FIX 2: Clean ID ----
    pmt_sms["id_number"] = pmt_sms["id_number"].apply(normalize_id)
    pmt_sms = pmt_sms.dropna(subset=["id_number", "payment_stage", "amount"])

    # ================================================================
    # ✅ FIX 1: Include ALL Failed/Disputed clients from Payment Status Report
    # ================================================================
    # No date restriction — the entire Payment Status Report is scanned.
    failed_keywords = ["FAILED", "FAIL", "DECLINED", "REJECTED", "DISPUTED", "CLIENT CANCELLED MANDATE"]
    failed_mask = pmt_sms["status"].str.upper().str.contains("|".join(failed_keywords), na=False)
    failed_pmt = pmt_sms[failed_mask].copy()
    # ^^^ That's it. No `.between(last_friday, today)` filter anymore.

    tracking_mask = pmt_sms["status"].str.upper().str.contains("TRACKING|INTRACKING", na=False)
    tracking_pmt = pmt_sms[tracking_mask].copy()

    def latest_per_client(df):
        """Keep the most recent row per client (by collection_date)."""
        if df.empty:
            return df
        return df.sort_values("collection_date").groupby("id_number").tail(1).reset_index(drop=True)

    failed_sms_df = latest_per_client(failed_pmt)[sms_cols].copy()
    tracking_sms_df = latest_per_client(tracking_pmt)[sms_cols].copy()

    # ---- Sale Not Submitted — from Fee Audit ----
    sale_not_submitted_mask = fee_base["status"].astype(str).str.upper().str.contains("SALE NOT SUBMITTED", na=False)
    sns_df = fee_base[sale_not_submitted_mask].copy()
    if not sns_df.empty:
        agg_cols = {}
        for c in ["client_name", "cell", "payment_stage", "amount", "status"]:
            if c in sns_df.columns:
                agg_cols[c] = "sum" if c == "amount" else "first"
        sns_df = sns_df.groupby("id_number").agg(agg_cols).reset_index()

    # ---- Client Cancelled Mandate — from Fee Audit ----
    cm_mask = fee_base["status"].astype(str).str.upper().str.contains("CLIENT CANCELLED MANDATE", na=False)
    cm_df = fee_base[cm_mask].copy()
    if not cm_df.empty:
        agg_cols = {}
        for c in ["client_name", "cell", "payment_stage", "amount", "status"]:
            if c in cm_df.columns:
                agg_cols[c] = "sum" if c == "amount" else "first"
        cm_df = cm_df.groupby("id_number").agg(agg_cols).reset_index()

    # ---- Metrics (month-to-date) ----
    merged = fee_base.merge(
        pmt[["id_number", "payment_stage", "status", "amount", "collection_date"]],
        on=["id_number", "payment_stage"], how="left", suffixes=("", "_pmt")
    )
    if "status_pmt" in merged.columns:
        merged["status"] = merged["status_pmt"].fillna(merged["status"])
    if "amount_pmt" in merged.columns:
        merged["amount"] = merged["amount_pmt"].fillna(merged["amount"])
    if "collection_date_pmt" in merged.columns:
        merged["collection_date"] = merged["collection_date_pmt"].fillna(merged["collection_date"])

    merged["status_upper"] = merged["status"].astype(str).str.upper()
    merged["payment_stage"] = pd.to_numeric(merged["payment_stage"], errors="coerce")
    stage12 = merged[merged["payment_stage"].isin([1, 2])].copy()
    stage12 = stage12[stage12["collection_date"] <= today]

    settled_mtd = stage12[(stage12["status_upper"] == "SETTLED") & (stage12["collection_date"] >= first_of_month)]
    failed_mtd = stage12[(stage12["status_upper"] == "FAILED") & (stage12["collection_date"] >= first_of_month)]
    disputed_mtd = stage12[(stage12["status_upper"] == "DISPUTED") & (stage12["collection_date"] >= first_of_month)]

    settled_mtd_v = settled_mtd["amount"].sum()
    failed_mtd_v = failed_mtd["amount"].sum()
    disputed_mtd_v = disputed_mtd["amount"].sum()

    denom = settled_mtd_v + failed_mtd_v + disputed_mtd_v
    success_rate = (settled_mtd_v / denom * 100) if denom > 0 else 0

    # ---- Revenue ----
    settled_all = stage12[stage12["status_upper"] == "SETTLED"].copy()
    settled_all = settled_all.sort_values(["id_number", "collection_date"])
    settled_all["rank"] = settled_all.groupby("id_number").cumcount() + 1

    def calc_rev(row):
        amt, rank = row["amount"], row["rank"]
        if pd.isna(rank): return 0
        if rank == 1: return amt if amt < 3000 else min(amt, 8000)
        elif rank == 2: return min(amt * 1.5, 3000) if amt < 3000 else min(amt, 8000)
        else: return min(amt * 0.05, 450)

    settled_all["revenue"] = settled_all.apply(calc_rev, axis=1)
    revenue_total = settled_all[settled_all["collection_date"] >= first_of_month]["revenue"].sum()

    # ---- Future Debits ----
    future_mask = fee_base["status"].astype(str).str.upper().str.contains("FUTURE", na=False)
    future_df = fee_base[future_mask & fee_base["payment_stage"].isin([1, 2])].dropna(subset=["collection_date"])
    tomorrow = today + timedelta(days=1)
    last_day_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    first_of_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_of_next = (first_of_next + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    current_debits_v = future_df[
        (future_df["collection_date"] >= tomorrow) &
        (future_df["collection_date"] <= last_day_month)
    ]["amount"].sum()
    next_debits_v = future_df[
        (future_df["collection_date"] >= first_of_next) &
        (future_df["collection_date"] <= last_of_next)
    ]["amount"].sum()

    metrics = {
        "report_date": today.strftime("%Y-%m-%d"),
        "month": today.strftime("%B %Y"),
        "settled_mtd_v": float(settled_mtd_v),
        "failed_mtd_v": float(failed_mtd_v),
        "success_rate": float(success_rate),
        "revenue_total": float(revenue_total),
        "current_debits_v": float(current_debits_v),
        "next_debits_v": float(next_debits_v),
        "settled_today_c": int(len(settled_mtd[settled_mtd["collection_date"] == today])),
        "tracking_c": int(tracking_pmt["id_number"].nunique()) if not tracking_pmt.empty else 0,
        "failed_cycle_c": int(failed_mtd["id_number"].nunique()),
        "disputed_v": float(disputed_mtd_v),
        "disputed_c": int(disputed_mtd["id_number"].nunique()),
        "cancelled_mandate_v": float(cm_df["amount"].sum()) if not cm_df.empty else 0.0,
        "cancelled_mandate_c": int(cm_df["id_number"].nunique()) if not cm_df.empty else 0,
        "sale_not_submitted_v": float(sns_df["amount"].sum()) if not sns_df.empty else 0.0,
        "sale_not_submitted_c": int(sns_df["id_number"].nunique()) if not sns_df.empty else 0,
    }

    return metrics, failed_sms_df, tracking_sms_df, sns_df, cm_df

# ================================================================
# 📊 EXCEL BUILDERS
# ================================================================
def build_excel(metrics, failed_sms_df, tracking_sms_df, sns_df, cm_df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dashboard = pd.DataFrame({
            "Metric": [
                "Settled Period Total", "Failed MTD", "Disputed MTD",
                "Client Cancelled Mandate", "Sale Not Submitted",
                "Revenue (Period)", "Success Rate",
                "Curr Month Debits", "Next Month Debits",
                "Intracking Clients", "Failed Cycle Count",
            ],
            "Value": [
                f"R {metrics['settled_mtd_v']:,.2f}",
                f"R {metrics['failed_mtd_v']:,.2f}",
                f"R {metrics['disputed_v']:,.2f}",
                f"R {metrics['cancelled_mandate_v']:,.2f}",
                f"R {metrics['sale_not_submitted_v']:,.2f}",
                f"R {metrics['revenue_total']:,.2f}",
                f"{metrics['success_rate']:.1f}%",
                f"R {metrics['current_debits_v']:,.2f}",
                f"R {metrics['next_debits_v']:,.2f}",
                f"{metrics['tracking_c']}",
                f"{metrics['failed_cycle_c']}",
            ],
        })
        dashboard.to_excel(writer, sheet_name="Dashboard", index=False)

        def prep(df):
            if df.empty:
                return df
            return df.rename(columns={
                "id_number": "ID NUMBER", "client_name": "Name", "cell": "Cell",
                "payment_stage": "Stage", "amount": "Amount", "status": "Status"
            })

        if not failed_sms_df.empty:
            prep(failed_sms_df).to_excel(writer, sheet_name="Failed SMS", index=False)
        if not tracking_sms_df.empty:
            prep(tracking_sms_df).to_excel(writer, sheet_name="Intracking SMS", index=False)
        if not sns_df.empty:
            prep(sns_df).to_excel(writer, sheet_name="Sale Not Submitted", index=False)
        if not cm_df.empty:
            prep(cm_df).to_excel(writer, sheet_name="Client Cancelled Mandate", index=False)

    output.seek(0)
    return output

def build_single_sheet_excel(df, sheet_name):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame({"Message": ["No records for this period"]}).to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            out_df = df.rename(columns={
                "id_number": "ID NUMBER", "client_name": "Name", "cell": "Cell",
                "payment_stage": "Stage", "amount": "Amount", "status": "Status"
            })
            out_df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output

# ================================================================
# 🚀 MAIN
# ================================================================
def main():
    folder_id = os.getenv("FOLDER_ID")
    service = get_drive_service()

    print("📥 Downloading source files from Google Drive...")
    fee_content = download_file(service, folder_id, "Monthly Fees Audit.xlsx")
    payment_content = download_file(service, folder_id, "Payment Status Report.xlsx")

    print("🧮 Computing metrics + building reports...")
    metrics, failed_sms_df, tracking_sms_df, sns_df, cm_df = build_report(fee_content, payment_content)
    print("Computed:", json.dumps(metrics, indent=2))
    print(f"📊 Failed SMS list size: {len(failed_sms_df)} clients")
    print(f"📊 Intracking SMS list size: {len(tracking_sms_df)} clients")

    # ---- Update metrics_history.csv ----
    try:
        history_bytes = download_file(service, folder_id, "metrics_history.csv")
        history_df = pd.read_csv(history_bytes)
    except Exception:
        history_df = pd.DataFrame()

    if not history_df.empty and "month" in history_df.columns:
        mask = history_df["month"] == metrics["month"]
        if mask.any():
            for k, v in metrics.items():
                history_df.loc[mask, k] = v
        else:
            history_df = pd.concat([history_df, pd.DataFrame([metrics])], ignore_index=True)
    else:
        history_df = pd.DataFrame([metrics])

    csv_bytes = io.BytesIO(history_df.to_csv(index=False).encode("utf-8"))
    upload_or_update(service, folder_id, "metrics_history.csv", csv_bytes, "text/csv")
    print("✅ Updated metrics_history.csv on Drive.")

    # ---- Full Excel report ----
    print("📊 Building full Excel report...")
    excel_bytes = build_excel(metrics, failed_sms_df, tracking_sms_df, sns_df, cm_df)
    excel_bytes.seek(0)
    upload_or_update(
        service, folder_id, "Debt_Review_Report.xlsx", excel_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    print("✅ Uploaded Debt_Review_Report.xlsx to Drive.")

    # ---- Failed SMS-only file ----
    print("📊 Building Failed SMS-only Excel...")
    failed_sms_bytes = build_single_sheet_excel(failed_sms_df, "Failed SMS")
    failed_sms_bytes.seek(0)
    upload_or_update(
        service, folder_id, "Failed_SMS.xlsx", failed_sms_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    print("✅ Uploaded Failed_SMS.xlsx to Drive.")

    # ---- Intracking SMS-only file ----
    print("📊 Building Intracking SMS-only Excel...")
    tracking_sms_bytes = build_single_sheet_excel(tracking_sms_df, "Intracking SMS")
    tracking_sms_bytes.seek(0)
    upload_or_update(
        service, folder_id, "Intracking_SMS.xlsx", tracking_sms_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    print("✅ Uploaded Intracking_SMS.xlsx to Drive.")

if __name__ == "__main__":
    main()
