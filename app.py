# ================================================================
# 📊 DEBT REVIEW DASHBOARD — FINAL (ROBUST COLUMN HANDLING)
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

# --- Page config ---
st.set_page_config(page_title="Debt Review Dashboard", layout="wide")
st.title("📊 Debt Review Operations Dashboard")

# ================================================================
# 1. DOWNLOAD FILES FROM GOOGLE DRIVE
# ================================================================

def download_file_from_drive(service, file_id):
    """Download a file from Google Drive and return it as a BytesIO object."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# ---- Google Drive authentication ----
try:
    # Build credentials dict from individual secrets
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

    # Get file IDs
    fee_file_id = st.secrets["FEE_FILE_ID"]
    payment_file_id = st.secrets["PAYMENT_FILE_ID"]

    # Download files (returns BytesIO objects)
    fee_content = download_file_from_drive(service, fee_file_id)
    payment_content = download_file_from_drive(service, payment_file_id)

    st.sidebar.success("✅ Connected to Google Drive")

except Exception as e:
    st.sidebar.error(f"❌ Error connecting to Google Drive: {e}")
    st.stop()

# ---- Helper functions ----
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
        col_lower = str(col).lower()
        if 'note' in col_lower or 'feedback' in col_lower or 'status' in col_lower:
            status_col = col
            break
    if status_col is None:
        status_col = df.columns[-1]

    id_col = None
    for col in df.columns:
        if col.strip().upper() == 'ID NUMBER':
            id_col = col
            break
    if id_col is None:
        for col in df.columns:
            if col.strip().upper() == 'APPLICANT NUMBER':
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
        if 'INSTALMENT AMOUNT' in col:
            amount_col = col
            break
    if amount_col is None:
        amount_col = df.columns[-2]

    stage_col = None
    for col in df.columns:
        if 'INSTALLMENT NO' in col or 'INSTALLMENT' in col:
            stage_col = col
            break
    if stage_col is None:
        stage_col = df.columns[3]

    date_col = None
    for col in df.columns:
        if 'COLLECTION DATE' in col or 'DATE' in col:
            date_col = col
            break

    name_col = None
    cell_col = None
    for col in df.columns:
        if 'APPLICANT NAME' in col or 'NAME' in col:
            name_col = col
        if 'CELL' in col or 'MOBILE' in col or 'PHONE' in col:
            cell_col = col

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
    
    df_future['id_number'] = df_future[id_col].astype(str).str.strip()
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

# ---- Core processing function (cached) ----
@st.cache_data
def process_data(fee_content, payment_content, current_sheet, next_sheet, single_month_mode=False, ref_date=None):
    if ref_date is None:
        ref_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today = ref_date

    # fee_content and payment_content are already BytesIO – use them directly
    fee_df_current = pd.read_excel(fee_content, sheet_name=current_sheet)
    
    fee_df_next = None
    if not single_month_mode and next_sheet is not None:
        fee_df_next = pd.read_excel(fee_content, sheet_name=next_sheet)
    
    future_current = extract_future_debits(fee_df_current, current_sheet, filter_future=True)
    future_next = extract_future_debits(fee_df_next, next_sheet, filter_future=False) if fee_df_next is not None else pd.DataFrame()
    
    all_future = pd.concat([future_current, future_next], ignore_index=True)

    if all_future.empty:
        current_debits_c = 0
        current_debits_v = 0
        next_debits_c = 0
        next_debits_v = 0
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
    fee_base.rename(columns={
        id_col: 'id_number',
        stage_col: 'payment_stage',
        amount_col: 'amount',
        status_col: 'status'
    }, inplace=True)
    if date_col is not None:
        fee_base.rename(columns={date_col: 'collection_date'}, inplace=True)
    if name_col is not None:
        fee_base.rename(columns={name_col: 'client_name'}, inplace=True)
    if cell_col is not None:
        fee_base.rename(columns={cell_col: 'cell'}, inplace=True)
    
    fee_base['payment_stage'] = pd.to_numeric(fee_base['payment_stage'], errors='coerce')
    if 'collection_date' in fee_base.columns:
        fee_base['collection_date'] = pd.to_datetime(fee_base['collection_date'], errors='coerce')
    fee_base['id_number'] = fee_base['id_number'].astype(str).str.strip()
    fee_base['status'] = fee_base['status'].astype(str).str.strip()
    fee_base = fee_base.dropna(subset=['id_number', 'payment_stage'])
    
    try:
        df_pmt = pd.read_excel(payment_content, sheet_name='Details', header=3)
    except:
        try:
            df_pmt = pd.read_excel(payment_content, header=3)
        except:
            df_pmt = pd.read_excel(payment_content)
    
    raw = df_pmt.copy()
    
    payment_id_col = None
    for col in raw.columns:
        if col.strip().upper() == 'ID NUMBER':
            payment_id_col = col
            break
    if payment_id_col is None:
        for col in raw.columns:
            if col.strip().upper() == 'APPLICANT NUMBER':
                payment_id_col = col
                break
    if payment_id_col is None:
        for col in raw.columns:
            if any(kw in str(col).lower() for kw in ['id', 'applicant', 'number']):
                payment_id_col = col
                break
    if payment_id_col is None:
        payment_id_col = raw.columns[0]
    raw.rename(columns={payment_id_col: 'id_number'}, inplace=True)
    
    col_map = {
        'APPLICANT NAME': 'client_name_pmt',
        'CELL': 'cell_pmt',
        'INSTALLMENT NO': 'payment_stage_pmt',
        'TOTAL INSTALMENTS LOADED': 'total_instalments',
        'INSTALMENT AMOUNT': 'amount_pmt',
        'COLLECTION STATUS': 'status_pmt',
        'COLLECTION DATE': 'collection_date_pmt',
        'SETTLEMENT DATE': 'settlement_date_pmt',
        'DISPUTE DATE': 'dispute_date_pmt',
        'Tracking Days Used': 'tracking_days',
        'Cancelled Date': 'cancelled_date_pmt',
        'Mandate Consumer Bank': 'bank'
    }
    for old, new in col_map.items():
        if old in raw.columns:
            raw.rename(columns={old: new}, inplace=True)
    
    raw['id_number'] = raw['id_number'].astype(str).str.strip()
    raw['payment_stage_pmt'] = pd.to_numeric(raw['payment_stage_pmt'], errors='coerce')
    
    pmt_cols = ['id_number', 'payment_stage_pmt', 'collection_date_pmt', 'settlement_date_pmt',
                'dispute_date_pmt', 'cell_pmt', 'client_name_pmt', 'amount_pmt', 'status_pmt',
                'total_instalments', 'tracking_days', 'cancelled_date_pmt', 'bank']
    pmt_cols_existing = [c for c in pmt_cols if c in raw.columns]
    pmt_data = raw[pmt_cols_existing].copy()
    pmt_data = pmt_data.drop_duplicates(subset=['id_number', 'payment_stage_pmt'], keep='first')
    pmt_data.rename(columns={
        'payment_stage_pmt': 'payment_stage',
        'collection_date_pmt': 'collection_date_pmt',
        'settlement_date_pmt': 'settlement_date_pmt',
        'dispute_date_pmt': 'dispute_date_pmt',
        'cell_pmt': 'cell_pmt',
        'client_name_pmt': 'client_name_pmt',
        'amount_pmt': 'amount_pmt',
        'status_pmt': 'status_pmt',
        'cancelled_date_pmt': 'cancelled_date_pmt'
    }, inplace=True)
    
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
    
    if 'settlement_date_pmt' in merged.columns:
        merged['settlement_date'] = merged['settlement_date_pmt']
    else:
        merged['settlement_date'] = pd.NaT
    if 'dispute_date_pmt' in merged.columns:
        merged['dispute_date'] = merged['dispute_date_pmt']
    else:
        merged['dispute_date'] = pd.NaT
    if 'cancelled_date_pmt' in merged.columns:
        merged['cancelled_date'] = merged['cancelled_date_pmt']
    else:
        merged['cancelled_date'] = pd.NaT
    
    drop_cols = ['client_name_pmt', 'cell_pmt', 'amount_pmt', 'status_pmt', 
                 'collection_date_pmt', 'settlement_date_pmt', 'dispute_date_pmt',
                 'cancelled_date_pmt']
    merged.drop(columns=[c for c in drop_cols if c in merged.columns], inplace=True, errors='ignore')
    
    cancelled_keywords = ['cancelled', 'Cancelled', 'CANCELLED', 
                          'RMS - Cancelled', 'RMS - Cancelled - Inactive']
    cancelled_mask = merged['status'].astype(str).str.contains('|'.join(cancelled_keywords), na=False)
    merged = merged[~cancelled_mask].copy()
    
    if merged.empty:
        return None
    
    raw = merged
    
    raw['payment_stage'] = pd.to_numeric(raw['payment_stage'], errors='coerce')
    raw['amount'] = pd.to_numeric(raw['amount'], errors='coerce')
    for col in ['collection_date', 'settlement_date', 'dispute_date', 'cancelled_date']:
        if col in raw.columns:
            raw[col] = pd.to_datetime(raw[col], errors='coerce')
    raw['due_date'] = raw['collection_date']
    raw['effective_settlement_date'] = raw['settlement_date'].fillna(raw['collection_date'])
    
    raw = raw[raw['collection_date'] <= today]
    raw = raw[raw['effective_settlement_date'] <= today]
    raw = raw[raw['due_date'] <= today]
    
    raw_stage_1_2 = raw[raw['payment_stage'].isin([1, 2])].copy()
    
    settled_all = raw[raw['status'].str.upper() == 'SETTLED'].copy()
    settled_all = settled_all.sort_values(['id_number', 'effective_settlement_date'])
    settled_all['settlement_rank'] = settled_all.groupby('id_number').cumcount() + 1
    
    raw = raw.merge(settled_all[['id_number', 'effective_settlement_date', 'amount', 'status', 'settlement_rank']],
                    on=['id_number', 'effective_settlement_date', 'amount', 'status'],
                    how='left')
    raw_stage_1_2 = raw_stage_1_2.merge(settled_all[['id_number', 'effective_settlement_date', 'amount', 'status', 'settlement_rank']],
                                        on=['id_number', 'effective_settlement_date', 'amount', 'status'],
                                        how='left')
    
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
    
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    first_of_month = today.replace(day=1)
    
    def get_settled_df(df, start_date=None, end_date=None):
        temp = df[df['status'].str.upper() == 'SETTLED']
        if start_date and end_date:
            temp = temp[temp['effective_settlement_date'] >= start_date]
            temp = temp[temp['effective_settlement_date'] <= end_date]
        return temp
    
    settled_today_df = get_settled_df(raw_stage_1_2, today, today)
    settled_cycle_df = get_settled_df(raw_stage_1_2, last_friday, today)
    settled_mtd_df = get_settled_df(raw_stage_1_2, first_of_month, today)
    
    settled_today_c, settled_today_v = len(settled_today_df), settled_today_df['amount'].sum()
    settled_cycle_c, settled_cycle_v = len(settled_cycle_df), settled_cycle_df['amount'].sum()
    settled_mtd_c, settled_mtd_v = len(settled_mtd_df), settled_mtd_df['amount'].sum()
    
    def get_unique_stage_clients(df, status_filter=None, date_col=None, start_date=None, end_date=None):
        temp = df.copy()
        if status_filter:
            temp = temp[temp['status'].str.upper() == status_filter.upper()]
        if date_col and start_date and end_date:
            temp = temp[temp[date_col] >= start_date]
            temp = temp[temp[date_col] <= end_date]
        if not temp.empty:
            grouped = temp.groupby('id_number').agg({
                'client_name': 'first',
                'cell': 'first',
                'payment_stage': 'first',
                'amount': 'sum',
                'status': 'first',
                'collection_date': 'max'
            }).reset_index()
            return grouped
        else:
            return pd.DataFrame()
    
    settling_df = get_unique_stage_clients(raw_stage_1_2, 'Settling')
    submitted_df = get_unique_stage_clients(raw_stage_1_2, 'Submitted')
    sub_col_df = get_unique_stage_clients(raw_stage_1_2, 'Submitting Collection')
    
    tracking_temp = raw_stage_1_2[raw_stage_1_2['status'].str.upper().isin(['TRACKING', 'INTRACKING'])]
    if not tracking_temp.empty:
        tracking_df = tracking_temp.groupby('id_number').agg({
            'client_name': 'first',
            'cell': 'first',
            'payment_stage': 'first',
            'amount': 'sum',
            'status': 'first',
            'collection_date': 'max'
        }).reset_index()
    else:
        tracking_df = pd.DataFrame()
    
    settling_c, settling_v = len(settling_df), settling_df['amount'].sum() if not settling_df.empty else 0
    submitted_c, submitted_v = len(submitted_df), submitted_df['amount'].sum() if not submitted_df.empty else 0
    sub_col_c, sub_col_v = len(sub_col_df), sub_col_df['amount'].sum() if not sub_col_df.empty else 0
    tracking_c, tracking_v = len(tracking_df), tracking_df['amount'].sum() if not tracking_df.empty else 0
    
    def get_failed_df(df, start_date=None, end_date=None):
        temp = df[df['status'].str.upper() == 'FAILED']
        if start_date and end_date:
            temp = temp[temp['collection_date'] >= start_date]
            temp = temp[temp['collection_date'] <= end_date]
        return temp
    
    failed_cycle_df = get_failed_df(raw_stage_1_2, last_friday, today)
    failed_mtd_df = get_failed_df(raw_stage_1_2, first_of_month, today)
    failed_cycle_c, failed_cycle_v = len(failed_cycle_df), failed_cycle_df['amount'].sum()
    failed_mtd_c, failed_mtd_v = len(failed_mtd_df), failed_mtd_df['amount'].sum()
    
    disputed_df = get_unique_stage_clients(raw_stage_1_2, 'Disputed')
    disputed_c, disputed_v = len(disputed_df), disputed_df['amount'].sum() if not disputed_df.empty else 0
    
    current_month_settled = raw_stage_1_2[
        (raw_stage_1_2['status'].str.upper() == 'SETTLED') &
        (raw_stage_1_2['effective_settlement_date'] >= first_of_month) &
        (raw_stage_1_2['effective_settlement_date'] <= today)
    ]
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

    if (settled_mtd_v + failed_mtd_v) > 0:
        success_rate = (settled_mtd_v / (settled_mtd_v + failed_mtd_v)) * 100
    else:
        success_rate = 0
    
    # ---- Priority Queue (ROBUST version) ----
    def get_latest_record(group):
        return group.sort_values('collection_date').iloc[-1]
    
    priority_df = raw[(raw['status'].str.upper().isin(['FAILED', 'TRACKING', 'INTRACKING'])) | 
                      ((raw['payment_stage'].isin([1,2,3])) & 
                       (raw['status'].str.upper().isin(['FAILED', 'TRACKING', 'INTRACKING', 'LATE'])))]
    if not priority_df.empty:
        # Ensure required columns exist
        for col in ['cell', 'client_name', 'id_number']:
            if col not in priority_df.columns:
                priority_df[col] = ''
        # Fill NaNs for numeric columns
        priority_df['amount'] = priority_df['amount'].fillna(0)
        priority_df['payment_stage'] = priority_df['payment_stage'].fillna(0)
        # Ensure due_date exists
        if 'due_date' not in priority_df.columns:
            priority_df['due_date'] = pd.NaT
        
        priority_df = priority_df.sort_values('collection_date').groupby('id_number').apply(get_latest_record).reset_index(drop=True)
        
        def get_weight(stage):
            if stage in [1, 2]: return 100
            if stage == 3: return 90
            if stage in [4,5,6]: return 60
            if stage >= 7: return 30
            return 50
        
        priority_df['stage_weight'] = priority_df['payment_stage'].apply(get_weight)
        # Calculate days overdue safely
        if 'due_date' in priority_df.columns:
            priority_df['days_overdue'] = (today - priority_df['due_date']).dt.days.fillna(0)
        else:
            priority_df['days_overdue'] = 0
        priority_df['priority_score'] = priority_df['stage_weight'] + priority_df['days_overdue'] * 2
        priority_df['Priority Level'] = priority_df['priority_score'].apply(lambda x: 'High' if x >= 150 else ('Medium' if x >= 100 else 'Low'))
        
        # Define columns to keep
        cols = ['id_number', 'client_name', 'cell', 'payment_stage', 'days_overdue', 
                'amount', 'status', 'priority_score', 'Priority Level']
        # Ensure all columns exist
        for col in cols:
            if col not in priority_df.columns:
                priority_df[col] = ''  # or 0 for numeric
        
        failed_priority = priority_df[priority_df['status'].str.upper() == 'FAILED'].copy()
        tracking_priority = priority_df[priority_df['status'].str.upper().isin(['TRACKING', 'INTRACKING'])].copy()
        
        # Sort
        failed_priority = failed_priority.sort_values('priority_score', ascending=False)
        tracking_priority = tracking_priority.sort_values('priority_score', ascending=False)
        
        # Rename columns for display
        if not failed_priority.empty:
            failed_priority = failed_priority[cols]
            failed_priority.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 
                                       'Amount', 'Status', 'Score', 'Priority Level']
        else:
            failed_priority = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 
                                                    'Amount', 'Status', 'Score', 'Priority Level'])
        
        if not tracking_priority.empty:
            tracking_priority = tracking_priority[cols]
            tracking_priority.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 
                                         'Amount', 'Status', 'Score', 'Priority Level']
        else:
            tracking_priority = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 
                                                      'Amount', 'Status', 'Score', 'Priority Level'])
        
        # Create combined with headers
        separator = pd.DataFrame([[''] * len(failed_priority.columns)], columns=failed_priority.columns)
        header_failed = pd.DataFrame([['=== FAILED PAYMENTS ==='] + [''] * (len(failed_priority.columns)-1)], 
                                      columns=failed_priority.columns)
        header_tracking = pd.DataFrame([['=== TRACKING / INTRACKING CLIENTS ==='] + [''] * (len(failed_priority.columns)-1)], 
                                        columns=failed_priority.columns)
        
        combined_priority = pd.concat([
            header_failed,
            failed_priority,
            separator,
            header_tracking,
            tracking_priority
        ], ignore_index=True)
    else:
        # No priority clients at all
        cols = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Days Overdue', 'Amount', 'Status', 'Score', 'Priority Level']
        combined_priority = pd.DataFrame(columns=cols)
    
    # ---- SMS lists (ROBUST) ----
    def ensure_columns(df, required_cols):
        """Ensure required columns exist in DataFrame, create empty if missing."""
        for col in required_cols:
            if col not in df.columns:
                df[col] = ''
        return df
    
    # Failed SMS
    failed_sms = raw[raw['status'].str.upper() == 'FAILED'].copy()
    if not failed_sms.empty:
        ensure_columns(failed_sms, ['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status'])
        failed_sms = failed_sms[['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status']]
        failed_sms.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status']
    else:
        failed_sms = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])
    
    # Tracking SMS
    tracking_sms = raw[raw['status'].str.upper().isin(['TRACKING', 'INTRACKING'])].copy()
    if not tracking_sms.empty:
        ensure_columns(tracking_sms, ['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status'])
        tracking_sms = tracking_sms[['id_number', 'client_name', 'cell', 'payment_stage', 'amount', 'status']]
        tracking_sms.columns = ['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status']
    else:
        tracking_sms = pd.DataFrame(columns=['ID NUMBER', 'Name', 'Cell', 'Stage', 'Amount', 'Status'])
    
    # Legacy failed clients (stage 1/2) - ROBUST
    def get_latest_record_for_sheet(df):
        if df.empty:
            return df
        # Ensure id_number exists
        if 'id_number' not in df.columns:
            # try to find an id column
            id_candidates = [col for col in df.columns if 'id' in col.lower() or 'number' in col.lower()]
            if id_candidates:
                df['id_number'] = df[id_candidates[0]]
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
    
    # ---- Detail sheets ----
    def prep_detail_df(df, date_col_name, status_col='status'):
        if df.empty:
            return pd.DataFrame()
        df_out = df.copy()
        if date_col_name not in df_out.columns:
            return pd.DataFrame()
        df_out['date_col'] = df_out[date_col_name]
        # Ensure required columns
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
        detail_dfs['Settled Fri-Today'] = prep_detail_df(settled_cycle_df, 'effective_settlement_date')
    if not settled_mtd_df.empty:
        detail_dfs['Settled 1st-Today'] = prep_detail_df(settled_mtd_df, 'effective_settlement_date')
    if not settling_df.empty:
        detail_dfs['Settling'] = prep_detail_df(settling_df, 'collection_date')
    if not submitted_df.empty:
        detail_dfs['Submitted'] = prep_detail_df(submitted_df, 'collection_date')
    if not sub_col_df.empty:
        detail_dfs['Sub Collect'] = prep_detail_df(sub_col_df, 'collection_date')
    if not tracking_df.empty:
        detail_dfs['Intracking'] = prep_detail_df(tracking_df, 'collection_date')
    if not failed_cycle_df.empty:
        detail_dfs['Failed Fri-Today'] = prep_detail_df(failed_cycle_df, 'collection_date')
    if not failed_mtd_df.empty:
        detail_dfs['Failed 1st-Today'] = prep_detail_df(failed_mtd_df, 'collection_date')
    if not disputed_df.empty:
        detail_dfs['Disputed'] = prep_detail_df(disputed_df, 'collection_date')
    
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
        'revenue_total': revenue_total,
        'forecast_restructuring': forecast_restructuring,
        'forecast_legal': forecast_legal,
        'forecast_aftercare': forecast_aftercare,
        'forecast_admin_app': forecast_admin_app,
        'forecast_total': forecast_total,
        'success_rate': success_rate,
        'combined_priority': combined_priority,
        'failed_sms': failed_sms,
        'tracking_sms': tracking_sms,
        'failed_clients': failed_clients,
        'detail_dfs': detail_dfs,
        'raw': raw,
        'raw_stage_1_2': raw_stage_1_2,
        'all_future': all_future,
        'fee_status_df': fee_status_df,
        'fee_base': fee_base
    }

# ---- Detect sheets and handle selection ----
with st.spinner("⏳ Reading file structure..."):
    # fee_content is already a BytesIO – use it directly
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
    month_abbrs = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']
    for sheet in all_sheets:
        if sheet != auto_current and not any(kw in sheet.upper() for kw in ['SUMMARY','TOTAL','DASHBOARD']):
            if any(abbr in sheet.upper() for abbr in month_abbrs):
                auto_next = sheet
                break

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Month Selection")

single_month_mode = st.sidebar.checkbox("📌 Single Month Mode", value=False)

current_sheet = st.sidebar.selectbox(
    "Current Month Sheet",
    all_sheets,
    index=all_sheets.index(auto_current) if auto_current in all_sheets else 0
)

def get_next_month_sheet(current_sheet_name, all_sheets):
    try:
        parts = current_sheet_name.split()
        for i, part in enumerate(parts):
            if part.upper() in ['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER']:
                month_str = part
                year_str = parts[i+1] if i+1 < len(parts) else None
                break
        else:
            return auto_next
        
        month_names = ['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER']
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
    next_sheet = st.sidebar.selectbox(
        "Next Month Sheet",
        all_sheets,
        index=all_sheets.index(next_sheet_default) if next_sheet_default in all_sheets else 0,
        disabled=False
    )

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

result = process_data(fee_content, payment_content, current_sheet, next_sheet, single_month_mode, ref_date)
if result is None:
    st.error("❌ No active fee-due clients found. Please check your data.")
    st.stop()

(
    ref_date_used,
    current_sheet_used,
    next_sheet_used,
    single_month_mode_flag,
    current_debits_c,
    current_debits_v,
    next_debits_c,
    next_debits_v,
    settled_today_c,
    settled_today_v,
    settled_cycle_c,
    settled_cycle_v,
    settled_mtd_c,
    settled_mtd_v,
    settling_c,
    settling_v,
    submitted_c,
    submitted_v,
    sub_col_c,
    sub_col_v,
    tracking_c,
    tracking_v,
    failed_cycle_c,
    failed_cycle_v,
    failed_mtd_c,
    failed_mtd_v,
    disputed_c,
    disputed_v,
    revenue_total,
    forecast_restructuring,
    forecast_legal,
    forecast_aftercare,
    forecast_admin_app,
    forecast_total,
    success_rate,
    combined_priority,
    failed_sms,
    tracking_sms,
    failed_clients,
    detail_dfs,
    raw,
    raw_stage_1_2,
    all_future,
    fee_status_df,
    fee_base
) = (
    result['ref_date'],
    result['current_sheet'],
    result['next_sheet'],
    result['single_month_mode'],
    result['current_debits_c'],
    result['current_debits_v'],
    result['next_debits_c'],
    result['next_debits_v'],
    result['settled_today_c'],
    result['settled_today_v'],
    result['settled_cycle_c'],
    result['settled_cycle_v'],
    result['settled_mtd_c'],
    result['settled_mtd_v'],
    result['settling_c'],
    result['settling_v'],
    result['submitted_c'],
    result['submitted_v'],
    result['sub_col_c'],
    result['sub_col_v'],
    result['tracking_c'],
    result['tracking_v'],
    result['failed_cycle_c'],
    result['failed_cycle_v'],
    result['failed_mtd_c'],
    result['failed_mtd_v'],
    result['disputed_c'],
    result['disputed_v'],
    result['revenue_total'],
    result['forecast_restructuring'],
    result['forecast_legal'],
    result['forecast_aftercare'],
    result['forecast_admin_app'],
    result['forecast_total'],
    result['success_rate'],
    result['combined_priority'],
    result['failed_sms'],
    result['tracking_sms'],
    result['failed_clients'],
    result['detail_dfs'],
    result['raw'],
    result['raw_stage_1_2'],
    result['all_future'],
    result['fee_status_df'],
    result['fee_base']
)

# ---- Dashboard output ----
st.success("✅ Data processed successfully!")

st.sidebar.markdown("---")
st.sidebar.write(f"**Current sheet:** `{current_sheet_used}`")
st.sidebar.write(f"**Next sheet:** `{next_sheet_used if next_sheet_used else 'None (single mode)'}`")
st.sidebar.write(f"**Report date:** {ref_date_used.strftime('%d %B %Y')}")
if single_month_mode:
    st.sidebar.write(f"**Single Month Mode:** On (ref: {ref_date_used.strftime('%B %Y')})")
else:
    st.sidebar.write("**Single Month Mode:** Off")

# ---- KPIs ----
col1, col2, col3, col4 = st.columns(4)
col1.metric("✅ Settled Today", f"R {settled_today_v:,.2f}", f"{settled_today_c} clients")
if not single_month_mode:
    col2.metric("📅 Next Month Debits", f"R {next_debits_v:,.2f}", f"{next_debits_c} clients")
else:
    col2.metric("📅 Next Month Debits", "N/A", "Single month mode")
col3.metric("💰 Revenue Total (MTD)", f"R {revenue_total:,.2f}")
col4.metric("🎯 Success Rate (MTD)", f"{success_rate:.1f}%", "By Value")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Settled Fri-Today", f"R {settled_cycle_v:,.2f}", f"{settled_cycle_c} clients")
col2.metric("Settled MTD", f"R {settled_mtd_v:,.2f}", f"{settled_mtd_c} clients")
col3.metric("Failed Fri-Today", f"R {failed_cycle_v:,.2f}", f"{failed_cycle_c} clients")
col4.metric("Failed MTD", f"R {failed_mtd_v:,.2f}", f"{failed_mtd_c} clients")

st.subheader("🔄 In Progress (Stage 1/2)")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Settling", f"R {settling_v:,.2f}", f"{settling_c} clients")
col2.metric("Submitted", f"R {submitted_v:,.2f}", f"{submitted_c} clients")
col3.metric("Sub Collect", f"R {sub_col_v:,.2f}", f"{sub_col_c} clients")
col4.metric("Intracking", f"R {tracking_v:,.2f}", f"{tracking_c} clients")

st.subheader("📅 Upcoming Debits (Stage 1/2)")
col1, col2 = st.columns(2)
col1.metric("Current Month (tomorrow → end)" if not single_month_mode else "Current Month Debits", 
            f"R {current_debits_v:,.2f}", f"{current_debits_c} clients")
if not single_month_mode:
    col2.metric("Next Month (full month)", f"R {next_debits_v:,.2f}", f"{next_debits_c} clients")
else:
    col2.metric("Next Month (full month)", "N/A", "Single month mode")

st.subheader("⚠️ Disputed")
st.metric("Disputed Clients", f"R {disputed_v:,.2f}", f"{disputed_c} clients")

# ---- Charts ----
st.subheader("📊 Visual Analytics")
fig_revenue = px.pie(
    names=['Restructuring', 'After-Care', 'Admin/App', 'Legal'],
    values=[forecast_restructuring, forecast_aftercare, forecast_admin_app, forecast_legal],
    title='Revenue Forecast Breakdown',
    hole=0.4
)
st.plotly_chart(fig_revenue, use_container_width=True)

col1, col2 = st.columns(2)
with col1:
    settled_vs_failed = pd.DataFrame({
        'Category': ['Settled MTD', 'Failed MTD'],
        'Amount': [settled_mtd_v, failed_mtd_v]
    })
    fig_bar = px.bar(settled_vs_failed, x='Category', y='Amount', title='Settled vs Failed (MTD)', color='Category')
    st.plotly_chart(fig_bar, use_container_width=True)

with col2:
    if not single_month_mode:
        debits_df = pd.DataFrame({
            'Month': ['Current', 'Next'],
            'Amount': [current_debits_v, next_debits_v]
        })
        fig_debits = px.bar(debits_df, x='Month', y='Amount', title='Debits Comparison', color='Month')
        st.plotly_chart(fig_debits, use_container_width=True)
    else:
        debits_df = pd.DataFrame({
            'Month': ['Selected Month'],
            'Amount': [current_debits_v]
        })
        fig_debits = px.bar(debits_df, x='Month', y='Amount', title='Debits (Single Month)', color='Month')
        st.plotly_chart(fig_debits, use_container_width=True)

priority_counts = combined_priority['Priority Level'].value_counts().reset_index()
priority_counts.columns = ['Priority', 'Count']
fig_priority = px.bar(priority_counts, x='Priority', y='Count', title='Priority Queue Distribution', color='Priority')
st.plotly_chart(fig_priority, use_container_width=True)

# ================================================================
# 📈 HISTORICAL TREND CHARTS
# ================================================================

# Save current month's metrics to history
history_file = "history/metrics_history.csv"
os.makedirs(os.path.dirname(history_file), exist_ok=True)

# Determine the month name for this report
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

# Append to CSV
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

# Load and display history
if os.path.exists(history_file):
    try:
        history_df = pd.read_csv(history_file)
        if len(history_df) > 1:
            history_df['report_date'] = pd.to_datetime(history_df['report_date'])
            history_df = history_df.sort_values('report_date')

            st.subheader("📈 Historical Trends")

            fig_trend = px.line(history_df, x='report_date', y=['settled_mtd_v', 'failed_mtd_v'],
                                title='Monthly Settled vs Failed Amount (R)',
                                labels={'value': 'Amount (R)', 'variable': 'Category'})
            st.plotly_chart(fig_trend, use_container_width=True)

            fig_sr = px.line(history_df, x='report_date', y='success_rate',
                             title='Success Rate (%) Over Time')
            st.plotly_chart(fig_sr, use_container_width=True)

            fig_rd = px.line(history_df, x='report_date', y=['revenue_total', 'current_debits_v', 'next_debits_v'],
                             title='Revenue, Current & Next Month Debits',
                             labels={'value': 'Amount (R)', 'variable': 'Category'})
            st.plotly_chart(fig_rd, use_container_width=True)
        else:
            st.info("📊 Collecting data for historical trends. Come back after more months of data.")
    except:
        pass

# ---- SMS Export ----
st.subheader("📱 Export SMS Lists")
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

# ---- Client Lists ----
st.subheader("📋 Failed Clients (SMS)")
if not failed_sms.empty:
    st.dataframe(failed_sms, use_container_width=True)
else:
    st.info("No failed clients.")

st.subheader("📋 Intracking Clients (SMS)")
if not tracking_sms.empty:
    st.dataframe(tracking_sms, use_container_width=True)
else:
    st.info("No intracking clients.")

# ---- Priority Queue ----
st.subheader("🔴 Priority Queue")
if not combined_priority.empty:
    def color_priority(val):
        if val == 'High':
            return 'background-color: #FF0000; color: white'
        elif val == 'Medium':
            return 'background-color: #FFA500; color: black'
        else:
            return 'background-color: #FFFF00; color: black'
    
    styled_priority = combined_priority.style.applymap(color_priority, subset=['Priority Level'])
    st.dataframe(styled_priority, use_container_width=True)
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
    st.subheader("Sample of Raw Data")
    st.dataframe(raw.head(10))
    st.subheader("Future Debits")
    st.dataframe(all_future.head(10))
    st.subheader("Status Counts (Stage 1/2)")
    if not raw_stage_1_2.empty:
        status_counts = raw_stage_1_2['status'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        st.dataframe(status_counts)

# ---- Download full Excel report ----
st.subheader("📥 Download Full Excel Report")

def generate_excel():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        dashboard_data = {
            'Metric': ['Settled Today (Stage 1/2)', 'Settled Fri-Today (Stage 1/2)', 'Settled 1st-Today (Stage 1/2)',
                       'Settling (Stage 1/2)', 'Submitted (Stage 1/2)', 'Sub Collect (Stage 1/2)', 'Intracking (Stage 1/2)',
                       'Curr Month Debits (Stage 1/2)', 'Next Month Debits (Stage 1/2)',
                       'Failed Fri-Today (Stage 1/2)', 'Failed 1st-Today (Stage 1/2)', 'Disputed (Stage 1/2)',
                       'Revenue Total (Stage 1/2, Current Month)',
                       'Success Rate (MTD, by value)',
                       'Single Month Mode'],
            'Value': [f"{settled_today_c} | R{settled_today_v:,.2f}",
                      f"{settled_cycle_c} | R{settled_cycle_v:,.2f}",
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
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {
            'type': 'formula',
            'criteria': f'=$I1="High"',
            'format': format_high
        })
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {
            'type': 'formula',
            'criteria': f'=$I1="Medium"',
            'format': format_medium
        })
        worksheet_pq.conditional_format(f'A1:I{last_row_pq}', {
            'type': 'formula',
            'criteria': f'=$I1="Low"',
            'format': format_low
        })

        failed_clients.to_excel(writer, sheet_name='Failed Clients', index=False)
        writer.sheets['Failed Clients'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))

        failed_sms.to_excel(writer, sheet_name='Failed Clients (SMS)', index=False)
        writer.sheets['Failed Clients (SMS)'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))
        tracking_sms.to_excel(writer, sheet_name='Intracking Clients (SMS)', index=False)
        writer.sheets['Intracking Clients (SMS)'].set_column('A:A', None, workbook.add_format({'num_format': '@'}))

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

st.caption(f"Report generated based on reference date: {ref_date_used.strftime('%d %B %Y')}")