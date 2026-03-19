"""
pull_new_urls.py
================
Stage 2 — Daily Solar Data Crawler

Fetches sunspot and magnetogram JPG URLs from the previous day.
Writes output in compressed JSONL format.
"""

import os
import re
import sys
import json
import logging
import datetime
import argparse
from pathlib import Path
import requests
from collections import defaultdict

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

SOURCE_MAP = {
    "sunspot": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_Ic_1k.jpg", "prefix": "sp"},
    "magnetogram": {"path": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/", "filter": "_M_1k.jpg", "prefix": "mg"},
}

LINK_REGEX = re.compile(r'href="([^"]+\.jpg)"')

def _get_existing_urls():
    token = os.environ.get("HF_TOKEN")
    all_urls = set()
    
    # Check local JSONL files first
    for p in REPO_ROOT.glob("**/*.jsonl"):
        if "data_processing" in str(p): continue
        try:
            with open(p, "r") as f:
                for line in f:
                    if not line.strip(): continue
                    all_urls.add(json.loads(line)["url"])
        except: pass

    if not token: return all_urls
    
    try:
        from datasets import load_dataset
        for task_type in SOURCE_MAP.keys():
            repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
            try:
                ds = load_dataset(repo_id, token=token, split="train")
                all_urls.update(ds["url"])
            except: continue
    except ImportError: pass
    return all_urls

def _get_last_serial(task_type):
    max_serial = 0
    # Search all local jsonl files for the highest serial for this task type
    for p in REPO_ROOT.glob("**/*.jsonl"):
        try:
            with open(p, "r") as f:
                for line in f:
                    if not line.strip(): continue
                    item = json.loads(line)
                    if item.get("task_type") == task_type:
                        max_serial = max(max_serial, item.get("serial_number", 0))
        except: pass

    token = os.environ.get("HF_TOKEN")
    if token:
        try:
            from datasets import load_dataset
            repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
            for split in ["tasks", "train"]:
                try:
                    ds = load_dataset(repo_id, token=token, split=split)
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    args = parser.parse_args()

    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    existing_urls = _get_existing_urls()
    target_date = datetime.date.today() - datetime.timedelta(days=args.days_back)
    log.info(f"Target date: {target_date}")

    for task_type, cfg in SOURCE_MAP.items():
        log.info(f"Processing {task_type}...")
        current_serial = _get_last_serial(task_type)
        prefix = cfg["prefix"]
        urls = _fetch_day_urls(task_type, target_date)
        
        file_path = DATA_PROCESSING_DIR / f"{task_type}.jsonl"
        new_count = 0
        
        # Open in write mode ('w') to keep only one day of data in the repository
        with open(file_path, "w", encoding="utf-8") as f:
            for url in urls:
                if url in existing_urls: continue
                current_serial += 1
                new_count += 1
                record = {
                    "id": f"{prefix}-{current_serial}",
                    "serial_number": current_serial,
                    "url": url,
                    "task_type": task_type,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "annotations": [],
                    "metadata": {
                        "source": "JSOC_HMI_JPG",
                        "captured_at": target_date.isoformat()
                    }
                }
                # Minified JSONL line
                f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        
        if new_count > 0:
            log.info(f"Saved {new_count} new tasks to {file_path.name}")

if __name__ == "__main__":
    main()
