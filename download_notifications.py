import re
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://www.incometaxindia.gov.in"
API = f"{BASE}/o/search/v1.0/search"
ATTRS = {
    "search.empty.search": True,
    "search.experiences.blueprint.external.reference.code": "CIRCULAR_NOTIFICATION_BP_ERC",
    "search.experiences.structure_key": "NOTIFICATION_KEY",
}
PAGE_SIZE = 200
OUT_DIR = Path("incometax_notifications")
PDF_DIR = OUT_DIR / "pdfs"
META_FILE = OUT_DIR / "metadata.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update(
    {
        "Accept-Language": "en-US",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
)


def safe_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value[:120] or "notification"


def get_cf(item: dict, name: str) -> dict:
    for cf in item.get("embedded", {}).get("contentFields", []):
        if cf.get("name") == name:
            return cf.get("contentFieldValue", {})
    return {}


def post_page(page: int, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            response = session.post(
                API,
                params={"nestedFields": "embedded", "page": page, "pageSize": PAGE_SIZE},
                json={"attributes": ATTRS},
                timeout=45,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)
    return {}


def download_file(url: str, target_path: Path) -> tuple[bool, str, str | None]:
    if target_path.exists() and target_path.stat().st_size > 0:
        return True, "exists", str(target_path)

    try:
        response = session.get(url, timeout=45)
        if response.status_code != 200:
            return False, f"http_{response.status_code}", None

        content = response.content
        if content[:4] == b"%PDF":
            target_path.write_bytes(content)
            return True, "downloaded", str(target_path)

        alt_path = target_path.with_suffix(".bin")
        alt_path.write_bytes(content)
        return True, "downloaded_non_pdf", str(alt_path)
    except Exception as ex:
        return False, f"error_{type(ex).__name__}", None


# Discover total pages from first request
first = post_page(1)
total_records = first.get("totalCount", 0)
last_page = first.get("lastPage", 1)
print(f"Found total notification records: {total_records} across {last_page} pages", flush=True)

records = []
seen_urls = set()
skipped_pages = []
processed_records = 0
ok = 0
fail = 0

# Process page 1 + remaining pages in one loop
for page in range(1, last_page + 1):
    try:
        page_data = first if page == 1 else post_page(page)
    except Exception:
        skipped_pages.append(page)
        print(f"Skipped page {page}/{last_page} after retries", flush=True)
        continue

    items = page_data.get("items", [])
    processed_records += len(items)

    for item in items:
        report_doc = get_cf(item, "reportFile").get("document") or {}
        content_url = report_doc.get("contentUrl")
        if not content_url:
            continue

        full_url = urljoin(BASE, content_url)
        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)
        record_idx = len(records) + 1
        number_part = safe_name(get_cf(item, "circularNotificationNumber").get("data") or "")
        title_part = safe_name(item.get("title") or "")
        filename = f"{record_idx:05d}_{number_part}_{title_part}"[:200] + ".pdf"
        file_path = PDF_DIR / filename

        success, status, saved_path = download_file(full_url, file_path)
        if success:
            ok += 1
        else:
            fail += 1

        records.append(
            {
                "title": item.get("title", ""),
                "notification_number": get_cf(item, "circularNotificationNumber").get("data"),
                "notification_date": get_cf(item, "circularNotificationDate").get("data"),
                "content_url": full_url,
                "item_url": item.get("itemURL", ""),
                "status": status,
                "file_path": saved_path,
            }
        )

    print(
        f"Page {page}/{last_page} | records_seen={processed_records} | unique_files={len(records)} | ok={ok} fail={fail}",
        flush=True,
    )

summary = {
    "source_url": "https://www.incometaxindia.gov.in/notifications",
    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "total_records_from_api": total_records,
    "records_seen_from_processed_pages": processed_records,
    "pages_total": last_page,
    "pages_skipped": skipped_pages,
    "unique_download_targets": len(records),
    "download_ok": ok,
    "download_failed": fail,
    "output_dir": str(OUT_DIR.resolve()),
    "records": records,
}
META_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")

print("DONE", flush=True)
print(f"ok {ok} fail {fail}", flush=True)
print(f"pages_skipped {len(skipped_pages)}", flush=True)
print(f"meta {META_FILE.resolve()}", flush=True)
