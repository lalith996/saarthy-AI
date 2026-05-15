#!/usr/bin/env python3
"""
Download scheme documents - intelligent scraper with fallbacks
"""
import os
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import json
import time

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Scheme configuration with direct URLs and search paths
SCHEMES_CONFIG = {
    "MGNREGA": {
        "urls": [
            "https://nrega.dord.gov.in/MGNREGA_new/Nrega_home.aspx",
            "https://nrega.dord.gov.in/",
        ],
        "filename": "MGNREGA-Guidelines.pdf"
    },
    "PM-JAY": {
        "urls": [
            "https://pmjay.gov.in/",
            "https://pmjay.gov.in/standard_treatment_guidelines",
        ],
        "filename": "PMJAY-Guidelines.pdf"
    },
    "PM-Awas-Urban": {
        "urls": [
            "https://pmay-urban.gov.in/",
            "https://pmay-urban.gov.in/guidelines",
        ],
        "filename": "PM-Awas-Urban-Guidelines.pdf"
    },
    "PM-Fasal-Bima": {
        "urls": [
            "https://pmfby.gov.in/",
            "https://pmfby.gov.in/guidelines",
        ],
        "filename": "PM-Fasal-Bima-Guidelines.pdf"
    },
    "Atal-Pension": {
        "urls": [
            "https://pfrda.org.in/",
            "https://pfrda.org.in/en/pension-schemes/apy/",
        ],
        "filename": "APY-Guidelines.pdf"
    },
    "PM-SVANidhi": {
        "urls": [
            "https://pmsvanidhi.mohua.gov.in/",
        ],
        "filename": "PM-SVANidhi-Guidelines.pdf"
    },
    "Jal-Jeevan": {
        "urls": [
            "https://jaljeevan.nic.in/",
        ],
        "filename": "Jal-Jeevan-Guidelines.pdf"
    },
    "PM-POSHAN": {
        "urls": [
            "https://pmposhan.education.gov.in/",
        ],
        "filename": "PM-POSHAN-Guidelines.pdf"
    },
    "PMGSY": {
        "urls": [
            "https://pmgsy.nic.in/",
        ],
        "filename": "PMGSY-Guidelines.pdf"
    },
    "StandUp-India": {
        "urls": [
            "https://standupmitra.in/",
        ],
        "filename": "StandUp-India-Details.pdf"
    },
    "Skill-India-PMKVY": {
        "urls": [
            "https://pmkvyofficial.org/",
        ],
        "filename": "PMKVY-Guidelines.pdf"
    },
    "Jan-Dhan": {
        "urls": [
            "https://pmjdy.gov.in/",
        ],
        "filename": "Jan-Dhan-Scheme.pdf"
    },
    "Sukanya-Samriddhi": {
        "urls": [
            "https://nsiindia.gov.in/",
            "https://nsiindia.gov.in/schemes/sukanya-samriddhi-yojana/",
        ],
        "filename": "Sukanya-Samriddhi-Rules.pdf"
    },
    "Senior-Citizen-Savings": {
        "urls": [
            "https://nsiindia.gov.in/",
            "https://nsiindia.gov.in/schemes/senior-citizens-savings-scheme/",
        ],
        "filename": "Senior-Citizen-Savings-Rules.pdf"
    },
    "NPS": {
        "urls": [
            "https://pfrda.org.in/",
            "https://pfrda.org.in/national-pension-system/",
        ],
        "filename": "NPS-Guidelines.pdf"
    }
}

def extract_pdf_links(url):
    """Extract all PDF links from a webpage"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
                    'source': url
                })
        
        return pdf_links
    except Exception as e:
        print(f"    ⚠ Scraping error: {str(e)[:60]}")
        return []

def download_pdf(url, filename):
    """Download and verify PDF"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True, stream=True)
        response.raise_for_status()
        
        content = response.content
        
        # Verify PDF header
        if b'%PDF' not in content[:20]:
            return False
        
        # Save file
        filepath = os.path.join(SCHEMES_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        
        return True
        
    except Exception as e:
        return False

# Main process
print("\n" + "="*70)
print("SCHEME DOCUMENTS DOWNLOADER")
print("="*70 + "\n")

downloaded = {}
failed = {}

for scheme_name, config in SCHEMES_CONFIG.items():
    print(f"📌 {scheme_name}")
    
    filename = config['filename']
    found = False
    
    for url in config['urls']:
        if found:
            break
        
        print(f"  Scanning: {url}")
        pdf_links = extract_pdf_links(url)
        
        if pdf_links:
            print(f"    Found {len(pdf_links)} PDF(s), downloading...")
            
            for pdf_info in pdf_links:
                print(f"      → {pdf_info['text']}")
                
                if download_pdf(pdf_info['url'], filename):
                    filepath = os.path.join(SCHEMES_DIR, filename)
                    size = os.path.getsize(filepath) / 1024
                    print(f"      ✓ Saved {filename} ({size:.1f} KB)")
                    downloaded[scheme_name] = filename
                    found = True
                    break
                else:
                    print(f"      ✗ Not a valid PDF")
        
        time.sleep(0.5)
    
    if not found:
        failed[scheme_name] = config['urls']
        print(f"  ✗ Could not download")
    
    print()

# Summary
print("="*70)
print("SUMMARY")
print("="*70)
print(f"✓ Downloaded: {len(downloaded)}/{len(SCHEMES_CONFIG)}")
print(f"✗ Failed: {len(failed)}/{len(SCHEMES_CONFIG)}\n")

if downloaded:
    print("Downloaded schemes:")
    for name, file in sorted(downloaded.items()):
        path = os.path.join(SCHEMES_DIR, file)
        size = os.path.getsize(path) / (1024*1024)
        print(f"  ✓ {name}: {file} ({size:.2f} MB)")

if failed:
    print("\nFailed schemes (manual download required):")
    for name, urls in sorted(failed.items()):
        print(f"  ✗ {name}")
        for url in urls:
            print(f"     {url}")

# Save metadata
manifest = {
    "downloaded": len(downloaded),
    "failed": len(failed),
    "total": len(SCHEMES_CONFIG),
    "files": downloaded,
    "directory": SCHEMES_DIR,
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
}

with open(os.path.join(SCHEMES_DIR, "manifest.json"), 'w') as f:
    json.dump(manifest, f, indent=2)

print(f"\n✅ Manifest saved: {os.path.join(SCHEMES_DIR, 'manifest.json')}")
print(f"📁 Location: {SCHEMES_DIR}")
