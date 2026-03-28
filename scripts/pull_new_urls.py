"""
pull_new_urls.py
================
Stage 2 — Daily Solar Data Crawler

Fetches sunspot and magnetogram JPG URLs for a specific day.
Parallelized fetch for faster performance.
"""

import re
import json
import logging
import datetime
import argparse
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"

SOURCE_MAP = {
    "sunspot": {
        "path": "http://jsoc1.stanford.edu/data/hmi/images/{Y}/{M}/{D}/",
        "filter": "_Ic_1k.jpg",
        "prefix": "sp"
    },
    "magnetogram": {
        "path": "http://jsoc1.stanford.edu/data/hmi/images/{Y}/{M}/{D}/",
        "filter": "_M_1k.jpg",
        "prefix": "mg"
    },
}

LINK_REGEX = re.compile(r'href="([^"]+\.jpg)"')

MAX_WORKERS = 10


def _get_last_id_numeric(task_type):
    max_id = 0
    prefix = SOURCE_MAP[task_type]["prefix"]

    for p in REPO_ROOT.glob("**/*.jsonl"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)

                    if item.get("task_type") == task_type:
                        id_str = item.get("id", "")
                        if id_str.startswith(f"{prefix}-"):
                            try:
                                num = int(id_str.split("-")[1])
                                max_id = max(max_id, num)
                            except Exception:
                                pass
        except Exception:
            pass

    return max_id


def _fetch_single_day(task_type, date_obj):
    y = date_obj.strftime("%Y")
    m = date_obj.strftime("%m")
    d = date_obj.strftime("%d")

    cfg = SOURCE_MAP[task_type]
    base_url = cfg["path"].format(Y=y, M=m, D=d)

    results = []

    try:
        response = requests.get(base_url, timeout=15)

        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)

            for match in matches:
                if cfg["filter"] in match:
                    results.append(base_url + match)
        else:
            log.warning(f"Failed {base_url} ({response.status_code})")

    except Exception as e:
        log.warning(f"Error {base_url}: {e}")

    return results


def _fetch_day_urls_parallel(task_type, date_obj):
    dates = [date_obj]
    all_results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_single_day, task_type, d): d
            for d in dates
        }

        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as e:
                log.warning(f"Thread failed: {e}")

    return all_results


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

        urls = _fetch_day_urls_parallel(task_type, target_date)

        new_records = []

        for url in urls:
            last_num += 1

            record = {
                "id": f"{prefix}-{last_num}",
                "url": url,
                "task_type": task_type,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "metadata": {
                    "source": "JSOC_HMI_JPG",
                    "captured_at": f"{target_date.isoformat()}T00:00:00Z"
                },
                "annotations": [],
            }

            new_records.append(record)

        if new_records:
            file_path = DATA_PROCESSING_DIR / f"{task_type}.jsonl"

            with open(file_path, "w", encoding="utf-8") as f:
                for record in new_records:
                    f.write(json.dumps(record, separators=(",", ":")) + "\n")

            log.info(
                f"{len(new_records)} records saved for {task_type} "
                f"(IDs {prefix}-{last_num - len(new_records) + 1} → {prefix}-{last_num})"
            )
        else:
            log.warning(f"No URLs found for {task_type} on {target_date}")


if __name__ == "__main__":
    main()
