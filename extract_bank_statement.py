import pandas as pd
import io
import re
from typing import List, Dict, Any
import pdfplumber
from fastapi import UploadFile
from unstructured.partition.pdf import partition_pdf
import shutil
import os
import logging
import pytesseract
from pdf2image import convert_from_bytes

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Shared Helpers & Normalization ---

_COLUMN_MAP = {
    'date': [r'date', r'txn date', r'transaction date'],
    'description': [r'particulars', r'description', r'details', r'transaction details', r'narration', r'desc'],
    'debit': [r'debit', r'withdrawal', r'withdrawals', r'withdrawn', r'dr'],
    'credit': [r'credit', r'deposit', r'deposits', r'cr'],
    'balance': [r'balance', r'closing balance', r'available balance'],
}

def _fuzzy_match_column(col_name: str) -> str | None:
    """Matches a column name to a standard key ('date', 'description', etc.)."""
    if not col_name:
        return None
    col_lower = col_name.strip().lower()
    logger.debug(f"Fuzzy matching column: '{col_lower}'")
    for key, patterns in _COLUMN_MAP.items():
        for pat in patterns:
            if re.search(rf'\b{pat}\b', col_lower):
                return key
    return None

def _get_column_rename_map(headers: List[str]) -> Dict[str, str]:
    """
    Given a list of header strings, returns a map for renaming,
    e.g., {'Transaction Date': 'date', 'Desc.': 'description'}.
    """
    rename_map = {}
    used_std_keys = set()
    logger.debug(f"Attempting to get rename map for headers: {headers}")
    for header in headers:
        std_key = _fuzzy_match_column(header)
        if std_key and std_key not in used_std_keys:
            # Ensure header is a string for the key
            rename_map[str(header)] = std_key
            used_std_keys.add(std_key)
    logger.debug(f"Generated rename map: {rename_map}")
    return rename_map

def _normalize_date(raw_date: Any) -> str | None:
    """Parses a date string into YYYY-MM-DD format, returning None on failure."""
    if pd.notnull(raw_date):
        try:
            return pd.to_datetime(str(raw_date), errors='coerce').strftime('%Y-%m-%d')
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not normalize date '{raw_date}': {e}")
            return None
    logger.debug(f"Raw date '{raw_date}' is null or not valid.")
    return None

def _normalize_amount(val: Any) -> float:
    """Converts a value to a float, cleaning up common currency artifacts."""
    if pd.notnull(val):
        try:
            s_val = str(val).replace(',', '').strip()
            # Remove common currency symbols and other non-numeric characters
            s_val = re.sub(r'[^\d.-]', '', s_val)
            if s_val:
                return float(s_val)
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not normalize amount '{val}': {e}")
            return 0.0
    logger.debug(f"Raw amount '{val}' is null or not valid.")
    return 0.0

def _process_dataframe_to_transactions(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Takes a DataFrame with standardized column names ('date', 'description', etc.)
    and returns a standardized list of transaction dictionaries.
    """
    result = []
    logger.info(f"Processing DataFrame with {len(df)} rows and columns: {df.columns.tolist()}")
    # Ensure optional columns exist to prevent errors
    for col in ['debit', 'credit', 'balance', 'description']:
        if col not in df.columns:
            df[col] = '' if col == 'description' else 0.0

    for _, row in df.iterrows():
        date_val = _normalize_date(row.get('date'))
        if not date_val:  # Skip rows that don't have a valid date
            logger.debug(f"Skipping row due to invalid date: {row.to_dict()}")
            continue
        result.append({
            'Date': date_val,
            'Description': str(row.get('description', '')) if pd.notnull(row.get('description')) else '',
            'Debit': _normalize_amount(row.get('debit')),
            'Credit': _normalize_amount(row.get('credit')),
            'Balance': _normalize_amount(row.get('balance')),
        })
    logger.info(f"Processed {len(result)} transactions from DataFrame.")
    return result

def extract_bank_statement_columns(uploaded_file: UploadFile) -> List[Dict[str, Any]]:
    # Read file into pandas DataFrame
    filename = uploaded_file.filename.lower()
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    if filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(content))
    elif filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(io.BytesIO(content))
    else:
        logger.error(f"Unsupported file type: {filename}")
        raise ValueError('Unsupported file type for data extraction.')

    logger.info(f"Successfully read {filename} into DataFrame with {len(df)} rows.")
    # Map columns
    headers = [str(h) for h in df.columns]
    rename_map = _get_column_rename_map(headers)
    required = ['date', 'description', 'debit', 'credit', 'balance']
    missing = [k for k in required if k not in rename_map.values()]
    if missing:
        logger.error(f"Missing required columns for {filename}: {', '.join(missing)}")
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    df.rename(columns=rename_map, inplace=True)
    return _process_dataframe_to_transactions(df)

def _check_tesseract_is_installed():
    """Checks if Tesseract OCR is installed and in the system's PATH."""
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract OCR is not installed or not in your PATH. "
            "It is required for processing scanned PDF documents. "
            "Please see https://tesseract-ocr.github.io/tessdoc/Installation.html for installation instructions."
        )

# --- PDF Extraction Strategies ---

