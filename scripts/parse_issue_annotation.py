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
from typing import Any, Callable

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

# Valid labels for each task type
PART_OF_LARGER = "part_of_larger"
HOT_REGION_LABELS = {"bright_region", "coronal_loops", PART_OF_LARGER, "none"}
CORONAL_DARK_LABELS = {"coronal_hole", "filament", PART_OF_LARGER, "none"}
LOWER_ATMOSPHERE_LABELS = {"plage", "flare_ribbon", "sunspot", PART_OF_LARGER, "none"}
VALID_LABELS: dict[str, set[str]] = {
    "sunspot": {"class_a", "class_b", "class_c", "class_d", "class_e", "class_f", "class_h", "none"},
    "magnetogram": {"alpha", "beta", "gamma", "beta-gamma", "delta", "beta-delta", "beta-gamma-delta", "gamma-delta", "none"},
    "aia_94": HOT_REGION_LABELS,
    "aia_131": HOT_REGION_LABELS,
    "aia_171": HOT_REGION_LABELS,
    "aia_193": CORONAL_DARK_LABELS,
    "aia_211": CORONAL_DARK_LABELS,
    "aia_304": {"filament", "prominence", "bright_region", PART_OF_LARGER, "none"},
    "aia_335": HOT_REGION_LABELS,
    "aia_1600": LOWER_ATMOSPHERE_LABELS,
    "aia_1700": LOWER_ATMOSPHERE_LABELS,
}
# Flare answers name a NOAA region, which must be one the task offered.
FLARE_LABELS = {"unnumbered_region", "behind_limb", "no_flare_visible"}
FLARE_NO_LOCATION = {"behind_limb", "no_flare_visible"}
FLARE_REGION = re.compile(r"^noaa_(\d{5})$")
VALID_LABELS["flare_source"] = FLARE_LABELS
VALID_TASK_TYPES = set(VALID_LABELS.keys())

IMAGE_SIZE = 1024.0
MAX_RADIUS = 300.0
MAX_REGIONS = 50
REVIEW_ACTIONS = {"confirmed", "moved", "outlined", "merged", "rejected", "deleted", "added"}
MAX_OUTLINE_POINTS = 64
MAX_PARTS = 64
MAX_REVIEW_CHARS = 40000
# Images keep the Sun centred. This radius covers HMI through the year and AIA edge prominences.
SUN_CENTRE = (511.5, 511.5)
MAX_MARK_DISTANCE = 480.0
AIA_WAVELENGTHS = ("94", "131", "171", "193", "211", "304", "335", "1600", "1700")
IMAGE_PATTERNS = {
    "sunspot": re.compile(r"^https://jsoc1\.stanford\.edu/data/hmi/images/(\d{4})/(\d{2})/(\d{2})/\d{8}_\d{6}_Ic_flat_1k\.jpg$"),
    "magnetogram": re.compile(r"^https://jsoc1\.stanford\.edu/data/hmi/images/(\d{4})/(\d{2})/(\d{2})/\d{8}_\d{6}_M_1k\.jpg$"),
    **{
        f"aia_{wavelength}": re.compile(
            rf"^https://sdo\.gsfc\.nasa\.gov/assets/img/browse/(\d{{4}})/(\d{{2}})/(\d{{2}})/\d{{8}}_\d{{6}}_1024_{int(wavelength):04d}\.jpg$"
        )
        for wavelength in AIA_WAVELENGTHS
    },
}
IMAGE_PATTERNS["flare_source"] = IMAGE_PATTERNS["aia_131"]
RECORD_ID_PATTERNS = {
    "flare_source": re.compile(r"^flare-[0-9a-f]{10}$"),
    "sunspot": re.compile(r"^sp-\d+$"),
    "magnetogram": re.compile(r"^mg-\d+$"),
    **{f"aia_{wavelength}": re.compile(rf"^aia{wavelength}-\d+$") for wavelength in AIA_WAVELENGTHS},
}


# Contributors walk back through NASA's archive between these dates; the browser works out the addresses.
ARCHIVE_FIRST = "2016-10-01"
ARCHIVE_LAST = "2026-11-20"
ARCHIVE_TASKS = {"aia_193", "aia_211", "aia_304"}
ARCHIVE_ID = re.compile(r"^aia(\d+)-(\d{14})$")
# The browser runs a copy of Aurora's finder; small decoding differences may move a ring slightly.
FINDER_MATCH_PIXELS = 6
FINDER_MATCH_RADIUS = 0.15


