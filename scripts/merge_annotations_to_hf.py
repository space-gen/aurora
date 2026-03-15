"""
merge_annotations_to_hf.py
===========================
Pipeline Stage 3 — Merge Annotations

Reads the task-specific JSON files from annotations/ (e.g. sunspot.json)
and pushes all non-empty annotations to HuggingFace.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

def _push_to_hf(task_type: str, records: list[dict], token: str):
    try:
        from datasets import Dataset
        repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
        
        # Only push records that have a user label
        labeled_records = [r for r in records if r.get("user_label") is not None]
        if not labeled_records:
            log.info(f"No labeled records for {task_type}. Skipping push.")
            return

        log.info(f"Pushing {len(labeled_records)} records to {repo_id}")
        
        # Format for HF
        hf_data = []
        for r in labeled_records:
            hf_data.append({
                "id": r["id"],
                "serial_number": r["serial_number"],
                "url": r["url"],
                "task_type": r["task_type"],
                "user_label": r["user_label"],
                "locations": json.dumps(r.get("locations", [])),
                "metadata": json.dumps(r.get("metadata", {}))
            })
            
        dataset = Dataset.from_list(hf_data)
        dataset.push_to_hub(repo_id, token=token, split="train")
        log.info(f"Successfully pushed to {repo_id}")
        
    except Exception as e:
        log.error(f"Failed to push {task_type}: {e}")

def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    for task_file in ANNOTATIONS_DIR.glob("*.json"):
        task_type = task_file.stem
        try:
            records = json.loads(task_file.read_text())
            if isinstance(records, list):
                _push_to_hf(task_type, records, token)
        except Exception as e:
            log.warning(f"Error reading {task_file.name}: {e}")

if __name__ == "__main__":
    main()
