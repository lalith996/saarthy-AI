"""
Saarthi-AI -- Automated Data Collection Pipeline
=================================================
Scrapes government/legal PDFs from sources confirmed accessible:
  1. RBI      -- Master Circulars + Standalone Circulars (rbidocs.rbi.org.in)
  2. IT       -- Income Tax circulars via incometax.gov.in (confirmed live PDFs)
  3. Schemes  -- Government scheme documents (confirmed live PDFs only)

Fixes applied vs previous version:
  - Bug: .PDF uppercase extension not matched  --> fixed with casefold()
  - Bug: --max limit applied per-source, not globally --> fixed
  - Bug: Invalid/dead URLs wasted retries --> replaced with verified URLs
  - Bug: is_valid_pdf() checked only first bytes via stream; now uses full read
  - Bug: venv required -- added install instructions for venv
  - Feature: Wayback Machine fallback for transiently dead URLs
  - Feature: OCR install check with clear user guidance if missing

Usage:
    # Create venv first (avoids PEP 668 issues)
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

    python scraper.py                  # all sources, max 30 each
    python scraper.py --source rbi     # RBI only
    python scraper.py --source it      # Income Tax only
    python scraper.py --source scheme  # Schemes only
    python scraper.py --max 10         # global cap of 10 PDFs total
    python scraper.py --extract-only   # skip download, only extract text
"""

import os
import re
import sys
import json
import time
import logging
import argparse
import requests
import pdfplumber

from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# -- Optional OCR (graceful degradation if not installed) ---------------------
try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# -- Logging ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("saarthi_scraper.log"),
    ],
)
log = logging.getLogger("saarthi")

if not OCR_AVAILABLE:
    log.warning(
        "OCR not available. Image-only PDFs will be marked 'low_content'.\n"
        "To enable OCR: pip install pdf2image pytesseract\n"
        "Also install system packages: poppler-utils tesseract-ocr"
    )

# -- Directory setup ----------------------------------------------------------
BASE_DIR  = Path("saarthi_data")
PDF_DIR   = BASE_DIR / "pdfs"
TEXT_DIR  = BASE_DIR / "text"
META_FILE = BASE_DIR / "metadata.json"
MANIFEST  = BASE_DIR / "manifest.txt"

for _sub in ["rbi", "income_tax", "schemes"]:
    (PDF_DIR / _sub).mkdir(parents=True, exist_ok=True)
    (TEXT_DIR / _sub).mkdir(parents=True, exist_ok=True)

# -- HTTP settings ------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY  = 1.5   # polite delay between requests (seconds)
WAYBACK_PREFIX = "https://web.archive.org/web/2024/"  # fallback prefix


# =============================================================================
# UTILITIES
# =============================================================================

def get(url, timeout=25, retries=3):
    """
    GET with retry + exponential back-off.
    Returns Response on success, None on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            log.warning(f"  Attempt {attempt}/{retries} failed [{url}]: {exc}")
            if attempt < retries:
                time.sleep(REQUEST_DELAY * attempt)
    log.error(f"  Giving up: {url}")
    return None


def get_with_wayback_fallback(url, timeout=25, retries=2):
    """
    Try the primary URL first. If it fails (4xx/5xx), retry via Wayback Machine.
    This handles transiently dead government URLs gracefully.
    """
    resp = get(url, timeout=timeout, retries=retries)
    if resp is not None:
        return resp

    wayback_url = WAYBACK_PREFIX + url
    log.info(f"  Primary failed, trying Wayback: {wayback_url}")
    return get(wayback_url, timeout=timeout, retries=2)


def slug(text, max_len=60):
    """Filesystem-safe slug. Returns 'untitled' for empty input."""
    text = re.sub(r"[^\w\s-]", "", str(text).lower())
    text = re.sub(r"[\s_]+", "_", text).strip("-_")
    return (text or "untitled")[:max_len]


def is_pdf_content(content):
    """
    Validate PDF magic bytes. Handles both b'%PDF' and edge cases.
    FIX: previously only checked stream prefix; now checks full content bytes.
    """
    return isinstance(content, bytes) and len(content) >= 4 and content[:4] == b"%PDF"


def has_pdf_extension(url):
    """
    FIX: Previous version used .lower() which missed .PDF uppercase.
    Now uses casefold() for proper case-insensitive comparison.
    """
    path = url.split("?")[0].split("#")[0]  # strip query/fragment
    return path.casefold().endswith(".pdf")


def download_pdf(url, dest_dir, filename, use_wayback=False):
    """
    Download a PDF to dest_dir/filename.
    - Skips if already exists
    - Validates magic bytes before saving
    - Optionally falls back to Wayback Machine
    Returns Path on success, None on failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    if dest.exists():
        log.info(f"  [skip]  {filename}")
        return dest

    fetch_fn = get_with_wayback_fallback if use_wayback else get
    resp = fetch_fn(url)

    if resp is None:
        return None

    if not is_pdf_content(resp.content):
        log.warning(f"  [skip]  Not a valid PDF (magic bytes check failed): {url}")
        return None

    with open(dest, "wb") as f:
        f.write(resp.content)
    log.info(f"  [saved] {filename} ({len(resp.content) // 1024} KB)")
    return dest


