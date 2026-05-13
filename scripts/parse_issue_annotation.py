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
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    # AIA common solar feature classifications (unified for all wavelengths)
    "aia_94": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_131": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_171": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_193": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_211": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_304": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_335": {"bright_loop", "dark_filament", "flare", "active_region", "coronal_mass", "quiet_sun", "none"},
    "aia_1600": {"bright_plage", "dark_filament", "sunspot_umbra", "active_region", "granulation", "quiet_sun", "none"},
    "aia_1700": {"bright_plage", "dark_filament", "sunspot_umbra", "active_region", "granulation", "quiet_sun", "none"},
    "aia_4500": {"bright_plage", "dark_sunspot", "active_region", "granulation", "quiet_sun", "none"},
}
VALID_TASK_TYPES = set(VALID_LABELS.keys())

def circle_to_rle(cx: float, cy: float, r: float, width: int = 1024) -> str:
    """
    Convert a circle (cx, cy, r) to a compressed RLE string.
    Format: start1 length1 gap1 length2 gap2 length3 ...
    gap is the distance from the end of the previous run to the start of the current one.
    """
    runs = []
    for y in range(int(cy - r), int(cy + r) + 1):
        if y < 0 or y >= 1024:
            continue
        dy = y - cy
        dx = math.sqrt(max(0, r*r - dy*dy))
        x1 = max(0, int(cx - dx))
        x2 = min(width - 1, int(cx + dx))
        if x1 <= x2:
            runs.append((y * width + x1, x2 - x1 + 1))
    
    if not runs:
        return ""
        
    rle_parts = [str(runs[0][0]), str(runs[0][1])]
    last_end = runs[0][0] + runs[0][1]
    
    for i in range(1, len(runs)):
        start, length = runs[i]
        gap = start - last_end
        rle_parts.extend([str(gap), str(length)])
        last_end = start + length
        
    return " ".join(rle_parts)

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
    """Parse regions provided as `label,rle ; label2,rle2` or `label,x,y,r`.

    Returns a list of dicts with keys: `label` and `rle`.
    Automatically converts x,y,r to RLE if 4 comma-separated values are found.
    """
    regions = []
    if not regions_raw:
        return regions
    log.info(f"Parsing regions from: {regions_raw}")
    for part in regions_raw.split(";"):
        part = part.strip()
        if not part:
            continue
        
        # Split by comma to check format
        bits = [b.strip() for b in part.split(",")]
        if len(bits) < 2:
            log.warning(f"Skipping malformed region string: {part}")
            continue
            
        label = bits[0].lower()
        # Validate label for the given task_type if possible
        if task_type and label not in VALID_LABELS.get(task_type, set()):
            log.warning(f"Skipping unknown label for task_type {task_type}: {label}")
            continue

        if len(bits) == 4:
            # Format: label,x,y,r
            try:
                x, y, r = map(float, bits[1:])
                # Store circle coordinates directly in the 'region' field as comma-separated x,y,r
                region_val = f"{x},{y},{r}"
                regions.append({"label": label, "region": region_val})
                log.info(f"Stored {label} circle as region ({region_val})")
            except ValueError:
                log.warning(f"Failed to parse x,y,r coordinates: {part}")
                continue
        else:
            # Format: label,rle or label,region-string
            region_val = ",".join(bits[1:]) # Re-join in case the region string contains commas
            regions.append({"label": label, "region": region_val})
            
    return regions


class AnnotationParseError(Exception):
    pass


def _ordered_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "url": task.get("url"),
        "task_type": task.get("task_type"),
        "created_at": task.get("created_at"),
        "metadata": task.get("metadata"),
        "annotations": task.get("annotations", []),
    }


def _parse_issue_submission(*, issue_number: Any, issue_body: str, issue_author: str) -> dict[str, Any]:
    fields = _parse_issue_body(issue_body)
    task_type = fields.get("task_type", "").strip().lower()
    record_id = fields.get("record_id", "").strip()

    regions_raw = ""
    for key in ["your_label", "label", "pixel_coordinates", "regions", "coordinates"]:
        if fields.get(key):
            regions_raw = fields[key]
            break

    confidence_raw = fields.get("confidence_score", "100").strip()
    try:
        confidence = float(re.sub(r"[^0-9.]", "", confidence_raw))
    except ValueError as exc:
        raise AnnotationParseError("confidence_score is invalid") from exc

    if task_type not in VALID_TASK_TYPES:
        raise AnnotationParseError(f"invalid task_type: {task_type}")
    if not record_id:
        raise AnnotationParseError("record_id is required")
    if not (0.0 <= confidence <= 100.0):
        raise AnnotationParseError("confidence_score must be between 0 and 100")

    regions = _parse_regions(regions_raw, task_type)
    if not regions:
        raise AnnotationParseError("no valid regions provided")

    normalized_issue_number: Any
    issue_number_str = str(issue_number).strip()
    if issue_number_str.isdigit():
        normalized_issue_number = int(issue_number_str)
    else:
        normalized_issue_number = issue_number

    annotation = {
        "user": issue_author,
        "confidence_score": confidence,
        "locations": regions,
        "issue_number": normalized_issue_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "issue_number": normalized_issue_number,
        "issue_author": issue_author,
        "task_type": task_type,
        "record_id": record_id,
        "annotation": annotation,
    }


