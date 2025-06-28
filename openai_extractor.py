import openai
import os
import json
import logging
import re
from paddle_ocr_extractor import extract_text_from_pdf_with_paddleocr

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configure the OpenAI client
try:
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
except KeyError:
    logging.error("OPENAI_API_KEY environment variable not set. The OpenAI extractor will not work.")
    client = None

def _clean_ocr_text(text: str) -> str:
    """
    Cleans and normalizes raw OCR text to make it more parsable by the LLM.
    - Replaces multiple newlines with a single one.
    - Trims leading/trailing whitespace from each line.
    - Removes lines that are empty or contain only whitespace.
    """
    lines = text.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return '\n'.join(cleaned_lines)

def _filter_transaction_lines(text: str) -> str:
    """
    Returns only lines that look like transactions (contain a date or a money value).
    """
    date_pattern = re.compile(r"\b(\d{1,2}\s*[A-Za-z]{3,}|[A-Za-z]{3,}\s*\d{1,2}|\d{4}-\d{2}-\d{2})\b")
    money_pattern = re.compile(r"\d+\.\d{2}")
    filtered_lines = []
    for line in text.split('\n'):
        if date_pattern.search(line) or money_pattern.search(line):
            filtered_lines.append(line)
    return '\n'.join(filtered_lines)

def extract_transactions_with_openai(text: str = None, pdf_path: str = None):
    """
    If pdf_path is provided, use PaddleOCR to extract text from the PDF.
    Otherwise, use the provided text (for legacy compatibility).
    """
    if pdf_path:
        text = extract_text_from_pdf_with_paddleocr(pdf_path)
    if not text:
        logging.warning("No text provided or extracted for OpenAI extraction.")
        return []

    """
    Uses a two-step approach with an OpenAI model to extract transaction data from raw text.
    1. Cleans the OCR text.
    2. Filters for likely transaction lines.
    3. Uses a targeted prompt to extract a JSON array of transactions.
    """
    if not client:
        logging.warning("Skipping OpenAI extraction because OPENAI_API_KEY is not set.")
        return []

    logging.info("Cleaning OCR text before sending to OpenAI.")
    cleaned_text = _clean_ocr_text(text)
    filtered_text = _filter_transaction_lines(cleaned_text)
    logging.info(f"Filtered text being sent to OpenAI:\n---BEGIN TEXT---\n{filtered_text}\n---END TEXT---")

    logging.info("Attempting transaction extraction with OpenAI using a more robust prompt.")

    prompt = f"""
    You are an expert data extraction assistant. Your task is to find and extract all financial transactions from the provided text.
    The text is from a bank statement's OCR scan and may be messy.

    Focus ONLY on lines that represent individual transactions. Ignore summary lines, headers, and any line that does not contain a date and at least one money value (debit, credit, or balance).
    Transactions may be split across multiple lines. Merge all lines that belong to the same transaction into a single object.

    Return the data as a single JSON object with a key named \"transactions\". This key should contain a JSON array of objects, where each object is a single transaction.
    Each object must have these keys: \"Date\", \"Description\", \"Debit\", \"Credit\", and \"Balance\".

    Follow these rules strictly:
    1.  **JSON OBJECT ONLY:** Your entire response must be ONLY a single JSON object with the \"transactions\" key. Do not include any other text, markdown, or explanations.
    2.  **MERGE DESCRIPTIONS:** Transaction descriptions can span multiple lines. You MUST merge these into a single \"Description\" string.
    3.  **HANDLE NUMBERS:** Debit, Credit, and Balance must be numbers. If a value is missing, use `null`. Do not include currency symbols.
    4.  **BE COMPLETE:** Extract every single transaction you can find. If in doubt, include the line as a transaction.

    Example OCR text:
    Date Description Withdrawals ($) Deposits ($) Balance ($)
    5 Apr e-Transfer - Autodeposit ~ 125.00 5,630.00
    Online Banking payment - 2850 VISA TD BANK 500.00
    Online Banking payment - 3022 VISA CIBC, 2000

    Should be extracted as:
    {{
        "transactions": [
            {{
                "Date": "5 Apr",
                "Description": "e-Transfer - Autodeposit",
                "Debit": 125.00,
                "Credit": null,
                "Balance": 5630.00
            }},
            {{
                "Date": null,
                "Description": "Online Banking payment - 2850 VISA TD BANK",
                "Debit": 500.00,
                "Credit": null,
                "Balance": null
            }},
            {{
                "Date": null,
                "Description": "Online Banking payment - 3022 VISA CIBC, 2000",
                "Debit": null,
                "Credit": null,
                "Balance": null
            }}
        ]
    }}

    Here is the text to analyze:
    ---
    {filtered_text}
    ---
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4-1106-preview", # Use GPT-4.1 model for improved extraction
            messages=[
                {"role": "system", "content": "You are an assistant that only responds with valid, raw JSON based on the user's request."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0, # For deterministic output
            response_format={ "type": "json_object" }, # Enforce JSON output
        )
        # The response from the API when using json_object mode is already a parsed JSON object.
        json_response_content = json.loads(response.choices[0].message.content)
        
        # The actual transaction list should be under the "transactions" key.
        transactions = json_response_content.get("transactions", [])

        if not isinstance(transactions, list):
            logging.warning(f"OpenAI returned JSON, but the 'transactions' key did not contain a list. Found type: {type(transactions).__name__}")
            return []
        
        if not transactions:
             logging.warning("OpenAI returned a list of transactions, but it was empty.")
             # This might not be an error, could be a statement with no transactions.

        logging.info(f"OpenAI GPT extracted {len(transactions)} transactions.")
        return transactions
    except Exception as e:
        logging.error(f"Failed to parse transactions using OpenAI: {e}")
        logging.error(f"OpenAI Response Text: {response.choices[0].message.content if 'response' in locals() else 'No response'}")
        return []
