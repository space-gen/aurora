"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

Optimized for high performance: Appends new rows to HuggingFace datasets
without pulling existing data. Falls back to schema-aware reconciliation 
only when necessary.
"""

from __future__ import annotations

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

# Desired column order
PREFERRED_KEY_ORDER = ["id", "serial_number", "url", "task_type", "created_at", "annotations", "metadata"]

def _safe_value(value: Any) -> Any:
    """Keep scalar values as-is; normalise dict/list into minified JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}

def _push_to_hf(task_type: str, local_records_raw: list[dict[str, Any]], token: str) -> None:
    from datasets import Dataset, load_dataset, concatenate_datasets

    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    local_records = [_normalise_record(r) for r in local_records_raw]
    new_ds = Dataset.from_list(local_records)
    
    # 1. Fast Path: Direct Remote Append
    # This is fast because it does NOT pull existing data.
    try:
        new_ds.push_to_hub(repo_id, token=token, split="train", append=True)
        log.info("Fast path: Successfully appended %d rows to %s", len(local_records), repo_id)
        return
    except Exception as exc:
        log.warning("Fast path failed for %s (Likely schema mismatch). Falling back to reconciliation...", repo_id)

    # 2. Slow Path (Fallback): Schema Reconciliation
    # Only triggered if the local columns differ from the remote columns.
    try:
        try:
            existing_ds = load_dataset(repo_id, token=token, split="train")
        except Exception:
            existing_ds = None

        if existing_ds:
            all_keys = sorted(set(existing_ds.column_names) | set(new_ds.column_names))
            
            # Align schemas (add missing columns as null)
            existing_aligned = existing_ds.map(lambda x: {k: x.get(k) for k in all_keys})
            new_aligned = new_ds.map(lambda x: {k: x.get(k) for k in all_keys})
            
            final_ds = concatenate_datasets([existing_aligned, new_aligned])
        else:
            final_ds = new_ds

        final_ds.push_to_hub(repo_id, token=token, split="train")
        log.info("Successfully reconciled and pushed %d rows to %s", len(local_records), repo_id)

    except Exception as exc:
        log.error("Critical failure during HF push for %s: %s", task_type, exc)

def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)
    
    target_files = list(ANNOTATIONS_DIR.glob("*.jsonl"))
    for task_file in target_files:
        task_type = task_file.stem
        records = []
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
            
            # Filter for labeled records only
            labeled = [r for r in records if r.get("annotations")]
            
            if labeled:
                _push_to_hf(task_type, labeled, token)
            else:
                log.info("No new annotations for %s. Skipping.", task_type)
        except Exception as exc:
            log.warning("Error processing %s: %s", task_file.name, exc)

if __name__ == "__main__":
    main()
