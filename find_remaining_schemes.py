#!/usr/bin/env python3
"""
Find and download remaining scheme documents from multiple sources
"""
import os
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import json
import time

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Alternative URLs and direct PDF links for remaining schemes
SCHEME_SOURCES = {
    "PM-Fasal-Bima": [
        "https://pmfby.gov.in/documents/DownloadDocuments",
        "https://pmfby.gov.in/media-resources",
        "https://pmfby.gov.in/",
    ],
    "Atal-Pension": [
        "https://pfrda.org.in/en/pension-schemes/apy/",
        "https://pfrda.org.in/",
        "https://www.pfrda.org.in/documents/upload/APY_Guideline_English_07052015.pdf",
    ],
    "PM-SVANidhi": [
        "https://pmsvanidhi.mohua.gov.in/guidelines",
        "https://pmsvanidhi.mohua.gov.in/",
        "https://pmsvanidhi.mohua.gov.in/UserFiles/File/Guidelines_English_PMVS.pdf",
    ],
    "Jal-Jeevan": [
        "https://jaljeevan.nic.in/guidelines",
        "https://jaljeevan.nic.in/",
        "https://jaljeevan.nic.in/UserFiles/File/Guidelines_English.pdf",
    ],
    "PM-POSHAN": [
        "https://pmposhan.education.gov.in/guidelines",
        "https://pmposhan.education.gov.in/",
    ],
    "PMGSY": [
        "https://pmgsy.nic.in/guidelines",
        "https://pmgsy.nic.in/",
        "https://pmgsy.nic.in/pdf/PMGSY_Guidelines_English.pdf",
    ],
    "StandUp-India": [
        "https://standupmitra.in/scheme-details",
        "https://standupmitra.in/",
    ],
    "Skill-India-PMKVY": [
        "https://pmkvyofficial.org/scheme-guidelines",
        "https://pmkvyofficial.org/",
    ],
    "Jan-Dhan": [
        "https://pmjdy.gov.in/scheme-document",
        "https://pmjdy.gov.in/",
    ],
    "Sukanya-Samriddhi": [
        "https://nsiindia.gov.in/schemes/sukanya-samriddhi-yojana/",
        "https://nsiindia.gov.in/",
    ],
    "Senior-Citizen-Savings": [
        "https://nsiindia.gov.in/schemes/senior-citizens-savings-scheme/",
        "https://nsiindia.gov.in/",
    ],
    "NPS": [
        "https://pfrda.org.in/national-pension-system/",
        "https://pfrda.org.in/",
    ]
}

# Known direct PDF URLs (from government sites)
DIRECT_PDF_URLS = {
    "Atal-Pension": [
        "https://www.pfrda.org.in/documents/upload/APY_Guideline_English_07052015.pdf",
        "https://pfrda.org.in/documents/upload/APY_Guidelines.pdf",
    ],
    "PM-SVANidhi": [
        "https://pmsvanidhi.mohua.gov.in/UserFiles/File/Guidelines_English_PMVS.pdf",
    ],
    "Jal-Jeevan": [
        "https://jaljeevan.nic.in/ContentFiles/pdf/Operational-Guidelines-Jal-Jeevan.pdf",
    ],
    "PM-POSHAN": [
        "https://pmposhan.education.gov.in/UserFiles/File/PM_POSHAN_Guidelines.pdf",
    ],
    "PMGSY": [
        "https://pmgsy.nic.in/PDF_File/PMGSY_Guidelines_2023.pdf",
    ],
    "StandUp-India": [
        "https://standupmitra.in/upload/docs/StandUpIndia_Scheme_Details.pdf",
    ],
    "Skill-India-PMKVY": [
        "https://pmkvyofficial.org/pdf/PMKVY_Guidelines.pdf",
    ],
    "Jan-Dhan": [
        "https://pmjdy.gov.in/UserFiles/File/JDY_Scheme_Document.pdf",
    ],
}

def extract_pdf_links(url):
    """Extract all PDF links from a webpage"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        pdf_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if '.pdf' in href.lower():
                full_url = urljoin(url, href)
                text = link.get_text(strip=True)
                pdf_links.append({
                    'url': full_url,
                    'text': text[:80] if text else 'PDF',
                })
        
        return pdf_links
    except Exception as e:
        return []

def download_pdf(url, filename):
    """Download and validate PDF"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True)
        response.raise_for_status()
        
        content = response.content
        
        # Check if it's a valid PDF
        if len(content) < 1000:
            return False
        
        if b'%PDF' not in content[:20]:
            return False
        
        # Save file
        filepath = os.path.join(SCHEMES_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        
        return True
        
    except Exception as e:
        return False

print("\n" + "="*70)
print("SEARCHING FOR REMAINING SCHEME DOCUMENTS")
print("="*70 + "\n")

downloaded = {}
failed_schemes = {}

# First try direct PDF URLs
print(">>> ATTEMPTING DIRECT PDF DOWNLOADS\n")

for scheme, urls in DIRECT_PDF_URLS.items():
    print(f"📌 {scheme}")
    filename = f"{scheme}-Guidelines.pdf"
    found = False
    
    for url in urls:
        print(f"  Trying: {url}")
        if download_pdf(url, filename):
            filepath = os.path.join(SCHEMES_DIR, filename)
            size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  ✓ Downloaded ({size:.2f} MB)")
            downloaded[scheme] = filename
            found = True
            break
        time.sleep(0.5)
    
    if not found:
        print(f"  ✗ Not available")
    
    print()

# Then try scraping homepages for PDF links
print("\n>>> SEARCHING HOMEPAGES FOR PDF LINKS\n")

remaining = set(SCHEME_SOURCES.keys()) - set(downloaded.keys())

for scheme in remaining:
    print(f"📌 {scheme}")
    urls = SCHEME_SOURCES[scheme]
    filename = f"{scheme}-Guidelines.pdf"
    found = False
    
    for url in urls:
        if found:
            break
        
        print(f"  Scanning: {url}")
        pdf_links = extract_pdf_links(url)
        
        if pdf_links:
            print(f"    Found {len(pdf_links)} PDF link(s)")
            for pdf_info in pdf_links[:3]:
                print(f"      → {pdf_info['text'][:60]}")
                
                if download_pdf(pdf_info['url'], filename):
                    filepath = os.path.join(SCHEMES_DIR, filename)
                    size = os.path.getsize(filepath) / (1024 * 1024)
                    print(f"      ✓ Downloaded ({size:.2f} MB)")
                    downloaded[scheme] = filename
                    found = True
                    break
        
        time.sleep(0.5)
    
    if not found:
        failed_schemes[scheme] = urls
        print(f"  ✗ Could not find PDF")
    
    print()

# Summary
print("="*70)
print("DOWNLOAD SUMMARY")
print("="*70)
print(f"\nSuccessfully downloaded: {len(downloaded)}")
print(f"Still missing: {len(failed_schemes)}")

if downloaded:
    print(f"\n✓ Downloaded schemes:")
    for scheme, file in sorted(downloaded.items()):
        path = os.path.join(SCHEMES_DIR, file)
        size = os.path.getsize(path) / (1024*1024)
        print(f"  • {scheme}: {file} ({size:.2f} MB)")

if failed_schemes:
    print(f"\n✗ Missing schemes (requires manual download):")
    for scheme in sorted(failed_schemes.keys()):
        print(f"  • {scheme}")

# Count total PDF files
all_pdfs = [f for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
print(f"\n📊 Total PDFs in schemes folder: {len(all_pdfs)}")
