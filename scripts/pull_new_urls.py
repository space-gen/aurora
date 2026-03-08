"""
pull_new_urls.py
================
Stage 2 — High-Volume Solar Data Crawler (JSOC)

Fetches solar observation URLs (JPG and JP2) from JSOC archives.
Groups them into a single JSON file per task type.
Ensures only one resolution per timestamp is pulled.
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

# Verified JSOC Map
SOURCE_MAP = {
    "sunspot": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_Ic_"},
    "magnetogram": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_M_"},
    "active_region": {"path": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/171/", "filter": ".jp2"},
    "coronal_hole": {"path": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/193/", "filter": ".jp2"},
    "prominence": {"path": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/304/", "filter": ".jp2"},
    "solar_flare": {"path": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/94/", "filter": ".jp2"},
    "cme": {"path": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/211/", "filter": ".jp2"}, # Placeholder for CME using AIA 211
}

LINK_REGEX = re.compile(r'href="([^"]+\.(?:jpg|jp2))"')

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

def _get_timestamp_key(filename, task_type):
    """Extract a unique timestamp key from the filename to prevent resolution duplicates."""
    parts = filename.split('_')
    if task_type in ["sunspot", "magnetogram"]:
        # Format: 20240101_000000_Ic_1k.jpg -> key: 20240101_000000_Ic
        # We include the 'Ic' or 'M' to separate sunspots from magnetograms in same dir
        return "_".join(parts[:3])
    else:
        # Format: 2024_01_01__00_00_09_351__SDO_AIA_AIA_171.jp2
        return "_".join(parts[:8])

def _fetch_day_urls(task_type, date_obj):
    y, m, d = date_obj.strftime("%Y"), date_obj.strftime("%m"), date_obj.strftime("%d")
    cfg = SOURCE_MAP.get(task_type)
    if not cfg: return []
    
    base_url = cfg["path"].format(Y=y, M=m, D=d)
    file_filter = cfg["filter"]
    
    unique_tasks = {} # key: timestamp_key, value: (priority, filename)
    
    try:
        response = requests.get(base_url, timeout=10)
        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)
            for match in matches:
                if file_filter in match:
                    ts_key = _get_timestamp_key(match, task_type)
                    
                    # Priority: 1k > 4k > others (to keep it manageable but standard)
                    priority = 99
                    if "1k" in match: priority = 1
                    elif "4k" in match: priority = 2
                    elif "512" in match: priority = 3
                    
                    if ts_key not in unique_tasks or priority < unique_tasks[ts_key][0]:
                        unique_tasks[ts_key] = (priority, match)
    except Exception:
        pass
        
    return [base_url + val[1] for val in unique_tasks.values()]

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
        if not tasks:
            continue
            
        file_path = DATA_PROCESSING_DIR / f"{task_type}.json"
        
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