# ================================================================
# 📊 DEBT REVIEW DASHBOARD — FOLDER ID METHOD (NO MORE FILE ID UPDATES)
# ================================================================

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import warnings
import os
import json
warnings.filterwarnings('ignore')
import plotly.express as px

# ---- Google Drive imports ----
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ================================================================
# 📱 SMS PROVIDER — Embedded (Generic HTTP API)
# ================================================================
import requests

class GenericSMSProvider:
    def __init__(self, api_url, api_key, from_number):
        self.api_url = api_url
        self.api_key = api_key
        self.from_number = from_number

    def send(self, to_number, message):
        payload = {
            "api_key": self.api_key,
            "from": self.from_number,
            "to": to_number,
            "message": message
        }
        response = requests.post(self.api_url, json=payload)
        return response.json()

# ================================================================
# 🆔 ID NORMALIZER — Keeps IDs as clean integer strings
# ================================================================
def normalize_id(val):
    """Convert any ID value to a clean integer-style string."""
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
# 0. CUSTOM STYLES
# ================================================================
st.set_page_config(page_title="Debt Review Dashboard", layout="wide")

st.markdown("""
<style>
    .metric-card { background-color: #ffffff; border-radius: 12px; padding: 16px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 10px; border-left: 4px solid #4e8cff; transition: box-shadow 0.2s; }
    .metric-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
    .metric-label { font-size: 14px; color: #8a8a8a; font-weight: 500; text-transform: uppercase; letter-spacing: 0.3px; }
    .metric-value { font-size: 28px; font-weight: 700; color: #1e1e2d; margin-top: 4px; }
    .metric-delta { font-size: 14px; color: #4e8cff; font-weight: 500; margin-top: 2px; }
    .chart-container { background-color: #ffffff; border-radius: 12px; padding: 16px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }
    .dataframe { border: none !important; font-size: 14px !important; }
    .dataframe thead tr th { background-color: #f8f9fa !important; color: #1e1e2d !important; font-weight: 600 !important; border-bottom: 2px solid #dee2e6 !important; }
    .dataframe tbody tr:hover { background-color: #f8f9fa !important; }
    .main-header { margin-bottom: 24px; }
    .main-header h1 { font-size: 28px; font-weight: 700; color: #1e1e2d; }
    .main-header .greeting { font-size: 16px; color: #6c757d; margin-top: -4px; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ================================================================
# 1. SIDEBAR – OPTIONS
# ================================================================
st.sidebar.markdown("""
<div style="padding: 10px 0 20px 0; text-align: center; color: #1e1e2d;">
    <h3 style="color: #1e1e2d;">📊 Debt Review</h3>
    <p style="color: #6c757d; font-size: 14px;">Operations Dashboard</p>
</div>
""", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Month Selection")
single_month_mode = st.sidebar.checkbox("📌 Single Month Mode", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("🔮 Forecast Mode")
forecast_mode = st.sidebar.checkbox("📌 Forecast Mode (Fee Audit only)", value=False)
if forecast_mode:
    st.sidebar.info("ℹ️ Using only Fees Audit. Payment Report ignored.")

st.sidebar.markdown("---")
st.sidebar.subheader("📆 Date Range")
date_mode = st.sidebar.radio("Date Mode", ["Current Date", "Custom Range"], index=0)

if date_mode == "Custom Range":
    today_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = st.sidebar.date_input("Start Date", today_date - timedelta(days=30))
    end_date = st.sidebar.date_input("End Date", today_date)
    if start_date > end_date:
        st.sidebar.error("Start date must be before end date.")
        st.stop()
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    ref_date = end_dt
    date_range = (start_dt, end_dt)
else:
    ref_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = None
    end_dt = None
    date_range = None

# ================================================================
# 2. GOOGLE DRIVE AUTHENTICATION & DOWNLOAD
# ================================================================
def download_file_from_drive(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

def get_file_id_from_folder(service, folder_id, file_name):
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    else:
        raise Exception(f"File '{file_name}' not found in folder.")

drive_connected = False
try:
    creds_info = {
        "type": "service_account",
        "project_id": st.secrets["PROJECT_ID"],
        "private_key_id": st.secrets["PRIVATE_KEY_ID"],
        "private_key": st.secrets["PRIVATE_KEY"],
        "client_email": st.secrets["CLIENT_EMAIL"],
        "client_id": st.secrets["CLIENT_ID"],
        "auth_uri": st.secrets["AUTH_URI"],
        "token_uri": st.secrets["TOKEN_URI"],
        "auth_provider_x509_cert_url": st.secrets["AUTH_PROVIDER_X509_CERT_URL"],
        "client_x509_cert_url": st.secrets["CLIENT_X509_CERT_URL"],
        "universe_domain": st.secrets.get("UNIVERSE_DOMAIN", "googleapis.com")
    }
    creds = service_account.Credentials.from_service_account_info(creds_info)
    service = build('drive', 'v3', credentials=creds)
    folder_id = st.secrets["FOLDER_ID"]
    fee_file_id = get_file_id_from_folder(service, folder_id, "Monthly Fees Audit.xlsx")
    if not forecast_mode:
        payment_file_id = get_file_id_from_folder(service, folder_id, "Payment Status Report.xlsx")
    else:
        payment_file_id = None
    fee_content = download_file_from_drive(service, fee_file_id)
    if not forecast_mode and payment_file_id is not None:
        payment_content = download_file_from_drive(service, payment_file_id)
    else:
        payment_content = None
    drive_connected = True
except Exception as e:
    st.error(f"❌ Error connecting to Google Drive: {e}")
    st.stop()

if drive_connected:
    st.success("✅ Connected to Google Drive")
else:
    st.warning("⚠️ Not connected to Google Drive")

# ================================================================
# ---- Helper functions ----
# ================================================================
def find_sheet(variants, all_sheets):
    for sheet in all_sheets:
        sheet_upper = sheet.upper()
        for variant in variants:
            if variant in sheet_upper:
                return sheet
    return None

def find_columns(df):
    status_col = None
    for col in df.columns:
        if col.strip().upper() == 'COLLECTION STATUS':
            status_col = col
            break
    if status_col is None:
        for col in df.columns:
            col_lower = str(col).lower()
            if 'note' in col_lower or 'feedback' in col_lower or 'status' in col_lower:
                status_col = col
                break
    if status_col is None:
        status_col = df.columns[-1]

    id_col = None
    for col in df.columns:
        if col.strip().upper() == 'APPLICANT NUMBER':
            id_col = col
            break
    if id_col is None:
        for col in df.columns:
            if col.strip().upper() == 'ID NUMBER':
                id_col = col
                break
    if id_col is None:
        for col in df.columns:
            if any(kw in str(col).lower() for kw in ['id', 'applicant', 'number']):
                id_col = col
                break
    if id_col is None:
        id_col = df.columns[0]

    amount_col = None
    for col in df.columns:
        if col.strip().upper() == 'INSTALMENT AMOUNT':
            amount_col = col
            break
    if amount_col is None:
        for col in df.columns:
            if 'INSTALMENT AMOUNT' in col:
                amount_col = col
                break
    if amount_col is None:
        amount_col = df.columns[-2]

    stage_col = None
    for col in df.columns:
        if col.strip().upper() == 'INSTALLMENT NO':
            stage_col = col
            break
    if stage_col is None:
        for col in df.columns:
            if 'INSTALLMENT NO' in col or 'INSTALLMENT' in col:
                stage_col = col
                break
    if stage_col is None:
        stage_col = df.columns[3]

    date_col = None
    for col in df.columns:
        if col.strip().upper() == 'COLLECTION DATE':
            date_col = col
            break
    if date_col is None:
        for col in df.columns:
            if 'COLLECTION DATE' in col or 'DATE' in col:
                date_col = col
                break

    name_col = None
    for col in df.columns:
        if col.strip().upper() == 'APPLICANT NAME':
            name_col = col
            break
    if name_col is None:
        for col in df.columns:
            if 'APPLICANT NAME' in col or 'NAME' in col:
                name_col = col
                break

    cell_col = None
    for col in df.columns:
        if col.strip().upper() == 'CELL':
            cell_col = col
            break
    if cell_col is None:
        for col in df.columns:
            if 'CELL' in col or 'MOBILE' in col or 'PHONE' in col:
                cell_col = col
                break

    return status_col, id_col, amount_col, stage_col, date_col, name_col, cell_col

def extract_future_debits(df, sheet_name, filter_future=True):
    if df is None or df.empty:
        return pd.DataFrame()
    status_col, id_col, amount_col, stage_col, date_col, name_col, cell_col = find_columns(df)
    df_temp = df.copy()
    df_temp = df_temp[df_temp[id_col].notna()]
    df_temp = df_temp[df_temp[id_col].astype(str).str.strip() != '']
    df_temp = df_temp[~df_temp[id_col].astype(str).str.upper().str.contains('ID|TOTAL|SUB', na=False)]
    if filter_future:
        future_mask = df_temp[status_col].astype(str).str.upper().str.contains('FUTURE', na=False)
        df_future = df_temp[future_mask].copy()
    else:
        df_future = df_temp.copy()
        if status_col in df_future.columns:
            cancel_mask = df_future[status_col].astype(str).str.upper().str.contains('CANCELLED', na=False)
            df_future = df_future[~cancel_mask]
    if df_future.empty:
        return pd.DataFrame()
    df_future['payment_stage'] = pd.to_numeric(df_future[stage_col], errors='coerce')
    df_future = df_future[df_future['payment_stage'].isin([1, 2])].copy()
    if date_col is not None:
        df_future['due_date'] = pd.to_datetime(df_future[date_col], errors='coerce')
    else:
        df_future['due_date'] = pd.NaT
    df_future['id_number'] = df_future[id_col].apply(normalize_id)
    df_future['amount'] = pd.to_numeric(df_future[amount_col], errors='coerce')
    if name_col is not None:
        df_future['client_name'] = df_future[name_col]
    else:
        df_future['client_name'] = ''
    if cell_col is not None:
        df_future['cell'] = df_future[cell_col]
    else:
        df_future['cell'] = ''
    df_future = df_future.dropna(subset=['id_number', 'payment_stage', 'due_date', 'amount'])
    df_future['sheet_source'] = sheet_name
    return df_future

# ================================================================
# ---- Core processing function (cached) ----
# ================================================================
@st.cache_data
def process_data(fee_content, payment_content, current_sheet, next_sheet, single_month_mode=False, ref_date=None, forecast_mode=False, date_range=None):

    def get_settled_df(df, start_date=None, end_date=None):
        temp = df[df['status'].str.upper() == 'SETTLED']
        if start_date and end_date:
            temp = temp[temp['effective_settlement_date'] >= start_date]
            temp = temp[temp['effective_settlement_date'] <= end_date]
        return temp

    def get_failed_df(df, start_date=None, end_date=None):
        temp = df[df['status'].str.upper() == 'FAILED']
        if start_date and end_date:
            temp = temp[temp['collection_date'] >= start_date]
            temp = temp[temp['collection_date'] <= end_date]
        return temp

    def get_disputed_df(df, start_date=None, end_date=None):
        temp = df[df['status'].str.upper() == 'DISPUTED']
        if start_date and end_date:
            temp = temp[temp['collection_date'] >= start_date]
            temp = temp[temp['collection_date'] <= end_date]
        return temp

    def get_cancelled_mandate_df(df, start_date=None, end_date=None):
        temp = df[df['status'].astype(str).str.upper().str.contains('CLIENT CANCELLED MANDATE', na=False)]
        if start_date and end_date:
            temp = temp[temp['collection_date'] >= start_date]
            temp = temp[temp['collection_date'] <= end_date]
        return temp

    def get_sale_not_submitted_df(df, start_date=None, end_date=None):
        temp = df[df['status'].astype(str).str.upper().str.contains('SALE NOT SUBMITTED', na=False)]
        if start_date and end_date:
            temp = temp[temp['collection_date'] >= start_date]
            temp = temp[temp['collection_date'] <= end_date]
        return temp

    def get_unique_stage_clients(df, status_filter=None, date_col=None, start_date=None, end_date=None):
        temp = df.copy()
        if status_filter:
            temp = temp[temp['status'].str.upper() == status_filter.upper()]
        if date_col and start_date and end_date:
            temp = temp[temp[date_col] >= start_date]
            temp = temp[temp[date_col] <= end_date]
        if not temp.empty:
            grouped = temp.groupby('id_number').agg({
                'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
                'amount': 'sum', 'status': 'first', 'collection_date': 'max'
            }).reset_index()
            return grouped
        else:
            return pd.DataFrame()

    def get_latest_record(group):
        return group.sort_values('collection_date').iloc[-1]

    def ensure_columns(df, required_cols):
        for col in required_cols:
            if col not in df.columns:
                df[col] = ''
        return df

    if ref_date is None:
        ref_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(ref_date, datetime) is False:
        ref_date = datetime.combine(ref_date, datetime.min.time())
    today = ref_date

    if date_range:
        start_dt, end_dt = date_range
        if isinstance(start_dt, datetime) is False:
            start_dt = datetime.combine(start_dt, datetime.min.time())
        if isinstance(end_dt, datetime) is False:
            end_dt = datetime.combine(end_dt, datetime.max.time())
        use_custom_range = True
    else:
        use_custom_range = False
        start_dt = None
        end_dt = None

    # Settled Period Total = last Friday → today
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    first_of_month = today.replace(day=1)

    fee_df_current = pd.read_excel(fee_content, sheet_name=current_sheet)
    fee_df_next = None
    if not single_month_mode and next_sheet is not None:
        fee_df_next = pd.read_excel(fee_content, sheet_name=next_sheet)

    future_current = extract_future_debits(fee_df_current, current_sheet, filter_future=True)
    future_next = extract_future_debits(fee_df_next, next_sheet, filter_future=False) if fee_df_next is not None else pd.DataFrame()
    all_future = pd.concat([future_current, future_next], ignore_index=True)

    status_col, id_col, amount_col, stage_col, date_col, name_col, cell_col = find_columns(fee_df_current)
    future_mask_current = fee_df_current[status_col].astype(str).str.upper().str.contains('FUTURE', na=False)
    fee_status_df = fee_df_current[~future_mask_current].copy()
    fee_status_df = fee_status_df[fee_status_df[status_col].notna()]
    fee_status_df = fee_status_df[fee_status_df[status_col].astype(str).str.strip() != '']
    fee_status_df = fee_status_df[~fee_status_df[status_col].astype(str).str.upper().str.contains('TOTAL', na=False)]
    fee_status_df = fee_status_df[fee_status_df[id_col].astype(str).str.strip() != id_col]

    fee_base_cols = [id_col, stage_col, amount_col, status_col]
    if date_col is not None:
        fee_base_cols.append(date_col)
    if name_col is not None:
        fee_base_cols.append(name_col)
    if cell_col is not None:
        fee_base_cols.append(cell_col)

    fee_base = fee_status_df[fee_base_cols].copy()
    fee_base.rename(columns={id_col: 'id_number', stage_col: 'payment_stage', amount_col: 'amount', status_col: 'status'}, inplace=True)
    if date_col is not None:
        fee_base.rename(columns={date_col: 'collection_date'}, inplace=True)
    if name_col is not None:
        fee_base.rename(columns={name_col: 'client_name'}, inplace=True)
    if cell_col is not None:
        fee_base.rename(columns={cell_col: 'cell'}, inplace=True)

    # Ensure all downstream-required columns exist
    for col in ['client_name', 'cell', 'collection_date']:
        if col not in fee_base.columns:
            fee_base[col] = ''

    # ✅ FIX: Use normalize_id to clean Fee Audit IDs
    fee_base['id_number'] = fee_base['id_number'].apply(normalize_id)

    fee_base['payment_stage'] = pd.to_numeric(fee_base['payment_stage'], errors='coerce')
    fee_base['amount'] = pd.to_numeric(fee_base['amount'], errors='coerce')
    fee_base['collection_date'] = pd.to_datetime(fee_base['collection_date'], errors='coerce')
    fee_base['status'] = fee_base['status'].astype(str).str.strip()
    fee_base = fee_base.dropna(subset=['id_number', 'payment_stage'])

    if forecast_mode:
        raw = fee_base.copy()
        for col in ['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status', 'collection_date']:
            if col not in raw.columns:
                raw[col] = '' if col in ['client_name', 'cell', 'status'] else 0
        raw['due_date'] = raw['collection_date']
        raw['effective_settlement_date'] = raw['collection_date']
        failed_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])
        tracking_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])
        sale_not_submitted_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])
        pmt_debug = None
    else:
        try:
            df_pmt = pd.read_excel(payment_content, sheet_name='Details', header=3)
        except:
            try:
                df_pmt = pd.read_excel(payment_content, header=3)
            except:
                df_pmt = pd.read_excel(payment_content)

        raw_pmt = df_pmt.copy()

        pmt_status_col, pmt_id_col, pmt_amount_col, pmt_stage_col, pmt_date_col, pmt_name_col, pmt_cell_col = find_columns(df_pmt)

        pmt_sms = df_pmt.copy()
        pmt_sms.rename(columns={
            pmt_id_col: 'id_number', pmt_name_col: 'client_name', pmt_cell_col: 'cell',
            pmt_stage_col: 'payment_stage', pmt_amount_col: 'amount',
            pmt_status_col: 'status', pmt_date_col: 'collection_date'
        }, inplace=True)

        pmt_sms['payment_stage'] = pd.to_numeric(pmt_sms['payment_stage'], errors='coerce')
        pmt_sms['amount'] = pd.to_numeric(pmt_sms['amount'], errors='coerce')
        pmt_sms['collection_date'] = pd.to_datetime(pmt_sms['collection_date'], errors='coerce')
        # ✅ FIX: Clean IDs
        pmt_sms['id_number'] = pmt_sms['id_number'].apply(normalize_id)
        pmt_sms = pmt_sms.dropna(subset=['id_number', 'payment_stage', 'amount'])

        pmt_debug = {
            'columns_detected': {'status': pmt_status_col, 'id': pmt_id_col, 'amount': pmt_amount_col,
                                 'stage': pmt_stage_col, 'date': pmt_date_col, 'name': pmt_name_col, 'cell': pmt_cell_col},
            'sample_rows': df_pmt.head(5).to_dict('records'),
            'unique_statuses': sorted(pmt_sms['status'].dropna().unique().tolist()) if not pmt_sms.empty else [],
            'pmt_sms_sample': pmt_sms.head(5).to_dict('records') if not pmt_sms.empty else [],
            'failed_count': 0, 'tracking_count': 0, 'disputed_count': 0,
            'cancelled_mandate_count': 0, 'sale_not_submitted_count': 0
        }

        # ================================================================
        # ✅ FIX: Failed SMS list now includes ALL Failed/Disputed clients
        #    (no date restriction to last Friday → today)
        # ================================================================
        failed_keywords = ['FAILED', 'FAIL', 'DECLINED', 'REJECTED', 'DISPUTED', 'CLIENT CANCELLED MANDATE']
        failed_mask = pmt_sms['status'].str.upper().str.contains('|'.join(failed_keywords), na=False)
        failed_pmt = pmt_sms[failed_mask].copy()
        # (No date filter — all failures included)

        pmt_debug['failed_count'] = len(failed_pmt)

        tracking_keywords = ['TRACKING', 'INTRACKING', 'PENDING', 'OUTSTANDING']
        tracking_mask = pmt_sms['status'].str.upper().str.contains('|'.join(tracking_keywords), na=False)
        tracking_pmt = pmt_sms[tracking_mask].copy()
        pmt_debug['tracking_count'] = len(tracking_pmt)

        sale_not_submitted_mask = pmt_sms['status'].str.upper().str.contains('SALE NOT SUBMITTED', na=False)
        sale_not_submitted_pmt = pmt_sms[sale_not_submitted_mask].copy()

        pmt_debug['disputed_count'] = int(pmt_sms['status'].str.upper().str.contains('DISPUTED', na=False).sum())
        pmt_debug['cancelled_mandate_count'] = int(pmt_sms['status'].str.upper().str.contains('CLIENT CANCELLED MANDATE', na=False).sum())
        pmt_debug['sale_not_submitted_count'] = int(sale_not_submitted_mask.sum())

        def get_latest_per_client(df):
            if df.empty:
                return df
            df = df.sort_values('collection_date')
            return df.groupby('id_number').tail(1).reset_index(drop=True)

        failed_pmt_unique = get_latest_per_client(failed_pmt)
        tracking_pmt_unique = get_latest_per_client(tracking_pmt)
        sale_not_submitted_unique = get_latest_per_client(sale_not_submitted_pmt)

        sms_cols = ['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status']

        failed_sms_pmt = failed_pmt_unique[sms_cols].copy() if not failed_pmt_unique.empty else pd.DataFrame(columns=sms_cols)
        tracking_sms_pmt = tracking_pmt_unique[sms_cols].copy() if not tracking_pmt_unique.empty else pd.DataFrame(columns=sms_cols)
        sale_not_submitted_sms_pmt = sale_not_submitted_unique[sms_cols].copy() if not sale_not_submitted_unique.empty else pd.DataFrame(columns=sms_cols)

        if not failed_sms_pmt.empty:
            failed_sms_pmt.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status']
        else:
            failed_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])

        if not tracking_sms_pmt.empty:
            tracking_sms_pmt.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status']
        else:
            tracking_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])

        if not sale_not_submitted_sms_pmt.empty:
            sale_not_submitted_sms_pmt.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status']
        else:
            sale_not_submitted_sms_pmt = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])

        payment_id_col = None
        for col in raw_pmt.columns:
            if col.strip().upper() == 'ID NUMBER':
                payment_id_col = col
                break
        if payment_id_col is None:
            for col in raw_pmt.columns:
                if col.strip().upper() == 'APPLICANT NUMBER':
                    payment_id_col = col
                    break
        if payment_id_col is None:
            for col in raw_pmt.columns:
                if any(kw in str(col).lower() for kw in ['id', 'applicant', 'number']):
                    payment_id_col = col
                    break
        if payment_id_col is None:
            payment_id_col = raw_pmt.columns[0]
        raw_pmt.rename(columns={payment_id_col: 'id_number'}, inplace=True)

        col_map = {
            'APPLICANT NAME': 'client_name_pmt', 'CELL': 'cell_pmt',
            'INSTALLMENT NO': 'payment_stage_pmt', 'TOTAL INSTALMENTS LOADED': 'total_instalments',
            'INSTALMENT AMOUNT': 'amount_pmt', 'COLLECTION STATUS': 'status_pmt',
            'COLLECTION DATE': 'collection_date_pmt', 'SETTLEMENT DATE': 'settlement_date_pmt',
            'DISPUTE DATE': 'dispute_date_pmt', 'Tracking Days Used': 'tracking_days',
            'Cancelled Date': 'cancelled_date_pmt', 'Mandate Consumer Bank': 'bank'
        }
        for old, new in col_map.items():
            if old in raw_pmt.columns:
                raw_pmt.rename(columns={old: new}, inplace=True)

        # ✅ FIX: Clean IDs
        raw_pmt['id_number'] = raw_pmt['id_number'].apply(normalize_id)
        raw_pmt['payment_stage_pmt'] = pd.to_numeric(raw_pmt['payment_stage_pmt'], errors='coerce')

        pmt_cols = ['id_number', 'payment_stage_pmt', 'collection_date_pmt', 'settlement_date_pmt',
                    'dispute_date_pmt', 'cell_pmt', 'client_name_pmt', 'amount_pmt', 'status_pmt',
                    'total_instalments', 'tracking_days', 'cancelled_date_pmt', 'bank']
        pmt_cols_existing = [c for c in pmt_cols if c in raw_pmt.columns]
        pmt_data = raw_pmt[pmt_cols_existing].copy()
        pmt_data = pmt_data.drop_duplicates(subset=['id_number', 'payment_stage_pmt'], keep='first')
        pmt_data.rename(columns={'payment_stage_pmt': 'payment_stage'}, inplace=True)

        merged = fee_base.merge(pmt_data, on=['id_number', 'payment_stage'], how='left')

        if 'client_name' in merged.columns and 'client_name_pmt' in merged.columns:
            merged['client_name'] = merged['client_name'].fillna(merged['client_name_pmt'])
        elif 'client_name_pmt' in merged.columns:
            merged['client_name'] = merged['client_name_pmt']
        if 'cell' in merged.columns and 'cell_pmt' in merged.columns:
            merged['cell'] = merged['cell'].fillna(merged['cell_pmt'])
        elif 'cell_pmt' in merged.columns:
            merged['cell'] = merged['cell_pmt']
        if 'collection_date' in merged.columns and 'collection_date_pmt' in merged.columns:
            merged['collection_date'] = merged['collection_date'].fillna(merged['collection_date_pmt'])
        elif 'collection_date_pmt' in merged.columns:
            merged['collection_date'] = merged['collection_date_pmt']

        merged['settlement_date'] = merged['settlement_date_pmt'] if 'settlement_date_pmt' in merged.columns else pd.NaT
        merged['dispute_date'] = merged['dispute_date_pmt'] if 'dispute_date_pmt' in merged.columns else pd.NaT
        merged['cancelled_date'] = merged['cancelled_date_pmt'] if 'cancelled_date_pmt' in merged.columns else pd.NaT

        drop_cols = ['client_name_pmt', 'cell_pmt', 'amount_pmt', 'status_pmt',
                     'collection_date_pmt', 'settlement_date_pmt', 'dispute_date_pmt', 'cancelled_date_pmt']
        merged.drop(columns=[c for c in drop_cols if c in merged.columns], inplace=True, errors='ignore')

        # Keep "Client Cancelled Mandate" rows, remove generic cancellations
        status_upper_series = merged['status'].astype(str).str.upper()
        cancelled_mask = status_upper_series.str.contains('CANCELLED', na=False)
        keep_mask = status_upper_series.str.contains('CLIENT CANCELLED MANDATE', na=False)
        merged = merged[~(cancelled_mask & ~keep_mask)].copy()

        if merged.empty:
            return None

        raw = merged

    raw['payment_stage'] = pd.to_numeric(raw['payment_stage'], errors='coerce')
    raw['amount'] = pd.to_numeric(raw['amount'], errors='coerce')
    for col in ['collection_date', 'settlement_date', 'dispute_date', 'cancelled_date']:
        if col in raw.columns:
            raw[col] = pd.to_datetime(raw[col], errors='coerce')
    raw['due_date'] = raw['collection_date']

    if 'settlement_date' in raw.columns and not forecast_mode:
        raw['effective_settlement_date'] = raw['settlement_date'].fillna(raw['collection_date'])
    else:
        raw['effective_settlement_date'] = raw['collection_date']

    if use_custom_range:
        raw = raw[raw['effective_settlement_date'] >= start_dt]
        raw = raw[raw['effective_settlement_date'] <= end_dt]
        raw = raw[raw['collection_date'] >= start_dt]
        raw = raw[raw['collection_date'] <= end_dt]
        today = end_dt
    else:
        raw = raw[raw['collection_date'] <= today]
        raw = raw[raw['effective_settlement_date'] <= today]
        raw = raw[raw['due_date'] <= today]

    raw_stage_1_2 = raw[raw['payment_stage'].isin([1, 2])].copy()

    settled_all = raw[raw['status'].str.upper() == 'SETTLED'].copy()
    settled_all = settled_all.sort_values(['id_number', 'effective_settlement_date'])
    settled_all['settlement_rank'] = settled_all.groupby('id_number').cumcount() + 1

    raw = raw.merge(settled_all[['id_number', 'effective_settlement_date', 'amount', 'status', 'settlement_rank']],
                    on=['id_number', 'effective_settlement_date', 'amount', 'status'], how='left')
    raw_stage_1_2 = raw_stage_1_2.merge(settled_all[['id_number', 'effective_settlement_date', 'amount', 'status', 'settlement_rank']],
                                        on=['id_number', 'effective_settlement_date', 'amount', 'status'], how='left')

    RESTRUCTURE_CAP = 8000
    LEGAL_CAP = 8000
    AFTERCARE_CAP = 450
    AFTERCARE_RATE = 0.05
    LEGAL_CAP_UNDER_3000 = 3000

    def calculate_revenue(row):
        amount = row['amount']
        rank = row['settlement_rank']
        if pd.isna(rank):
            return 0
        if rank == 1:
            if amount < 3000:
                return amount
            else:
                return min(amount, RESTRUCTURE_CAP)
        elif rank == 2:
            if amount < 3000:
                return min(amount * 1.5, LEGAL_CAP_UNDER_3000)
            else:
                return min(amount, LEGAL_CAP)
        else:
            return min(amount * AFTERCARE_RATE, AFTERCARE_CAP)

    raw['revenue'] = raw.apply(calculate_revenue, axis=1)
    raw_stage_1_2['revenue'] = raw_stage_1_2.apply(calculate_revenue, axis=1)

    if use_custom_range:
        settled_today_df = get_settled_df(raw_stage_1_2, end_dt, end_dt)
        settled_cycle_df = get_settled_df(raw_stage_1_2, start_dt, end_dt)
        settled_mtd_df = get_settled_df(raw_stage_1_2, start_dt, end_dt)
        settling_df = get_unique_stage_clients(raw_stage_1_2, 'Settling', 'collection_date', start_dt, end_dt)
        submitted_df = get_unique_stage_clients(raw_stage_1_2, 'Submitted', 'collection_date', start_dt, end_dt)
        sub_col_df = get_unique_stage_clients(raw_stage_1_2, 'Submitting Collection', 'collection_date', start_dt, end_dt)
        tracking_temp = raw_stage_1_2[
            (raw_stage_1_2['status'].str.upper().isin(['TRACKING', 'INTRACKING'])) &
            (raw_stage_1_2['collection_date'] >= start_dt) &
            (raw_stage_1_2['collection_date'] <= end_dt)
        ]
        failed_cycle_df = get_failed_df(raw_stage_1_2, start_dt, end_dt)
        failed_mtd_df = get_failed_df(raw_stage_1_2, start_dt, end_dt)
        disputed_df = get_unique_stage_clients(raw_stage_1_2, 'Disputed', 'collection_date', start_dt, end_dt)
        disputed_mtd_df = get_disputed_df(raw_stage_1_2, start_dt, end_dt)
        disputed_mtd_v = disputed_mtd_df['amount'].sum()

        cancelled_mandate_mtd_df = get_cancelled_mandate_df(raw_stage_1_2, start_dt, end_dt)
        cancelled_mandate_mtd_v = cancelled_mandate_mtd_df['amount'].sum()
        cancelled_mandate_c = len(cancelled_mandate_mtd_df)

        sale_not_submitted_mtd_df = get_sale_not_submitted_df(raw_stage_1_2, start_dt, end_dt)
        sale_not_submitted_mtd_v = sale_not_submitted_mtd_df['amount'].sum()
        sale_not_submitted_c = len(sale_not_submitted_mtd_df)

        current_month_settled = raw_stage_1_2[
            (raw_stage_1_2['status'].str.upper() == 'SETTLED') &
            (raw_stage_1_2['effective_settlement_date'] >= start_dt) &
            (raw_stage_1_2['effective_settlement_date'] <= end_dt)
        ]
    else:
        settled_today_df = get_settled_df(raw_stage_1_2, today, today)
        settled_cycle_df = get_settled_df(raw_stage_1_2, last_friday, today)
        settled_mtd_df = get_settled_df(raw_stage_1_2, first_of_month, today)
        settling_df = get_unique_stage_clients(raw_stage_1_2, 'Settling')
        submitted_df = get_unique_stage_clients(raw_stage_1_2, 'Submitted')
        sub_col_df = get_unique_stage_clients(raw_stage_1_2, 'Submitting Collection')
        tracking_temp = raw_stage_1_2[raw_stage_1_2['status'].str.upper().isin(['TRACKING', 'INTRACKING'])]
        failed_cycle_df = get_failed_df(raw_stage_1_2, last_friday, today)
        failed_mtd_df = get_failed_df(raw_stage_1_2, first_of_month, today)
        disputed_df = get_unique_stage_clients(raw_stage_1_2, 'Disputed')
        disputed_mtd_df = get_disputed_df(raw_stage_1_2, first_of_month, today)
        disputed_mtd_v = disputed_mtd_df['amount'].sum()

        cancelled_mandate_mtd_df = get_cancelled_mandate_df(raw_stage_1_2, first_of_month, today)
        cancelled_mandate_mtd_v = cancelled_mandate_mtd_df['amount'].sum()
        cancelled_mandate_c = len(cancelled_mandate_mtd_df)

        sale_not_submitted_mtd_df = get_sale_not_submitted_df(raw_stage_1_2, first_of_month, today)
        sale_not_submitted_mtd_v = sale_not_submitted_mtd_df['amount'].sum()
        sale_not_submitted_c = len(sale_not_submitted_mtd_df)

        current_month_settled = raw_stage_1_2[
            (raw_stage_1_2['status'].str.upper() == 'SETTLED') &
            (raw_stage_1_2['effective_settlement_date'] >= first_of_month) &
            (raw_stage_1_2['effective_settlement_date'] <= today)
        ]

    if not tracking_temp.empty:
        tracking_df = tracking_temp.groupby('id_number').agg({
            'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
            'amount': 'sum', 'status': 'first', 'collection_date': 'max'
        }).reset_index()
    else:
        tracking_df = pd.DataFrame()

    settled_today_c, settled_today_v = len(settled_today_df), settled_today_df['amount'].sum()
    settled_cycle_c, settled_cycle_v = len(settled_cycle_df), settled_cycle_df['amount'].sum()
    settled_mtd_c, settled_mtd_v = len(settled_mtd_df), settled_mtd_df['amount'].sum()
    settling_c, settling_v = len(settling_df), settling_df['amount'].sum() if not settling_df.empty else 0
    submitted_c, submitted_v = len(submitted_df), submitted_df['amount'].sum() if not submitted_df.empty else 0
    sub_col_c, sub_col_v = len(sub_col_df), sub_col_df['amount'].sum() if not sub_col_df.empty else 0
    tracking_c, tracking_v = len(tracking_df), tracking_df['amount'].sum() if not tracking_df.empty else 0
    failed_cycle_c, failed_cycle_v = len(failed_cycle_df), failed_cycle_df['amount'].sum()
    failed_mtd_c, failed_mtd_v = len(failed_mtd_df), failed_mtd_df['amount'].sum()
    disputed_c, disputed_v = len(disputed_df), disputed_df['amount'].sum() if not disputed_df.empty else 0

    revenue_total = current_month_settled['revenue'].sum()

    settled_clients = raw_stage_1_2[raw_stage_1_2['status'].str.upper() == 'SETTLED'].copy()
    rank_1_revenue = settled_clients[settled_clients['settlement_rank'] == 1]['revenue']
    rank_2_revenue = settled_clients[settled_clients['settlement_rank'] == 2]['revenue']
    rank_3plus_revenue = settled_clients[settled_clients['settlement_rank'] >= 3]['revenue']

    avg_rank1 = rank_1_revenue.mean() if not rank_1_revenue.empty else 8000
    avg_rank2 = rank_2_revenue.mean() if not rank_2_revenue.empty else 8000
    avg_rank3 = rank_3plus_revenue.mean() if not rank_3plus_revenue.empty else 450

    new_clients_est = max(1, len(settled_clients[settled_clients['settlement_rank'] == 1]['id_number'].unique()) // 12) if not settled_clients.empty else 1
    legal_clients_est = max(1, len(settled_clients[settled_clients['settlement_rank'] == 2]['id_number'].unique()) // 12) if not settled_clients.empty else 1
    after_clients_est = max(1, len(settled_clients[settled_clients['settlement_rank'] >= 3]['id_number'].unique()) // 12) if not settled_clients.empty else 1

    forecast_restructuring = new_clients_est * avg_rank1
    forecast_legal = legal_clients_est * avg_rank2
    forecast_aftercare = after_clients_est * avg_rank3
    forecast_admin_app = new_clients_est * 350
    forecast_total = forecast_restructuring + forecast_aftercare + forecast_admin_app + forecast_legal

    denominator = settled_mtd_v + failed_mtd_v + disputed_mtd_v
    if denominator > 0:
        success_rate = (settled_mtd_v / denominator) * 100
    else:
        success_rate = 0

    # ---- DEBITS ----
    if use_custom_range:
        def extract_all_debits(df, sheet_name):
            if df is None or df.empty:
                return pd.DataFrame()
            status_col, id_col, amount_col, stage_col, date_col, name_col, cell_col = find_columns(df)
            if date_col is None:
                return pd.DataFrame()
            df_temp = df.copy()
            df_temp = df_temp[df_temp[id_col].notna()]
            df_temp = df_temp[df_temp[id_col].astype(str).str.strip() != '']
            df_temp = df_temp[~df_temp[id_col].astype(str).str.upper().str.contains('ID|TOTAL|SUB', na=False)]
            df_temp['due_date'] = pd.to_datetime(df_temp[date_col], errors='coerce')
            df_temp['amount'] = pd.to_numeric(df_temp[amount_col], errors='coerce')
            if status_col in df_temp.columns:
                cancel_mask = df_temp[status_col].astype(str).str.upper().str.contains('CANCELLED', na=False)
                df_temp = df_temp[~cancel_mask]
            df_temp = df_temp.dropna(subset=['due_date', 'amount'])
            df_temp = df_temp[df_temp['amount'] > 0]
            df_temp['id_number'] = df_temp[id_col].apply(normalize_id)
            df_temp['client_name'] = df_temp[name_col] if name_col else ''
            df_temp['cell'] = df_temp[cell_col] if cell_col else ''
            df_temp['payment_stage'] = pd.to_numeric(df_temp[stage_col], errors='coerce')
            return df_temp[['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'due_date']]

        debits_current = extract_all_debits(fee_df_current, current_sheet)
        debits_next = extract_all_debits(fee_df_next, next_sheet) if fee_df_next is not None else pd.DataFrame()
        all_debits = pd.concat([debits_current, debits_next], ignore_index=True)
        range_debits = all_debits[(all_debits['due_date'] >= start_dt) & (all_debits['due_date'] <= end_dt)]
        current_debits_c = range_debits['id_number'].nunique()
        current_debits_v = range_debits['amount'].sum()
        next_debits_c = 0
        next_debits_v = 0
        range_debits_df = range_debits.copy()
    else:
        if all_future.empty:
            current_debits_c = 0
            current_debits_v = 0
            next_debits_c = 0
            next_debits_v = 0
            range_debits_df = pd.DataFrame()
        else:
            tomorrow = today + timedelta(days=1)
            if today.month == 12:
                last_day_month = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
            else:
                last_day_month = today.replace(month=today.month+1, day=1) - timedelta(days=1)
            if today.month == 12:
                first_of_next_month = today.replace(year=today.year+1, month=1, day=1)
            else:
                first_of_next_month = today.replace(month=today.month+1, day=1)
            last_of_next_month = (first_of_next_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            if single_month_mode:
                first_of_current = today.replace(day=1)
                current_future = all_future[(all_future['due_date'] >= first_of_current) & (all_future['due_date'] <= last_day_month)]
                current_debits_c = current_future['id_number'].nunique()
                current_debits_v = current_future['amount'].sum()
                next_debits_c = 0
                next_debits_v = 0
                range_debits_df = current_future
            else:
                current_future = all_future[(all_future['due_date'] >= tomorrow) & (all_future['due_date'] <= last_day_month)]
                current_debits_c = current_future['id_number'].nunique()
                current_debits_v = current_future['amount'].sum()
                if next_sheet is not None:
                    next_future = all_future[(all_future['due_date'] >= first_of_next_month) & (all_future['due_date'] <= last_of_next_month)]
                    next_debits_c = next_future['id_number'].nunique()
                    next_debits_v = next_future['amount'].sum()
                else:
                    next_debits_c = 0
                    next_debits_v = 0
                range_debits_df = pd.concat([current_future, next_future], ignore_index=True)

    # ---- Priority Queue ----
    priority_df = raw[(raw['status'].str.upper().isin(['FAILED', 'TRACKING', 'INTRACKING'])) |
                      ((raw['payment_stage'].isin([1, 2, 3])) &
                       (raw['status'].str.upper().isin(['FAILED', 'TRACKING', 'INTRACKING', 'LATE'])))]
    if not priority_df.empty:
        for col in ['cell', 'client_name', 'id_number']:
            if col not in priority_df.columns:
                priority_df[col] = ''
        priority_df['amount'] = priority_df['amount'].fillna(0)
        priority_df['payment_stage'] = priority_df['payment_stage'].fillna(0)
        if 'due_date' not in priority_df.columns:
            priority_df['due_date'] = pd.NaT

        priority_df = priority_df.sort_values('collection_date').groupby('id_number').apply(get_latest_record).reset_index(drop=True)

        def get_weight(stage):
            if stage in [1, 2]: return 100
            if stage == 3: return 90
            if stage in [4, 5, 6]: return 60
            if stage >= 7: return 30
            return 50

        priority_df['stage_weight'] = priority_df['payment_stage'].apply(get_weight)
        if 'due_date' in priority_df.columns:
            priority_df['days_overdue'] = (today - priority_df['due_date']).dt.days.fillna(0)
        else:
            priority_df['days_overdue'] = 0
        priority_df['priority_score'] = priority_df['stage_weight'] + priority_df['days_overdue'] * 2
        priority_df['Priority Level'] = priority_df['priority_score'].apply(lambda x: 'High' if x >= 150 else ('Medium' if x >= 100 else 'Low'))

        cols = ['id_number', 'client_name', 'cell', 'payment_stage', 'days_overdue', 'amount', 'status', 'priority_score', 'Priority Level']
        for col in cols:
            if col not in priority_df.columns:
                priority_df[col] = ''

        failed_priority = priority_df[priority_df['status'].str.upper() == 'FAILED'].copy()
        tracking_priority = priority_df[priority_df['status'].str.upper().isin(['TRACKING', 'INTRACKING'])].copy()
        failed_priority = failed_priority.sort_values('priority_score', ascending=False)
        tracking_priority = tracking_priority.sort_values('priority_score', ascending=False)

        if not failed_priority.empty:
            failed_priority = failed_priority[cols]
            failed_priority.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level']
        else:
            failed_priority = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level'])

        if not tracking_priority.empty:
            tracking_priority = tracking_priority[cols]
            tracking_priority.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level']
        else:
            tracking_priority = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level'])

        separator = pd.DataFrame([[''] * len(failed_priority.columns)], columns=failed_priority.columns)
        header_failed = pd.DataFrame([['=== FAILED PAYMENTS ==='] + [''] * (len(failed_priority.columns) - 1)], columns=failed_priority.columns)
        header_tracking = pd.DataFrame([['=== TRACKING / INTRACKING CLIENTS ==='] + [''] * (len(failed_priority.columns) - 1)], columns=failed_priority.columns)

        combined_priority = pd.concat([header_failed, failed_priority, separator, header_tracking, tracking_priority], ignore_index=True)
    else:
        cols = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level']
        combined_priority = pd.DataFrame(columns=cols)

    # ---- Failed Clients list ----
    def get_latest_record_for_sheet(df):
        if df.empty:
            return df
        if 'id_number' not in df.columns:
            id_candidates = [col for col in df.columns if 'id' in col.lower() or 'number' in col.lower()]
            if id_candidates:
                df['id_number'] = df[id_candidates[0]].apply(normalize_id)
            else:
                df['id_number'] = df.index.astype(str)
        return df.sort_values('collection_date').groupby('id_number').apply(lambda g: g.iloc[-1]).reset_index(drop=True)

    failed_clients = raw[raw['status'].str.upper() == 'FAILED'].copy()
    if not failed_clients.empty:
        failed_clients = get_latest_record_for_sheet(failed_clients)
        ensure_columns(failed_clients, ['id_number', 'client_name', 'cell', 'payment_stage', 'amount'])
        failed_clients = failed_clients[['id_number', 'client_name', 'cell', 'payment_stage', 'amount']]
        failed_clients.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount']
    else:
        failed_clients = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount'])

    def prep_detail_df(df, date_col_name, status_col='status'):
        if df.empty:
            return pd.DataFrame()
        df_out = df.copy()
        if date_col_name not in df_out.columns:
            return pd.DataFrame()
        df_out['date_col'] = df_out[date_col_name]
        for col in ['id_number', 'client_name', 'cell', 'payment_stage', 'amount']:
            if col not in df_out.columns:
                df_out[col] = ''
        cols_to_keep = ['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'date_col']
        if status_col in df_out.columns:
            cols_to_keep.append(status_col)
        df_out = df_out[cols_to_keep]
        df_out.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Date', 'Status'] if status_col in df_out.columns else ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Date']
        return df_out

    detail_dfs = {}
    if not settled_today_df.empty:
        detail_dfs['Settled Today'] = prep_detail_df(settled_today_df, 'effective_settlement_date')
    if not settled_cycle_df.empty:
        detail_dfs['Settled Period'] = prep_detail_df(settled_cycle_df, 'effective_settlement_date')
    if not settling_df.empty:
        detail_dfs['Settling'] = prep_detail_df(settling_df, 'collection_date')
    if not submitted_df.empty:
        detail_dfs['Submitted'] = prep_detail_df(submitted_df, 'collection_date')
    if not sub_col_df.empty:
        detail_dfs['Sub Collect'] = prep_detail_df(sub_col_df, 'collection_date')
    if not tracking_df.empty:
        detail_dfs['Intracking'] = prep_detail_df(tracking_df, 'collection_date')
    if not failed_cycle_df.empty:
        detail_dfs['Failed Period'] = prep_detail_df(failed_cycle_df, 'collection_date')
    if not disputed_df.empty:
        detail_dfs['Disputed'] = prep_detail_df(disputed_df, 'collection_date')

    if not cancelled_mandate_mtd_df.empty:
        cm_dedup = cancelled_mandate_mtd_df.groupby('id_number').agg({
            'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
            'amount': 'sum', 'status': 'first', 'collection_date': 'max'
        }).reset_index()
        detail_dfs['Client Cancelled Mandate'] = prep_detail_df(cm_dedup, 'collection_date')

    if not sale_not_submitted_mtd_df.empty:
        sns_dedup = sale_not_submitted_mtd_df.groupby('id_number').agg({
            'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
            'amount': 'sum', 'status': 'first', 'collection_date': 'max'
        }).reset_index()
        detail_dfs['Sale Not Submitted'] = prep_detail_df(sns_dedup, 'collection_date')

    if use_custom_range and not range_debits_df.empty:
        detail_dfs['Total Due Period'] = range_debits_df[['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'due_date']].copy()
        detail_dfs['Total Due Period'].columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Date']
    else:
        if not range_debits_df.empty:
            detail_dfs['Debits Detail'] = range_debits_df[['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'due_date']].copy()
            detail_dfs['Debits Detail'].columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Date']

    # ---- OVERRIDE: Rebuild Sale Not Submitted & Cancelled Mandate from Fee Audit ----
    if not sale_not_submitted_mtd_df.empty:
        sns_dedup2 = sale_not_submitted_mtd_df.groupby('id_number').agg({
            'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
            'amount': 'sum', 'status': 'first'
        }).reset_index()
        sale_not_submitted_sms_pmt = pd.DataFrame({
            'ID NUMBER': sns_dedup2['id_number'].astype(str),
            'Name': sns_dedup2['client_name'],
            'Cell': sns_dedup2['cell'],
            'Stage': sns_dedup2['payment_stage'],
            'Amount': sns_dedup2['amount'],
            'Status': sns_dedup2['status']
        })
    else:
        sale_not_submitted_sms_pmt = pd.DataFrame(
            columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])

    if not cancelled_mandate_mtd_df.empty:
        cm_dedup2 = cancelled_mandate_mtd_df.groupby('id_number').agg({
            'client_name': 'first', 'cell': 'first', 'payment_stage': 'first',
            'amount': 'sum', 'status': 'first'
        }).reset_index()
        cm_sms = pd.DataFrame({
            'ID NUMBER': cm_dedup2['id_number'].astype(str),
            'Name': cm_dedup2['client_name'],
            'Cell': cm_dedup2['cell'],
            'Stage': cm_dedup2['payment_stage'],
            'Amount': cm_dedup2['amount'],
            'Status': cm_dedup2['status']
        })
        existing_ids = set(failed_sms_pmt['ID NUMBER'].astype(str)) if not failed_sms_pmt.empty else set()
        cm_sms = cm_sms[~cm_sms['ID NUMBER'].astype(str).isin(existing_ids)]
        failed_sms_pmt = pd.concat([failed_sms_pmt, cm_sms], ignore_index=True)

    return {
        'ref_date': today,
        'current_sheet': current_sheet,
        'next_sheet': next_sheet if not single_month_mode else None,
        'single_month_mode': single_month_mode,
        'current_debits_c': current_debits_c,
        'current_debits_v': current_debits_v,
        'next_debits_c': next_debits_c,
        'next_debits_v': next_debits_v,
        'settled_today_c': settled_today_c,
        'settled_today_v': settled_today_v,
        'settled_cycle_c': settled_cycle_c,
        'settled_cycle_v': settled_cycle_v,
        'settled_mtd_c': settled_mtd_c,
        'settled_mtd_v': settled_mtd_v,
        'settling_c': settling_c,
        'settling_v': settling_v,
        'submitted_c': submitted_c,
        'submitted_v': submitted_v,
        'sub_col_c': sub_col_c,
        'sub_col_v': sub_col_v,
        'tracking_c': tracking_c,
        'tracking_v': tracking_v,
        'failed_cycle_c': failed_cycle_c,
        'failed_cycle_v': failed_cycle_v,
        'failed_mtd_c': failed_mtd_c,
        'failed_mtd_v': failed_mtd_v,
        'disputed_c': disputed_c,
        'disputed_v': disputed_v,
        'cancelled_mandate_c': cancelled_mandate_c,
        'cancelled_mandate_v': cancelled_mandate_mtd_v,
        'sale_not_submitted_c': sale_not_submitted_c,
        'sale_not_submitted_v': sale_not_submitted_mtd_v,
        'revenue_total': revenue_total,
        'forecast_restructuring': forecast_restructuring,
        'forecast_legal': forecast_legal,
        'forecast_aftercare': forecast_aftercare,
        'forecast_admin_app': forecast_admin_app,
        'forecast_total': forecast_total,
        'success_rate': success_rate,
        'combined_priority': combined_priority,
        'failed_sms': failed_sms_pmt,
        'tracking_sms': tracking_sms_pmt,
        'sale_not_submitted_sms': sale_not_submitted_sms_pmt,
        'failed_clients': failed_clients,
        'detail_dfs': detail_dfs,
        'raw': raw,
        'raw_stage_1_2': raw_stage_1_2,
        'all_future': all_future,
        'fee_status_df': fee_status_df,
        'fee_base': fee_base,
        'use_custom_range': use_custom_range,
        'pmt_debug': pmt_debug if not forecast_mode else None
    }

# ================================================================
# ---- Helper function to send SMS ----
# ================================================================
def send_sms(to_number, message, provider_type="generic"):
    try:
        if provider_type == "generic":
            provider = GenericSMSProvider(
                st.secrets["SMS_API_URL"],
                st.secrets["SMS_API_KEY"],
                st.secrets["SMS_FROM_NUMBER"]
            )
        else:
            raise ValueError("Unknown provider type")

        to_number = str(to_number).strip()
        if not to_number.startswith("+"):
            to_number = "+27" + to_number.lstrip("0")

        result = provider.send(to_number, message)
        return True, result
    except Exception as e:
        return False, str(e)

# ================================================================
# ---- Detect sheets and handle selection ----
# ================================================================
with st.spinner("⏳ Reading file structure..."):
    xls = pd.ExcelFile(fee_content)
    all_sheets = xls.sheet_names

today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
current_month_full = today.strftime('%B %Y').upper()
current_month_name = today.strftime('%B').upper()
current_month_short = today.strftime('%b').upper()

if today.month == 12:
    next_month_date = today.replace(year=today.year+1, month=1, day=1)
else:
    next_month_date = today.replace(month=today.month+1, day=1)
next_month_full = next_month_date.strftime('%B %Y').upper()
next_month_name = next_month_date.strftime('%B').upper()

auto_current = find_sheet([current_month_full, current_month_name, current_month_short], all_sheets)
if auto_current is None:
    auto_current = all_sheets[0]

auto_next = find_sheet([next_month_full, next_month_name], all_sheets)
if auto_next is None:
    month_abbrs = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    for sheet in all_sheets:
        if sheet != auto_current and not any(kw in sheet.upper() for kw in ['SUMMARY', 'TOTAL', 'DASHBOARD']):
            if any(abbr in sheet.upper() for abbr in month_abbrs):
                auto_next = sheet
                break

current_sheet = st.sidebar.selectbox("Current Month Sheet", all_sheets,
    index=all_sheets.index(auto_current) if auto_current in all_sheets else 0)

def get_next_month_sheet(current_sheet_name, all_sheets):
    try:
        parts = current_sheet_name.split()
        for i, part in enumerate(parts):
            if part.upper() in ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER']:
                month_str = part
                year_str = parts[i+1] if i+1 < len(parts) else None
                break
        else:
            return auto_next
        month_names = ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER']
        idx = month_names.index(month_str.upper())
        next_idx = (idx + 1) % 12
        next_month_str = month_names[next_idx]
        next_year = int(year_str) if year_str else datetime.now().year
        if next_idx == 0:
            next_year += 1
        next_month_full = f"{next_month_str} {next_year}"
        for sheet in all_sheets:
            if next_month_full in sheet.upper():
                return sheet
        return None
    except:
        return None

next_sheet_default = get_next_month_sheet(current_sheet, all_sheets) if not single_month_mode else None

if single_month_mode:
    next_sheet = None
else:
    next_sheet = st.sidebar.selectbox("Next Month Sheet", all_sheets,
        index=all_sheets.index(next_sheet_default) if next_sheet_default in all_sheets else 0, disabled=False)

if single_month_mode:
    try:
        parts = current_sheet.split()
        month_str = parts[0]
        year_str = parts[1]
        month_num = datetime.strptime(month_str, '%B').month
        year = int(year_str)
        ref_date = datetime(year, month_num, 1)
        if month_num == 12:
            next_month = datetime(year+1, 1, 1)
        else:
            next_month = datetime(year, month_num+1, 1)
        ref_date = next_month - timedelta(days=1)
    except:
        ref_date = today
else:
    ref_date = today

if date_mode == "Custom Range":
    result = process_data(fee_content, payment_content, current_sheet, next_sheet, single_month_mode, end_dt, forecast_mode, date_range)
else:
    result = process_data(fee_content, payment_content, current_sheet, next_sheet, single_month_mode, ref_date, forecast_mode)

if result is None:
    st.error("❌ No active fee-due clients found. Please check your data.")
    st.stop()

(
    ref_date_used, current_sheet_used, next_sheet_used, single_month_mode_flag,
    current_debits_c, current_debits_v, next_debits_c, next_debits_v,
    settled_today_c, settled_today_v, settled_cycle_c, settled_cycle_v,
    settled_mtd_c, settled_mtd_v, settling_c, settling_v,
    submitted_c, submitted_v, sub_col_c, sub_col_v,
    tracking_c, tracking_v, failed_cycle_c, failed_cycle_v,
    failed_mtd_c, failed_mtd_v, disputed_c, disputed_v,
    cancelled_mandate_c, cancelled_mandate_v,
    sale_not_submitted_c, sale_not_submitted_v,
    revenue_total, forecast_restructuring, forecast_legal, forecast_aftercare,
    forecast_admin_app, forecast_total, success_rate,
    combined_priority, failed_sms, tracking_sms, sale_not_submitted_sms,
    failed_clients, detail_dfs, raw, raw_stage_1_2, all_future, fee_status_df, fee_base
) = (
    result['ref_date'], result['current_sheet'], result['next_sheet'], result['single_month_mode'],
    result['current_debits_c'], result['current_debits_v'], result['next_debits_c'], result['next_debits_v'],
    result['settled_today_c'], result['settled_today_v'], result['settled_cycle_c'], result['settled_cycle_v'],
    result['settled_mtd_c'], result['settled_mtd_v'], result['settling_c'], result['settling_v'],
    result['submitted_c'], result['submitted_v'], result['sub_col_c'], result['sub_col_v'],
    result['tracking_c'], result['tracking_v'], result['failed_cycle_c'], result['failed_cycle_v'],
    result['failed_mtd_c'], result['failed_mtd_v'], result['disputed_c'], result['disputed_v'],
    result['cancelled_mandate_c'], result['cancelled_mandate_v'],
    result['sale_not_submitted_c'], result['sale_not_submitted_v'],
    result['revenue_total'], result['forecast_restructuring'], result['forecast_legal'], result['forecast_aftercare'],
    result['forecast_admin_app'], result['forecast_total'], result['success_rate'],
    result['combined_priority'], result['failed_sms'], result['tracking_sms'], result['sale_not_submitted_sms'],
    result['failed_clients'], result['detail_dfs'], result['raw'], result['raw_stage_1_2'],
    result['all_future'], result['fee_status_df'], result['fee_base']
)

# ================================================================
# ---- Dashboard output ----
# ================================================================
if date_mode == "Custom Range":
    date_label = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
else:
    date_label = ref_date_used.strftime('%d %B %Y')

st.markdown(f"""
<div class="main-header">
    <h1>Debt Review Dashboard</h1>
    <div class="greeting">Welcome! · Report date: {date_label}</div>
</div>
""", unsafe_allow_html=True)

# ---- Row 1: Main KPIs ----
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">✅ Settled {date_mode}</div>
        <div class="metric-value">R {settled_cycle_v:,.2f}</div>
        <div class="metric-delta">{settled_cycle_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    if date_mode == "Custom Range":
        label = "📅 Total Due in Period"
        value = f"R {current_debits_v:,.2f}"
        delta = f"{current_debits_c} clients"
    else:
        if not single_month_mode:
            label = "📅 Next Month Debits"
            value = f"R {next_debits_v:,.2f}"
            delta = f"{next_debits_c} clients"
        else:
            label = "📅 Next Month Debits"
            value = "N/A"
            delta = "Single month mode"
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #ff9f43;">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-delta">{delta}</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #28a745;">
        <div class="metric-label">💰 Revenue {date_mode}</div>
        <div class="metric-value">R {revenue_total:,.2f}</div>
        <div class="metric-delta">&nbsp;</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #6f42c1;">
        <div class="metric-label">🎯 Success Rate {date_mode}</div>
        <div class="metric-value">{success_rate:.1f}%</div>
        <div class="metric-delta">Settled / (Settled + Failed + Disputed)</div>
    </div>
    """, unsafe_allow_html=True)