def download_image(url: str) -> bytes | None:
    import requests

    try:
        response = requests.get(url, timeout=60)
    except requests.RequestException:
        return None
    is_jpeg = response.ok and response.content[:3] == b"\xff\xd8\xff"
    return response.content if is_jpeg else None


def canonical_image_url(url: str) -> str:
    return re.sub(r"^https?://jsoc1?\.stanford\.edu/", "https://jsoc1.stanford.edu/", url.strip())


def _valid_circle(label: str, x: float, y: float, r: float, task_type: str | None) -> bool:
    if not all(math.isfinite(value) for value in (x, y, r)):
        return False
    if (label == "none" or label in FLARE_NO_LOCATION) and x == 0 and y == 0 and r == 0:
        return True
    if not (0 <= x <= IMAGE_SIZE and 0 <= y <= IMAGE_SIZE and 0 < r <= MAX_RADIUS):
        return False
    return math.hypot(x - SUN_CENTRE[0], y - SUN_CENTRE[1]) <= MAX_MARK_DISTANCE

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
        # The first heading wins, so free-text notes cannot replace earlier fields.
        fields.setdefault(key, value)
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
    for part in regions_raw.split(";")[:MAX_REGIONS]:
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
        if task_type and label not in VALID_LABELS.get(task_type, set()) and not (task_type == "flare_source" and FLARE_REGION.match(label)):
            log.warning(f"Skipping unknown label for task_type {task_type}: {label}")
            continue

        if len(bits) == 4:
            # Format: label,x,y,r
            try:
                x, y, r = map(float, bits[1:])
                if not _valid_circle(label, x, y, r, task_type):
                    log.warning(f"Skipping out-of-range region: {part}")
                    continue
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


def _in_image(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= IMAGE_SIZE


def _circle(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 3 or not all(_in_image(item) for item in value):
        return None
    return value if _valid_circle("review", value[0], value[1], value[2], None) else None


def _review_ring(ring: Any, task_type: str) -> dict[str, Any] | None:
    if not isinstance(ring, dict) or ring.get("action") not in REVIEW_ACTIONS:
        return None
    action = ring["action"]
    label = ring.get("label")
    circle = _circle(ring.get("ring"))
    finder = _circle(ring.get("finder")) if ring.get("finder") is not None else None
    if circle is None or (finder is None) != (action == "added"):
        return None
    if (action == "deleted") != (label is None) or (label is not None and label not in VALID_LABELS[task_type]):
        return None
    result: dict[str, Any] = {"action": action, "label": label, "finder": finder, "ring": circle}
    if ring.get("part_of_larger") is True:
        result["part_of_larger"] = True
    outline = ring.get("outline")
    if outline is not None:
        valid = isinstance(outline, list) and 3 <= len(outline) <= MAX_OUTLINE_POINTS and all(
            isinstance(point, list) and len(point) == 2 and all(_in_image(item) for item in point) for point in outline
        )
        if not valid:
            return None
        result["outline"] = outline
    return result


def _parse_review(raw: str, task_type: str) -> dict[str, Any] | None:
    """Validates optional corrections; bad ones are dropped without losing the labels."""
    if not raw or len(raw) > MAX_REVIEW_CHARS:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("Ignoring unreadable finder review")
        return None
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("rings"), list):
        return None
    part, parts = data.get("part"), data.get("parts")
    if not (isinstance(part, int) and isinstance(parts, int) and 1 <= part <= parts <= MAX_PARTS):
        return None
    rings = [_review_ring(ring, task_type) for ring in data["rings"][:MAX_REGIONS]]
    if not rings or any(ring is None for ring in rings):
        log.warning("Ignoring invalid finder review")
        return None
    return {"v": 1, "part": part, "parts": parts, "rings": rings}


def _finder_match(finder: list[float], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    x, y, r = finder
    for item in candidates:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), (int, float)) for key in ("x", "y", "r")):
            continue
        if math.hypot(item["x"] - x, item["y"] - y) <= FINDER_MATCH_PIXELS and abs(item["r"] - r) <= max(4, FINDER_MATCH_RADIUS * item["r"]):
            return item
    return None


def _verify_review(annotation: dict[str, Any], task: dict[str, Any]) -> None:
    """Marks which reviewed rings really came from Aurora's own finder output for this image."""
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    candidates = metadata.get("candidates") or []
    for ring in annotation.get("review", {}).get("rings", []):
        candidate = _finder_match(ring["finder"], candidates) if ring["finder"] else None
        ring["finder_verified"] = candidate is not None
        # Copied from Aurora's own task, so a contributor cannot alter the finder's shape.
        if candidate and candidate.get("mask"):
            ring["finder_mask"] = candidate["mask"]


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
        confidence = float(confidence_raw.rstrip("%").strip())
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
    review = _parse_review(fields.get("finder_review", ""), task_type)
    if review:
        annotation["review"] = review
    return {
        "issue_number": normalized_issue_number,
        "issue_author": issue_author,
        "task_type": task_type,
        "record_id": record_id,
        "image_url": fields.get("image_url", "").strip(),
        "annotation": annotation,
    }


