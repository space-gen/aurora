"""
parse_issue_annotation.py
=========================
Parse a GitHub issue body (submitted via the annotation issue template) and
write the resulting annotation JSON into the annotations/ directory.

The issue body produced by a GitHub issue form contains field values in
Markdown format:

    ### Image URL
    https://solar-data-source/image.jpg

    ### Task Type
    sunspot

    ### Your Label
    active_region

    ### Notes (optional)
    Some optional notes...

This script extracts those fields, validates them, and writes the annotation
to ``annotations/annotation_{issue_number}.json``.

Environment variables (set by the calling GitHub Actions workflow):
  ISSUE_NUMBER   — GitHub issue number (used as the output file name).
  ISSUE_BODY     — Raw Markdown body text of the GitHub issue.
  ISSUE_AUTHOR   — GitHub username of the issue author (the annotator).

Usage:
    python scripts/parse_issue_annotation.py
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

# Valid labels for each task type.
VALID_LABELS: dict[str, set[str]] = {
    "sunspot": {"active_region", "quiet_sun", "sunspot_group", "no_sunspot"},
    "solar_flare": {"a_class", "b_class", "c_class", "m_class", "x_class", "no_flare"},
    "magnetogram": {"bipolar_active", "unipolar", "complex", "quiet"},
    "coronal_hole": {"polar", "equatorial", "mid_latitude", "none"},
    "prominence": {"eruptive", "quiescent", "active", "none"},
    "active_region": {"alpha", "beta", "beta_gamma", "beta_gamma_delta", "none"},
    "cme": {"halo", "partial_halo", "narrow", "none"},
}

VALID_TASK_TYPES: set[str] = set(VALID_LABELS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_issue_body(body: str) -> dict[str, str]:
    """
    Extract field values from a GitHub issue form body.

    GitHub issue forms render each field as:
        ### Field Label
        <blank line>
        field value

    Returns a dict mapping lowercase field labels (with spaces replaced by
    underscores) to their values.  Fields with the placeholder ``_No
    response_`` are stored as empty strings.
    """
    fields: dict[str, str] = {}

    # Split on "### " headings to get (heading, value) pairs.
    sections = re.split(r"^###\s+", body, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        lines = section.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        # Value is everything after the heading, stripped of leading/trailing whitespace.
        value = "\n".join(lines[1:]).strip()
        # GitHub renders empty optional fields as "_No response_".
        if value in ("_No response_", "_No response_\n"):
            value = ""
        # Normalise the heading to a simple key.
        key = heading.lower().replace(" ", "_").replace("(optional)", "").rstrip("_").strip("_")
        fields[key] = value

    return fields


def _validate_url(url: str) -> bool:
    """Return True if *url* is a well-formed HTTPS URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc)
    except ValueError:
        return False


def _build_annotation(
    fields: dict[str, str],
    issue_number: str,
    author: str,
) -> dict:
    """
    Validate extracted fields and build the annotation dict.

    Raises SystemExit with a descriptive message on validation failure.
    """
    image_url = fields.get("image_url", "").strip()
    task_type = fields.get("task_type", "").strip().lower()
    user_label = fields.get("your_label", "").strip().lower()
    record_id = fields.get("record_id", "").strip()
    serial_number_str = fields.get("serial_number", "").strip()
    notes = fields.get("notes", "").strip()

    # --- validate ---
    if not image_url:
        log.error("Missing required field: Image URL")
        sys.exit(1)

    if not _validate_url(image_url):
        log.error(
            "Invalid Image URL '%s': must be a well-formed HTTPS URL.", image_url
        )
        sys.exit(1)

    if task_type not in VALID_TASK_TYPES:
        log.error(
            "Invalid task_type '%s'. Must be one of: %s",
            task_type,
            ", ".join(sorted(VALID_TASK_TYPES)),
        )
        sys.exit(1)

    if user_label not in VALID_LABELS[task_type]:
        log.error(
            "Invalid user_label '%s' for task_type '%s'. Valid labels: %s",
            user_label,
            task_type,
            ", ".join(sorted(VALID_LABELS[task_type])),
        )
        sys.exit(1)

    if not record_id or not serial_number_str:
        log.error("Missing record_id or serial_number in issue body.")
        sys.exit(1)

    try:
        serial_number = int(serial_number_str)
    except ValueError:
        log.error("Invalid serial number: %s", serial_number_str)
        sys.exit(1)

    annotation: dict = {
        "url": image_url,
        "task_type": task_type,
        "user_label": user_label,
        "id": record_id,
        "serial_number": serial_number,
        "locations": [],
        "metadata": {
            "annotator": author,
            "issue_number": int(issue_number),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
    }

    # Parse coordinates if present (format: x,y ; x,y)
    coords_raw = fields.get("pixel_coordinates", "").strip()
    if coords_raw and coords_raw.lower() != "none":
        for pair in coords_raw.split(";"):
            try:
                x_str, y_str = pair.strip().split(",")
                annotation["locations"].append({
                    "x": int(x_str.strip()),
                    "y": int(y_str.strip()),
                    "label": user_label
                })
            except ValueError:
                log.warning("Skipping invalid coordinate pair: %s", pair)

    if notes:
        annotation["metadata"]["notes"] = notes

    return annotation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "").strip()
    issue_author = os.environ.get("ISSUE_AUTHOR", "unknown").strip()

    if not issue_number:
        log.error("ISSUE_NUMBER environment variable is not set.")
        sys.exit(1)

    try:
        issue_number_int = int(issue_number)
    except ValueError:
        log.error(
            "ISSUE_NUMBER '%s' is not a valid integer. "
            "Expected a GitHub issue number.",
            issue_number,
        )
        sys.exit(1)

    if not issue_body:
        log.error("ISSUE_BODY environment variable is not set or is empty.")
        sys.exit(1)

    log.info("Parsing annotation from issue #%d by @%s.", issue_number_int, issue_author)

    fields = _parse_issue_body(issue_body)
    log.debug("Extracted fields: %s", fields)

    annotation = _build_annotation(fields, issue_number, issue_author)

    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANNOTATIONS_DIR / f"annotation_{issue_number_int:07d}.json"
    out_path.write_text(json.dumps(annotation, indent=2), encoding="utf-8")

    log.info(
        "Annotation written to %s  (url=%s  task_type=%s  user_label=%s)",
        out_path.name,
        annotation["url"],
        annotation["task_type"],
        annotation["user_label"],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in parse_issue_annotation: %s", exc)
        sys.exit(1)
