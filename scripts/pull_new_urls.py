"""
pull_new_urls.py
================
Stage 2 — High-Volume Solar Data Crawler (JSOC)

Fetches solar observation URLs from JSOC archives and groups them 
into a single JSON file per task type for scalability.
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
MAX_WORKERS = int(os.environ.get("SOLARHUB_FETCH_WORKERS", "20"))
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

SOURCE_MAP = {
    "sunspot": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/",
    "magnetogram": "http://jsoc.stanford.edu/data/hmi/mag_images/{Y}/{M}/{D}/",
    "active_region": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/171/",
    "coronal_hole": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/193/",
    "prominence": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/304/",
    "solar_flare": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/94/",
}

LINK_REGEX = re.compile(r'href="([^"]+\.jpg)"')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_existing_urls():
    token = os.environ.get("HF_TOKEN")
    if not token:
        return set()
    
    try:
        from datasets import load_dataset
    except ImportError:
        return set()

    all_urls = set()
    for task_type in SOURCE_MAP.keys():
        repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
        try:
            ds = load_dataset(repo_id, token=token, split="train", trust_remote_code=True)
            all_urls.update(ds["url"])
        except Exception:
            continue
    return all_urls

def _fetch_day_urls(task_type, date_obj):
    y, m, d = date_obj.strftime("%Y"), date_obj.strftime("%m"), date_obj.strftime("%d")
    base_url = SOURCE_MAP[task_type].format(Y=y, M=m, D=d)
    urls = []
    try:
        response = requests.get(base_url, timeout=10)
        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)
            for match in matches:
                if "_1k.jpg" in match or "171.jpg" in match:
                    urls.append(base_url + match)
    except Exception:
        pass
    return urls

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    existing_urls = _get_existing_urls()
    
    days_to_pull = BULK_DAYS if BULK_DAYS > 0 else LOOKBACK_DAYS
    start_date = datetime.date.today() - datetime.timedelta(days=days_to_pull)
    all_dates = [start_date + datetime.timedelta(days=i) for i in range(days_to_pull + 1)]
    
    log.info(f"Crawling {len(all_dates)} days from {start_date}")

    tasks_by_type = defaultdict(list)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for task_type in SOURCE_MAP.keys():
            log.info(f"Processing {task_type}...")
            futures = {executor.submit(_fetch_day_urls, task_type, dt): dt for dt in all_dates}
            
            for future in as_completed(futures):
                day_urls = future.result()
                for url in day_urls:
                    if url not in existing_urls:
                        tasks_by_type[task_type].append({
                            "url": url,
                            "task_type": task_type,
                            "ml_prediction": None,
                            "confidence": None,
                            "metadata": {"source": "JSOC", "date": datetime.datetime.now(datetime.UTC).isoformat()}
                        })
                        existing_urls.add(url)

    # Write one file per task type
    for task_type, tasks in tasks_by_type.items():
        file_path = DATA_PROCESSING_DIR / f"{task_type}.json"
        
        # Load existing local tasks if file exists to append
        current_data = []
        if file_path.exists():
            try:
                current_data = json.loads(file_path.read_text())
            except Exception:
                current_data = []
        
        current_data.extend(tasks)
        file_path.write_text(json.dumps(current_data, indent=2))
        log.info(f"Saved {len(tasks)} new tasks to {file_path.name} (Total: {len(current_data)})")

if __name__ == "__main__":
    main()