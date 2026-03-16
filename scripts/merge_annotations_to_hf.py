"""
merge_annotations_to_hf.py
===========================
Pipeline Stage 3 — Merge Annotations

Reads the task-specific JSON files from annotations/ (e.g. sunspot.json)
and pushes ALL records (labeled and unlabeled) to HuggingFace.

Schema changes are handled gracefully: if the HF repo has an incompatible
schema, old records are downloaded, migrated to the new schema (matching
fields are preserved, new fields default to None, removed fields are
dropped), merged with local records, and pushed as a single dataset.
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

# The canonical schema for a formatted HF record.  All keys must be present.
CANONICAL_KEYS = ["id", "serial_number", "url", "task_type", "user_label", "locations", "metadata"]


def _format_record(r: dict) -> dict:
    """Convert a raw annotation dict into the canonical HF record format."""
    return {
        "id": r.get("id"),
        "serial_number": r.get("serial_number"),
        "url": r.get("url"),
        "task_type": r.get("task_type"),
        "user_label": r.get("user_label"),      # May be None
        "locations": json.dumps(r.get("locations", [])),
        "metadata": json.dumps(r.get("metadata", {})),
    }


def _migrate_old_record(old: dict) -> dict:
    """
    Migrate a record from an old HF schema to the current canonical schema.

    - Fields present in both schemas keep their values.
    - Fields new to the canonical schema default to None.
    - Fields no longer in the canonical schema are dropped.
    - 'locations' and 'metadata' are normalised to JSON strings if needed.
    """
    migrated: dict = {k: None for k in CANONICAL_KEYS}
    for key in CANONICAL_KEYS:
        if key in old:
            migrated[key] = old[key]
    # Ensure locations / metadata are always stored as JSON strings
    if not isinstance(migrated.get("locations"), str):
        migrated["locations"] = json.dumps(migrated.get("locations") or [])
    if not isinstance(migrated.get("metadata"), str):
        migrated["metadata"] = json.dumps(migrated.get("metadata") or {})
    return migrated


def _fetch_old_records(repo_id: str, token: str) -> list[dict]:
    """Download all existing records from an HF dataset repo, ignoring schema errors."""
    try:
        from datasets import load_dataset
        ds = load_dataset(repo_id, token=token, split="train", download_mode="force_redownload")
        return [dict(row) for row in ds]
    except Exception as e:
        log.warning(f"Could not fetch old records from {repo_id}: {e}")
        return []


def _push_to_hf(task_type: str, records: list[dict], token: str):
    try:
        from datasets import Dataset
        from huggingface_hub import HfApi
        repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"

        if not records:
            log.info(f"No records for {task_type}. Skipping.")
            return

        log.info(f"Pushing {len(records)} records to {repo_id}")

        new_hf_data = [_format_record(r) for r in records]
        dataset = Dataset.from_list(new_hf_data)

        try:
            dataset.push_to_hub(repo_id, token=token, split="train")

        except Exception as push_err:
            if "don't match the features" in str(push_err) or "features" in str(push_err).lower():
                log.warning(
                    f"Schema mismatch on {repo_id} — migrating old records to new schema "
                    f"to avoid data loss, then re-pushing..."
                )
                # 1. Download and migrate old records
                old_raw = _fetch_old_records(repo_id, token)
                old_migrated = [_migrate_old_record(r) for r in old_raw]
                log.info(f"Fetched {len(old_migrated)} old records from {repo_id} for migration.")

                # 2. Merge: new records win on id/url collision
                new_ids  = {r["id"] for r in new_hf_data if r.get("id")}
                new_urls = {r["url"] for r in new_hf_data if r.get("url")}
                kept_old = [
                    r for r in old_migrated
                    if r.get("id") not in new_ids and r.get("url") not in new_urls
                ]
                merged = kept_old + new_hf_data
                log.info(
                    f"Merged dataset: {len(kept_old)} preserved old + "
                    f"{len(new_hf_data)} new = {len(merged)} total records."
                )

                # 3. Wipe stale parquet files so push_to_hub can write fresh ones
                api = HfApi(token=token)
                try:
                    for f in api.list_repo_files(repo_id=repo_id, repo_type="dataset"):
                        if f.startswith("data/"):
                            api.delete_file(
                                path_in_repo=f, repo_id=repo_id, repo_type="dataset",
                                commit_message="chore: clear old parquet for schema migration [skip ci]",
                            )
                except Exception as del_err:
                    log.warning(f"Could not clear old parquet for {repo_id}: {del_err}")

                # 4. Push merged dataset with new schema
                Dataset.from_list(merged).push_to_hub(repo_id, token=token, split="train")
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
