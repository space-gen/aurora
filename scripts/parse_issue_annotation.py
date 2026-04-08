"""
parse_issue_annotation.py
=========================
Parses a GitHub issue body and merges the annotation (regions) into the corresponding
task JSONL file within annotations/. 

Strict Schema:
- Top-level metadata is for system/source info only.
- All user data (username, locations, labels, timestamps, confidence) lives inside the 'annotations' list.
- Each location has its own label; no top-level user_label.
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
    "sunspot": {"class_a", "class_b", "class_c", "class_d", "class_e", "class_f", "class_h", "none"},
    "magnetogram": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-delta", "beta-gamma-delta", "gamma-delta", "none"},
}
VALID_TASK_TYPES = set(VALID_LABELS.keys())

def _parse_issue_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    sections = re.split(r"^###\s+", body, flags=re.MULTILINE)
    for section in sections:
        if not section.strip(): continue
        lines = section.splitlines()
        if not lines: continue
        heading = lines[0].strip()
        value = "\n".join(lines[1:]).strip()
        if value in ("_No response_", "_No response_\n"): value = ""
        
        # Normalize key
        key = heading.lower()
        if "(" in key:
            key = key.split("(")[0].strip()
        key = key.replace(" ", "_").replace("(optional)", "").rstrip("_").strip("_")
        fields[key] = value
    log.info(f"Parsed fields: {list(fields.keys())}")
    return fields

def _parse_regions(regions_raw: str, task_type: str | None = None) -> list[dict]:
    """Parse regions provided as `label,region ; label2,region2`.

    Region payloads are stored exactly as submitted (no RLE conversion).
    """
    regions = []
    if not regions_raw:
        return regions
    log.info(f"Parsing regions from: {regions_raw}")
    for part in regions_raw.split(";"):
        part = part.strip()
        if not part:
            continue

        if "," not in part:
            log.warning(f"Skipping malformed region string: {part}")
            continue

        label_raw, region_payload = part.split(",", 1)
        label = label_raw.strip().lower()
        region_payload = region_payload.strip()

        if not region_payload:
            log.warning(f"Skipping region with empty payload: {part}")
            continue

        # Validate label for the given task_type if possible
        if task_type and label not in VALID_LABELS.get(task_type, set()):
            log.warning(f"Skipping unknown label for task_type {task_type}: {label}")
            continue

        regions.append({"label": label, "region": region_payload})
            
    return regions

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
    
    # Try multiple common keys for regions
    regions_raw = ""
    for key in ["your_label", "label", "pixel_coordinates", "regions", "coordinates"]:
        if fields.get(key):
            regions_raw = fields[key]
            break
            
    confidence_raw = fields.get("confidence_score", "100").strip()
    
    try:
        # Extract numeric value, handle % if present
        confidence = float(re.sub(r"[^0-9.]", "", confidence_raw))
    except ValueError:
        confidence = 100.0

    if task_type not in VALID_TASK_TYPES:
        log.error(f"Invalid task_type: {task_type}")
        sys.exit(1)
    if not record_id:
        log.error("record_id is required")
        sys.exit(1)

    regions = _parse_regions(regions_raw, task_type)
    if not regions:
        log.error("No valid regions provided.")
        sys.exit(1)

    file_path = ANNOTATIONS_DIR / f"{task_type}.jsonl"
    if not file_path.exists():
        log.error(f"Task file {file_path.name} not found")
        sys.exit(1)

    tasks = []
    found = False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                task = json.loads(line)
                if str(task.get("id")) == record_id:
                    found = True
                    
                    # Remove legacy fields
                    for legacy in ["user_label", "ml_label", "locations", "serial_number"]:
                        task.pop(legacy, None)
                    
                    # Clean metadata
                    if "metadata" in task:
                        for legacy_meta in ["last_user", "last_annotator", "last_timestamp", "last_issue_number"]:
                            task["metadata"].pop(legacy_meta, None)

                    if "annotations" not in task or not isinstance(task["annotations"], list):
                        task["annotations"] = []

                    normalized_author = issue_author.strip().lower()
                    if normalized_author and any(
                        isinstance(a, dict)
                        and str(a.get("user", "")).strip().lower() == normalized_author
                        for a in task["annotations"]
                    ):
                        log.error(
                            "Duplicate annotation rejected: user '%s' has already annotated record '%s'. "
                            "Each username can annotate a given record only once.",
                            issue_author,
                            record_id,
                        )
                        sys.exit(1)
                    
                    # Append new annotation entry
                    task["annotations"].append({
                        "user": issue_author,
                        "locations": regions,
                        "confidence_score": confidence,
                        "issue_number": int(issue_number) if str(issue_number).isdigit() else issue_number,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                
                # Enforce field order
                ordered_task = {
                    "id": task.get("id"),
                    "url": task.get("url"),
                    "task_type": task.get("task_type"),
                    "created_at": task.get("created_at"),
                    "metadata": task.get("metadata"),
                    "annotations": task.get("annotations", [])
                }
                tasks.append(ordered_task)
    except Exception as exc:
        log.error(f"Failed to process {file_path}: {exc}")
        sys.exit(1)

    if not found:
        log.error(f"Record {record_id} not found")
        sys.exit(1)

    with open(file_path, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, separators=(",", ":")) + "\n")
    log.info(f"Updated {record_id} with annotation from {issue_author} (Confidence: {confidence})")

if __name__ == "__main__":
    main()
