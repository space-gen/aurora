"""
pull_new_urls.py
================
Stage 2 — High-Volume Solar Data Crawler (JSOC Synoptic JPGs)

Fetches daily-updating JPG URLs for all task types from the JSOC synoptic
archive. These are standard JPGs suitable for web embedding.
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

# JSOC Synoptic JPG Patterns
# HMI: hmi.ic_720s, hmi.m_720s
# AIA: aia.lev1_euv_12s (171, 193, 211, 304, 94)
SOURCE_MAP = {
    "sunspot": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_Ic_1k.jpg"},
    "magnetogram": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_M_1k.jpg"},
    "active_region": {"path": "http://jsoc.stanford.edu/data/aia/synoptic/{Y}/{M}/{D}/H0000/", "filter": "_0171.jpg"},
    "coronal_hole": {"path": "http://jsoc.stanford.edu/data/aia/synoptic/{Y}/{M}/{D}/H0000/", "filter": "_0193.jpg"},
    "prominence": {"path": "http://jsoc.stanford.edu/data/aia/synoptic/{Y}/{M}/{D}/H0000/", "filter": "_0304.jpg"},
    "solar_flare": {"path": "http://jsoc.stanford.edu/data/aia/synoptic/{Y}/{M}/{D}/H0000/", "filter": "_0094.jpg"},
    "cme": {"path": "http://jsoc.stanford.edu/data/aia/synoptic/{Y}/{M}/{D}/H0000/", "filter": "_0211.jpg"},
}

LINK_REGEX = re.compile(r'href="([^"]+\.jpg)"')

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

def _fetch_day_urls(task_type, date_obj):
    y, m, d = date_obj.strftime("%Y"), date_obj.strftime("%m"), date_obj.strftime("%d")
    cfg = SOURCE_MAP.get(task_type)
    if not cfg: return []
    
    url = cfg["path"].format(Y=y, M=m, D=d)
    file_filter = cfg["filter"]
    
    results = []
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)
            for match in matches:
                if file_filter in match:
                    results.append(url + match)
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
    start_date = datetime.date.today() - datetime.timedelta(days=days_to_pull)
    
    all_dates = [start_date + datetime.timedelta(days=i) for i in range(days_to_pull + 1)]
    log.info(f"Crawling JSOC JPG Archive: {len(all_dates)} days from {start_date}")

    tasks_by_type = defaultdict(list)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for task_type in SOURCE_MAP.keys():
            log.info(f"Processing {task_type}...")
            futures = {executor.submit(_fetch_day_urls, task_type, dt): dt for dt in all_dates}
            
            for future in as_completed(futures):
                urls = future.result()
                for url in urls:
                    if url not in existing_urls:
                        tasks_by_type[task_type].append({
                            "url": url,
                            "task_type": task_type,
                            "ml_prediction": None,
                            "confidence": None,
                            "metadata": {"source": "JSOC_SYNOPTIC_JPG", "date": datetime.datetime.now(datetime.UTC).isoformat()}
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
