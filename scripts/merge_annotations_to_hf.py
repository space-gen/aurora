"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3: archive raw annotations and publish private science catalogues.

Raw submissions are merged by image URL into a private archive first. Catalogue
datasets are then rebuilt from that archive, so they never contain usernames,
issue numbers or interface data. Any failure exits non-zero so the next stage does
not reset annotations that were not stored.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.finder_review import review_rows, tally
    from scripts.science_dataset import build_catalogue, dataset_card, jsonl, manifest
except ModuleNotFoundError:
    from finder_review import review_rows, tally
    from science_dataset import build_catalogue, dataset_card, jsonl, manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = Path(os.environ.get("ANNOTATIONS_DIR", REPO_ROOT / "annotations"))
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"
HF_ARCHIVE_REPO = "SpaceGen/solarhub-archive"
UPLOAD_ATTEMPTS = 3
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


def _rows_by_url(text: str) -> set[str]:
    return {_normalize_url(json.loads(line).get("url", "")) for line in text.splitlines() if line.strip()}


def _commit_files(api: Any, repo_id: str, files: dict[str, str], message: str) -> None:
    """Uploads every file in one commit, so readers never see a half-finished update."""
    with tempfile.TemporaryDirectory() as folder:
        for path, content in files.items():
            target = Path(folder) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for attempt in range(UPLOAD_ATTEMPTS):
            try:
                api.upload_folder(folder_path=folder, repo_id=repo_id, repo_type="dataset", commit_message=message)
                return
            except Exception:
                if attempt == UPLOAD_ATTEMPTS - 1:
                    raise
                time.sleep(2**attempt)


def _rows(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


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

    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.create_repo(repo_id=HF_ARCHIVE_REPO, repo_type="dataset", private=True, exist_ok=True)
    public_paths = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset"))
    archive_paths = set(api.list_repo_files(repo_id=HF_ARCHIVE_REPO, repo_type="dataset"))
    archive_prefix = f"annotations/{task_type}/"
    days = set(by_date)
    days |= {Path(path).stem for path in public_paths if re.fullmatch(r"data/\d{4}-\d{2}-\d{2}\.yml", path)}
    days |= {Path(path).stem for path in archive_paths if path.startswith(archive_prefix)}

    archive_files: dict[str, str] = {}
    changed_archive: dict[str, str] = {}
    for day in sorted(days):
        path = f"{archive_prefix}{day}.jsonl"
        legacy = f"data/{day}.yml"
        # Older public day files seed the archive once.
        before = _read_existing(api, HF_ARCHIVE_REPO, path) if path in archive_paths else _read_existing(api, repo_id, legacy) if legacy in public_paths else ""
        content = merge_rows(before, by_date.get(day, []))
        if not _rows_by_url(before) <= _rows_by_url(content):
            raise ValueError(f"merge would remove archived rows from {path}")
        archive_files[path] = content
        if path not in archive_paths or content != before:
            changed_archive[path] = content
    if changed_archive:
        _commit_files(api, HF_ARCHIVE_REPO, changed_archive, f"chore: archive {task_type} annotations")

    records = [row for text in archive_files.values() for row in _rows(text)]
    observations, features, summary = build_catalogue(task_type, records)
    files: dict[str, str] = {}
    day_of = lambda row: (row.get("t_obs") or row["t_peak"])[:10]
    for day in sorted({day_of(row) for row in observations + features}):
        if any(day_of(row) == day for row in observations):
            files[f"observations/{day}.jsonl"] = jsonl([row for row in observations if day_of(row) == day])
        for split in ("train", "validation", "test"):
            selected = [row for row in features if day_of(row) == day and row["split"] == split]
            if selected:
                files[f"features/{split}/{day}.jsonl"] = jsonl(selected)
    detector = tally(review_rows(records, task_type, ""))
    splits = [split for split in ("train", "validation", "test") if any(path.startswith(f"features/{split}/") for path in files)]
    files["stats/summary.json"] = json.dumps({**summary, "detector_validation": detector_public(detector)}, indent=2, sort_keys=True) + "\n"
    files["stats/manifest.json"] = json.dumps(manifest(files), indent=2, sort_keys=True) + "\n"
    files["README.md"] = dataset_card(task_type, summary, detector, splits)

    changed = {path: text for path, text in files.items() if path not in public_paths or text != _read_existing(api, repo_id, path)}
    if changed:
        _commit_files(api, repo_id, changed, f"data: update {task_type} science catalogue")
    log.info("Archived %d records and published %d features to %s", len(records), len(features), repo_id)
    return len(records)


def detector_public(stats: dict[str, Any]) -> dict[str, Any]:
    """Keeps detector scores and drops annotator counts tied to the review interface."""
    return {
        "proposals_reviewed": stats["rings_reviewed"],
        "precision": stats["finder_precision"],
        "accepted_with_corrections_share": stats["rings_corrected_share"],
        "annotator_added_share": stats["human_added_share"],
        "median_shape_iou_with_annotators": stats["finder_shape_overlap_median"],
        "repeat_review_agreement": stats["reviewer_agreement"],
    }


def make_private(api: Any) -> list[str]:
    """Datasets stay private until the project chooses to release them."""
    failed = []
    for dataset in api.list_datasets(author=HF_DATASET_REPO_PREFIX.split("/")[0]):
        if dataset.id.startswith(HF_DATASET_REPO_PREFIX) and dataset.private is not True:
            try:
                api.update_repo_settings(repo_id=dataset.id, repo_type="dataset", private=True)
            except Exception as exc:
                log.error("Could not make %s private: %s", dataset.id, exc)
                failed.append(dataset.id)
    return failed


def publish_all(api: Any, annotations_dir: Path, fallback_date: str) -> list[str]:
    failed = make_private(api)
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