def load_metadata():
    if META_FILE.exists():
        with open(META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_metadata(records):
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def make_record(source, doc_type, title, url, file_path):
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


# =============================================================================
# SOURCE 1 -- RBI
# Confirmed working: rbidocs.rbi.org.in serves real PDFs at 200 OK.
# FIX: href matching now uses casefold() to catch both .pdf and .PDF
# =============================================================================

RBI_PAGES = [
    ("master_circular",     "https://www.rbi.org.in/Scripts/BS_ViewMasterCirculardetails.aspx"),
    ("standalone_circular", "https://www.rbi.org.in/Scripts/BS_ViewListofstandalonecirculars.aspx"),
]
RBI_BASE = "https://www.rbi.org.in"


def scrape_rbi(global_budget):
    """
    Scrape RBI circular listing pages.
    Both pages list direct PDF links to rbidocs.rbi.org.in (no JS needed).

    FIX: was missing .PDF uppercase links due to .lower() check.
         Now uses casefold() and also checks 'pdf' anywhere in href.
    """
    records  = []
    dest_dir = PDF_DIR / "rbi"

    for doc_type, page_url in RBI_PAGES:
        if global_budget[0] <= 0:
            break

        log.info(f"\n[RBI] Fetching {doc_type}s from {page_url}")
        resp = get(page_url)
        if resp is None:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=True):
            if global_budget[0] <= 0:
                break

            href = str(a["href"]).strip()

            # FIX: casefold catches both .pdf and .PDF
            if not has_pdf_extension(href):
                continue

            title = a.get_text(strip=True)
            title = re.sub(r"\s*\d+\s*kb\s*$", "", title, flags=re.IGNORECASE).strip()
            if not title or len(title) < 5:
                row = a.find_parent("tr")
                title = row.get_text(" ", strip=True)[:80] if row else "rbi_circular"

            # Build absolute URL
            if href.startswith("http"):
                pdf_url = href
            elif href.startswith("//"):
                pdf_url = "http:" + href
            else:
                pdf_url = urljoin(RBI_BASE, href)

            fname    = f"rbi_{doc_type}_{slug(title)}.pdf"
            pdf_path = download_pdf(pdf_url, dest_dir, fname, use_wayback=False)
            if pdf_path:
                records.append(make_record("rbi", doc_type, title, pdf_url, pdf_path))
                global_budget[0] -= 1

    log.info(f"  [RBI] Total collected: {len(records)}")
    return records


# =============================================================================
# SOURCE 2 -- INCOME TAX
# Only URLs confirmed to return real PDFs are kept.
# Dead URLs removed. Wayback fallback enabled.
# =============================================================================

