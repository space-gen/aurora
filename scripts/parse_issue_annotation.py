"""
parse_issue_annotation.py
=========================
Parses a GitHub issue body and merges the annotation (regions) into the corresponding
task JSON file within annotations/. 

Format: 
{
  "_comment": "Created on ...",
  "data": [
    {
      "id": "...",
      "annotations": [
        {
          "user": "username",
          "locations": [{"label": "...", "x": ..., "y": ..., "radius": ...}]
        }
      ]
    }
  ]
}
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
            continue
        label = pieces[0].lower()
        try:
            x = float(pieces[1])
            y = float(pieces[2])
            r = float(pieces[3]) if len(pieces) >= 4 else 0.0
        except ValueError:
            continue
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

    file_path = ANNOTATIONS_DIR / f"{task_type}.json"
    if not file_path.exists():
        log.error(f"Task file {file_path.name} not found")
        sys.exit(1)

    try:
        content = json.loads(file_path.read_text())
        if isinstance(content, dict) and "data" in content:
            tasks = content["data"]
            comment = content.get("_comment", "")
        else:
            tasks = content
            comment = ""
    except Exception as exc:
        log.error(f"Failed to read {file_path}: {exc}")
        sys.exit(1)

    found = False
    for task in tasks:
        if str(task.get("id")) == record_id:
            found = True
            
            if "annotations" not in task or not isinstance(task["annotations"], list):
                task["annotations"] = []
            
            task["annotations"].append({
                "user": issue_author,
                "locations": regions,
                "issue_number": int(issue_number) if issue_number.isdigit() else issue_number,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            if "metadata" not in task: task["metadata"] = {}
            task["metadata"]["last_user"] = issue_author
            task["metadata"]["last_timestamp"] = task["annotations"][-1]["timestamp"]
            break

    if not found:
        log.error(f"Record {record_id} not found")
        sys.exit(1)

    # Wrap output
    if comment:
        output = {"_comment": comment, "data": tasks}
    else:
        # Generate new comment if it was somehow missing
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        output = {"_comment": f"Created on {date_str}", "data": tasks}

    file_path.write_text(json.dumps(output, indent=2))
    log.info(f"Updated {record_id} with annotation from {issue_author}")

if __name__ == "__main__":
    main()
