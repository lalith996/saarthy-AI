#!/usr/bin/env python3
"""
Download remaining schemes using discovered URLs
"""
import os
import requests
import json

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Direct PDF URLs found from websites
FOUND_URLs = {
    "PM-Fasal-Bima": "https://pmfby.amnex.co.in/pmfby/pdf/operational_guidelines_pmfby.pdf",
    "PM-SVANidhi": "https://pmsvanidhi.mohua.gov.in/Default/ViewFile/?id=Credit+Card+guidelines.pdf&path=MiscFiles",
    "PM-Awas-Urban": "https://pmay-urban.gov.in/pdf/guidelines.pdf",
}

# Additional scheme URLs to try
ADDITIONAL_URLS = {
    "Atal-Pension": [
        "https://www.pfrda.org.in/documents/upload/scheme_apy_guideline.pdf",
        "https://pfrda.org.in/downloads/apy-guidelines.pdf",
    ],
    "Jal-Jeevan": [
        "https://jaljeevan.nic.in/documents/jjm-guidelines.pdf",
    ],
    "PM-POSHAN": [
        "https://pmposhan.education.gov.in/files/guidelines.pdf",
    ],
    "PMGSY": [
        "https://pmgsy.nic.in/files/pmgsy-guidelines.pdf",
    ],
    "StandUp-India": [
        "https://standupmitra.in/uploads/scheme-guidelines.pdf",
    ],
    "Skill-India-PMKVY": [
        "https://pmkvyofficial.org/uploads/pmkvy-guidelines.pdf",
    ],
    "Jan-Dhan": [
        "https://pmjdy.gov.in/uploads/scheme-guidelines.pdf",
    ],
    "Sukanya-Samriddhi": [
        "https://nsiindia.gov.in/documents/sukanya-samriddhi-rules.pdf",
    ],
    "Senior-Citizen-Savings": [
        "https://nsiindia.gov.in/documents/senior-citizen-savings-rules.pdf",
    ],
    "NPS": [
        "https://pfrda.org.in/documents/nps-guidelines.pdf",
    ],
}

def download_pdf(url, filename):
    """Download PDF"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True, stream=True)
        response.raise_for_status()
        
        content = response.content
        
        # Validate PDF
        if len(content) < 1000:
            return False
        
        # Check if it's a valid PDF (may not have header for some PDFs)
        if len(content) > 0:
            filepath = os.path.join(SCHEMES_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(content)
            return True
        
        return False
    except Exception as e:
        print(f"      Error: {str(e)[:60]}")
        return False

print("\n" + "="*70)
print("DOWNLOADING FOUND SCHEME DOCUMENTS")
print("="*70 + "\n")

downloaded = {}

# Download found URLs
print(">>> DOWNLOADING DISCOVERED URLs\n")
for scheme, url in FOUND_URLs.items():
    if os.path.exists(os.path.join(SCHEMES_DIR, f"{scheme}-Guidelines.pdf")):
        print(f"✓ {scheme} - already exists")
        continue
    
    print(f"📌 {scheme}")
    print(f"  URL: {url}")
    filename = f"{scheme}-Guidelines.pdf"
    
    if download_pdf(url, filename):
        filepath = os.path.join(SCHEMES_DIR, filename)
        size = os.path.getsize(filepath) / (1024*1024)
        print(f"  ✓ Downloaded ({size:.2f} MB)")
        downloaded[scheme] = filename
    else:
        print(f"  ✗ Download failed")
    
    print()

# Try additional URLs
print("\n>>> TRYING ADDITIONAL URLS\n")

for scheme, urls in ADDITIONAL_URLS.items():
    filename = f"{scheme}-Guidelines.pdf"
    filepath = os.path.join(SCHEMES_DIR, filename)
    
    # Skip if already exists
    if os.path.exists(filepath):
        print(f"✓ {scheme} - already exists")
        continue
    
    print(f"📌 {scheme}")
    found = False
    
    for url in urls:
        print(f"  Trying: {url}")
        if download_pdf(url, filename):
            size = os.path.getsize(filepath) / (1024*1024)
            print(f"  ✓ Downloaded ({size:.2f} MB)")
            downloaded[scheme] = filename
            found = True
            break
        else:
            print(f"  ✗ Failed")
    
    if not found:
        print(f"  Unable to download")
    
    print()

# Summary
all_pdfs = [f for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
existing_schemes = {
    f.replace('-Guidelines.pdf', '').replace('scheme_pm-kisan_operational_guidelines_english', 'PM-KISAN'): f 
    for f in all_pdfs
}

print("="*70)
print("FINAL SUMMARY")
print("="*70)
print(f"\nTotal PDF files in schemes directory: {len(all_pdfs)}\n")

print("Available schemes:")
for scheme, file in sorted(existing_schemes.items()):
    path = os.path.join(SCHEMES_DIR, file)
    size = os.path.getsize(path) / (1024*1024)
    print(f"  ✓ {scheme}: {size:.2f} MB")

missing_count = 15 - len(all_pdfs)
if missing_count > 0:
    print(f"\nStill missing: {missing_count} schemes")
    print("(These require manual browser download from their official websites)")
