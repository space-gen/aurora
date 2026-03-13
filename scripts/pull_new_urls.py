"""
pull_new_urls.py
================
Stage 2 — High-Volume Solar Data Crawler (Yesterday's Data)

Fetches sunspot and magnetogram JPG URLs from the previous day from JSOC.
ML fields are omitted as they are now managed directly on HuggingFace.
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
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# SDO is down for other channels, only HMI is reliable for now.
SOURCE_MAP = {
    "sunspot": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_Ic_1k.jpg"},
    "magnetogram": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_M_1k.jpg"},
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
    cfg = SOURCE_MAP[task_type]
    url = cfg["path"].format(Y=y, M=m, D=d)
    
    results = []
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)
            for match in matches:
                if cfg["filter"] in match:
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
    
    # Check if we should do initial 3-month pull or just daily
    is_initial = os.environ.get("SOLARHUB_INITIAL_SETUP", "false").lower() == "true"
    
    if is_initial:
        days_to_pull = 90
        log.info("Initial setup mode: Pulling 3 months of data.")
    else:
        days_to_pull = 1
        log.info("Daily mode: Pulling yesterday's data.")

    start_date = datetime.date.today() - datetime.timedelta(days=days_to_pull)
    all_dates = [start_date + datetime.timedelta(days=i) for i in range(days_to_pull)]
    
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
                            "user_comments": [],
                            "metadata": {"source": "JSOC_HMI_JPG", "date": datetime.datetime.now(datetime.UTC).isoformat()}
                        })
                        existing_urls.add(url)

    # Write grouped files
    for task_type, tasks in tasks_by_type.items():
        if not tasks: continue
        file_path = DATA_PROCESSING_DIR / f"{task_type}.json"
        
        # Fresh daily files, no appending needed as Stage 1 moves them
        file_path.write_text(json.dumps(tasks, indent=2))
        log.info(f"Saved {len(tasks)} new tasks to {file_path.name}")

if __name__ == "__main__":
    main()
