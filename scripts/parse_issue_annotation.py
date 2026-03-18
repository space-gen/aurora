"""
parse_issue_annotation.py
=========================
Parses a GitHub issue body and merges the annotation (regions) into the corresponding
task JSON file within annotations/. New format stores per-annotator region lists
under `annotations_by_user` in each task record.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

# Valid labels for each task type
VALID_LABELS: dict[str, set[str]] = {
    "sunspot": {"class_a", "class_b", "class_c", "class_d", "class_e", "class_f", "class_h", "none", "sunspot"},
    "solar_flare": {"x_class", "m_class", "c_class", "b_class", "a_class", "none"},
    "magnetogram": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-delta", "beta-gamma-delta", "gamma-delta", "none"},
    "coronal_hole": {"polar", "equatorial", "mid-latitude", "transequatorial", "none"},
    "prominence": {"quiescent", "active", "eruptive", "intermediate", "none"},
    "active_region": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-gamma-delta", "none"},
    "cme": {"full_halo", "partial_halo", "normal", "narrow", "none"},
}
VALID_TASK_TYPES = set(VALID_LABELS.keys())

# Helpers
def _parse_issue_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    # Expect GitHub issue form uses headings or simple key: value pairs.
    # Try to capture both `### Heading` sections and `FieldName:\nvalue` styles.
    sections = re.split(r"^###\s+", body, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        lines = section.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        value = "\n".join(lines[1:]).strip()
        if value in ("_No response_", "_No response_\n"):
            value = ""
        key = heading.lower().replace(" ", "_").replace("(optional)", "").rstrip("_").strip("_")
        fields[key] = value
    # Fallback: parse simple `Field: value` pairs
    for m in re.finditer(r"(?m)^([A-Za-z _]+):\s*\n([^\n][\s\S]*?)(?=^\w+:|\Z)", body):
        k = m.group(1).strip().lower().replace(" ", "_")
        if k not in fields:
            fields[k] = m.group(2).strip()
    return fields


def _parse_regions(regions_raw: str) -> list[dict]:
    regions = []
    if not regions_raw:
        return regions
    for part in regions_raw.split(";"):
        part = part.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split(",") if p.strip()]
        if len(pieces) < 3:
            # Need at least label,x,y
            continue
        label = pieces[0]
        try:
            x = float(pieces[1])
            y = float(pieces[2])
            r = float(pieces[3]) if len(pieces) >= 4 else 0.0
        except ValueError:
            continue
        regions.append({"label": label, "x": x, "y": y, "radius": r})
    return regions


def _merge_annotations_by_user(task: dict, annotator: str, regions: list[dict], issue_number: str, timestamp: str) -> None:
    # Ensure structure
    if "annotations_by_user" not in task or not isinstance(task["annotations_by_user"], dict):
        task["annotations_by_user"] = {}
    user_map = task["annotations_by_user"]
    user_list = user_map.get(annotator, [])
    # append regions as provided (no dedup) but keep as list
    user_list.extend(regions)
    user_map[annotator] = user_list
    # Also maintain a shallow history list for convenience
    if "annotation_history" not in task or not isinstance(task["annotation_history"], list):
        task["annotation_history"] = []
    task["annotation_history"].append({"annotator": annotator, "issue_number": issue_number, "timestamp": timestamp, "regions": regions})


# Main
def main() -> None:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "").strip()
    issue_author = os.environ.get("ISSUE_AUTHOR", "unknown").strip()

    if not all([issue_number, issue_body]):
        log.error("Missing ISSUE_NUMBER or ISSUE_BODY")
        sys.exit(1)

    fields = _parse_issue_body(issue_body)
    task_type = fields.get("task_type", "").strip().lower()
    record_id = fields.get("record_id", "").strip()
    image_url = fields.get("image_url", "").strip()
    regions_raw = fields.get("regions", "").strip()
    notes = fields.get("notes", "").strip()

    if task_type not in VALID_TASK_TYPES:
        log.error(f"Invalid task_type: {task_type}")
        sys.exit(1)
    if not record_id:
        log.error("record_id is required")
        sys.exit(1)
    if not image_url:
        log.error("image_url is required")
        sys.exit(1)

    regions = _parse_regions(regions_raw)
    if not regions:
        log.error("No valid regions parsed from 'regions' field")
        sys.exit(1)

    file_path = ANNOTATIONS_DIR / f"{task_type}.json"
    if not file_path.exists():
        log.error(f"Task file {file_path.name} not found in annotations/")
        sys.exit(1)

    try:
        tasks = json.loads(file_path.read_text())
    except Exception as exc:
        log.error(f"Failed to read {file_path}: {exc}")
        sys.exit(1)

    found = False
    timestamp = datetime.now(timezone.utc).isoformat()
    for task in tasks:
        if str(task.get("id")) == record_id:
            found = True
            # Update image_url if missing
            if "url" not in task or not task.get("url"):
                task["url"] = image_url
            # Ensure metadata exists
            if "metadata" not in task or not isinstance(task["metadata"], dict):
                task["metadata"] = {}
            task["metadata"].setdefault("last_annotator", issue_author)
            task["metadata"]["last_issue_number"] = issue_number
            task["metadata"]["last_timestamp"] = timestamp

            # Merge per-annotator regions
            _merge_annotations_by_user(task, issue_author, regions, issue_number, timestamp)

            # Optionally store notes
            if notes:
                task.setdefault("notes", "")
                task["notes"] = (task.get("notes", "") + "\n" + notes).strip()
            break

    if not found:
        log.error(f"Record {record_id} not found in {file_path.name}")
        sys.exit(1)

    try:
        file_path.write_text(json.dumps(tasks, indent=2))
        log.info(f"Merged annotation by {issue_author} into {file_path.name} for record {record_id}")
    except Exception as exc:
        log.error(f"Failed to write {file_path}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