def process_issue_submissions(
    issues: list[dict[str, Any]], annotations_dir: Path = ANNOTATIONS_DIR
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for issue in issues:
        number = issue.get("number")
        body = str(issue.get("body", "") or "")
        author = str(issue.get("author", "unknown") or "unknown").strip()
        try:
            parsed.append(
                _parse_issue_submission(
                    issue_number=number,
                    issue_body=body,
                    issue_author=author,
                )
            )
        except AnnotationParseError as exc:
            failures.append({"number": number, "author": author, "error": str(exc)})

    by_task_type: dict[str, list[dict[str, Any]]] = {}
    for item in parsed:
        by_task_type.setdefault(item["task_type"], []).append(item)

    successes: list[dict[str, Any]] = []
    for task_type, batch in by_task_type.items():
        file_path = annotations_dir / f"{task_type}.jsonl"
        if not file_path.exists():
            for item in batch:
                failures.append(
                    {
                        "number": item["issue_number"],
                        "author": item["issue_author"],
                        "error": f"task file {file_path.name} not found",
                    }
                )
            continue

        tasks: list[dict[str, Any]] = []
        index_by_id: dict[str, int] = {}
        with open(file_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if not line.strip():
                    continue
                task = json.loads(line)

                for legacy in ["user_label", "ml_label", "locations", "serial_number"]:
                    task.pop(legacy, None)
                if isinstance(task.get("metadata"), dict):
                    for legacy_meta in ["last_user", "last_annotator", "last_timestamp", "last_issue_number"]:
                        task["metadata"].pop(legacy_meta, None)
                if not isinstance(task.get("annotations"), list):
                    task["annotations"] = []

                task_id = str(task.get("id", "")).strip()
                if task_id:
                    index_by_id[task_id] = idx
                tasks.append(_ordered_task(task))

        changed = False
        for item in batch:
            task_idx = index_by_id.get(item["record_id"])
            if task_idx is None:
                failures.append(
                    {
                        "number": item["issue_number"],
                        "author": item["issue_author"],
                        "error": (
                            f"data_expired: record {item['record_id']} not found in "
                            f"{task_type}.jsonl"
                        ),
                    }
                )
                continue

            task = tasks[task_idx]
            existing_annotations = task["annotations"]
            already_exists = any(
                str(existing.get("user", "")).strip().lower() == item["issue_author"].lower()
                for existing in existing_annotations
            )
            if already_exists:
                failures.append(
                    {
                        "number": item["issue_number"],
                        "author": item["issue_author"],
                        "error": f"user '{item['issue_author']}' already annotated record {item['record_id']}",
                    }
                )
                continue

            existing_annotations.append(item["annotation"])
            try:
                existing_annotations.sort(key=lambda a: a.get("timestamp", ""))
            except Exception:
                pass
            changed = True
            successes.append(
                {
                    "number": item["issue_number"],
                    "author": item["issue_author"],
                    "record_id": item["record_id"],
                    "task_type": item["task_type"],
                }
            )

        if changed:
            with open(file_path, "w", encoding="utf-8") as f:
                for task in tasks:
                    f.write(json.dumps(_ordered_task(task), separators=(",", ":")) + "\n")

    return successes, failures

def main() -> None:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "").strip()
    issue_author = os.environ.get("ISSUE_AUTHOR", "unknown").strip()
    if not all([issue_number, issue_body]):
        log.error("Missing ISSUE_NUMBER or ISSUE_BODY")
        sys.exit(1)

    successes, failures = process_issue_submissions(
        [{"number": issue_number, "body": issue_body, "author": issue_author}],
        annotations_dir=ANNOTATIONS_DIR,
    )
    if failures:
        log.error(failures[0]["error"])
        sys.exit(1)
    if not successes:
        log.error("No annotation was processed")
        sys.exit(1)

    success = successes[0]
    log.info(
        f"Updated {success['record_id']} ({success['task_type']}) with annotation from {success['author']}"
    )

if __name__ == "__main__":
    main()
