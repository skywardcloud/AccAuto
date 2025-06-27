import pandas as pd
import io
import re
from datetime import datetime
from typing import List, Dict, Any
import pdfplumber
from fastapi import UploadFile
from unstructured.partition.pdf import partition_pdf
import tempfile
import os
import pytesseract
from pdf2image import convert_from_bytes

def extract_bank_statement_columns(uploaded_file: UploadFile) -> List[Dict[str, Any]]:
    # Define fuzzy column mapping
    COLUMN_MAP = {
        'date': [r'date', r'txn date', r'transaction date'],
        'description': [r'particulars', r'description', r'details', r'transaction details', r'narration', r'desc'],  # Added 'desc'
        'debit': [r'debit', r'withdrawal', r'withdrawals', r'withdrawn'],
        'credit': [r'credit', r'deposit', r'deposits'],
        'balance': [r'balance', r'closing balance', r'available balance'],
    }

    def fuzzy_match(col):
        col_lower = col.strip().lower()
        for key, patterns in COLUMN_MAP.items():
            for pat in patterns:
                if re.search(rf'\b{pat}\b', col_lower):
                    return key
        return None

    # Read file into pandas DataFrame
    filename = uploaded_file.filename.lower()
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    if filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(content))
    elif filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(io.BytesIO(content))
    else:
        raise ValueError('Unsupported file type for data extraction.')

    # Map columns
    col_map = {}
    for col in df.columns:
        match = fuzzy_match(col)
        if match and match not in col_map:
            col_map[match] = col
    required = ['date', 'description', 'debit', 'credit', 'balance']
    missing = [k for k in required if k not in col_map]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    # Extract and normalize
    result = []
    for _, row in df.iterrows():
        # Normalize date
        raw_date = row[col_map['date']]
        date_val = None
        if pd.notnull(raw_date):
            try:
                date_val = pd.to_datetime(str(raw_date), errors='coerce').strftime('%Y-%m-%d')
            except Exception:
                date_val = None
        # Normalize debit/credit
        def to_float(val):
            try:
                return float(str(val).replace(',', '').strip()) if pd.notnull(val) else 0.0
            except Exception:
                return 0.0
        result.append({
            'Date': date_val,
            'Description': str(row[col_map['description']]) if pd.notnull(row[col_map['description']]) else '',
            'Debit': to_float(row[col_map['debit']]),
            'Credit': to_float(row[col_map['credit']]),
            'Balance': to_float(row[col_map['balance']]),
        })
    return result

def extract_bank_statement_from_pdf(uploaded_file: UploadFile) -> list:
    """
    Extracts bank statement data from a text-based PDF using pdfplumber.
    Tries to find tables with at least Date, Description, and (Debit or Credit).
    Allows missing Balance, Debit, or Credit columns (sets to 0.0 if missing).
    Returns a list of dictionaries.
    """
    COLUMN_MAP = {
        'date': [r'date', r'txn date', r'transaction date'],
        'description': [r'particulars', r'description', r'details', r'transaction details', r'narration'],
        'debit': [r'debit', r'withdrawal', r'withdrawals', r'withdrawn'],
        'credit': [r'credit', r'deposit', r'deposits'],
        'balance': [r'balance', r'closing balance', r'available balance'],
    }
    def fuzzy_match(col):
        col_lower = str(col).strip().lower()
        for key, patterns in COLUMN_MAP.items():
            for pat in patterns:
                if re.search(rf'\b{pat}\b', col_lower):
                    return key
        return None

    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    result = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = table[0]
                col_map = {}
                for idx, col in enumerate(headers):
                    match = fuzzy_match(col)
                    if match and match not in col_map:
                        col_map[match] = idx
                # Accept tables with at least date, description, and (debit or credit)
                if not ('date' in col_map and 'description' in col_map and ('debit' in col_map or 'credit' in col_map)):
                    continue
                for row in table[1:]:
                    # Normalize date
                    raw_date = row[col_map['date']] if 'date' in col_map else None
                    date_val = None
                    if raw_date:
                        try:
                            date_val = pd.to_datetime(str(raw_date), errors='coerce').strftime('%Y-%m-%d')
                        except Exception:
                            date_val = None
                    def to_float(val):
                        try:
                            return float(str(val).replace(',', '').strip()) if val else 0.0
                        except Exception:
                            return 0.0
                    result.append({
                        'Date': date_val,
                        'Description': str(row[col_map['description']]) if 'description' in col_map and row[col_map['description']] else '',
                        'Debit': to_float(row[col_map['debit']]) if 'debit' in col_map else 0.0,
                        'Credit': to_float(row[col_map['credit']]) if 'credit' in col_map else 0.0,
                        'Balance': to_float(row[col_map['balance']]) if 'balance' in col_map else 0.0,
                    })
    return result

