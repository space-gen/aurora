"""
test_pull.py
============
Experimental crawler for new SDO/SOHO task types using JSOC mirror patterns.
Excludes sunspot and magnetogram.
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
# Write to a temporary folder to avoid messing up production data
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing_test" 

# Experimental Source Configurations (JSOC for SDO, SOHO for CME)
SOURCE_MAP = {
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
        
        # Start IDs from 0 for testing
        prefix = cfg["prefix"]
        
        # Format URL for target date
        url = cfg["url_pattern"].format(
            Y=target_date.strftime("%Y"),
            M=target_date.strftime("%m"),
            D=target_date.strftime("%d"),
            ymd=target_date.strftime("%Y%m%d")
        )
        
        if _check_url_exists(url):
            log.info(f"[SUCCESS] Found valid image for {task_type}: {url}")
            
            # Write a sample record
            record = {
                "id": f"{prefix}-test",
                "url": url,
                "task_type": task_type,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "metadata": {"source": "Experimental JSOC/SOHO", "captured_at": target_date.isoformat()}
            }
            
            file_path = DATA_PROCESSING_DIR / f"{task_type}.jsonl"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        else:
            log.warning(f"[FAILED] No image found for {task_type} on {target_date}")

if __name__ == "__main__":
    main()