def _extract_with_unstructured(content: bytes) -> List[Dict[str, Any]]:
    """Strategy 1: Use `unstructured` to parse PDF, prioritizing HTML table output."""
    logger.info("Attempting PDF extraction with 'unstructured' strategy.")
    try:
        elements = partition_pdf(
            file=io.BytesIO(content),
            strategy="hi_res",
            infer_table_structure=True,
            languages=['eng']
        )
        logger.info(f"Unstructured partition_pdf returned {len(elements)} elements.")
        tables = [el for el in elements if el.category == 'Table']
        logger.info(f"Found {len(tables)} table elements using unstructured.")
        all_transactions = []
        for table in tables:
            html_table = table.metadata.text_as_html
            if not html_table:
                logger.debug("Skipping table as no HTML representation found.")
                continue
            try:
                # Read without assuming a header row initially to handle tables where headers aren't on the first line
                df_list = pd.read_html(io.StringIO(html_table)) # No header=0
                if not df_list:
                    logger.debug("pd.read_html returned no DataFrames.")
                    continue

                df = df_list[0]

                # Dynamically find the header row
                header_row_index = -1
                rename_map = {}
                # Check the first few rows (e.g., 5) to find one that matches our column patterns
                for i, row in df.head().iterrows():
                    potential_headers = [str(h) for h in row.values]
                    potential_rename_map = _get_column_rename_map(potential_headers)
                    # A good header row should have at least 'date' and one of debit/credit
                    if 'date' in potential_rename_map.values() and \
                       ('debit' in potential_rename_map.values() or 'credit' in potential_rename_map.values()):
                        header_row_index = i
                        rename_map = potential_rename_map
                        logger.info(f"Found potential header at row index {i}: {potential_headers}")
                        break

                if header_row_index == -1:
                    logger.debug(f"Skipping table as no suitable header row found in first {len(df.head())} rows.")
                    continue

                # Set the found header row as the column names and drop the rows above it
                df.columns = df.iloc[header_row_index]
                df = df.drop(df.index[:header_row_index + 1]).reset_index(drop=True)

                df.rename(columns=rename_map, inplace=True)
                all_transactions.extend(_process_dataframe_to_transactions(df))
            except Exception as e:
                logger.warning(f"Error processing unstructured HTML table: {e}")
                continue
        logger.info(f"Unstructured strategy extracted {len(all_transactions)} transactions.")
        return all_transactions
    except Exception as e:
        logger.error(f"Error during unstructured PDF processing: {e}")
        return []

def _extract_with_pdfplumber(content: bytes) -> List[Dict[str, Any]]:
    """Strategy 2: Use `pdfplumber` for clean, text-based PDFs."""
    all_transactions = []
    logger.info("Attempting PDF extraction with 'pdfplumber' strategy.")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table_data in tables:
                    if not table_data or len(table_data) < 2:
                        logger.debug("Skipping table as it's empty or has only headers.")
                        continue

                    # Dynamically find the header row instead of assuming it's the first one
                    header_row_index = -1
                    rename_map = {}
                    for i, row in enumerate(table_data[:5]): # Check first 5 rows
                        potential_headers = [str(h) if h is not None else '' for h in row]
                        potential_rename_map = _get_column_rename_map(potential_headers)
                        # A good header row should have at least 'date' and one of debit/credit
                        if 'date' in potential_rename_map.values() and \
                           ('debit' in potential_rename_map.values() or 'credit' in potential_rename_map.values()):
                            header_row_index = i
                            rename_map = potential_rename_map
                            logger.info(f"Found potential header at row index {i}: {potential_headers}")
                            break

                    if header_row_index == -1:
                        logger.debug(f"Skipping table as no suitable header row found. First row was: {table_data[0] if table_data else 'N/A'}")
                        continue

                    # Create DataFrame with the correct header and data
                    df = pd.DataFrame(table_data[header_row_index + 1:], columns=table_data[header_row_index])

                    # Clean up column names that might be None before renaming
                    df.columns = [str(c) if c is not None else '' for c in df.columns]

                    df.rename(columns=rename_map, inplace=True)
                    all_transactions.extend(_process_dataframe_to_transactions(df))
        logger.info(f"pdfplumber strategy extracted {len(all_transactions)} transactions.")
        return all_transactions
    except Exception as e:
        logger.error(f"Error during pdfplumber PDF processing: {e}")
        return []

# --- Public API Functions ---

def extract_transactions_from_pdf(uploaded_file: UploadFile) -> List[Dict[str, Any]]:
    """
    Extracts transactions from a PDF using a multi-strategy approach for resilience.
    1. Tries `unstructured` for complex/scanned PDFs (requires Tesseract).
    2. Falls back to `pdfplumber` for simpler, text-based PDFs.
    """
    logger.info(f"Starting transaction extraction for PDF: {uploaded_file.filename}")
    _check_tesseract_is_installed()
    os.environ["OCR_AGENT"] = "pytesseract"
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()

    # Strategy 1: Unstructured (best for complex or scanned PDFs)
    transactions = _extract_with_unstructured(content)
    if transactions:
        logger.info(f"Successfully extracted {len(transactions)} transactions using 'unstructured' strategy.")
        return transactions

    # Strategy 2: pdfplumber (fallback for clean, text-based PDFs)
    logger.info("Unstructured strategy yielded no results. Falling back to 'pdfplumber' strategy.")
    transactions = _extract_with_pdfplumber(content)
    if transactions:
        logger.info(f"Successfully extracted {len(transactions)} transactions using 'pdfplumber' strategy.")
        return transactions

    logger.warning("No transactions extracted using either 'unstructured' or 'pdfplumber' strategies.")
    return []

def extract_bank_statement_from_pdf_ocr(uploaded_file: UploadFile) -> str:
    """
    Extracts text from each page of a PDF using OCR (Tesseract).
    Returns the full extracted text as a string.
    """
    _check_tesseract_is_installed()
    logger.info(f"Starting OCR text extraction for PDF: {uploaded_file.filename}")
    content = uploaded_file.file.read() if hasattr(uploaded_file, 'file') else uploaded_file.read()
    images = convert_from_bytes(content)
    all_text = []
    for img in images:
        text = pytesseract.image_to_string(img)
        all_text.append(text)
    return '\n'.join(all_text)
