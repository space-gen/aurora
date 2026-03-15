"""
pull_new_urls.py
================
Stage 2 — Daily Solar Data Crawler

Fetches sunspot and magnetogram JPG URLs from the previous day.
Each record includes a unique ID (sp-N, mg-N) and serial number.
"""

import os
import re
import sys
import json
import logging
import datetime
import argparse
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

SOURCE_MAP = {
    "sunspot": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_Ic_1k.jpg", "prefix": "sp"},
    "magnetogram": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_M_1k.jpg", "prefix": "mg"},
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

def _get_last_serial_and_id(task_type):
    """Find the highest serial number and ID from existing HF and local data."""
    # Start at 0
    max_serial = 0
    
    # 1. Check local file if it exists
    local_file = DATA_PROCESSING_DIR / f"{task_type}.json"
    if local_file.exists():
        try:
            data = json.loads(local_file.read_text())
            if data:
                max_serial = max(max_serial, max(item.get("serial_number", 0) for item in data))
        except: pass

    # 2. Check HF
    token = os.environ.get("HF_TOKEN")
    if token:
        try:
            from datasets import load_dataset
            repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
            # Check both splits as data migrates from tasks to train
            for split in ["tasks", "train"]:
                try:
                    ds = load_dataset(repo_id, token=token, split=split, trust_remote_code=True)
                    if len(ds) > 0:
                        max_serial = max(max_serial, max(ds["serial_number"]))
                except: pass
        except: pass
        
    return max_serial

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
    except: pass
    return results

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    existing_urls = _get_existing_urls()
    
    # Use environment variable for task filtering
    task_filter = os.environ.get("TASK_TYPE")
    
    # Always pull exactly "yesterday"
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    log.info(f"Crawling JSOC for yesterday: {yesterday}")

    tasks_by_type = defaultdict(list)
    
    # Filter SOURCE_MAP if TASK_TYPE is provided
    active_sources = {task_filter: SOURCE_MAP[task_filter]} if task_filter and task_filter in SOURCE_MAP else SOURCE_MAP

    for task_type, cfg in active_sources.items():
        log.info(f"Processing {task_type}...")
        
        # Get starting serial number
        current_serial = _get_last_serial_and_id(task_type)
        prefix = cfg["prefix"]
        
        urls = _fetch_day_urls(task_type, yesterday)
        
        for url in urls:
            current_serial += 1
            tasks_by_type[task_type].append({
                "id": f"{prefix}-{current_serial}",
                "serial_number": current_serial,
                "url": url,
                "task_type": task_type,
                "user_label": None,
                "locations": [],
                "metadata": {
                    "source": "JSOC_HMI_JPG",
                    "captured_at": yesterday.isoformat()
                }
            })

    # Write files
    for task_type, tasks in tasks_by_type.items():
        if not tasks: continue
        file_path = DATA_PROCESSING_DIR / f"{task_type}.json"
        
        # Append to existing or create new
        existing_data = []
        if file_path.exists():
            try: existing_data = json.loads(file_path.read_text())
            except: pass
        
        existing_data.extend(tasks)
        file_path.write_text(json.dumps(existing_data, indent=2))
        log.info(f"Saved {len(tasks)} new tasks to {file_path.name}")

if __name__ == "__main__":
    main()