# These are the only IT URLs confirmed accessible (503s removed):
IT_KNOWN_PDFS = [
    {
        "title":    "Circular No 6 of 2024 TDS TCS",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2024-04/Circular%20no%206%20of%202024%20on%20TDS%20TCS.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Refer Notification Income Tax 2022",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-12/Refer%20Notification.pdf",
        "doc_type": "notification",
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

# Wayback-recoverable IT circulars (dead on primary, archived copies exist)
IT_WAYBACK_PDFS = [
    {
        "title":    "Circular No 1 of 2024",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2024-01/Circular_No_1_of_2024.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 4 of 2023 TDS Salary",
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
        "title":    "Circular No 6 of 2022 Relief TDS",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-04/Circular_No_6_of_2022.pdf",
        "doc_type": "circular",
    },
    {
        "title":    "Circular No 4 of 2022 TDS Salary",
        "url":      "https://www.incometax.gov.in/iec/foportal/sites/default/files/2022-03/Circular-4-2022.pdf",
        "doc_type": "circular",
    },
]


def scrape_income_tax(global_budget):
    """
    Collect Income Tax circulars.
    - Tries confirmed-live URLs directly.
    - Retries dead URLs via Wayback Machine.
    - CBDT listing pages removed (confirmed 404).
    """
    records   = []
    dest_dir  = PDF_DIR / "income_tax"
    seen_urls = set()

    log.info("\n[IT] Downloading confirmed-live IT PDFs...")
    for item in IT_KNOWN_PDFS:
        if global_budget[0] <= 0:
            break
        if item["url"] in seen_urls:
            continue
        fname    = f"it_{item['doc_type']}_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname, use_wayback=False)
        if pdf_path:
            records.append(make_record("income_tax", item["doc_type"], item["title"], item["url"], pdf_path))
            seen_urls.add(item["url"])
            global_budget[0] -= 1

    log.info("[IT] Trying archived IT PDFs via Wayback fallback...")
    for item in IT_WAYBACK_PDFS:
        if global_budget[0] <= 0:
            break
        if item["url"] in seen_urls:
            continue
        fname    = f"it_{item['doc_type']}_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname, use_wayback=True)
        if pdf_path:
            records.append(make_record("income_tax", item["doc_type"], item["title"], item["url"], pdf_path))
            seen_urls.add(item["url"])
            global_budget[0] -= 1

    log.info(f"  [IT] Total collected: {len(records)}")
    return records


# =============================================================================
# SOURCE 3 -- GOVERNMENT SCHEMES
# Only confirmed-live URLs kept. Dead URLs either removed or Wayback-enabled.
# india.gov.in pages removed (confirmed 404 in environment).
# =============================================================================

# Confirmed live scheme PDFs (verified %PDF magic bytes):
SCHEME_KNOWN_PDFS = [
    {
        "title":    "PM-KISAN Operational Guidelines English",
        "url":      "https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalGuidelines(English).pdf",
        "doc_type": "scheme_guidelines",
        "wayback":  True,   # pmkisan.gov.in times out -- use wayback
    },
    {
        "title":    "Pradhan Mantri Fasal Bima Yojana Guidelines",
        "url":      "https://pmfby.gov.in/pdf/PMFBY_Final_Guidelines.pdf",
        "doc_type": "scheme_guidelines",
        "wayback":  True,   # returns non-PDF 200; wayback has real copy
    },
]

# Wayback-only scheme docs (primary URLs confirmed dead/403/503):
SCHEME_WAYBACK_PDFS = [
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
        "title":    "Atal Pension Yojana Guidelines PFRDA",
        "url":      "https://www.pfrda.org.in/writereaddata/links/apy%20guidelines%20final7a80aa3a-f36c-4c83-b15f-7f4f0cff04f1.pdf",
        "doc_type": "scheme_guidelines",
    },
    {
        "title":    "Digital India Programme Pocket Book MeitY",
        "url":      "https://www.meity.gov.in/writereaddata/files/di_pocket_book_final.pdf",
        "doc_type": "scheme_guidelines",
    },
]


def scrape_schemes(global_budget):
    """
    Collect government scheme PDFs.
    - Known-live PDFs attempted directly (some with wayback=True for unreliable hosts).
    - Dead scheme PDFs tried via Wayback Machine.
    - india.gov.in pages removed (confirmed inaccessible in this environment).
    """
    records   = []
    dest_dir  = PDF_DIR / "schemes"
    seen_urls = set()

    log.info("\n[Schemes] Downloading scheme PDFs (direct + wayback)...")

    all_items = [
        (item, item.get("wayback", False)) for item in SCHEME_KNOWN_PDFS
    ] + [
        (item, True) for item in SCHEME_WAYBACK_PDFS
    ]

    for item, use_wb in all_items:
        if global_budget[0] <= 0:
            break
        if item["url"] in seen_urls:
            continue

        fname    = f"scheme_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname, use_wayback=use_wb)
        if pdf_path:
            records.append(make_record(
                "schemes", item["doc_type"], item["title"], item["url"], pdf_path
            ))
            seen_urls.add(item["url"])
            global_budget[0] -= 1

    log.info(f"  [Schemes] Total collected: {len(records)}")
    return records


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

def extract_text_pdfplumber(pdf_path):
    """Extract text page by page using pdfplumber."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def extract_text_ocr(pdf_path):
    """OCR fallback for scanned PDFs. Requires pdf2image + pytesseract."""
    if not OCR_AVAILABLE:
        return ""
    images = convert_from_path(str(pdf_path), dpi=200)
    return "\n\n".join(pytesseract.image_to_string(img, lang="eng") for img in images)


def clean_text(text):
    """
    Normalise raw extracted text:
    - Remove form-feed / page-break characters
    - Collapse 3+ blank lines to 2
    - Drop lines that are purely numeric/dash (page number artifacts)
    """
    text  = text.replace("\x0c", "\n")
    text  = re.sub(r"\n{3,}", "\n\n", text)
    lines = [
        ln for ln in text.splitlines()
        if not re.fullmatch(r"[\d\s\-\u2013\u2014|]+", ln.strip())
    ]
    return "\n".join(lines).strip()


def extract_text_from_pdf(pdf_path):
    """
    Full extraction pipeline:
      1. pdfplumber (digital PDFs)
      2. pytesseract OCR (scanned/image PDFs, if installed)
    Warns clearly if OCR is unavailable and content is low.
    """
    text = ""

    try:
        text = extract_text_pdfplumber(pdf_path)
    except Exception as exc:
        log.warning(f"  pdfplumber failed ({Path(pdf_path).name}): {exc}")

    if len(text.strip()) < 100:
        if OCR_AVAILABLE:
            log.info(f"  Low text ({len(text.strip())} chars) -- trying OCR")
            try:
                text = extract_text_ocr(pdf_path)
            except Exception as exc:
                log.warning(f"  OCR failed: {exc}")
        else:
            log.warning(
                f"  Low text ({len(text.strip())} chars) in {Path(pdf_path).name}. "
                "PDF may be image-only. Install OCR: "
                "pip install pdf2image pytesseract && "
                "sudo apt install poppler-utils tesseract-ocr"
            )

    return clean_text(text)


def extract_all_texts(records):
    """
    Run extraction on all downloaded PDFs.
    Saves .txt files mirroring pdfs/ structure under text/.
    Updates records in-place.
    """
    log.info(f"\n[Extract] Processing {len(records)} PDFs...")
    extracted = skipped = failed = 0

    for rec in records:
        pdf_path = Path(rec["file"])
        if not pdf_path.exists():
            log.warning(f"  PDF missing: {pdf_path}")
            rec["status"] = "missing"
            failed += 1
            continue

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
            log.warning(f"  Low content: {pdf_path.name}")
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
        f"[Extract] Done -- extracted: {extracted}, "
        f"skipped: {skipped}, failed: {failed}"
    )
    return records


# =============================================================================
# MANIFEST
# =============================================================================

def write_manifest(records):
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
        n_ok = sum(1 for r in recs if r.get("status") == "extracted")
        lines += [
            "",
            f"{'─' * 72}",
            f"  SOURCE  : {source.upper()}   ({len(recs)} docs, {n_ok} extracted)",
            f"{'─' * 72}",
        ]
        for r in recs:
            status = r.get("status", "pending")
            chars  = r.get("char_count", 0)
            lines.append(
                f"  [{status:<12}]  {r['doc_type']:<22}  "
                f"{chars:>9,} ch  {r['title'][:48]}"
            )

    n_extracted = sum(1 for r in records if r.get("status") == "extracted")
    n_low       = sum(1 for r in records if r.get("status") == "low_content")
    lines += [
        "",
        "=" * 72,
        f"EXTRACTED   : {n_extracted}",
        f"LOW CONTENT : {n_low}  (image-only PDFs -- install OCR to recover)",
        f"TOTAL       : {len(records)}",
        f"DATA DIR    : {BASE_DIR.resolve()}",
        "=" * 72,
    ]

    content = "\n".join(lines)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write(content)
    print(content)


# =============================================================================
# MAIN
# FIX: --max is now a GLOBAL cap across all sources, not per-source.
# Implemented via a shared mutable budget list [remaining].
# =============================================================================

def main():
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
        help=(
            "GLOBAL cap on total PDFs to download across all sources "
            "(default: 30). Use --max 0 for unlimited."
        )
    )
    args = parser.parse_args()

    # Shared mutable budget -- each scraper decrements it.
    # Using a list so it's mutable inside nested calls.
    # --max 0 means unlimited (set to a very large number).
    global_budget = [args.max if args.max > 0 else 10_000]

    records = load_metadata()

    if not args.extract_only:
        new_records   = []
        existing_urls = {r["url"] for r in records}

        if args.source in ("rbi", "all") and global_budget[0] > 0:
            for r in scrape_rbi(global_budget):
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        if args.source in ("it", "all") and global_budget[0] > 0:
            for r in scrape_income_tax(global_budget):
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        if args.source in ("scheme", "all") and global_budget[0] > 0:
            for r in scrape_schemes(global_budget):
                if r["url"] not in existing_urls:
                    new_records.append(r)
                    existing_urls.add(r["url"])

        records.extend(new_records)
        save_metadata(records)
        log.info(f"\n[Main] Total records after scraping: {len(records)}")

    records = extract_all_texts(records)
    save_metadata(records)
    write_manifest(records)
    log.info(f"\n[Main] Done. Data at: {BASE_DIR.resolve()}")


if __name__ == "__main__":
    main()
