"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

Supports compressed JSONL local files.
Non-destructive schema reconciliation with HuggingFace datasets.
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

PREFERRED_KEY_ORDER = ["id", "serial_number", "url", "task_type", "created_at", "annotations", "metadata"]

def _safe_value(value: Any) -> Any:
    """Keep scalar values as-is; normalise dict/list into JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}

def _load_hf_splits(repo_id: str, token: str) -> dict[str, list[dict[str, Any]]]:
    try:
        from datasets import load_dataset
        ds_dict = load_dataset(repo_id, token=token, download_mode="force_redownload")
        splits: dict[str, list[dict[str, Any]]] = {}
        for split_name, ds in ds_dict.items():
            splits[split_name] = [_normalise_record(dict(row)) for row in ds]
        return splits
    except Exception as exc:
        log.info("HF repo %s unavailable (%s).", repo_id, exc)
        return {}

def _union_keys(*record_sets: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for records in record_sets:
        for record in records:
            keys.update(record.keys())
    ordered = [k for k in PREFERRED_KEY_ORDER if k in keys]
    ordered.extend(sorted(k for k in keys if k not in ordered))
    return ordered

def _align_schema(records: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    for record in records:
        row = {k: None for k in keys}
        for k, v in record.items():
            row[k] = _safe_value(v)
        aligned.append(row)
    return aligned

def _is_blank(value: Any) -> bool:
    return value is None or value == ""

def _merge_values_union(left: Any, right: Any) -> Any:
    if _is_blank(left): return right
    if _is_blank(right): return left
    if left == right: return left
    return json.dumps(sorted({str(left), str(right)}), separators=(",", ":"))

def _merge_annotations_list(left_str: str | None, right_str: str | None) -> str:
    def parse_list(s):
        if not s: return []
        try:
            val = json.loads(s)
            return val if isinstance(val, list) else [val]
        except: return []
    left_list = parse_list(left_str)
    right_list = parse_list(right_str)
    seen = set()
    merged = []
    for item in (left_list + right_list):
        s_item = json.dumps(item, separators=(",", ":"), sort_keys=True)
        if s_item not in seen:
            seen.add(s_item)
            merged.append(item)
    return json.dumps(merged, separators=(",", ":"), sort_keys=True)

def _merge_records_union(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if base is None: return incoming
    merged = dict(base)
    for key in set(base.keys()) | set(incoming.keys()):
        val_base = base.get(key)
        val_incoming = incoming.get(key)
        if key == "annotations":
            merged[key] = _merge_annotations_list(val_base, val_incoming)
        else:
            merged[key] = _merge_values_union(val_base, val_incoming)
    return merged

def _merge_train_records(hf_train: list[dict[str, Any]], local_train: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    remainder: list[dict[str, Any]] = []
    def upsert(record: dict[str, Any]) -> None:
        rec_id = record.get("id")
        rec_url = record.get("url")
        if rec_id is not None:
            key = str(rec_id)
            existing = by_id.get(key)
            by_id[key] = _merge_records_union(existing, record) if existing else record
            return
        if rec_url is not None:
            key = str(rec_url)
            existing = by_url.get(key)
            by_url[key] = _merge_records_union(existing, record) if existing else record
            return
        remainder.append(record)
    for rec in hf_train: upsert(rec)
    for rec in local_train: upsert(rec)
    return list(by_id.values()) + list(by_url.values()) + remainder

def _push_splits(repo_id: str, token: str, splits: dict[str, list[dict[str, Any]]]) -> None:
    from datasets import Dataset
    split_names = sorted(splits.keys(), key=lambda s: (s != "train", s))
    for split_name in split_names:
        rows = splits[split_name]
        if not rows: continue
        Dataset.from_list(rows).push_to_hub(repo_id, token=token, split=split_name)
        log.info("Pushed %d rows to %s split '%s'", len(rows), repo_id, split_name)

def _push_to_hf(task_type: str, local_records_raw: list[dict[str, Any]], token: str) -> None:
    from datasets import Dataset
    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    local_records = [_normalise_record(r) for r in local_records_raw]
    try:
        Dataset.from_list(local_records).push_to_hub(repo_id, token=token, split="train")
        log.info("Pushed %d rows to %s split 'train' (Fast path).", len(local_records), repo_id)
        return
    except Exception:
        log.warning("Fast path failed for %s. Reconciling...", repo_id)
    hf_splits = _load_hf_splits(repo_id, token)
    hf_train = hf_splits.get("train", [])
    merged_train = _merge_train_records(hf_train, local_records)
    all_hf_records: list[dict[str, Any]] = []
    for split_rows in hf_splits.values(): all_hf_records.extend(split_rows)
    keys = _union_keys(all_hf_records, local_records)
    reconciled_splits: dict[str, list[dict[str, Any]]] = {}
    for split_name, split_rows in hf_splits.items():
        if split_name != "train": reconciled_splits[split_name] = _align_schema(split_rows, keys)
    reconciled_splits["train"] = _align_schema(merged_train, keys)
    _push_splits(repo_id, token, reconciled_splits)

def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token: sys.exit(1)
    
    # Strictly process only the annotations folder
    target_files = list(ANNOTATIONS_DIR.glob("*.jsonl"))
    log.info("Starting synchronization for %d annotation file(s).", len(target_files))
    
    for task_file in target_files:
        task_type = task_file.stem
        records = []
        try:
            with open(task_file, "r") as f:
                for line in f:
                    if line.strip(): records.append(json.loads(line))
            
            # Only push if there are actual annotations provided by users
            labeled_records = [r for r in records if r.get("annotations")]
            
            if labeled_records:
                log.info("Pushing %d labeled records for %s to HF...", len(labeled_records), task_type)
                _push_to_hf(task_type, labeled_records, token)
            else:
                log.info("No labeled annotations found in %s. Skipping HF push.", task_file.name)
        except Exception as exc: 
            log.warning("Error processing %s: %s", task_file.name, exc)

if __name__ == "__main__":
    main()
