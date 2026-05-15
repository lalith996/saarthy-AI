"""
Saarthi-AI — Automated Data Collection Pipeline
================================================
Scrapes government/legal PDFs from:
  1. RBI (rbi.org.in)               -- Master Circulars (confirmed working)
  2. Income Tax (incometax.gov.in)  -- Circulars via direct known PDF URLs
  3. Government Schemes             -- Known direct PDF URLs (PM-KISAN, MGNREGA etc.)

Then extracts and cleans text from all downloaded PDFs.

Usage:
    python scraper.py                    # run all sources
    python scraper.py --source rbi       # rbi only
    python scraper.py --source it        # income tax only
    python scraper.py --source scheme    # schemes only
    python scraper.py --extract-only     # skip download, only extract text
    python scraper.py --max 10           # limit PDFs per source
"""

import os
import re
import json
import time
import logging
import argparse
import hashlib
import requests
import pdfplumber

from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# -- Optional OCR fallback -----------------------------------------------------
try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# -- Logging -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("saarthi_scraper.log"),
    ],
)
log = logging.getLogger("saarthi")

# -- Directories ---------------------------------------------------------------
BASE_DIR  = Path("saarthi_data")
PDF_DIR   = BASE_DIR / "pdfs"
TEXT_DIR  = BASE_DIR / "text"
META_FILE = BASE_DIR / "metadata.json"
MANIFEST  = BASE_DIR / "manifest.txt"

for _d in [
    PDF_DIR / "rbi", PDF_DIR / "income_tax", PDF_DIR / "schemes",
    TEXT_DIR / "rbi", TEXT_DIR / "income_tax", TEXT_DIR / "schemes",
]:
    _d.mkdir(parents=True, exist_ok=True)

