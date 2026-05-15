#!/usr/bin/env python3
"""
Search alternative government repositories for scheme documents
"""
import os
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import time

SCHEMES_DIR = "/Users/lalithmachavarapu/Desktop/NLP/saarthi_data/pdfs/schemes"
os.makedirs(SCHEMES_DIR, exist_ok=True)

# Alternative repositories to search
REPOSITORIES = {
    "Ministry of Finance": [
        "https://finmin.gov.in/",
        "https://indiabudget.gov.in/",
    ],
    "PIB Press": [
        "https://pib.gov.in/",
    ],
    "Government e-Gazette": [
        "https://egazette.nic.in/",
    ],
    "Ministry of Rural Development": [
        "https://www.rural.gov.in/",
    ],
    "Ministry of Labour": [
        "https://labour.gov.in/",
    ],
    "Ministry of Housing": [
        "https://mohua.gov.in/",
    ],
    "Ministry of Education": [
        "https://education.gov.in/",
    ]
}

# Specific search terms for each scheme
SCHEME_KEYWORDS = {
    "PM-Fasal-Bima": ["Pradhan Mantri Fasal Bima", "PMFBY", "crop insurance"],
    "Atal-Pension": ["Atal Pension Yojana", "APY", "pension scheme"],
    "PM-SVANidhi": ["PM SVANidhi", "micro credit", "street vendor"],
    "Jal-Jeevan": ["Jal Jeevan Mission", "water supply", "rural water"],
    "PM-POSHAN": ["PM POSHAN", "mid day meal", "school nutrition"],
    "PMGSY": ["Pradhan Mantri Gram Sadak", "rural roads", "PMGSY"],
    "StandUp-India": ["Stand Up India", "business loan", "scheduled caste"],
    "Skill-India-PMKVY": ["PMKVY", "skill development", "vocational training"],
    "Jan-Dhan": ["Pradhan Mantri Jan Dhan", "bank account", "financial inclusion"],
    "Sukanya-Samriddhi": ["Sukanya Samriddhi Yojana", "girl child", "savings scheme"],
    "Senior-Citizen-Savings": ["Senior Citizen Savings Scheme", "SCSS", "senior citizen"],
    "NPS": ["National Pension System", "NPS", "pension"]
}

def search_repository(repo_url, keywords):
    """Search repository for documents"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(repo_url, timeout=15, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        results = []
        # Look for PDF links and relevant text
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # Check if link contains keywords or is a PDF
            if any(kw.lower() in text for kw in keywords) or '.pdf' in href.lower():
                if '.pdf' in href.lower():
                    results.append({
                        'url': urljoin(repo_url, href),
                        'text': text[:60]
                    })
        
        return results
    except Exception as e:
        return []

def download_pdf(url, filename):
    """Download PDF"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True)
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
print("SEARCHING GOVERNMENT REPOSITORIES")
print("="*70 + "\n")

downloaded = {}

# Check which schemes still need to be downloaded
existing = [f.replace('-Guidelines.pdf', '') for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
missing_schemes = {k: v for k, v in SCHEME_KEYWORDS.items() if k not in existing}

if not missing_schemes:
    print("✓ All schemes already downloaded!")
else:
    for scheme, keywords in list(missing_schemes.items())[:6]:  # Try first 6
        print(f"📌 {scheme}")
        print(f"  Keywords: {', '.join(keywords)}")
        
        filename = f"{scheme}-Guidelines.pdf"
        found = False
        
        # Search through repositories
        for repo_name, repo_urls in list(REPOSITORIES.items())[:3]:
            if found:
                break
            
            for repo_url in repo_urls:
                if found:
                    break
                
                print(f"  Searching {repo_name}: {repo_url}")
                results = search_repository(repo_url, keywords)
                
                if results:
                    print(f"    Found {len(results)} PDF(s)")
                    for result in results[:2]:
                        print(f"      Trying: {result['text']}")
                        if download_pdf(result['url'], filename):
                            filepath = os.path.join(SCHEMES_DIR, filename)
                            size = os.path.getsize(filepath) / (1024*1024)
                            print(f"      ✓ Downloaded ({size:.2f} MB)")
                            downloaded[scheme] = filename
                            found = True
                            break
                
                time.sleep(0.5)
        
        if not found:
            print(f"  ✗ Not found in repositories")
        
        print()

all_pdfs = [f for f in os.listdir(SCHEMES_DIR) if f.endswith('.pdf')]
print(f"📊 Total PDFs in schemes: {len(all_pdfs)}")
