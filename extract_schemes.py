#!/usr/bin/env python3
"""
Extract text from scheme documents
"""
import os
import sys
import pdfplumber
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
TEXT_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/text/schemes"
os.makedirs(TEXT_DIR, exist_ok=True)

def extract_text_from_pdf(pdf_path, txt_path):
    """Extract text from PDF using pdfplumber"""
    try:
        text_content = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            logger.info(f"  Pages: {len(pdf.pages)}")
            
            for i, page in enumerate(pdf.pages):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += f"\n--- Page {i+1} ---\n{page_text}\n"
                except Exception as e:
                    logger.warning(f"    Page {i+1}: {str(e)[:60]}")
        
        if text_content.strip():
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
            
            size_kb = len(text_content) / 1024
            logger.info(f"  ✓ Extracted: {os.path.basename(txt_path)} ({size_kb:.1f} KB)")
            return True
        else:
            logger.warning(f"  ⚠ No text content extracted")
            return False
            
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        return False

# Process scheme PDFs
print("\n" + "="*70)
print("SCHEME TEXT EXTRACTION")
print("="*70 + "\n")

scheme_files = [f for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
logger.info(f"Found {len(scheme_files)} scheme PDF(s)\n")

extracted = 0
failed = 0

for pdf_file in sorted(scheme_files):
    pdf_path = os.path.join(SCHEMES_DIR, pdf_file)
    txt_file = pdf_file.replace('.pdf', '.txt')
    txt_path = os.path.join(TEXT_DIR, txt_file)
    
    # Skip if already extracted
    if os.path.exists(txt_path):
        size = os.path.getsize(txt_path)
        if size > 100:
            logger.info(f"[skip] {txt_file} (already extracted)")
            continue
    
    logger.info(f"Extracting: {pdf_file}")
    
    if extract_text_from_pdf(pdf_path, txt_path):
        extracted += 1
    else:
        failed += 1

# Summary
print("\n" + "="*70)
print("EXTRACTION SUMMARY")
print("="*70)
print(f"Extracted: {extracted}")
print(f"Failed: {failed}")
print(f"Text files location: {TEXT_DIR}\n")

# List extracted files
txt_files = [f for f in os.listdir(TEXT_DIR) if f.endswith('.txt')]
if txt_files:
    print(f"Extracted files ({len(txt_files)}):")
    for txt_file in sorted(txt_files):
        path = os.path.join(TEXT_DIR, txt_file)
        size = os.path.getsize(path) / 1024
        print(f"  • {txt_file} ({size:.1f} KB)")
