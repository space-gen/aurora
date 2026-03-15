"""
merge_annotations_to_hf.py
===========================
Pipeline Stage 3 — Merge Annotations

Reads the task-specific JSON files from annotations/ (e.g. sunspot.json)
and pushes ALL records (labeled and unlabeled) to HuggingFace.
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
        from huggingface_hub import HfApi
        repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
        
        if not records:
            log.info(f"No records for {task_type}. Skipping.")
            return

        log.info(f"Pushing all {len(records)} records to {repo_id}")
        
        # Format for HF - Include all fields as requested
        hf_data = []
        for r in records:
            hf_data.append({
                "id": r.get("id"),
                "serial_number": r.get("serial_number"),
                "url": r.get("url"),
                "task_type": r.get("task_type"),
                "user_label": r.get("user_label"), # Might be None
                "locations": json.dumps(r.get("locations", [])),
                "metadata": json.dumps(r.get("metadata", {}))
            })
            
        dataset = Dataset.from_list(hf_data)
        
        def _do_push():
            dataset.push_to_hub(repo_id, token=token, split="train")

        try:
            _do_push()
        except Exception as push_err:
            if "don't match the features" in str(push_err) or "features" in str(push_err).lower():
                # Schema mismatch: wipe old data from the repo then retry
                log.warning(f"Schema mismatch for {repo_id}, clearing old data and retrying...")
                api = HfApi(token=token)
                try:
                    for f in api.list_repo_files(repo_id=repo_id, repo_type="dataset"):
                        if f.startswith("data/"):
                            api.delete_file(path_in_repo=f, repo_id=repo_id, repo_type="dataset")
                except Exception as del_err:
                    log.warning(f"Could not clear old files for {repo_id}: {del_err}")
                _do_push()
            else:
                raise

        log.info(f"Successfully pushed to {repo_id}")
        
    except Exception as e:
        log.error(f"Failed to push {task_type}: {e}")

def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    task_filter = os.environ.get("TASK_TYPE")

    # Find relevant task files
    if task_filter:
        target_files = [ANNOTATIONS_DIR / f"{task_filter}.json"]
    else:
        target_files = list(ANNOTATIONS_DIR.glob("*.json"))

    for task_file in target_files:
        if not task_file.exists():
            continue
        task_type = task_file.stem
        try:
            records = json.loads(task_file.read_text())
            if isinstance(records, list):
                _push_to_hf(task_type, records, token)
        except Exception as e:
            log.warning(f"Error reading {task_file.name}: {e}")

if __name__ == "__main__":
    main()
