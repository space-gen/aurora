"""
pull_new_urls.py
================
Stage 2 — High-Volume Solar Data Crawler (NASA SDO Browse)

Fetches daily-updating JPG URLs for all task types from the official 
NASA SDO browse image archive. These are standard JPGs suitable for web.
"""

import os
import re
import sys
import json
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from collections import defaultdict

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"

LOOKBACK_DAYS = int(os.environ.get("SOLARHUB_LOOKBACK_DAYS", "3"))
BULK_DAYS = int(os.environ.get("SOLARHUB_BULK_DAYS", "0"))
MAX_WORKERS = int(os.environ.get("SOLARHUB_FETCH_WORKERS", "15"))
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# NASA SDO Browse Patterns
# Channels: 0171, 0193, 0304, 0094, 0211, HMIIC (Continuum), HMIB (Magnetogram)
SOURCE_MAP = {
    "sunspot": {"filter": "_1024_HMIIC.jpg"},
    "magnetogram": {"filter": "_1024_HMIB.jpg"},
    "active_region": {"filter": "_1024_0171.jpg"},
    "coronal_hole": {"filter": "_1024_0193.jpg"},
    "prominence": {"filter": "_1024_0304.jpg"},
    "solar_flare": {"filter": "_1024_0094.jpg"},
    "cme": {"filter": "_1024_0211.jpg"},
}

LINK_REGEX = re.compile(r'href="([^"]+\.jpg)"')
BASE_BROWSE_URL = "https://sdo.gsfc.nasa.gov/assets/img/browse/{Y}/{M}/{D}/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_existing_urls():
    token = os.environ.get("HF_TOKEN")
    if not token: return set()
    try:
        from datasets import load_dataset
        all_urls = set()
        for task_type in SOURCE_MAP.keys():
            repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
            try:
                ds = load_dataset(repo_id, token=token, split="train", trust_remote_code=True)
                all_urls.update(ds["url"])
            except Exception: continue
        return all_urls
    except ImportError: return set()

def _fetch_day_urls(date_obj):
    y, m, d = date_obj.strftime("%Y"), date_obj.strftime("%m"), date_obj.strftime("%d")
    url = BASE_BROWSE_URL.format(Y=y, M=m, D=d)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    results = defaultdict(list)
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)
            for match in matches:
                for task_type, cfg in SOURCE_MAP.items():
                    if cfg["filter"] in match:
                        results[task_type].append(url + match)
    except Exception:
        pass
    return results

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    existing_urls = _get_existing_urls()
    
    days_to_pull = BULK_DAYS if BULK_DAYS > 0 else LOOKBACK_DAYS
    # SDO browse usually has a slight delay, so we start from yesterday
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=days_to_pull)
    
    all_dates = [start_date + datetime.timedelta(days=i) for i in range(days_to_pull + 1)]
    log.info(f"Crawling NASA SDO Browse: {len(all_dates)} days from {start_date}")

    tasks_by_type = defaultdict(list)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_day_urls, dt): dt for dt in all_dates}
        
        for future in as_completed(futures):
            day_results = future.result()
            for task_type, urls in day_results.items():
                for url in urls:
                    if url not in existing_urls:
                        tasks_by_type[task_type].append({
                            "url": url,
                            "task_type": task_type,
                            "ml_prediction": None,
                            "confidence": None,
                            "metadata": {"source": "NASA_SDO_BROWSE", "date": datetime.datetime.now(datetime.UTC).isoformat()}
                        })
                        existing_urls.add(url)

    # Write grouped files
    for task_type, tasks in tasks_by_type.items():
        if not tasks: continue
        file_path = DATA_PROCESSING_DIR / f"{task_type}.json"
        
        current_data = []
        if file_path.exists():
            try:
                current_data = json.loads(file_path.read_text())
            except Exception: current_data = []
        
        current_data.extend(tasks)
        file_path.write_text(json.dumps(current_data, indent=2))
        log.info(f"Saved {len(tasks)} new JPG tasks to {file_path.name}")

if __name__ == "__main__":
    main()