def extract_bank_statement_from_pdf_unstructured(uploaded_file: UploadFile) -> list:
    """
    Extracts tables from PDF using unstructured and tries to intelligently map columns.
    Returns a list of dictionaries with keys: Date, Description, Debit, Credit, Balance.
    """
    # Ensure OCR_AGENT is set for unstructured OCR support
    os.environ["OCR_AGENT"] = "pytesseract"
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    elements = partition_pdf(tmp_path)
    os.unlink(tmp_path)
    # Find all tables
    tables = [el for el in elements if el.category == 'Table']
    result = []
    for table in tables:
        # table.text is a string representation; try to split into rows/columns
        rows = [row for row in table.text.split('\n') if row.strip()]
        if not rows or len(rows) < 2:
            continue
        headers = [h.strip() for h in rows[0].split('  ') if h.strip()]
        # Fuzzy match headers to standard columns
        COLUMN_MAP = {
            'date': [r'date', r'txn date', r'transaction date'],
            'description': [r'particulars', r'description', r'details', r'transaction details', r'narration', r'desc'],
            'debit': [r'debit', r'withdrawal', r'withdrawals', r'withdrawn'],
            'credit': [r'credit', r'deposit', r'deposits'],
            'balance': [r'balance', r'closing balance', r'available balance'],
        }
        def fuzzy_match(col):
            col_lower = col.strip().lower()
            for key, patterns in COLUMN_MAP.items():
                for pat in patterns:
                    if re.search(rf'\b{pat}\b', col_lower):
                        return key
            return None
        col_map = {}
        for idx, col in enumerate(headers):
            match = fuzzy_match(col)
            if match and match not in col_map:
                col_map[match] = idx
        # Accept tables with at least date, description, and (debit or credit)
        if not ('date' in col_map and 'description' in col_map and ('debit' in col_map or 'credit' in col_map)):
            continue
        for row in rows[1:]:
            cells = [c.strip() for c in row.split('  ') if c.strip()]
            def get_cell(col):
                idx = col_map.get(col)
                return cells[idx] if idx is not None and idx < len(cells) else ''
            # Normalize date
            raw_date = get_cell('date')
            date_val = None
            if raw_date:
                try:
                    date_val = pd.to_datetime(str(raw_date), errors='coerce').strftime('%Y-%m-%d')
                except Exception:
                    date_val = None
            def to_float(val):
                try:
                    return float(str(val).replace(',', '').strip()) if val else 0.0
                except Exception:
                    return 0.0
            result.append({
                'Date': date_val,
                'Description': get_cell('description'),
                'Debit': to_float(get_cell('debit')),
                'Credit': to_float(get_cell('credit')),
                'Balance': to_float(get_cell('balance')),
            })
    return result

def extract_bank_statement_from_pdf_ocr(uploaded_file: UploadFile) -> str:
    """
    Extracts text from each page of a PDF using OCR (Tesseract).
    Returns the full extracted text as a string.
    """
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    images = convert_from_bytes(content)
    all_text = []
    for img in images:
        text = pytesseract.image_to_string(img)
        all_text.append(text)
    return '\n'.join(all_text)