# -- Request settings ----------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 1.5   # seconds between requests
MAX_PDFS      = 30    # per source — overridden by --max flag


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def get(url, timeout=25, retries=3):
    """GET with retry, delay, and error handling. Returns Response or None."""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            log.warning(f"Attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt == retries:
                log.error(f"Giving up on: {url}")
                return None
            time.sleep(REQUEST_DELAY * attempt)
    return None


def slug(text, max_len=60):
    """Filesystem-safe slug from any string."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "_", text).strip("-_")
    return (text or "untitled")[:max_len]


def is_valid_pdf(content):
    """Check PDF magic bytes to confirm file is actually a PDF."""
    return len(content) > 4 and content[:4] == b"%PDF"


def download_pdf(url, dest_dir, filename):
    """
    Download a PDF to dest_dir/filename.
    Skips if file already exists.
    Validates magic bytes before saving.
    Returns Path on success, None on failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    if dest.exists():
        log.info(f"  [skip]  Already exists: {filename}")
        return dest

    resp = get(url)
    if resp is None:
        return None

    if not is_valid_pdf(resp.content):
        log.warning(f"  [skip]  Not a valid PDF: {url}")
        return None

    with open(dest, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) // 1024
    log.info(f"  [saved] {filename} ({size_kb} KB)")
    return dest


def load_metadata():
    """Load existing metadata JSON, or return empty list."""
    if META_FILE.exists():
        with open(META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_metadata(records):
    """Persist metadata list to JSON."""
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def make_record(source, doc_type, title, url, file_path):
    """Create a standardised metadata record dict."""
    return {
        "source":     source,
        "doc_type":   doc_type,
        "title":      title,
        "url":        url,
        "file":       str(file_path),
        "scraped_at": datetime.now().isoformat(),
        "status":     "downloaded",
        "text_file":  None,
        "char_count": 0,
    }


# ==============================================================================
# SOURCE 1 -- RBI MASTER CIRCULARS
# ==============================================================================

RBI_MASTER_URL = "https://www.rbi.org.in/Scripts/BS_ViewMasterCirculardetails.aspx"
RBI_STANDALONE = "https://www.rbi.org.in/Scripts/BS_ViewListofstandalonecirculars.aspx"
RBI_BASE       = "https://www.rbi.org.in"


def scrape_rbi():
    """
    Scrape RBI Master Circulars and Standalone Circulars.
    Both pages directly list PDF links (no JS rendering required).
    PDFs are hosted on rbidocs.rbi.org.in.
    """
    records = []
    dest_dir = PDF_DIR / "rbi"

    pages = [
        ("master_circular",     RBI_MASTER_URL),
        ("standalone_circular", RBI_STANDALONE),
    ]

    for doc_type, page_url in pages:
        log.info(f"\n[RBI] Fetching {doc_type}s from {page_url}")
        resp = get(page_url)
        if resp is None:
            continue

        soup      = BeautifulSoup(resp.text, "html.parser")
        collected = 0

        for a in soup.find_all("a", href=True):
            if collected >= MAX_PDFS:
                break

            href  = a["href"].strip()
            title = a.get_text(strip=True)

            # Strip trailing size annotations like "1614 kb"
            title = re.sub(r"\s*\d+\s*kb\s*$", "", title, flags=re.IGNORECASE).strip()

            # Fall back to parent row text if anchor text is empty
            if not title or len(title) < 5:
                row = a.find_parent("tr")
                if row:
                    title = row.get_text(" ", strip=True)[:80]

            # Only process PDF hrefs
            if ".pdf" not in href.lower():
                continue

            # Build absolute URL
            if href.startswith("http"):
                pdf_url = href
            elif href.startswith("//"):
                pdf_url = "http:" + href
            else:
                pdf_url = urljoin(RBI_BASE, href)

            fname    = f"rbi_{doc_type}_{slug(title)}.pdf"
            pdf_path = download_pdf(pdf_url, dest_dir, fname)
            if pdf_path:
                records.append(make_record("rbi", doc_type, title, pdf_url, pdf_path))
                collected += 1

        log.info(f"  Collected {collected} from {doc_type}")

    return records


# ==============================================================================
# SOURCE 2 -- INCOME TAX CIRCULARS
# ==============================================================================

# Confirmed direct PDF URLs from incometax.gov.in portal
IT_KNOWN_PDFS = [
    {
        "title":    "Circular No 6 of 2024 TDS TCS",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2024-04/Circular%20no%206%20of%202024%20on%20TDS%20TCS.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 1 of 2024",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2024-01/Circular_No_1_of_2024.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 4 of 2023 TDS on Salary",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2023-04/Circular-4-2023.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 3 of 2023",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2023-03/Circular_No_3_of_2023.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 1 of 2023",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2023-01/Circular_No_1_of_2023.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 24 of 2022",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-12/Circular_24_2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 23 of 2022",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-11/Circular_23_2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Refer Notification Income Tax",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-12/Refer%20Notification.pdf",
        "doc_type": "notification",
    },
    {
        "title":    "Circular No 6 of 2022 Relief TDS",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-04/Circular_No_6_of_2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 4 of 2022 TDS Salary",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-03/Circular-4-2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 2 of 2022",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-01/Circular_No_2_of_2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 1 of 2022",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-01/Circular_No_1_of_2022.pdf",
        "doc_type": "circular",
    },
]

# CBDT listing pages for dynamic discovery
CBDT_PAGES = [
    ("circular",     "https://incometaxindia.gov.in/communications/circular/circular2425.htm"),
    ("circular",     "https://incometaxindia.gov.in/communications/circular/circular2324.htm"),
    ("notification", "https://incometaxindia.gov.in/communications/notification/notification2425.htm"),
]
CBDT_BASE = "https://incometaxindia.gov.in"


def scrape_income_tax():
    """
    Collect Income Tax circulars and notifications.
    1. Downloads confirmed direct PDF URLs first.
    2. Scrapes CBDT listing pages for additional PDFs.
    """
    records  = []
    dest_dir = PDF_DIR / "income_tax"

    # Step 1: confirmed direct URLs
    log.info("\n[IT] Downloading confirmed IT circular PDFs...")
    for item in IT_KNOWN_PDFS[:MAX_PDFS]:
        fname    = f"it_{item['doc_type']}_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname)
        if pdf_path:
            records.append(make_record(
                "income_tax", item["doc_type"],
                item["title"], item["url"], pdf_path
            ))

    # Step 2: dynamic scraping of CBDT pages
    log.info("[IT] Scraping CBDT pages for additional PDFs...")
    seen_urls = {r["url"] for r in records}

    for doc_type, page_url in CBDT_PAGES:
        if len(records) >= MAX_PDFS:
            break
        resp = get(page_url)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if len(records) >= MAX_PDFS:
                break
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            pdf_url = urljoin(CBDT_BASE, href) if not href.startswith("http") else href
            if pdf_url in seen_urls:
                continue
            title    = a.get_text(strip=True) or Path(href).stem
            fname    = f"it_{doc_type}_{slug(title)}.pdf"
            pdf_path = download_pdf(pdf_url, dest_dir, fname)
            if pdf_path:
                records.append(make_record("income_tax", doc_type, title, pdf_url, pdf_path))
                seen_urls.add(pdf_url)

    log.info(f"  Total IT docs: {len(records)}")
    return records


# ==============================================================================
# SOURCE 3 -- GOVERNMENT SCHEME DOCUMENTS
# ==============================================================================

SCHEME_PDFS = [
    {
        "title":    "PM-KISAN Operational Guidelines English",
        "url":      "https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalGuidelines(English).pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "MGNREGA Operational Guidelines 4th Edition",
        "url":      "https://nrega.nic.in/Circular_Archive/archive/MGNREGA_Operational_Guidelines_4thEdition_English.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "Ayushman Bharat PMJAY Operational Guidelines",
        "url":      "https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "National Food Security Act 2013",
        "url":      "https://dfpd.gov.in/writereaddata/Portal/News/313_1_NFSA-2013-ENGLISH.pdf",
        "doc_type": "act_scheme",
    },
    {
        "title":    "Pradhan Mantri Awas Yojana Urban Guidelines",
        "url":      "https://pmay-urban.gov.in/uploads/guidelines/1495604987Guidelines.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "Atal Pension Yojana Guidelines",
        "url":      "https://www.pfrda.org.in/writereaddata/links/apy%20guidelines%20final7a80aa3a-f36c-4c83-b15f-7f4f0cff04f1.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "Pradhan Mantri Fasal Bima Yojana Guidelines",
        "url":      "https://pmfby.gov.in/pdf/PMFBY_Final_Guidelines.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "Digital India Programme Pocket Book",
        "url":      "https://www.meity.gov.in/writereaddata/files/di_pocket_book_final.pdf",
        "doc_type": "scheme_guidelines",
    },
]

INDIA_GOV_PAGES = [
    "https://www.india.gov.in/topics/social-welfare",
    "https://www.india.gov.in/topics/agriculture",
    "https://www.india.gov.in/topics/health-family-welfare",
]
INDIA_GOV_BASE = "https://www.india.gov.in"


def scrape_schemes():
    """
    Collect government scheme PDFs.
    1. Downloads known confirmed PDFs.
    2. Scrapes india.gov.in topic pages for additional PDFs.
    """
    records  = []
    dest_dir = PDF_DIR / "schemes"

    # Step 1: known scheme PDFs
    log.info("\n[Schemes] Downloading known scheme PDFs...")
    for item in SCHEME_PDFS[:MAX_PDFS]:
        fname    = f"scheme_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname)
        if pdf_path:
            records.append(make_record(
                "schemes", item["doc_type"],
                item["title"], item["url"], pdf_path
            ))

    # Step 2: dynamic scraping
    log.info("[Schemes] Scraping india.gov.in for additional PDFs...")
    seen_urls = {r["url"] for r in records}

    for page_url in INDIA_GOV_PAGES:
        if len(records) >= MAX_PDFS:
            break
        resp = get(page_url)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if len(records) >= MAX_PDFS:
                break
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            pdf_url = urljoin(INDIA_GOV_BASE, href) if not href.startswith("http") else href
            if pdf_url in seen_urls:
                continue
            title    = a.get_text(strip=True) or Path(href).stem
            fname    = f"scheme_india_{slug(title)}.pdf"
            pdf_path = download_pdf(pdf_url, dest_dir, fname)
            if pdf_path:
                records.append(make_record("schemes", "scheme_document", title, pdf_url, pdf_path))
                seen_urls.add(pdf_url)

    log.info(f"  Total scheme docs: {len(records)}")
    return records


# ==============================================================================
# PDF TEXT EXTRACTION
# ==============================================================================

def extract_text_pdfplumber(pdf_path):
    """Extract text using pdfplumber -- best for digital/born-PDF files."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def extract_text_ocr(pdf_path):
    """OCR fallback for scanned/image-only PDFs using pytesseract."""
    if not OCR_AVAILABLE:
        log.warning("  OCR not available. Install: pip install pdf2image pytesseract")
        return ""
    images = convert_from_path(str(pdf_path), dpi=200)
    pages  = [pytesseract.image_to_string(img, lang="eng") for img in images]
    return "\n\n".join(pages)


def clean_text(text):
    """
    Clean raw extracted PDF text:
    - Remove form-feed / page-break characters
    - Collapse 3+ consecutive blank lines to 2
    - Drop lines that are only digits, spaces, or dash characters (page artifacts)
    """
    text  = text.replace("\x0c", "\n")
    text  = re.sub(r"\n{3,}", "\n\n", text)
    lines = [
        line for line in text.splitlines()
        if not re.fullmatch(r"[\d\s\-\u2013\u2014|]+", line.strip())
    ]
    return "\n".join(lines).strip()


def extract_text_from_pdf(pdf_path):
    """
    Extract and clean text from a PDF file.
    Primary  : pdfplumber (handles digital PDFs well)
    Fallback : pytesseract OCR (for scanned/image PDFs)
    """
    text = ""

    try:
        text = extract_text_pdfplumber(Path(pdf_path))
    except Exception as e:
        log.warning(f"  pdfplumber failed for {Path(pdf_path).name}: {e}")

    if len(text.strip()) < 100:
        log.info(f"  Low pdfplumber output ({len(text.strip())} chars) -- trying OCR")
        try:
            text = extract_text_ocr(Path(pdf_path))
        except Exception as e:
            log.warning(f"  OCR also failed: {e}")

    return clean_text(text)


def extract_all_texts(records):
    """
    Run text extraction across all records.
    Saves .txt files mirroring the PDF directory structure under TEXT_DIR.
    Updates each record in-place with text_file, char_count, status.
    """
    log.info(f"\n[Extract] Processing {len(records)} records...")
    extracted = skipped = failed = 0

    for rec in records:
        pdf_path = Path(rec["file"])

        if not pdf_path.exists():
            log.warning(f"  PDF missing: {pdf_path}")
            rec["status"] = "missing"
            failed += 1
            continue

        # Mirror PDF subdirectory structure under TEXT_DIR
        rel      = pdf_path.relative_to(PDF_DIR)
        txt_path = TEXT_DIR / rel.parent / (rel.stem + ".txt")
        txt_path.parent.mkdir(parents=True, exist_ok=True)

        if txt_path.exists():
            log.info(f"  [skip]  {txt_path.name}")
            rec["text_file"] = str(txt_path)
            rec["status"]    = "extracted"
            skipped += 1
            continue

        log.info(f"  Extracting: {pdf_path.name}")
        text = extract_text_from_pdf(pdf_path)

        if len(text.strip()) < 50:
            log.warning(f"  Low content in {pdf_path.name} -- may be image-only")
            rec["status"] = "low_content"
            failed += 1
            continue

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        rec["text_file"]  = str(txt_path)
        rec["char_count"] = len(text)
        rec["status"]     = "extracted"
        log.info(f"  Saved: {txt_path.name} ({len(text):,} chars)")
        extracted += 1

    log.info(
        f"\n[Extract] Done -- extracted: {extracted}, "
        f"skipped: {skipped}, failed: {failed}"
    )
    return records


# ==============================================================================
# MANIFEST
# ==============================================================================

def write_manifest(records):
    """Write a human-readable summary of all collected documents."""
    by_source = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)

    lines = [
        "=" * 72,
        "SAARTHI-AI -- DATA COLLECTION MANIFEST",
        f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total     : {len(records)} documents",
        "=" * 72,
    ]

    for source, recs in by_source.items():
        n_extracted = sum(1 for r in recs if r.get("status") == "extracted")
        lines += [
            "",
            f"{'─' * 72}",
            f"  SOURCE  : {source.upper()}",
            f"  Docs    : {len(recs)}   Extracted: {n_extracted}",
            f"{'─' * 72}",
        ]
        for r in recs:
            status = r.get("status", "pending")
            chars  = r.get("char_count", 0)
            title  = r["title"][:50]
            lines.append(
                f"  [{status:<12}]  {r['doc_type']:<22}  {chars:>9,} ch  {title}"
            )

    lines += [
        "",
        "=" * 72,
        f"EXTRACTED : {sum(1 for r in records if r.get('status') == 'extracted')} / {len(records)}",
        f"DATA DIR  : {BASE_DIR.resolve()}",
        "=" * 72,
    ]

    content = "\n".join(lines)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write(content)
    print(content)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    global MAX_PDFS

    parser = argparse.ArgumentParser(
        description="Saarthi-AI Government Document Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source", choices=["rbi", "it", "scheme", "all"],
        default="all", help="Source to scrape (default: all)"
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Skip downloading, only run text extraction on existing PDFs"
    )
    parser.add_argument(
        "--max", type=int, default=30,
        help="Max PDFs per source (default: 30)"
    )
    args     = parser.parse_args()
    MAX_PDFS = args.max

    records = load_metadata()

    if not args.extract_only:
        new_records   = []
        existing_urls = {r["url"] for r in records}

        if args.source in ("rbi", "all"):
            for r in scrape_rbi():
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        if args.source in ("it", "all"):
            for r in scrape_income_tax():
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        if args.source in ("scheme", "all"):
            for r in scrape_schemes():
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        records.extend(new_records)
        save_metadata(records)
        log.info(f"\n[Main] Total after scraping: {len(records)} records")

    records = extract_all_texts(records)
    save_metadata(records)
    write_manifest(records)
    log.info(f"\n[Main] Done. Data at: {BASE_DIR.resolve()}")


if __name__ == "__main__":
    main()