def _archive_candidates(task_type: str, url: str, record_id: str, fetch_image: Callable[[str], bytes | None]) -> list[dict[str, Any]] | None:
    """Checks an archive picture the browser chose and reruns Aurora's finder on it; None means reject."""
    archive_id = ARCHIVE_ID.match(record_id)
    stamp = re.search(r"/(\d{8})_(\d{6})_1024_(\d{4})\.jpg$", url)
    if not archive_id or not stamp or archive_id.group(2) != stamp.group(1) + stamp.group(2) or int(archive_id.group(1)) != int(stamp.group(3)):
        return None
    day = f"{stamp.group(1)[:4]}-{stamp.group(1)[4:6]}-{stamp.group(1)[6:]}"
    if not ARCHIVE_FIRST <= day <= ARCHIVE_LAST:
        return None
    content = fetch_image(url)
    if content is None:
        return None
    try:
        from scripts.find_candidates import candidates_from_jpeg
    except ModuleNotFoundError:  # run as a script from scripts/
        from find_candidates import candidates_from_jpeg

    try:
        return candidates_from_jpeg(content, task_type)
    except Exception:
        log.warning("Finder failed on %s", url)
        return None


def _restored_task(item: dict[str, Any], fetch_image: Callable[[str], bytes | None] = download_image) -> dict[str, Any] | None:
    """Rebuild a task from its image address, so late and archive contributions are kept."""
    task_type = item["task_type"]
    pattern = IMAGE_PATTERNS.get(task_type)
    url = canonical_image_url(item.get("image_url", ""))
    match = pattern.match(url) if pattern else None
    if not match or not RECORD_ID_PATTERNS[task_type].match(item["record_id"]):
        return None
    year, month, day = match.groups()
    candidates = None
    if task_type in ARCHIVE_TASKS:
        candidates = _archive_candidates(task_type, url, item["record_id"], fetch_image)
        if candidates is None:
            return None
    restored = {
        "id": item["record_id"],
        "url": url,
        "task_type": task_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "SDO_AIA_BROWSE" if task_type.startswith("aia_") else "JSOC_HMI_JPG", "captured_at": f"{year}-{month}-{day}T00:00:00Z"},
        "annotations": [],
    }
    if candidates is not None:
        hhmmss = item["record_id"][-6:]
        restored["metadata"]["captured_at"] = f"{year}-{month}-{day}T{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]}Z"
        restored["metadata"]["candidates"] = candidates
    return restored


def process_issue_submissions(
    issues: list[dict[str, Any]], annotations_dir: Path = ANNOTATIONS_DIR, fetch_image: Callable[[str], bytes | None] = download_image
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
        if not file_path.exists() and task_type in ARCHIVE_TASKS:
            # Archive pictures need no published task list; the first answer starts the file.
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.touch()
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
            for line in f:
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
                    index_by_id[task_id] = len(tasks)
                tasks.append(_ordered_task(task))

        changed = False
        for item in batch:
            task_idx = index_by_id.get(item["record_id"])
            if task_idx is None:
                restored = _restored_task(item, fetch_image)
                if restored is None:
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
                task_idx = len(tasks)
                tasks.append(restored)
                index_by_id[item["record_id"]] = task_idx
                changed = True

            task = tasks[task_idx]
            submitted_url = item.get("image_url", "")
            if submitted_url and canonical_image_url(submitted_url) != canonical_image_url(str(task.get("url", ""))):
                failures.append(
                    {
                        "number": item["issue_number"],
                        "author": item["issue_author"],
                        "error": f"image does not match record {item['record_id']}",
                    }
                )
                continue
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

            offered = {f"noaa_{item.get('noaa')}" for item in (task.get("metadata") or {}).get("candidates") or [] if isinstance(item, dict)}
            if task_type == "flare_source" and any(FLARE_REGION.match(spot["label"]) and spot["label"] not in offered for spot in item["annotation"]["locations"]):
                failures.append({"number": item["issue_number"], "author": item["issue_author"], "error": "flare region was not one of the offered regions"})
                continue
            _verify_review(item["annotation"], task)
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
