"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

ID-based synchronization: 
- If ID exists on HF, appends local annotations to the remote record.
- Otherwise, appends as a new row.
Optimized for data integrity over performance.
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
PREFERRED_KEY_ORDER = ["id", "url", "task_type", "created_at", "annotations", "metadata"]

def _safe_value(value: Any) -> Any:
    """Normalise dict/list into minified JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}

def _merge_annotations_list(remote_str: str | None, local_list: list[dict[str, Any]]) -> str:
    """Merge local annotation objects into the remote JSON-stringified list."""
    def parse_list(s):
        if not s: return []
        try:
            val = json.loads(s)
            return val if isinstance(val, list) else [val]
        except: return []

    merged_list = parse_list(remote_str)
    
    seen = {json.dumps(item, sort_keys=True) for item in merged_list}
    
    for item in local_list:
        s_item = json.dumps(item, sort_keys=True)
        if s_item not in seen:
            merged_list.append(item)
            seen.add(s_item)

    return json.dumps(merged_list, separators=(",", ":"), sort_keys=True)

def _push_to_hf(task_type: str, local_records: list[dict[str, Any]], token: str) -> None:
    from datasets import Dataset, load_dataset

    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    try:
        # 1. Load existing dataset
        try:
            hf_ds = load_dataset(repo_id, token=token, split="train")
            hf_records = [dict(row) for row in hf_ds]
            log.info("Loaded %d existing records from %s", len(hf_records), repo_id)
        except Exception:
            hf_records = []
            log.info("No existing dataset found for %s. Creating new.", repo_id)

        # 2. Merge logic (ID-based)
        hf_index = {str(r["id"]): r for r in hf_records if "id" in r}
        
        for local in local_records:
            lid = str(local["id"])
            if lid in hf_index:
                # Merge annotations list into existing record
                remote_record = hf_index[lid]
                remote_record["annotations"] = _merge_annotations_list(
                    remote_record.get("annotations"), 
                    local.get("annotations", [])
                )
            else:
                # Add as new record
                hf_records.append(_normalise_record(local))

        # 3. Final alignment and push
        if not hf_records: return
        
        all_keys = PREFERRED_KEY_ORDER.copy()
        found_keys = set().union(*(r.keys() for r in hf_records))
        for k in sorted(found_keys):
            if k not in all_keys: all_keys.append(k)

        aligned_data = []
        for r in hf_records:
            row = {k: _safe_value(r.get(k)) for k in all_keys}
            aligned_data.append(row)

        final_ds = Dataset.from_list(aligned_data)
        final_ds.push_to_hub(repo_id, token=token, split="train")
        log.info("Successfully synchronized %s (Total rows: %d)", repo_id, len(hf_records))

    except Exception as exc:
        log.error("Failed to push %s to HF: %s", task_type, exc)

def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token: sys.exit(1)
    
    target_files = list(ANNOTATIONS_DIR.glob("*.jsonl"))
    for task_file in target_files:
        task_type = task_file.stem
        local_records = []
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip(): local_records.append(json.loads(line))
            
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
