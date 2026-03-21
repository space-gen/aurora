"""
pull_new_urls.py
================
Stage 2 — Daily Solar Data Crawler

Fetches solar imagery for multiple task types (Sunspots, Flares, CMEs, etc.).
Prioritizes unique global IDs and removes serial numbers.
Records are created with ISO 8601 timestamps.
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

# Source Configurations
# {Y} = YYYY, {M} = MM, {D} = DD, {ymd} = YYYYMMDD
SOURCE_MAP = {
    "sunspot": {
        "url_pattern": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/{ymd}_000000_Ic_1k.jpg",
        "prefix": "sp"
    },
    "magnetogram": {
        "url_pattern": "http://jsoc.stanford.edu/data/hmi/images/{Y}/{M}/{D}/{ymd}_000000_M_1k.jpg",
        "prefix": "mg"
    },
    "solar_flare": {
        "url_pattern": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/0094/AIA.{ymd}_000000.0094.jpg",
        "prefix": "fl"
    },
    "coronal_hole": {
        "url_pattern": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/0193/AIA.{ymd}_000000.0193.jpg",
        "prefix": "ch"
    },
    "active_region": {
        "url_pattern": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/0171/AIA.{ymd}_000000.0171.jpg",
        "prefix": "ar"
    },
    "prominence": {
        "url_pattern": "http://jsoc.stanford.edu/data/aia/images/{Y}/{M}/{D}/0304/AIA.{ymd}_000000.0304.jpg",
        "prefix": "pr"
    },
    "cme": {
        # SOHO LASCO C3
        "url_pattern": "https://soho.nascom.nasa.gov/data/REPROCESSING/Completed/{Y}/c3/{ymd}/{ymd}_0000_c3_1024.jpg",
        "prefix": "cme"
    }
}

def _get_last_id_numeric(task_type):
    """Find the highest numeric part of the ID from existing local data."""
    max_id = 0
    prefix = SOURCE_MAP[task_type]["prefix"]
    
    for p in REPO_ROOT.glob("**/*.jsonl"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    item = json.loads(line)
                    if item.get("task_type") == task_type:
                        id_str = item.get("id", "")
                        if id_str.startswith(f"{prefix}-"):
                            try:
                                num = int(id_str.split("-")[1])
                                max_id = max(max_id, num)
                            except (ValueError, IndexError):
                                pass
        except Exception:
            pass
    return max_id

def _check_url_exists(url):
    """Head request to verify URL exists."""
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            return True
        log.warning(f"URL check failed: {url} (Status: {r.status_code})")
        return False
    except Exception as e:
        log.warning(f"URL check error for {url}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    args = parser.parse_args()

    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    target_date = datetime.date.today() - datetime.timedelta(days=args.days_back)
    log.info(f"Target date: {target_date}")

    for task_type, cfg in SOURCE_MAP.items():
        log.info(f"Processing {task_type}...")
        
        last_num = _get_last_id_numeric(task_type)
        prefix = cfg["prefix"]
        
        # Format URL for target date
        url = cfg["url_pattern"].format(
            Y=target_date.strftime("%Y"),
            M=target_date.strftime("%m"),
            D=target_date.strftime("%d"),
            ymd=target_date.strftime("%Y%m%d")
        )
        
        new_records = []
        if _check_url_exists(url):
            last_num += 1
            captured_at_ts = f"{target_date.isoformat()}T00:00:00Z"
            
            record = {
                "id": f"{prefix}-{last_num}",
                "url": url,
                "task_type": task_type,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "annotations": [],
                "metadata": {
                    "source": "Official Observatory",
                    "captured_at": captured_at_ts
                }
            }
            new_records.append(record)
        
        if new_records:
            file_path = DATA_PROCESSING_DIR / f"{task_type}.jsonl"
            # Overwrite processing file with ONLY this day's data
            with open(file_path, "w", encoding="utf-8") as f:
                for record in new_records:
                    f.write(json.dumps(record, separators=(",", ":")) + "\n")
            log.info(f"Generated {len(new_records)} task for {task_type}. ID: {prefix}-{last_num}")
        else:
            log.warning(f"No valid image found for {task_type} on {target_date}.")

if __name__ == "__main__":
    main()
