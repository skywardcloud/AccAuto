from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os
import mimetypes
from extract_bank_statement import extract_bank_statement_columns, extract_bank_statement_from_pdf, extract_bank_statement_from_pdf_unstructured, extract_bank_statement_from_pdf_ocr

app = FastAPI()

# Allow CORS for local development (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {'.csv', '.xls', '.xlsx', '.pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file extension.")
    contents = await file.read()
    size = len(contents)
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 10 MB.")
    # Rewind file for reading by pandas/pdfplumber/unstructured
    file.file.seek(0)
    try:
        ocr_text = None
        if ext == '.pdf':
            # Use the new unstructured-based extraction for PDFs
            file.file.seek(0)
            data = extract_bank_statement_from_pdf_unstructured(file)
            # Fallback to old method if nothing found
            if not data:
                file.file.seek(0)
                data = extract_bank_statement_from_pdf(file)
            # Always get OCR text for inspection
            file.file.seek(0)
            ocr_text = extract_bank_statement_from_pdf_ocr(file)
        else:
            file.file.seek(0)
            data = extract_bank_statement_columns(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")
    # Format output keys to match frontend expectations
    formatted = []
    for row in data:
        formatted.append({
            'date': row.get('Date'),
            'description': row.get('Description'),
            'debit': float(row.get('Debit', 0.0)) if row.get('Debit') is not None else 0.0,
            'credit': float(row.get('Credit', 0.0)) if row.get('Credit') is not None else 0.0,
            'balance': float(row.get('Balance', 0.0)) if row.get('Balance') is not None else 0.0,
        })
    response = {
        "filename": filename,
        "content_type": file.content_type,
        "size": size,
        "transactions": formatted,
        "message": "File uploaded and parsed successfully."
    }
    if ext == '.pdf':
        response["ocr_text"] = ocr_text
    return JSONResponse(response)
