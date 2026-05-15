#!/usr/bin/env python3
"""
Search Wayback Machine for scheme documents
"""
import requests
import json
import os
import time

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Schemes and their official websites
SCHEMES_WAYBACK = {
    "PM-Fasal-Bima": "pmfby.gov.in",
    "Atal-Pension": "pfrda.org.in",
    "PM-SVANidhi": "pmsvanidhi.mohua.gov.in",
    "Jal-Jeevan": "jaljeevan.nic.in",
    "PM-POSHAN": "pmposhan.education.gov.in",
    "PMGSY": "pmgsy.nic.in",
    "StandUp-India": "standupmitra.in",
    "Skill-India-PMKVY": "pmkvyofficial.org",
    "Jan-Dhan": "pmjdy.gov.in",
    "Sukanya-Samriddhi": "nsiindia.gov.in",
    "Senior-Citizen-Savings": "nsiindia.gov.in",
    "NPS": "pfrda.org.in"
}

def search_wayback_for_pdfs(domain):
    """Search Wayback Machine for PDF files from a domain"""
    try:
        # Search for all PDF snapshots
        url = f"https://web.archive.org/web/*/{ domain }/*/*.pdf"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            lines = response.text.split('\n')
            pdfs = []
            for line in lines:
                if '.pdf' in line.lower():
                    # Extract URL
                    parts = line.strip().split()
                    if parts:
                        pdfs.append(parts[0])
            
            return pdfs[:5]  # Return first 5 PDFs
        
        return []
    except Exception as e:
        return []

def download_from_wayback(url, filename):
    """Download PDF from Wayback Machine snapshot"""
    try:
        # Construct Wayback Machine URL
        if 'web.archive.org' not in url:
            wayback_url = f"https://web.archive.org/web/20231201000000*/{url}"
        else:
            wayback_url = url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        }
        
        response = requests.get(wayback_url, timeout=20, headers=headers, allow_redirects=True)
        response.raise_for_status()
        
        content = response.content
        
        if len(content) > 1000 and b'%PDF' in content[:20]:
            filepath = os.path.join(SCHEMES_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(content)
            return True
        
        return False
    except Exception as e:
        return False

print("\n" + "="*70)
print("WAYBACK MACHINE SCHEME SEARCH")
print("="*70 + "\n")

downloaded = {}

for scheme, domain in SCHEMES_WAYBACK.items():
    print(f"📌 {scheme}")
    print(f"  Domain: {domain}")
    
    filename = f"{scheme}-Guidelines.pdf"
    
    # Skip if already downloaded
    if os.path.exists(os.path.join(SCHEMES_DIR, filename)):
        print(f"  ✓ Already downloaded")
        print()
        continue
    
    # Search Wayback Machine
    pdfs = search_wayback_for_pdfs(domain)
    
    if pdfs:
        print(f"  Found {len(pdfs)} PDFs in Wayback")
        for pdf_url in pdfs:
            print(f"    Trying: {pdf_url}")
            if download_from_wayback(pdf_url, filename):
                filepath = os.path.join(SCHEMES_DIR, filename)
                size = os.path.getsize(filepath) / (1024*1024)
                print(f"    ✓ Downloaded ({size:.2f} MB)")
                downloaded[scheme] = filename
                break
    else:
        print(f"  ✗ No PDFs found in Wayback")
    
    print()
    time.sleep(1)

# Summary
print("="*70)
print(f"Wayback Machine downloads: {len(downloaded)}")
if downloaded:
    for scheme, file in sorted(downloaded.items()):
        print(f"  ✓ {scheme}")

all_pdfs = [f for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
print(f"\nTotal PDFs in schemes: {len(all_pdfs)}")
