"""
Saarthi-AI -- Automated Data Collection Pipeline
=================================================
Sources (all confirmed accessible in your environment):
  1. RBI      -- Master Circulars + Standalone Circulars
  2. IT       -- Income Tax circulars (2 confirmed live URLs only)
  3. Schemes  -- PM-KISAN (1 confirmed live URL only)

Key design:
  - Skip-once: URLs already in metadata.json are NEVER re-attempted,
    not even to check. No re-fetching listing pages for already-known URLs.
  - Dead URLs removed: All permanently-dead IT/scheme URLs stripped out.
    Wayback fallback removed (confirmed non-functional for these sources).
  - On re-runs, only genuinely new URLs from RBI listing page are processed.

Usage:
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

    python scraper.py                  # all sources
    python scraper.py --source rbi     # RBI only
    python scraper.py --source it      # IT only
    python scraper.py --source scheme  # schemes only
    python scraper.py --extract-only   # only run text extraction
    python scraper.py --max 10         # global cap of 10 new PDFs
"""

import re
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

# -- Optional OCR -------------------------------------------------------------
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
        "OCR not available -- image-only PDFs will be marked 'low_content'.\n"
        "To enable: pip install pdf2image pytesseract\n"
        "System deps: sudo apt install poppler-utils tesseract-ocr  (or brew install)"
    )

# -- Directories --------------------------------------------------------------
BASE_DIR  = Path("saarthi_data")
PDF_DIR   = BASE_DIR / "pdfs"
TEXT_DIR  = BASE_DIR / "text"
META_FILE = BASE_DIR / "metadata.json"
MANIFEST  = BASE_DIR / "manifest.txt"

for _sub in ["rbi", "income_tax", "schemes"]:
    (PDF_DIR / _sub).mkdir(parents=True, exist_ok=True)
    (TEXT_DIR / _sub).mkdir(parents=True, exist_ok=True)

# -- HTTP ---------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY = 1.5


# =============================================================================
# UTILITIES
# =============================================================================

def get(url, timeout=25, retries=3):
    """GET with retry + exponential back-off. Returns Response or None."""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=HEADERS, timeout=timeout,
                                allow_redirects=True)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            log.warning(f"  Attempt {attempt}/{retries} failed [{url}]: {exc}")
            if attempt < retries:
                time.sleep(REQUEST_DELAY * attempt)
    log.error(f"  Giving up: {url}")
    return None


def slug(text, max_len=60):
    text = re.sub(r"[^\w\s-]", "", str(text).lower())
    text = re.sub(r"[\s_]+", "_", text).strip("-_")
    return (text or "untitled")[:max_len]


def is_pdf_content(content):
    return isinstance(content, bytes) and len(content) >= 4 and content[:4] == b"%PDF"


def has_pdf_extension(url):
    """Case-insensitive .pdf check, ignoring query strings."""
    return url.split("?")[0].split("#")[0].casefold().endswith(".pdf")


