"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3: publish annotated records to per-task Hugging Face datasets.

Records are written to data/<capture-date>.yml. Existing rows are merged by image
URL, so running the pipeline twice cannot erase published annotations. Any failure
exits non-zero so the next stage does not reset annotations that were not published.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"
PREFERRED_KEY_ORDER = ["id", "url", "task_type", "created_at", "metadata", "annotations"]


def _normalize_url(url: Any) -> str:
    value = str(url).strip()
    if value.startswith("//"):
        value = "https:" + value
    return re.sub(r"^https?://jsoc1?\.stanford\.edu/", "https://jsoc1.stanford.edu/", value)


def _safe_value(value: Any) -> Any:
    return json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else value


def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    ordered = {key: record[key] for key in PREFERRED_KEY_ORDER if key in record}
    ordered.update({key: value for key, value in record.items() if key not in ordered})
    return {key: _safe_value(value) for key, value in ordered.items()}


def _as_list(value: Any) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, list) else [parsed]


def _normalize_annotation(annotation: Any) -> Any:
    if not isinstance(annotation, dict):
        return annotation
    result = dict(annotation)
    locations = result.get("locations")
    if isinstance(locations, str):
        locations = json.loads(locations)
    normalized = []
    for location in locations if isinstance(locations, list) else []:
        if isinstance(location, dict):
            location = dict(location)
            if "rle" in location and "region" not in location:
                location["region"] = location.pop("rle")
            normalized.append(location)
    result["locations"] = normalized
    return result


def _merge_annotations_list(remote: Any, local: Any) -> str:
    merged: list[Any] = []
    seen: set[str] = set()
    for item in [*_as_list(remote), *_as_list(local)]:
        annotation = _normalize_annotation(item)
        if isinstance(annotation, dict):
            key = f"{str(annotation.get('user', '')).lower()}:{annotation.get('issue_number')}"
        else:
            key = json.dumps(annotation, sort_keys=True)
        if key not in seen:
            seen.add(key)
            merged.append(annotation)
    return json.dumps(merged, separators=(",", ":"))


def merge_rows(existing_text: str, local_records: list[dict[str, Any]]) -> str:
    rows: dict[str, dict[str, Any]] = {}
    for line in existing_text.splitlines():
        if line.strip():
            row = json.loads(line)
            rows[_normalize_url(row.get("url", ""))] = row

    for record in local_records:
        row = _normalise_record(record)
        key = _normalize_url(row.get("url", ""))
        row["url"] = key
        previous = rows.get(key)
        if previous:
            row = {**previous, "annotations": _merge_annotations_list(previous.get("annotations"), record.get("annotations"))}
        else:
            row["annotations"] = _merge_annotations_list(None, record.get("annotations"))
        rows[key] = row

    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows.values())


def _capture_date(record: dict[str, Any], fallback: str) -> str:
    metadata = record.get("metadata")
    captured = metadata.get("captured_at") if isinstance(metadata, dict) else None
    match = re.match(r"\d{4}-\d{2}-\d{2}", str(captured or ""))
    return match.group(0) if match else fallback


def _read_existing(api: Any, repo_id: str, path: str) -> str:
    if not api.file_exists(repo_id=repo_id, filename=path, repo_type="dataset"):
        return ""
    local_path = api.hf_hub_download(repo_id=repo_id, filename=path, repo_type="dataset")
    return Path(local_path).read_text(encoding="utf-8")


def push_task_file(api: Any, task_file: Path, fallback_date: str) -> int:
    task_type = task_file.stem
    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in task_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if _as_list(record.get("annotations")):
                by_date[_capture_date(record, fallback_date)].append(record)

    if not by_date:
        log.info("No annotations to publish for %s.", task_type)
        return 0

    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
    published = 0
    for date_key, records in sorted(by_date.items()):
        path = f"data/{date_key}.yml"
        content = merge_rows(_read_existing(api, repo_id, path), records)
        api.upload_file(
            path_or_fileobj=content.encode("utf-8"),
            path_in_repo=path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"chore: merge annotations into {path}",
        )
        published += len(records)
        log.info("Published %d annotated records to %s:%s", len(records), repo_id, path)
    return published


def publish_all(api: Any, annotations_dir: Path, fallback_date: str) -> list[str]:
    failed = []
    for task_file in sorted(annotations_dir.glob("*.jsonl")):
        try:
            push_task_file(api, task_file, fallback_date)
        except Exception as exc:
            log.error("Could not publish %s: %s", task_file.name, exc)
            failed.append(task_file.name)
    return failed


def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    from huggingface_hub import HfApi

    fallback_date = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    failed = publish_all(HfApi(token=token), ANNOTATIONS_DIR, fallback_date)
    if failed:
        log.error("Keeping annotations because publishing failed for: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
