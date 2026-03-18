"""
parse_issue_annotation.py
=========================
Parses a GitHub issue body and merges the annotation (label + locations)
directly into the corresponding task JSON file within annotations/.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

# Valid labels for each task type based on scientific classification systems.
VALID_LABELS: dict[str, set[str]] = {
    # McIntosh Classification (Modified Zurich)
    "sunspot": {"class_a", "class_b", "class_c", "class_d", "class_e", "class_f", "class_h", "none"},
    # GOES X-ray Classification
    "solar_flare": {"x_class", "m_class", "c_class", "b_class", "a_class", "none"},
    # Mount Wilson Magnetic Classification
    "magnetogram": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-delta", "beta-gamma-delta", "gamma-delta", "none"},
    # Heliographic Latitude Classification
    "coronal_hole": {"polar", "equatorial", "mid-latitude", "transequatorial", "none"},
    # Behavioral Classification
    "prominence": {"quiescent", "active", "eruptive", "intermediate", "none"},
    # Secondary classification for active regions (often uses Mount Wilson)
    "active_region": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-gamma-delta", "none"},
    # Angular Width Classification (CDAW)
    "cme": {"full_halo", "partial_halo", "normal", "narrow", "none"},
}

VALID_TASK_TYPES: set[str] = set(VALID_LABELS.keys())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

def _merge_to_task_file(ann: dict):
    """Finds the record in the task file and updates it."""
    task_type = ann["task_type"]
    record_id = ann["id"]
    file_path = ANNOTATIONS_DIR / f"{task_type}.json"
    
    if not file_path.exists():
        log.error(f"Task file {file_path.name} not found in annotations/")
        sys.exit(1)
        
    try:
        tasks = json.loads(file_path.read_text())
        found = False
        for task in tasks:
            if task.get("id") == record_id:
                # 1. Append to history
                if "annotations" not in task:
                    task["annotations"] = []
                
                new_entry = {
                    "user_label": ann["user_label"],
                    "locations": ann["locations"],
                    "annotator": ann["metadata"]["annotator"],
                    "issue_number": ann["metadata"]["issue_number"],
                    "timestamp": ann["metadata"]["timestamp"]
                }
                task["annotations"].append(new_entry)

                # 2. Update top-level "latest" state (backward compatibility)
                task["user_label"] = ann["user_label"]
                task["locations"] = ann["locations"]
                
                # Store extra metadata in the record itself
                task["metadata"]["annotator"] = ann["metadata"]["annotator"]
                task["metadata"]["issue_number"] = ann["metadata"]["issue_number"]
                task["metadata"]["timestamp"] = ann["metadata"]["timestamp"]
                found = True
                break
        
        if not found:
            log.error(f"Record {record_id} not found in {file_path.name}")
            sys.exit(1)
            
        file_path.write_text(json.dumps(tasks, indent=2))
        log.info(f"Merged annotation into {file_path.name} for record {record_id}")
        
    except Exception as e:
        log.error(f"Failed to merge to file: {e}")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "").strip()
    issue_author = os.environ.get("ISSUE_AUTHOR", "unknown").strip()

    if not all([issue_number, issue_body]):
        log.error("Missing ISSUE_NUMBER or ISSUE_BODY")
        sys.exit(1)

    fields = _parse_issue_body(issue_body)
    
    # Extract
    task_type = fields.get("task_type", "").strip().lower()
    user_label = fields.get("your_label", "").strip().lower()
    record_id = fields.get("record_id", "").strip()
    
    # Simple validation
    if task_type not in VALID_TASK_TYPES:
        log.error(f"Invalid task_type: {task_type}")
        sys.exit(1)

    # Locations parsing
    locations = []
    coords_raw = fields.get("pixel_coordinates", "").strip()
    if coords_raw and coords_raw.lower() != "none":
        for pair in coords_raw.split(";"):
            try:
                parts = [p.strip() for p in pair.strip().split(",")]
                if len(parts) >= 2:
                    x, y = int(parts[0]), int(parts[1])
                    radius = int(parts[2]) if len(parts) >= 3 else 0
                    locations.append({"x": x, "y": y, "radius": radius, "label": user_label})
            except: pass

    ann = {
        "task_type": task_type,
        "user_label": user_label,
        "id": record_id,
        "locations": locations,
        "metadata": {
            "annotator": issue_author,
            "issue_number": int(issue_number),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
    }

    _merge_to_task_file(ann)

if __name__ == "__main__":
    main()