def download_pdf(url, dest_dir, filename):
    """
    Download a PDF to dest_dir/filename.
    Caller is responsible for checking existing_urls before calling this.
    Returns Path on success, None on failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    # File may already exist from a previous run even if URL wasn't in metadata
    if dest.exists():
        log.info(f"  [skip]  File exists: {filename}")
        return dest

    resp = get(url)
    if resp is None:
        return None

    if not is_pdf_content(resp.content):
        log.warning(f"  [skip]  Not a valid PDF: {url}")
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
# Listing pages are fetched once. Only URLs NOT in existing_urls are downloaded.
# =============================================================================

RBI_PAGES = [
    ("master_circular",     "https://www.rbi.org.in/Scripts/BS_ViewMasterCirculardetails.aspx"),
    ("standalone_circular", "https://www.rbi.org.in/Scripts/BS_ViewListofstandalonecirculars.aspx"),
]
RBI_BASE = "https://www.rbi.org.in"


def scrape_rbi(existing_urls, global_budget):
    """
    Fetch RBI listing pages and download only NEW PDFs not in existing_urls.
    If all PDFs on the page are already known, the page is still fetched once
    but zero downloads happen -- this is unavoidable for dynamic listing pages.
    """
    records  = []
    dest_dir = PDF_DIR / "rbi"

    for doc_type, page_url in RBI_PAGES:
        if global_budget[0] <= 0:
            break

        resp = get(page_url)
        if resp is None:
            log.warning(f"  [RBI] Could not fetch listing page: {page_url}")
            continue

        soup      = BeautifulSoup(resp.text, "html.parser")
        new_found = 0

        for a in soup.find_all("a", href=True):
            if global_budget[0] <= 0:
                break

            href = str(a["href"]).strip()
            if not has_pdf_extension(href):
                continue

            # Build absolute URL
            if href.startswith("http"):
                pdf_url = href
            elif href.startswith("//"):
                pdf_url = "http:" + href
            else:
                pdf_url = urljoin(RBI_BASE, href)

            # SKIP-ONCE: if URL already recorded, skip without any log noise
            if pdf_url in existing_urls:
                continue

            # New URL -- process it
            title = a.get_text(strip=True)
            title = re.sub(r"\s*\d+\s*kb\s*$", "", title, flags=re.IGNORECASE).strip()
            if not title or len(title) < 5:
                row = a.find_parent("tr")
                title = row.get_text(" ", strip=True)[:80] if row else "rbi_doc"

            fname    = f"rbi_{doc_type}_{slug(title)}.pdf"
            pdf_path = download_pdf(pdf_url, dest_dir, fname)
            if pdf_path:
                rec = make_record("rbi", doc_type, title, pdf_url, pdf_path)
                records.append(rec)
                existing_urls.add(pdf_url)
                global_budget[0] -= 1
                new_found += 1

        log.info(f"  [RBI] {doc_type}: {new_found} new PDFs downloaded")

    return records


# =============================================================================
# SOURCE 2 -- INCOME TAX
# Only 2 URLs confirmed live in your environment. All others removed.
# =============================================================================

IT_LIVE_PDFS = [
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
]


def scrape_income_tax(existing_urls, global_budget):
    """
    Download the 2 confirmed-live IT PDFs.
    All other IT URLs (Circular_No_1_of_2024, Circular-4-2023, etc.)
    confirmed permanently dead in your environment -- removed entirely.
    """
    records  = []
    dest_dir = PDF_DIR / "income_tax"

    log.info("\n[IT] Checking confirmed-live IT PDFs...")
    for item in IT_LIVE_PDFS:
        if global_budget[0] <= 0:
            break
        if item["url"] in existing_urls:
            continue  # already downloaded -- silent skip

        fname    = f"it_{item['doc_type']}_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname)
        if pdf_path:
            rec = make_record("income_tax", item["doc_type"],
                              item["title"], item["url"], pdf_path)
            records.append(rec)
            existing_urls.add(item["url"])
            global_budget[0] -= 1

    new = len(records)
    log.info(f"  [IT] {new} new PDFs downloaded (0 retried, 0 dead URLs attempted)")
    return records


# =============================================================================
# SOURCE 3 -- GOVERNMENT SCHEMES
# Only PM-KISAN confirmed live. All other scheme URLs removed.
# =============================================================================

SCHEME_LIVE_PDFS = [
    {
        "title":    "PM-KISAN Operational Guidelines English",
        "url":      "https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalGuidelines(English).pdf",
        "doc_type": "scheme_guidelines",
    },
]


def scrape_schemes(existing_urls, global_budget):
    """
    Download confirmed-live scheme PDFs.
    Dead URLs removed (MGNREGA, PMJAY, NFSA, PMAY, PFRDA, MeitY,
    india.gov.in pages -- all confirmed permanently inaccessible).
    """
    records  = []
    dest_dir = PDF_DIR / "schemes"

    log.info("\n[Schemes] Checking confirmed-live scheme PDFs...")
    for item in SCHEME_LIVE_PDFS:
        if global_budget[0] <= 0:
            break
        if item["url"] in existing_urls:
            continue

        fname    = f"scheme_{slug(item['title'])}.pdf"
        pdf_path = download_pdf(item["url"], dest_dir, fname)
        if pdf_path:
            rec = make_record("schemes", item["doc_type"],
                              item["title"], item["url"], pdf_path)
            records.append(rec)
            existing_urls.add(item["url"])
            global_budget[0] -= 1

    new = len(records)
    log.info(f"  [Schemes] {new} new PDFs downloaded")
    return records


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

def extract_text_pdfplumber(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n\n".join(pages)


def extract_text_ocr(pdf_path):
    if not OCR_AVAILABLE:
        return ""
    images = convert_from_path(str(pdf_path), dpi=200)
    return "\n\n".join(pytesseract.image_to_string(img, lang="eng") for img in images)


def clean_text(text):
    text  = text.replace("\x0c", "\n")
    text  = re.sub(r"\n{3,}", "\n\n", text)
    lines = [
        ln for ln in text.splitlines()
        if not re.fullmatch(r"[\d\s\-\u2013\u2014|]+", ln.strip())
    ]
    return "\n".join(lines).strip()


def extract_text_from_pdf(pdf_path):
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
                f"  Low text ({len(text.strip())} chars) in "
                f"{Path(pdf_path).name}. PDF may be image-only.\n"
                "  Install OCR: pip install pdf2image pytesseract && "
                "sudo apt install poppler-utils tesseract-ocr"
            )
    return clean_text(text)


def extract_all_texts(records):
    """
    Extract text from PDFs that don't yet have a .txt file.
    Already-extracted records are silently skipped (no log spam).
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

        rel      = pdf_path.relative_to(PDF_DIR)
        txt_path = TEXT_DIR / rel.parent / (rel.stem + ".txt")
        txt_path.parent.mkdir(parents=True, exist_ok=True)

        # Silent skip -- no log line for already-extracted files
        if txt_path.exists():
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
        f"already done (silent): {skipped}, failed: {failed}"
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
        f"LOW CONTENT : {n_low}  (image-only -- install OCR to recover)",
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
        help="Skip downloading, only run text extraction"
    )
    parser.add_argument(
        "--max", type=int, default=50,
        help="Global cap on NEW PDFs to download across all sources (default: 50, 0=unlimited)"
    )
    args = parser.parse_args()

    records       = load_metadata()
    existing_urls = {r["url"] for r in records}  # URLs already in corpus
    global_budget = [args.max if args.max > 0 else 10_000]

    if not args.extract_only:
        new_records = []

        if args.source in ("rbi", "all") and global_budget[0] > 0:
            new_records.extend(scrape_rbi(existing_urls, global_budget))

        if args.source in ("it", "all") and global_budget[0] > 0:
            new_records.extend(scrape_income_tax(existing_urls, global_budget))

        if args.source in ("scheme", "all") and global_budget[0] > 0:
            new_records.extend(scrape_schemes(existing_urls, global_budget))

        if new_records:
            records.extend(new_records)
            save_metadata(records)
            log.info(f"\n[Main] Added {len(new_records)} new records "
                     f"(total: {len(records)})")
        else:
            log.info("\n[Main] No new PDFs found -- corpus is up to date")

    records = extract_all_texts(records)
    save_metadata(records)
    write_manifest(records)
    log.info(f"\n[Main] Done. Data at: {BASE_DIR.resolve()}")


if __name__ == "__main__":
    main()