# ---- Row 2: Additional KPIs ----
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #17a2b8;">
        <div class="metric-label">Settled Today</div>
        <div class="metric-value">R {settled_today_v:,.2f}</div>
        <div class="metric-delta">{settled_today_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #17a2b8;">
        <div class="metric-label">Settled Period Total</div>
        <div class="metric-value">R {settled_mtd_v:,.2f}</div>
        <div class="metric-delta">{settled_mtd_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #dc3545;">
        <div class="metric-label">Failed Period</div>
        <div class="metric-value">R {failed_cycle_v:,.2f}</div>
        <div class="metric-delta">{failed_cycle_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #dc3545;">
        <div class="metric-label">Failed MTD</div>
        <div class="metric-value">R {failed_mtd_v:,.2f}</div>
        <div class="metric-delta">{failed_mtd_c} clients</div>
    </div>
    """, unsafe_allow_html=True)

# ---- Row 3: In Progress ----
st.markdown("""
<div style="margin-top: 24px; margin-bottom: 16px;">
    <h3 style="font-weight: 600; color: #1e1e2d;">🔄 In Progress (Stage 1/2)</h3>
</div>
""", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #fd7e14;">
        <div class="metric-label">Settling</div>
        <div class="metric-value">R {settling_v:,.2f}</div>
        <div class="metric-delta">{settling_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #fd7e14;">
        <div class="metric-label">Submitted</div>
        <div class="metric-value">R {submitted_v:,.2f}</div>
        <div class="metric-delta">{submitted_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #fd7e14;">
        <div class="metric-label">Sub Collect</div>
        <div class="metric-value">R {sub_col_v:,.2f}</div>
        <div class="metric-delta">{sub_col_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #20c997;">
        <div class="metric-label">Intracking</div>
        <div class="metric-value">R {tracking_v:,.2f}</div>
        <div class="metric-delta">{tracking_c} clients</div>
    </div>
    """, unsafe_allow_html=True)

# ---- Row 4: Independent Statuses ----
st.markdown("""
<div style="margin-top: 24px; margin-bottom: 16px;">
    <h3 style="font-weight: 600; color: #1e1e2d;">📌 Independent Statuses (not counted as failures)</h3>
</div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #e83e8c;">
        <div class="metric-label">⚠️ Client Cancelled Mandate</div>
        <div class="metric-value">R {cancelled_mandate_v:,.2f}</div>
        <div class="metric-delta">{cancelled_mandate_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #6c757d;">
        <div class="metric-label">📭 Sale Not Submitted</div>
        <div class="metric-value">R {sale_not_submitted_v:,.2f}</div>
        <div class="metric-delta">{sale_not_submitted_c} clients</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: #dc3545;">
        <div class="metric-label">🔴 Disputed</div>
        <div class="metric-value">R {disputed_v:,.2f}</div>
        <div class="metric-delta">{disputed_c} clients</div>
    </div>
    """, unsafe_allow_html=True)

# ---- Row 5: Debits ----
st.markdown("""
<div style="margin-top: 24px; margin-bottom: 16px;">
    <h3 style="font-weight: 600; color: #1e1e2d;">📅 Upcoming Debits (Stage 1/2)</h3>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
if date_mode == "Custom Range":
    with col1:
        st.markdown(f"""
        <div class="metric-card" style="border-left-color: #4e8cff;">
            <div class="metric-label">Total Due in Period</div>
            <div class="metric-value">R {current_debits_v:,.2f}</div>
            <div class="metric-delta">{current_debits_c} clients</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card" style="border-left-color: #4e8cff;">
            <div class="metric-label">Next Month (N/A)</div>
            <div class="metric-value">N/A</div>
            <div class="metric-delta">In custom range</div>
        </div>
        """, unsafe_allow_html=True)
else:
    with col1:
        st.markdown(f"""
        <div class="metric-card" style="border-left-color: #4e8cff;">
            <div class="metric-label">{"Current Month (tomorrow → end)" if not single_month_mode else "Current Month Debits"}</div>
            <div class="metric-value">R {current_debits_v:,.2f}</div>
            <div class="metric-delta">{current_debits_c} clients</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        if not single_month_mode:
            st.markdown(f"""
            <div class="metric-card" style="border-left-color: #4e8cff;">
                <div class="metric-label">Next Month (full month)</div>
                <div class="metric-value">R {next_debits_v:,.2f}</div>
                <div class="metric-delta">{next_debits_c} clients</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="metric-card" style="border-left-color: #4e8cff;">
                <div class="metric-label">Next Month (full month)</div>
                <div class="metric-value">N/A</div>
                <div class="metric-delta">Single month mode</div>
            </div>
            """, unsafe_allow_html=True)

# ---- Charts ----
st.subheader("📊 Visual Analytics")

col1, col2 = st.columns(2)
with col1:
    with st.container():
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        st.plotly_chart(px.pie(
            names=['Restructuring', 'After-Care', 'Admin/App', 'Legal'],
            values=[forecast_restructuring, forecast_aftercare, forecast_admin_app, forecast_legal],
            title='Revenue Forecast Breakdown',
            hole=0.4
        ), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
with col2:
    with st.container():
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        settled_vs_failed = pd.DataFrame({
            'Category': ['Settled Period', 'Failed Period'],
            'Amount': [settled_cycle_v, failed_cycle_v]
        })
        st.plotly_chart(px.bar(settled_vs_failed, x='Category', y='Amount', title=f'Settled vs Failed ({date_mode})', color='Category'), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    with st.container():
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        if date_mode == "Custom Range":
            debits_df = pd.DataFrame({'Period': ['Total Due'], 'Amount': [current_debits_v]})
            st.plotly_chart(px.bar(debits_df, x='Period', y='Amount', title='Total Due in Period', color='Period'), use_container_width=True)
        else:
            if not single_month_mode:
                debits_df = pd.DataFrame({'Month': ['Current', 'Next'], 'Amount': [current_debits_v, next_debits_v]})
                st.plotly_chart(px.bar(debits_df, x='Month', y='Amount', title='Debits Comparison', color='Month'), use_container_width=True)
            else:
                debits_df = pd.DataFrame({'Month': ['Selected Month'], 'Amount': [current_debits_v]})
                st.plotly_chart(px.bar(debits_df, x='Month', y='Amount', title='Debits (Single Month)', color='Month'), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
with col2:
    with st.container():
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        if not combined_priority.empty and 'Priority Level' in combined_priority.columns:
            priority_counts = combined_priority['Priority Level'].value_counts().reset_index()
            priority_counts.columns = ['Priority', 'Count']
            st.plotly_chart(px.bar(priority_counts, x='Priority', y='Count', title='Priority Queue Distribution', color='Priority'), use_container_width=True)
        else:
            st.info("No priority data available.")
        st.markdown('</div>', unsafe_allow_html=True)

# ---- Historical Trends ----
history_file = "history/metrics_history.csv"
os.makedirs(os.path.dirname(history_file), exist_ok=True)

if single_month_mode:
    month_name = current_sheet_used
else:
    month_name = ref_date_used.strftime('%B %Y')

new_row = {
    'report_date': ref_date_used.strftime('%Y-%m-%d'),
    'month': month_name,
    'settled_mtd_v': settled_mtd_v,
    'failed_mtd_v': failed_mtd_v,
    'success_rate': success_rate,
    'revenue_total': revenue_total,
    'current_debits_v': current_debits_v,
    'next_debits_v': next_debits_v,
    'settled_today_c': settled_today_c,
    'tracking_c': tracking_c,
    'failed_cycle_c': failed_cycle_c,
}

try:
    if os.path.exists(history_file):
        history_df = pd.read_csv(history_file)
        if 'month' in history_df.columns and month_name not in history_df['month'].values:
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            idx = history_df[history_df['month'] == month_name].index
            if len(idx) > 0:
                history_df.loc[idx[0]] = new_row
            else:
                history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)
    else:
        history_df = pd.DataFrame([new_row])
    history_df.to_csv(history_file, index=False)
except:
    pass

if os.path.exists(history_file):
    try:
        history_df = pd.read_csv(history_file)
        if len(history_df) > 1:
            history_df['report_date'] = pd.to_datetime(history_df['report_date'])
            history_df = history_df.sort_values('report_date')

            st.markdown("""
            <div style="margin-top: 24px; margin-bottom: 16px;">
                <h3 style="font-weight: 600; color: #1e1e2d;">📈 Historical Trends</h3>
            </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                with st.container():
                    st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                    fig_trend = px.line(history_df, x='report_date', y=['settled_mtd_v', 'failed_mtd_v'],
                                        title='Monthly Settled vs Failed Amount (R)',
                                        labels={'value': 'Amount (R)', 'variable': 'Category'})
                    st.plotly_chart(fig_trend, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            with col2:
                with st.container():
                    st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                    fig_sr = px.line(history_df, x='report_date', y='success_rate',
                                     title='Success Rate (%) Over Time')
                    st.plotly_chart(fig_sr, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            fig_rd = px.line(history_df, x='report_date', y=['revenue_total', 'current_debits_v', 'next_debits_v'],
                             title='Revenue, Current & Next Month Debits',
                             labels={'value': 'Amount (R)', 'variable': 'Category'})
            st.plotly_chart(fig_rd, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("📊 Collecting data for historical trends. Come back after more months of data.")
    except:
        pass

# ================================================================
# 📱 SMS SENDING SECTION
# ================================================================
st.markdown("""
<div style="margin-top: 24px; margin-bottom: 16px;">
    <h3 style="font-weight: 600; color: #1e1e2d;">📱 Send SMS Messages</h3>
</div>
""", unsafe_allow_html=True)

def send_bulk_sms(selected_df, message, list_name):
    if selected_df.empty:
        st.warning("No clients selected.")
        return
    if not st.button(f"📱 Confirm Send {len(selected_df)} SMS to {list_name}"):
        return
    progress = st.progress(0)
    success_count = 0
    failed_list = []
    for i, (idx, row) in enumerate(selected_df.iterrows()):
        cell = row.get("Cell") or row.get("cell")
        if pd.isna(cell) or not str(cell).strip():
            failed_list.append(f"Row {i+1}: No phone number")
            continue
        phone = str(cell).strip()
        if not phone.startswith("+"):
            phone = "+27" + phone.lstrip("0")
        name = row.get("Name") or row.get("client_name") or "Client"
        personalised_msg = message.replace("{name}", name)
        success, result = send_sms(phone, personalised_msg)
        if success:
            success_count += 1
        else:
            failed_list.append(f"{name} ({phone}): {result}")
        progress.progress((i + 1) / len(selected_df))
    if success_count == len(selected_df):
        st.success(f"✅ All {success_count} SMS messages sent successfully to {list_name}.")
    else:
        st.warning(f"⚠️ Sent {success_count} out of {len(selected_df)}. Failed: {', '.join(failed_list)}")

# ---- Failed Clients SMS ----
st.subheader("📋 Failed Clients (SMS)")
st.caption("Includes all Failed, Disputed, and Client Cancelled Mandate clients from the Payment Status Report.")
if not failed_sms.empty:
    select_all_failed = st.checkbox("Select all Failed clients", key="select_all_failed")
    display_failed = failed_sms.copy()
    display_failed["Send"] = select_all_failed
    edited_failed = st.data_editor(
        display_failed,
        column_config={"Send": st.column_config.CheckboxColumn("Send", default=select_all_failed)},
        disabled=["ID NUMBER", "Name", "Cell", "Stage", "Amount", "Status"],
        hide_index=True,
        key="failed_editor"
    )
    failed_message = st.text_area(
        "Message for Failed Clients",
        value="Dear {name},\nURGENT: Your debit order has failed. Please make payment immediately to avoid arrears and possible termination of your debt review agreements. For assistance, contact us at: info@nationaldebt.org.za / 0873541057 / WhatsApp: https://wa.me/27873541057",
        key="failed_msg"
    )
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("📱 Send SMS to Selected Failed Clients", key="send_failed"):
            selected = edited_failed[edited_failed["Send"] == True]
            send_bulk_sms(selected, failed_message, "Failed Clients")
else:
    st.info("No failed clients in the current period.")

# ---- Intracking Clients SMS ----
st.subheader("📋 Intracking Clients (SMS)")
if not tracking_sms.empty:
    select_all_tracking = st.checkbox("Select all Intracking clients", key="select_all_tracking")
    display_tracking = tracking_sms.copy()
    display_tracking["Send"] = select_all_tracking
    edited_tracking = st.data_editor(
        display_tracking,
        column_config={"Send": st.column_config.CheckboxColumn("Send", default=select_all_tracking)},
        disabled=["ID NUMBER", "Name", "Cell", "Stage", "Amount", "Status"],
        hide_index=True,
        key="tracking_editor"
    )
    tracking_message = st.text_area(
        "Message for Intracking Clients",
        value="NATIONAL DEBT INTERVENTION: Dear {name}, we have not yet received your monthly instalment, please ensure you have enough funds available in your bank account for the debit to go off successfully. 0873541057 / info@nationaldebt.org.za/ WhatsApp https://wa.me/27873541057",
        key="tracking_msg"
    )
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("📱 Send SMS to Selected Intracking Clients", key="send_tracking"):
            selected = edited_tracking[edited_tracking["Send"] == True]
            send_bulk_sms(selected, tracking_message, "Intracking Clients")
else:
    st.info("No intracking clients.")

# ================================================================
# 📭 SALE NOT SUBMITTED LIST
# ================================================================
st.markdown("""
<div style="margin-top: 32px; margin-bottom: 16px;">
    <h3 style="font-weight: 600; color: #1e1e2d;">📭 Sale Not Submitted — Send to Sales Department</h3>
    <p style="color: #6c757d; font-size: 14px;">Source: Fee Audit. No SMS is sent to these clients.</p>
</div>
""", unsafe_allow_html=True)

if not sale_not_submitted_sms.empty:
    st.dataframe(sale_not_submitted_sms, width='stretch')
    csv_sns = sale_not_submitted_sms.to_csv(index=False).encode('utf-8')
    st.download_button(
        "📥 Download Sale Not Submitted CSV",
        data=csv_sns,
        file_name="sale_not_submitted.csv",
        mime="text/csv"
    )
else:
    st.info("No clients with 'Sale Not Submitted' status in the Fee Audit for the current period.")

# ---- CSV downloads ----
st.markdown("---")
st.subheader("📥 Export SMS Lists (CSV)")
col1, col2 = st.columns(2)
with col1:
    if not failed_sms.empty:
        csv_failed = failed_sms.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Failed SMS CSV", data=csv_failed, file_name="failed_sms.csv", mime="text/csv")
    else:
        st.info("No failed clients to export.")
with col2:
    if not tracking_sms.empty:
        csv_tracking = tracking_sms.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Intracking SMS CSV", data=csv_tracking, file_name="intracking_sms.csv", mime="text/csv")
    else:
        st.info("No intracking clients to export.")

# ---- Priority Queue ----
st.subheader("🔴 Priority Queue")
if not combined_priority.empty:
    def color_priority(val):
        if val == 'High':
            return 'background-color: #FF0000; color: white; font-weight: 600;'
        elif val == 'Medium':
            return 'background-color: #FFA500; color: black; font-weight: 600;'
        else:
            return 'background-color: #FFFF00; color: black; font-weight: 600;'
    styled_priority = combined_priority.style.map(color_priority, subset=['Priority Level'])
    st.dataframe(styled_priority, width='stretch')
else:
    st.info("No clients in the priority queue.")

# ---- Data Preview ----
with st.expander("🔍 Data Preview (Debugging)"):
    st.subheader("Summary")
    st.write(f"**Total rows after merge:** {len(raw)}")
    st.write(f"**Rows in stage 1/2:** {len(raw_stage_1_2)}")
    st.write(f"**Current sheet:** `{current_sheet_used}`")
    st.write(f"**Next sheet:** `{next_sheet_used if next_sheet_used else 'None'}`")
    st.write(f"**Unique clients (all):** {raw['id_number'].nunique()}")
    st.write(f"**Unique clients (stage 1/2):** {raw_stage_1_2['id_number'].nunique() if not raw_stage_1_2.empty else 0}")

    if not forecast_mode and 'pmt_debug' in result and result['pmt_debug']:
        pmt_debug = result['pmt_debug']
        st.subheader("📄 Payment Status Report Diagnostics")
        st.write("**Detected columns:**", pmt_debug['columns_detected'])
        st.write("**Unique status values found:**", pmt_debug['unique_statuses'])
        st.write("**First 5 rows of raw Payment Report:**")
        st.dataframe(pd.DataFrame(pmt_debug['sample_rows']), width='stretch')
        st.write("**First 5 rows of cleaned Payment Report (after renaming):**")
        if pmt_debug['pmt_sms_sample']:
            st.dataframe(pd.DataFrame(pmt_debug['pmt_sms_sample']), width='stretch')
        else:
            st.warning("Cleaned Payment Report is empty – check column detection.")
        st.write(f"**Rows matching 'Failed/Disputed/Cancelled Mandate' keywords (ALL):** {pmt_debug['failed_count']}")
        st.write(f"**Rows matching 'Tracking/Intracking' keywords:** {pmt_debug['tracking_count']}")
        st.write(f"**Rows matching 'Disputed' only:** {pmt_debug['disputed_count']}")
        st.write(f"**Rows matching 'Client Cancelled Mandate' only:** {pmt_debug['cancelled_mandate_count']}")
        st.write(f"**Rows matching 'Sale Not Submitted' only:** {pmt_debug['sale_not_submitted_count']}")

    st.subheader("Sample of Raw Data")
    st.dataframe(raw.head(10), width='stretch')
    st.subheader("Future Debits")
    st.dataframe(all_future.head(10), width='stretch')
    st.subheader("Status Counts (Stage 1/2)")
    if not raw_stage_1_2.empty:
        status_counts = raw_stage_1_2['status'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        st.dataframe(status_counts, width='stretch')

# ---- Download full Excel report ----
st.subheader("📥 Download Full Excel Report")

def generate_excel():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        dashboard_data = {
            'Metric': ['Settled Period (Stage 1/2)', 'Settled Today', 'Settled Period Total',
                       'Settling (Stage 1/2)', 'Submitted (Stage 1/2)', 'Sub Collect (Stage 1/2)', 'Intracking (Stage 1/2)',
                       'Curr Month Debits (Stage 1/2)', 'Next Month Debits (Stage 1/2)',
                       'Failed Period (Stage 1/2)', 'Failed MTD (Stage 1/2)',
                       'Disputed (Stage 1/2)', 'Client Cancelled Mandate (Stage 1/2)', 'Sale Not Submitted (Stage 1/2)',
                       'Revenue Total (Stage 1/2, Period)',
                       'Success Rate (Period, by value, Disputed = Failure)',
                       'Single Month Mode'],
            'Value': [f"{settled_cycle_c} | R{settled_cycle_v:,.2f}",
                      f"{settled_today_c} | R{settled_today_v:,.2f}",
                      f"{settled_mtd_c} | R{settled_mtd_v:,.2f}",
                      f"{settling_c} | R{settling_v:,.2f}",
                      f"{submitted_c} | R{submitted_v:,.2f}",
                      f"{sub_col_c} | R{sub_col_v:,.2f}",
                      f"{tracking_c} | R{tracking_v:,.2f}",
                      f"{current_debits_c} | R{current_debits_v:,.2f}",
                      f"{next_debits_c} | R{next_debits_v:,.2f}" if not single_month_mode else "N/A",
                      f"{failed_cycle_c} | R{failed_cycle_v:,.2f}",
                      f"{failed_mtd_c} | R{failed_mtd_v:,.2f}",
                      f"{disputed_c} | R{disputed_v:,.2f}",
                      f"{cancelled_mandate_c} | R{cancelled_mandate_v:,.2f}",
                      f"{sale_not_submitted_c} | R{sale_not_submitted_v:,.2f}",
                      f"R{revenue_total:,.2f}",
                      f"{success_rate:.1f}%",
                      "Yes" if single_month_mode else "No"]
        }
        pd.DataFrame(dashboard_data).to_excel(writer, sheet_name='Dashboard', index=False)

        combined_priority.to_excel(writer, sheet_name='Priority Queue', index=False, header=False)
        workbook = writer.book
        worksheet_pq = writer.sheets['Priority Queue']
        worksheet_pq.set_column('A:A', None, workbook.add_format({'num_format': '@'}))

        format_high = workbook.add_format({'bg_color': '#FF0000', 'font_color': '#FFFFFF', 'bold': True})
        format_medium = workbook.add_format({'bg_color': '#FFA500', 'font_color': '#000000'})
        format_low = workbook.add_format({'bg_color': '#FFFF00', 'font_color': '#000000'})
        last_row_pq = len(combined_priority) + 1
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {'type': 'formula', 'criteria': f'=$I1="High"', 'format': format_high})
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {'type': 'formula', 'criteria': f'=$I1="Medium"', 'format': format_medium})
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {'type': 'formula', 'criteria': f'=$I1="Low"', 'format': format_low})

        failed_clients.to_excel(writer, sheet_name='Failed Clients', index=False)
        writer.sheets['Failed Clients'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))

        failed_sms.to_excel(writer, sheet_name='Failed Clients (SMS)', index=False)
        writer.sheets['Failed Clients (SMS)'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))
        tracking_sms.to_excel(writer, sheet_name='Intracking Clients (SMS)', index=False)
        writer.sheets['Intracking Clients (SMS)'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))
        sale_not_submitted_sms.to_excel(writer, sheet_name='Sale Not Submitted', index=False)
        writer.sheets['Sale Not Submitted'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))

        for sheet_name, df in detail_dfs.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                writer.sheets[sheet_name].set_column('A:A', None, workbook.add_format({'num_format': '@'}))

    output.seek(0)
    return output

excel_data = generate_excel()
st.download_button(
    label="📥 Download Full Excel Report",
    data=excel_data,
    file_name=f"Debt_Review_Dashboard_{ref_date_used.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.caption(f"Report generated based on reference date: {date_label}")