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
    "solar_flare": {"x_class", "m_class", "c_class", "b_class", "a_class", "none"},
    "magnetogram": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-delta", "beta-gamma-delta", "gamma-delta", "none"},
    "coronal_hole": {"polar", "equatorial", "mid-latitude", "transequatorial", "none"},
    "prominence": {"quiescent", "active", "eruptive", "intermediate", "none"},
    "active_region": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-gamma-delta", "none"},
    "cme": {"full_halo", "partial_halo", "normal", "narrow", "none"},
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
        key = heading.lower().replace(" ", "_").replace("(optional)", "").rstrip("_").strip("_")
        fields[key] = value
    return fields

def _parse_regions(regions_raw: str) -> list[dict]:
    regions = []
    if not regions_raw: return regions
    for part in regions_raw.split(";"):
        part = part.strip()
        if not part: continue
        pieces = [p.strip() for p in part.split(",") if p.strip()]
        if len(pieces) < 3: continue # Need label,x,y
        label = pieces[0].lower()
        try:
            x = float(pieces[1])
            y = float(pieces[2])
            r = float(pieces[3]) if len(pieces) >= 4 else 0.0
        except ValueError: continue
        regions.append({"label": label, "x": x, "y": y, "radius": r})
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
    regions_raw = fields.get("pixel_coordinates", fields.get("regions", "")).strip()
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

    regions = _parse_regions(regions_raw)
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
                    
                    # Remove any leftover top-level user fields
                    task.pop("user_label", None)
                    task.pop("ml_label", None)
                    task.pop("locations", None)
                    
                    # Clean system metadata from user info
                    if "metadata" in task:
                        task["metadata"].pop("last_user", None)
                        task["metadata"].pop("last_annotator", None)
                        task["metadata"].pop("last_timestamp", None)
                        task["metadata"].pop("last_issue_number", None)

                    if "annotations" not in task or not isinstance(task["annotations"], list):
                        task["annotations"] = []
                    
                    # Append new clean annotation entry
                    task["annotations"].append({
                        "user": issue_author,
                        "locations": regions,
                        "confidence_score": confidence,
                        "issue_number": int(issue_number) if issue_number.isdigit() else issue_number,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                tasks.append(task)
    except Exception as exc:
        log.error(f"Failed to process {file_path}: {exc}")
        sys.exit(1)

    if not found:
        log.error(f"Record {record_id} not found")
        sys.exit(1)

    with open(file_path, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, separators=(",", ":"), sort_keys=True) + "\n")
    log.info(f"Updated {record_id} with annotation from {issue_author} (Confidence: {confidence})")

if __name__ == "__main__":
    main()
