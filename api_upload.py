from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os
from extract_bank_statement import extract_bank_statement_columns, extract_transactions_from_pdf, extract_bank_statement_from_pdf_ocr
from openai_extractor import extract_transactions_with_openai

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
    # Save the uploaded file to a temp location for PaddleOCR
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        ocr_text = None
        data = []
        if ext == '.pdf':
            # Use PaddleOCR + LLM pipeline
            data = extract_transactions_with_openai(pdf_path=tmp_path)
            # Optionally, also return the OCR text for debugging
            from paddle_ocr_extractor import extract_text_from_pdf_with_paddleocr
            ocr_text = extract_text_from_pdf_with_paddleocr(tmp_path)
        else:
            file.file.seek(0)
            from extract_bank_statement import extract_bank_statement_columns
            data = extract_bank_statement_columns(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")
    finally:
        os.remove(tmp_path)
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
