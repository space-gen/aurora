"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

Non-destructive schema reconciliation between local annotation files and
HuggingFace dataset splits, triggered only when a schema mismatch is detected:
1) Try normal train push first
2) If features/schema mismatch appears, pull existing HF data (all splits)
3) Build a union schema across HF + local records
4) Fill missing fields on both sides with blank values (None)
5) Merge train split records (local wins on id/url collision)
6) Push reconciled splits back to HF without deleting repository files
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

PREFERRED_KEY_ORDER = ["id", "serial_number", "url", "task_type", "user_label", "ml_label", "locations", "metadata"]


def _safe_value(value: Any) -> Any:
    """Keep scalar values as-is; normalise dict/list into JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}


def _load_hf_splits(repo_id: str, token: str) -> dict[str, list[dict[str, Any]]]:
    """Load all existing HF splits (if any)."""
    try:
        from datasets import load_dataset
        ds_dict = load_dataset(repo_id, token=token, download_mode="force_redownload")
        splits: dict[str, list[dict[str, Any]]] = {}
        for split_name, ds in ds_dict.items():
            splits[split_name] = [_normalise_record(dict(row)) for row in ds]
        return splits
    except Exception as exc:
        log.info("HF repo %s unavailable or empty (%s). Creating/refreshing from local.", repo_id, exc)
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
    """
    Merge two values with no precedence/winner.
    - If one side is blank, keep the other.
    - If both equal, keep the value.
    - If both differ and non-blank, preserve both as a stable JSON array string.
    """
    if _is_blank(left):
        return right
    if _is_blank(right):
        return left
    if left == right:
        return left
    return json.dumps(sorted({str(left), str(right)}))


def _merge_records_union(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in set(base.keys()) | set(incoming.keys()):
        merged[key] = _merge_values_union(base.get(key), incoming.get(key))
    return merged


def _merge_train_records(
    hf_train: list[dict[str, Any]],
    local_train: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge train records non-destructively.
    No side wins on collisions: values are union-merged field-by-field.
    """
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

    for rec in hf_train:
        upsert(rec)
    for rec in local_train:
        upsert(rec)

    return list(by_id.values()) + list(by_url.values()) + remainder


def _push_splits(repo_id: str, token: str, splits: dict[str, list[dict[str, Any]]]) -> None:
    from datasets import Dataset

    # Push train first, then others, to keep behavior predictable.
    split_names = sorted(splits.keys(), key=lambda s: (s != "train", s))
    for split_name in split_names:
        rows = splits[split_name]
        if not rows:
            log.info("Skipping empty split '%s' for %s", split_name, repo_id)
            continue
        Dataset.from_list(rows).push_to_hub(repo_id, token=token, split=split_name)
        log.info("Pushed %d rows to %s split '%s'", len(rows), repo_id, split_name)


def _is_schema_mismatch_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "features" in text and ("mismatch" in text or "don't match" in text)


def _push_to_hf(task_type: str, local_records_raw: list[dict[str, Any]], token: str) -> None:
    from datasets import Dataset

    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    local_records = [_normalise_record(r) for r in local_records_raw]

    # Fast path: normal push when schemas are already compatible.
    try:
        Dataset.from_list(local_records).push_to_hub(repo_id, token=token, split="train")
        log.info("Pushed %d rows to %s split 'train' (no schema mismatch).", len(local_records), repo_id)
        return
    except Exception as exc:
        if not _is_schema_mismatch_error(exc):
            raise
        log.warning("Schema mismatch detected for %s. Starting non-destructive reconciliation...", repo_id)

    # Slow path: mismatch-only, non-destructive reconciliation.
    hf_splits = _load_hf_splits(repo_id, token)
    hf_train = hf_splits.get("train", [])
    merged_train = _merge_train_records(hf_train, local_records)

    all_hf_records: list[dict[str, Any]] = []
    for split_rows in hf_splits.values():
        all_hf_records.extend(split_rows)
    keys = _union_keys(all_hf_records, local_records)
    if not keys:
        keys = PREFERRED_KEY_ORDER.copy()

    reconciled_splits: dict[str, list[dict[str, Any]]] = {}
    for split_name, split_rows in hf_splits.items():
        if split_name != "train":
            reconciled_splits[split_name] = _align_schema(split_rows, keys)
    reconciled_splits["train"] = _align_schema(merged_train, keys)

    log.info("Reconciled schema for %s with %d fields.", repo_id, len(keys))
    _push_splits(repo_id, token, reconciled_splits)


def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    task_filter = os.environ.get("TASK_TYPE")
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
        except Exception as exc:
            log.warning("Error processing %s: %s", task_file.name, exc)


if __name__ == "__main__":
    main()
