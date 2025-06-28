from paddleocr import PaddleOCR
from pdf2image import convert_from_path
import logging
import numpy as np

def extract_text_from_pdf_with_paddleocr(pdf_path: str) -> str:
    """
    Extracts text from the first page of a PDF using PaddleOCR, downscaling the image to reduce memory usage.
    Returns the full extracted text as a string.
    """
    logging.info(f"Extracting text from PDF using PaddleOCR: {pdf_path}")
    # Convert only the first page of the PDF to an image
    images = convert_from_path(pdf_path, first_page=1, last_page=1)
    ocr = PaddleOCR(use_angle_cls=True, lang='en')
    all_text = []
    for img in images:
        # Downscale image by 50% to reduce memory usage
        img = img.resize((img.width // 2, img.height // 2))
        img_np = np.array(img)
        # Remove 'cls' argument for compatibility with some PaddleOCR versions
        result = ocr.ocr(img_np)
        for line in result:
            for word_info in line:
                all_text.append(word_info[1][0])
    return '\n'.join(all_text)
