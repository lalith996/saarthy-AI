#!/usr/bin/env python3
"""
Direct download of remaining scheme PDFs using known URLs
"""
import os
import requests
import json

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Direct PDF URLs for schemes
DIRECT_PDF_URLS = {
    "PM-Fasal-Bima": "https://pmfby.gov.in/documents/DownloadDocuments",
    "Atal-Pension": "https://pfrda.org.in/myfile/webform/data/files/0000000001/File1.pdf",
    "PM-SVANidhi": "https://pmsvanidhi.mohua.gov.in/UserFiles/File/Guidelines_English_PMVS.pdf",
    "Jal-Jeevan": "https://jaljeevan.nic.in/documents",
    "PM-POSHAN": "https://pmposhan.education.gov.in/documents/guidelines.pdf",
    "PMGSY": "https://pmgsy.nic.in/documents/guidelines.pdf",
    "StandUp-India": "https://standupmitra.in/download/scheme",
    "Skill-India-PMKVY": "https://pmkvyofficial.org/scheme-guidelines.pdf",
    "Jan-Dhan": "https://pmjdy.gov.in/scheme-document.pdf",
    "Sukanya-Samriddhi": "https://nsiindia.gov.in/schemes/sukanya-samriddhi-yojana/rules.pdf",
    "Senior-Citizen-Savings": "https://nsiindia.gov.in/schemes/senior-citizens-savings-scheme/rules.pdf",
    "NPS": "https://pfrda.org.in/national-pension-system/guidelines.pdf"
}

def download_pdf(url, filename):
    """Download PDF from direct URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True, stream=True)
        response.raise_for_status()
        
        content = response.content
        
        # Basic validation
        if len(content) < 100:
            print(f"    ✗ Downloaded content too small ({len(content)} bytes)")
            return False
        
        # Save file
        filepath = os.path.join(SCHEMES_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        
        size = len(content) / (1024 * 1024)
        print(f"    ✓ Downloaded {filename} ({size:.2f} MB)")
        return True
        
    except Exception as e:
        print(f"    ✗ Error: {str(e)[:80]}")
        return False

print("\n" + "="*70)
print("DIRECT PDF DOWNLOADER FOR REMAINING SCHEMES")
print("="*70 + "\n")

downloaded = {}

for scheme, url in DIRECT_PDF_URLS.items():
    filename = scheme.lower().replace("-", "_") + ".pdf"
    print(f"📌 {scheme}")
    print(f"  URL: {url}")
    
    if download_pdf(url, filename):
        downloaded[scheme] = filename
    
    print()

# Update manifest
manifest_path = os.path.join(SCHEMES_DIR, "manifest.json")
if os.path.exists(manifest_path):
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
else:
    manifest = {"files": {}}

manifest["files"].update(downloaded)
manifest["total_downloaded"] = len(manifest["files"])

with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)

print("="*70)
print(f"✅ Downloaded {len(downloaded)} additional schemes")
print(f"📁 Total files in {SCHEMES_DIR}: {len(os.listdir(os.path.join(SCHEMES_DIR, 'pdfs')) if os.path.exists(os.path.join(SCHEMES_DIR, 'pdfs')) else [])}")
