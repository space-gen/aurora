"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

ID-based synchronization: 
- If ID exists on HF, appends local annotations to the remote record.
- Otherwise, appends as a new row.
Optimized for data integrity and performance by avoiding full remote pulls.
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

# Desired column order for consistency
PREFERRED_KEY_ORDER = ["id", "url", "task_type", "created_at", "annotations", "metadata"]

def _safe_value(value: Any) -> Any:
    """Keep scalar values as-is; normalise dict/list into minified JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}

def _merge_annotations_list(remote_str: str | None, local_list: list[dict[str, Any]]) -> str:
    """
    Merge local annotation objects into the remote JSON-stringified list.
    Deduplicates based on the JSON string representation of each annotation object.
    """
    def parse_list(s):
        if not s: return []
        try:
            val = json.loads(s)
            return val if isinstance(val, list) else [val]
        except: 
            log.warning("Could not parse JSON string as a list: %s", s)
            return []

    remote_list = parse_list(remote_str)
    
    seen_hashes = set()
    merged_list = []
    
    # Add remote items first, ensuring they are added only if not seen
    for item in remote_list:
        s_item = json.dumps(item, sort_keys=True)
        if s_item not in seen_hashes:
            seen_hashes.add(s_item)
            merged_list.append(item)
            
    # Add local items, ensuring they are unique and not already present
    for item in local_list:
        s_item = json.dumps(item, sort_keys=True)
        if s_item not in seen_hashes:
            seen_hashes.add(s_item)
            merged_list.append(item)

    return json.dumps(merged_list, separators=(",", ":"), sort_keys=True)

def _push_to_hf(task_type: str, local_records_raw: list[dict[str, Any]], token: str) -> None:
    from datasets import Dataset, load_dataset

    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    local_records = [_normalise_record(r) for r in local_records_raw]
    
    # Get existing records and their schema keys
    existing_records = []
    existing_keys = set()
    try:
        # Attempt to load the entire dataset to get existing records and schema
        # Note: This can be slow for very large datasets, but is necessary for robust merging
        # If this is too slow, we might need a dedicated API to only fetch specific IDs.
        existing_ds = load_dataset(repo_id, token=token, split="train")
        existing_records = [dict(row) for row in existing_ds]
        existing_keys = set(existing_ds.column_names)
        log.info("Loaded %d existing records from %s", len(existing_records), repo_id)
    except Exception as e:
        log.info("No existing dataset found for %s or error loading it (%s). Creating new.", repo_id, e)
        existing_records = []
        existing_keys = set() # Start fresh if no existing dataset

    # Index existing records by ID for efficient lookup
    hf_index = {str(r["id"]): r for r in existing_records if "id" in r}
    
    merged_records_map = hf_index.copy() # Start with existing records
    
    # Process local records: merge or append
    for local in local_records:
        lid = str(local["id"])
        if lid in merged_records_map:
            # ID exists, merge annotations
            remote_record = merged_records_map[lid]
            remote_annotations_str = remote_record.get("annotations")
            local_annotations = local.get("annotations", [])
            
            merged_annotations_str = _merge_annotations_list(remote_annotations_str, local_annotations)
            remote_record["annotations"] = merged_annotations_str # Update with merged annotations
            # Update timestamp/user/issue_number from the latest local record for this ID (optional, but useful)
            if local.get("annotations"): # If local record has annotations
                latest_local_ann = local["annotations"][-1] # Assume latest annotation in local list
                remote_record["metadata"]["last_user"] = latest_local_ann.get("user")
                remote_record["metadata"]["last_issue_number"] = latest_local_ann.get("issue_number")
                remote_record["metadata"]["last_timestamp"] = latest_local_ann.get("timestamp")
        else:
            # New ID, append as a new record
            merged_records_map[lid] = _normalise_record(local) # Normalize before adding

    # Combine all records (existing merged + new ones)
    final_records_list = list(merged_records_map.values())

    if not final_records_list:
        log.info("No records to push for %s.", task_type)
        return

    # Align schema based on all keys found
    all_keys = PREFERRED_KEY_ORDER.copy()
    found_keys = set().union(*(r.keys() for r in final_records_list))
    for k in sorted(found_keys):
        if k not in all_keys:
            all_keys.append(k)

    aligned_data = []
    for r in final_records_list:
        row = {k: r.get(k) for k in all_keys}
        aligned_data.append(row)

    final_ds = Dataset.from_list(aligned_data)
    final_ds.push_to_hub(repo_id, token=token, split="train")
    log.info("Successfully synchronized %d records for %s (Total rows: %d)", len(local_records_raw), repo_id, len(final_ds))


def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)
    
    target_files = list(ANNOTATIONS_DIR.glob("*.jsonl"))
    for task_file in target_files:
        task_type = task_file.stem
        local_records = []
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        local_records.append(json.loads(line))
            
            # Filter for labeled records only
            labeled = [r for r in local_records if r.get("annotations")]
            
            if labeled:
                _push_to_hf(task_type, labeled, token)
            else:
                log.info("No new annotations for %s. Skipping.", task_type)
        except Exception as exc:
            log.warning("Error processing %s: %s", task_file.name, exc)

if __name__ == "__main__":
    main()
